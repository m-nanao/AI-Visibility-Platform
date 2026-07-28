"""Common Crawl WARC record fetch + HTML extraction — the second slice
of Common Crawl integration (see docs/13_common_crawl_mvp_design.md for
the full MVP design and services/common_crawl_index.py for the first
slice, Index API search).

This module fetches **at most one** WARC record — using the
`filename`/`offset`/`length` a services/common_crawl_index.py
`CommonCrawlCandidate` already carries — via an HTTP Range request,
decompresses it, and extracts the embedded HTTP response's HTML body.
It does **not** decide which candidate to fetch (that's the caller's
job — fetching multiple candidates is out of scope for this slice), do
any HTML cleaning/normalization (that's services/document_cleaner.py's
job, for a later step to wire up), build `Document[]`, or integrate
with `/analyze` or the UI.

Like services/common_crawl_index.py, **this module never decides
*whether* Common Crawl fetching is allowed** — it has no read of
`COMMON_CRAWL_ENABLED` and performs no gating of its own. A future
common_crawl_provider.py is expected to gate calls into this module,
exactly like it's expected to gate services/common_crawl_index.py.

Common Crawl's WARC storage is public and unauthenticated — there is
no credential type here, and nothing in this module is ever a secret.

This client never raises out of `fetch_common_crawl_warc_record()` —
a missing filename/offset/length, an oversized range, a network error,
a non-2xx/206 response, an empty body, a gzip decompression failure, a
missing HTTP response block, a non-HTML content type, and an empty
HTML body are all caught and converted into a `CommonCrawlFetchResult`
with `status="unavailable"` and a short, safe `reason` — never the raw
WARC bytes or the extracted HTML itself.

Only bounded data is ever kept: the compressed WARC range fetched over
the network is capped at `MAX_WARC_RANGE_BYTES` before any request is
made (based on the candidate's own `length`), the decompressed payload
is capped at `MAX_DECOMPRESSED_BYTES`, and the extracted HTML text is
truncated to `MAX_HTML_CHARS`. These are plain module-level constants
rather than new `COMMON_CRAWL_*` environment variables, since this is a
single internal safety cap rather than a per-deployment tuning knob (a
new env var was judged not worth the added configuration surface for
this MVP slice).
"""

import codecs
import gzip
import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from services.common_crawl_index import CommonCrawlCandidate
from services.common_crawl_settings import CommonCrawlSettings

logger = logging.getLogger(__name__)

COMMON_CRAWL_WARC_HOST = "https://data.commoncrawl.org"

# Upper bound on the compressed WARC byte range this module will ever
# request — checked against candidate.length *before* any HTTP request
# is made, so an unreasonably large candidate never reaches the
# network at all.
MAX_WARC_RANGE_BYTES = 1_500_000

# Upper bound on the decompressed WARC record size. gzip text
# compression ratios rarely exceed ~10x, so this comfortably covers a
# MAX_WARC_RANGE_BYTES-sized fetch while still rejecting a pathological
# payload before it's fully processed.
MAX_DECOMPRESSED_BYTES = 8_000_000

# Upper bound on the extracted HTML text, in characters. Excess text is
# truncated (mirrors document_cleaner.MAX_BODY_TEXT_LENGTH's plain
# slicing), not rejected — a long-but-otherwise-valid page shouldn't
# become "unavailable" just for being long.
MAX_HTML_CHARS = 200_000

_ALLOWED_HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}


@dataclass(frozen=True)
class CommonCrawlFetchResult:
    """Outcome of fetching and extracting HTML from one Common Crawl
    WARC record. `status` mirrors this codebase's existing
    SectionStatus-shaped result types (see CommonCrawlIndexResult) —
    "real" only when an HTML body was actually extracted, "unavailable"
    for every failure case. Deliberately holds only the extracted HTML
    text (already size-capped) — never the raw WARC bytes, and never a
    huge response body inside `reason`.
    """

    status: Literal["real", "unavailable"]
    reason: str
    url: str | None = None
    crawl_index: str | None = None
    html: str | None = None
    content_type: str | None = None
    fetched_bytes: int | None = None


def _unavailable(
    reason: str,
    *,
    url: str | None,
    crawl_index: str | None,
    content_type: str | None = None,
) -> CommonCrawlFetchResult:
    return CommonCrawlFetchResult(
        status="unavailable",
        reason=reason,
        url=url,
        crawl_index=crawl_index,
        content_type=content_type,
    )


def _split_on_blank_line(data: bytes) -> tuple[bytes, bytes] | None:
    """Splits `data` at the first blank-line boundary (CRLF-CRLF, with
    a bare-LF-LF fallback for tolerance), returning (before, after). The
    separator itself is dropped. Returns None if no blank line is
    found.
    """
    for separator in (b"\r\n\r\n", b"\n\n"):
        index = data.find(separator)
        if index != -1:
            return data[:index], data[index + len(separator) :]
    return None


def _split_http_block(decompressed: bytes) -> tuple[bytes, bytes] | None:
    """Splits a decompressed WARC "response" record into
    (http_header_bytes, html_body_bytes).

    A WARC response record looks roughly like:

        WARC/1.0\\r\\n
        <WARC headers>\\r\\n
        \\r\\n
        HTTP/1.1 200 OK\\r\\n
        <HTTP headers>\\r\\n
        \\r\\n
        <html body>

    So there are two blank-line boundaries to cross: first past the
    WARC header block, then past the embedded HTTP header block.
    """
    after_warc_headers = _split_on_blank_line(decompressed)
    if after_warc_headers is None:
        return None
    _warc_headers, remainder = after_warc_headers

    return _split_on_blank_line(remainder)


