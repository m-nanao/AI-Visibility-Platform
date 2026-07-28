"""Common Crawl Index API client — the first slice of Common Crawl
integration (see docs/13_common_crawl_mvp_design.md for the full MVP
design). This module only searches the Index API for a domain's URL
candidates; it does **not** fetch WARC records, extract HTML, build
`Document[]`, or integrate with `/analyze` — those are later steps in
the design doc's 10-step plan.

**This module never decides *whether* Common Crawl search is allowed**
— it has no read of `COMMON_CRAWL_ENABLED` and performs no gating of
its own, mirroring services/dataforseo_client.py's and
services/chatgpt_client.py's "client trusts the caller" design (see
those modules' docstrings for the same rationale). A future
common_crawl_provider.py is expected to read
`CommonCrawlSettings.enabled` before ever calling
`search_common_crawl_domain()` — exactly like
services/ai_overview_provider.py/services/chatgpt_provider.py gate
their respective clients.

Common Crawl's Index API and WARC storage are both public and
unauthenticated — there is no credential type in this module or in
services/common_crawl_settings.py, unlike the DataForSEO/ChatGPT
clients.

This client never raises out of `search_common_crawl_domain()` or
`resolve_common_crawl_index()` — network errors, timeouts, non-2xx
responses, and unexpected response shapes are all caught and converted
into a result with `status="unavailable"` (or `success=False` for the
index resolution step) and a safe `reason`, so a Common Crawl outage or
response-shape quirk can never take down `/analyze` once this is wired
in.

Only bounded, structured data is ever kept — no HTML body, no WARC
body, and no raw Index API response text is retained past this
function call (see `CommonCrawlCandidate`, which deliberately has no
field for either).
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

import httpx

from services.common_crawl_settings import CommonCrawlSettings

logger = logging.getLogger(__name__)

COMMON_CRAWL_HOST = "https://index.commoncrawl.org"
COLLINFO_URL = f"{COMMON_CRAWL_HOST}/collinfo.json"

# One label of a DNS hostname: 1-63 chars, alphanumeric/hyphen, not
# starting or ending with a hyphen. A full hostname is 2+ labels
# joined by dots — this is what makes "localhost" (no dot) and bare
# words get rejected by _normalize_domain, alongside anything with a
# disallowed character (scheme separators, whitespace, etc.).
_HOSTNAME_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
_HOSTNAME_PATTERN = re.compile(rf"^{_HOSTNAME_LABEL}(\.{_HOSTNAME_LABEL})+$")

# Matches a Common Crawl crawl id, e.g. "CC-MAIN-2026-08" — used to
# pick the actual latest entry out of collinfo.json by (year, week)
# rather than assuming the API always returns entries in a particular
# order.
_CRAWL_INDEX_ID_PATTERN = re.compile(r"^CC-MAIN-(\d{4})-(\d{1,2})$", re.IGNORECASE)


@dataclass(frozen=True)
class CommonCrawlIndexResolution:
    """Outcome of resolving which Common Crawl index id to search
    against — either the configured id as-is, or (when
    CommonCrawlSettings.index == "latest") whichever id collinfo.json
    reports as the newest. Never holds the raw collinfo.json response.
    """

    success: bool
    reason: str
    crawl_index: str | None = None


@dataclass(frozen=True)
class CommonCrawlCandidate:
    """One URL candidate from a Common Crawl Index API search result,
    normalized from the API's JSON Lines (CDXJ-style) response.
    Deliberately holds only bounded metadata — no HTML body, no WARC
    body. `filename`/`offset`/`length` are what a later step would need
    to fetch the actual WARC record; this module does not fetch it.
    """

    url: str
    timestamp: str | None = None
    status: int | None = None
    mime: str | None = None
    digest: str | None = None
    length: int | None = None
    offset: int | None = None
    filename: str | None = None
    crawl_index: str = ""
    source: Literal["common_crawl"] = "common_crawl"


@dataclass(frozen=True)
class CommonCrawlIndexResult:
    """Outcome of one domain search against the Common Crawl Index API.
    `status` mirrors this codebase's existing SectionStatus-shaped
    result types (see DataForSEOSerpResult/ChatGptObservationResult) —
    "real" only when at least one candidate was found and parsed,
    "unavailable" for every failure/empty-result case. "off" is
    included in the type for a future common_crawl_provider.py to use
    when COMMON_CRAWL_ENABLED is false — this module itself never
    returns "off", since it does no enabled-gating of its own (see
    module docstring).
    """

    status: Literal["real", "unavailable", "off"]
    reason: str
    crawl_index: str | None = None
    candidates: tuple[CommonCrawlCandidate, ...] = ()


def _normalize_domain(raw: str) -> str | None:
    """Reduces a user-supplied domain (which may be a bare hostname, a
    full URL, or something malformed/dangerous) down to a lowercase
    hostname suitable for a Common Crawl Index API `url=` query, or
    None if it doesn't look like a usable hostname at all.

    Strips a scheme (`https://...`), any path/query/fragment, and any
    userinfo/port, then validates what's left against a strict
    hostname allow-list (_HOSTNAME_PATTERN) — this rejects anything
    with disallowed characters (spaces, control characters, stray
    scheme-like prefixes such as "javascript:") as well as anything
    with no dot at all (e.g. "localhost").
    """
    text = raw.strip()
    if not text:
        return None

    if "://" in text:
        text = text.split("://", 1)[1]

    text = text.split("/", 1)[0]
    text = text.split("?", 1)[0]
    text = text.split("#", 1)[0]
    text = text.rsplit("@", 1)[-1]
    text = text.split(":", 1)[0]
    text = text.lower()

    if not _HOSTNAME_PATTERN.match(text):
        return None
    return text


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _parse_crawl_index_id(raw: object) -> tuple[int, int] | None:
    """Extracts (year, week) from a Common Crawl id string like
    "CC-MAIN-2026-08" for comparison purposes. Returns None for
    anything that doesn't match the expected shape.
    """
    if not isinstance(raw, str):
        return None
    match = _CRAWL_INDEX_ID_PATTERN.match(raw.strip())
    if match is None:
        return None
    year, week = match.groups()
    return int(year), int(week)


def _fetch_latest_index(settings: CommonCrawlSettings) -> CommonCrawlIndexResolution:
    """Fetches collinfo.json and picks the entry with the greatest
    (year, week) — not just the first entry — so this doesn't depend
    on collinfo.json always being sorted a particular way.
    """
    try:
        response = httpx.get(
            COLLINFO_URL,
            headers={"User-Agent": settings.user_agent},
            timeout=settings.timeout_seconds,
        )
    except httpx.HTTPError:
        logger.warning("Common Crawl collinfo.json request failed (network/timeout error)")
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("Common Crawl collinfo.json returned HTTP %d", response.status_code)
        return CommonCrawlIndexResolution(
            success=False,
            reason=f"Common Crawl collinfo.json request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Common Crawl collinfo.json returned a non-JSON response")
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json request failed: response was not valid JSON.",
        )

    if not isinstance(payload, list):
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json response was not a list.",
        )

    best_id: str | None = None
    best_key: tuple[int, int] | None = None
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        key = _parse_crawl_index_id(entry_id)
        if key is None:
            continue
        if best_key is None or key > best_key:
            best_key = key
            best_id = entry_id

    if best_id is None:
        return CommonCrawlIndexResolution(
            success=False,
            reason="Common Crawl collinfo.json contained no recognizable crawl index id.",
        )

    return CommonCrawlIndexResolution(
        success=True,
        reason="Resolved the latest Common Crawl index from collinfo.json.",
        crawl_index=best_id,
    )


def resolve_common_crawl_index(settings: CommonCrawlSettings) -> CommonCrawlIndexResolution:
    """Decides which Common Crawl index id to search against.

    When `settings.index` is an explicit "CC-MAIN-YYYY-NN" id (already
    validated by services/common_crawl_settings.py), it's used as-is —
    no extra HTTP request is made to confirm it exists, since that
    would be an unnecessary additional external call for the common
    case. Only `settings.index == "latest"` triggers a collinfo.json
    fetch (see `_fetch_latest_index`).
    """
    if settings.index != "latest":
        return CommonCrawlIndexResolution(
            success=True,
            reason="Using the configured Common Crawl index.",
            crawl_index=settings.index,
        )
    return _fetch_latest_index(settings)


def _parse_candidates(
    text: str, crawl_index: str, max_results: int
) -> tuple[CommonCrawlCandidate, ...]:
    """Parses the Index API's JSON Lines (one JSON object per line)
    response body into CommonCrawlCandidate entries, skipping blank
    lines and any line that isn't a parseable JSON object with a
    usable `url`. Stops once `max_results` candidates have been
    collected, regardless of how many lines remain.
    """
    candidates: list[CommonCrawlCandidate] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue

        url = _string_or_none(raw.get("url"))
        if url is None:
            continue

        candidates.append(
            CommonCrawlCandidate(
                url=url,
                timestamp=_string_or_none(raw.get("timestamp")),
                status=_int_or_none(raw.get("status")),
                mime=_string_or_none(raw.get("mime")),
                digest=_string_or_none(raw.get("digest")),
                length=_int_or_none(raw.get("length")),
                offset=_int_or_none(raw.get("offset")),
                filename=_string_or_none(raw.get("filename")),
                crawl_index=crawl_index,
            )
        )
        if len(candidates) >= max_results:
            break

    return tuple(candidates)


def search_common_crawl_domain(domain: str, settings: CommonCrawlSettings) -> CommonCrawlIndexResult:
    """Searches the Common Crawl Index API for URLs under `domain`
    (e.g. "cybozu.co.jp"), restricted to successful (`status:200`) HTML
    (`mime:text/html`) captures, capped at `settings.max_results`.

    This function itself does not decide whether calling Common Crawl
    is *allowed* — see the module docstring: any `COMMON_CRAWL_ENABLED`
    gating belongs to a future provider layer, not here.

    Issues at most two HTTP requests: one to resolve the index (only
    when `settings.index == "latest"` — see `resolve_common_crawl_index`)
    and one to the Index API itself. Never raises; every failure path
    (invalid domain, index resolution failure, network/timeout error,
    non-200 response, empty result) returns a `CommonCrawlIndexResult`
    with `status="unavailable"` and a safe, credential-free `reason`
    (there are no credentials to leak in the first place, since Common
    Crawl is a public, unauthenticated dataset).
    """
    normalized_domain = _normalize_domain(domain)
    if normalized_domain is None:
        return CommonCrawlIndexResult(
            status="unavailable",
            reason="Common Crawl domain is empty or not a valid hostname.",
        )

    resolution = resolve_common_crawl_index(settings)
    if not resolution.success:
        return CommonCrawlIndexResult(status="unavailable", reason=resolution.reason)

    crawl_index = resolution.crawl_index or ""
    url = f"{COMMON_CRAWL_HOST}/{crawl_index}-index"
    params = [
        ("url", f"{normalized_domain}/*"),
        ("output", "json"),
        ("filter", "status:200"),
        ("filter", "mime:text/html"),
        ("limit", str(settings.max_results)),
    ]

    try:
        response = httpx.get(
            url,
            params=params,
            headers={"User-Agent": settings.user_agent},
            timeout=settings.timeout_seconds,
        )
    except httpx.HTTPError:
        logger.warning("Common Crawl Index API request failed (network/timeout error)")
        return CommonCrawlIndexResult(
            status="unavailable",
            reason="Common Crawl Index API request failed due to a network or timeout error.",
            crawl_index=crawl_index,
        )

    if response.status_code != 200:
        logger.warning("Common Crawl Index API returned HTTP %d", response.status_code)
        return CommonCrawlIndexResult(
            status="unavailable",
            reason=f"Common Crawl Index API request failed with HTTP {response.status_code}.",
            crawl_index=crawl_index,
        )

    candidates = _parse_candidates(response.text, crawl_index, settings.max_results)
    if not candidates:
        return CommonCrawlIndexResult(
            status="unavailable",
            reason="Common Crawl index result was empty.",
            crawl_index=crawl_index,
        )

    return CommonCrawlIndexResult(
        status="real",
        reason=f"Common Crawl Index API request succeeded ({len(candidates)} candidate(s)).",
        crawl_index=crawl_index,
        candidates=candidates,
    )