def _extract_header_value(headers: bytes, name: bytes) -> bytes | None:
    pattern = re.compile(rb"(?im)^" + re.escape(name) + rb":[ \t]*([^\r\n]+)")
    match = pattern.search(headers)
    if match is None:
        return None
    return match.group(1).strip()


def _parse_content_type(raw: bytes | None) -> tuple[str | None, str | None]:
    """Parses an HTTP Content-Type header value into (media_type,
    charset), e.g. b"text/html; charset=Shift_JIS" ->
    ("text/html", "Shift_JIS"). Either element may be None.
    """
    if raw is None:
        return None, None

    text = raw.decode("ascii", errors="ignore")
    parts = text.split(";")

    media_type = parts[0].strip().lower() or None

    charset: str | None = None
    for part in parts[1:]:
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip().strip("\"'") or None

    return media_type, charset


def _decode_body(body: bytes, charset: str | None) -> str:
    encoding = (charset or "utf-8").strip() or "utf-8"
    try:
        codecs.lookup(encoding)
    except LookupError:
        encoding = "utf-8"
    return body.decode(encoding, errors="replace")


def fetch_common_crawl_warc_record(
    candidate: CommonCrawlCandidate, settings: CommonCrawlSettings
) -> CommonCrawlFetchResult:
    """Fetches the single WARC record described by `candidate` (via an
    HTTP Range request against `https://data.commoncrawl.org/{filename}`),
    decompresses it, and extracts its HTML body.

    This function itself does not decide whether calling Common Crawl
    is *allowed* — see the module docstring: any `COMMON_CRAWL_ENABLED`
    gating belongs to a future provider layer, not here.

    Issues at most one HTTP request. Never raises; every failure path
    (missing filename/offset/length, an oversized range, a network/
    timeout error, a non-2xx/206 response, an empty body, a gzip
    failure, an oversized decompressed payload, a missing HTTP block, a
    non-HTML content type, or an empty HTML body) returns a
    `CommonCrawlFetchResult` with `status="unavailable"` and a short,
    safe reason — never the raw WARC bytes or extracted HTML itself.
    """
    url = candidate.url
    crawl_index = candidate.crawl_index or None

    filename = candidate.filename
    if not filename or not filename.strip():
        return _unavailable(
            "Common Crawl candidate is missing WARC filename.",
            url=url,
            crawl_index=crawl_index,
        )

    offset = candidate.offset
    length = candidate.length
    if offset is None or offset < 0 or length is None or length <= 0:
        return _unavailable(
            "Common Crawl candidate is missing WARC offset or length.",
            url=url,
            crawl_index=crawl_index,
        )

    if length > MAX_WARC_RANGE_BYTES:
        return _unavailable(
            "Common Crawl WARC range is too large.",
            url=url,
            crawl_index=crawl_index,
        )

    warc_url = f"{COMMON_CRAWL_WARC_HOST}/{filename}"
    range_header = f"bytes={offset}-{offset + length - 1}"

    try:
        response = httpx.get(
            warc_url,
            headers={"User-Agent": settings.user_agent, "Range": range_header},
            timeout=settings.timeout_seconds,
        )
    except httpx.HTTPError:
        logger.warning("Common Crawl WARC request failed (network/timeout error)")
        return _unavailable(
            "Common Crawl WARC request failed due to a network or timeout error.",
            url=url,
            crawl_index=crawl_index,
        )

    if response.status_code not in (200, 206):
        logger.warning("Common Crawl WARC request returned HTTP %d", response.status_code)
        return _unavailable(
            f"Common Crawl WARC request failed with HTTP {response.status_code}.",
            url=url,
            crawl_index=crawl_index,
        )

    raw_bytes = response.content
    if not raw_bytes:
        return _unavailable(
            "Common Crawl WARC response was empty.",
            url=url,
            crawl_index=crawl_index,
        )

    try:
        decompressed = gzip.decompress(raw_bytes)
    except OSError:
        logger.warning("Common Crawl WARC gzip decompression failed")
        return _unavailable(
            "Common Crawl WARC gzip decompression failed.",
            url=url,
            crawl_index=crawl_index,
        )

    if len(decompressed) > MAX_DECOMPRESSED_BYTES:
        return _unavailable(
            "Common Crawl WARC payload was too large after decompression.",
            url=url,
            crawl_index=crawl_index,
        )

    split = _split_http_block(decompressed)
    if split is None:
        return _unavailable(
            "Common Crawl WARC payload did not contain an HTTP response body.",
            url=url,
            crawl_index=crawl_index,
        )

    http_headers, body = split
    content_type_raw = _extract_header_value(http_headers, b"content-type")
    media_type, charset = _parse_content_type(content_type_raw)

    if media_type not in _ALLOWED_HTML_MEDIA_TYPES:
        return _unavailable(
            "Common Crawl WARC content type is not HTML.",
            url=url,
            crawl_index=crawl_index,
            content_type=media_type,
        )

    html = _decode_body(body, charset)
    if not html.strip():
        return _unavailable(
            "Common Crawl WARC HTML body was empty.",
            url=url,
            crawl_index=crawl_index,
            content_type=media_type,
        )

    if len(html) > MAX_HTML_CHARS:
        html = html[:MAX_HTML_CHARS]

    return CommonCrawlFetchResult(
        status="real",
        reason="Common Crawl WARC record fetched and HTML extracted successfully.",
        url=url,
        crawl_index=crawl_index,
        html=html,
        content_type=media_type,
        fetched_bytes=len(raw_bytes),
    )
