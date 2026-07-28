"""Converts Common Crawl Index/WARC results into `Document[]` — the
"Provider" stage of the Document Pipeline (see
docs/11_architecture_v1.md "4. Document Pipeline") for the
`common_crawl` source, playing the same role services/web_fetcher.py's
`to_documents()` plays for `web_fetch` and
services/sample_documents.py's `build_sample_documents_as_documents()`
plays for `development_sample`.

This module does not call Common Crawl itself — it only converts
already-fetched results (see services/common_crawl_index.py's
`CommonCrawlCandidate` and services/common_crawl_warc.py's
`CommonCrawlFetchResult`) into `Document`. It does not search Common
Crawl, does not fetch WARC records, does not decide whether Common
Crawl integration is enabled, and is not called from `/analyze` or the
UI yet — wiring a search -> fetch -> Document pipeline together, and
integrating it into `/analyze`, are later steps (see
docs/13_common_crawl_mvp_design.md).

HTML is cleaned through the existing Cleaner stage
(services/document_cleaner.py's `clean_html_to_text()`/`extract_title()`
— unchanged, no Common Crawl-specific HTML parsing added) and then
through the existing Normalizer stage
(services/document_normalizer.py's `normalize_text()`), exactly like
`web_fetch` and `development_sample` text already are — Common Crawl
text reaches the Analyzer through the same path.

Only bounded, already-validated data is ever converted — no raw WARC
bytes, and no oversized HTML/cleaned text (both are already capped
upstream, by common_crawl_warc.MAX_HTML_CHARS and
document_cleaner.MAX_BODY_TEXT_LENGTH respectively). `reason` fields on
this module's result types never contain HTML/cleaned body text, WARC
bytes, or a secret — there is nothing secret to leak in the first
place, since Common Crawl is a public, unauthenticated dataset.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from models import Document
from services.common_crawl_index import CommonCrawlCandidate
from services.common_crawl_warc import CommonCrawlFetchResult
from services.document_cleaner import clean_html_to_text, extract_title
from services.document_normalizer import normalize_text


@dataclass(frozen=True)
class CommonCrawlDocumentResult:
    """Outcome of converting one or more Common Crawl (candidate,
    fetch_result) pairs into Document[]. Mirrors this codebase's
    existing Common Crawl result types (CommonCrawlIndexResult,
    CommonCrawlFetchResult) — "real" only when at least one Document
    was actually produced, "unavailable" otherwise, with a short, safe
    `reason`.
    """

    status: Literal["real", "unavailable"]
    reason: str
    documents: tuple[Document, ...] = ()


def _unavailable(reason: str) -> CommonCrawlDocumentResult:
    return CommonCrawlDocumentResult(status="unavailable", reason=reason)


def build_common_crawl_document(
    candidate: CommonCrawlCandidate,
    fetch_result: CommonCrawlFetchResult,
) -> CommonCrawlDocumentResult:
    """Converts one Common Crawl candidate + its fetched WARC result
    into a single Document, wrapped in a CommonCrawlDocumentResult
    (`documents` has 0 or 1 element).

    `candidate.url` is always used as the Document's `sourceUrl` (not
    `fetch_result.url`) — the two are expected to agree, but the
    candidate is the identity the caller already has a handle on, and
    this function makes no attempt to reconcile a mismatch.

    Never raises. Every failure path (the fetch itself having failed,
    a missing/empty HTML body, or the Cleaner/Normalizer producing
    empty text — e.g. a page that was all script/nav/ads) returns
    `status="unavailable"` with a short, safe reason — never the HTML
    or WARC body itself.
    """
    if fetch_result.status != "real":
        return _unavailable("Common Crawl fetch result was unavailable.")

    if not fetch_result.html or not fetch_result.html.strip():
        return _unavailable("Common Crawl fetch result did not contain HTML.")

    cleaned_text = clean_html_to_text(fetch_result.html, source_url=candidate.url)
    normalized_text = normalize_text(cleaned_text)
    if not normalized_text.strip():
        return _unavailable("Common Crawl cleaned text was empty.")

    title = extract_title(fetch_result.html)

    document = Document(
        id=str(uuid4()),
        sourceType="common_crawl",
        sourceUrl=candidate.url,
        title=title,
        domain=urlparse(candidate.url).hostname,
        fetchedAt=datetime.now(timezone.utc).isoformat(),
        text=normalized_text,
        metadata={
            "provider": "common_crawl",
            "crawlIndex": candidate.crawl_index or None,
            "warcFilename": candidate.filename,
            "warcOffset": candidate.offset,
            "warcLength": candidate.length,
            "warcTimestamp": candidate.timestamp,
            "mime": candidate.mime,
            "status": candidate.status,
            "digest": candidate.digest,
            "fetchedBytes": fetch_result.fetched_bytes,
            "contentType": fetch_result.content_type,
        },
    )

    return CommonCrawlDocumentResult(
        status="real",
        reason="Common Crawl document created successfully.",
        documents=(document,),
    )


def build_common_crawl_documents(
    pairs: list[tuple[CommonCrawlCandidate, CommonCrawlFetchResult]],
) -> CommonCrawlDocumentResult:
    """Converts each (candidate, fetch_result) pair independently — one
    pair's failure never drops the others, mirroring
    services/web_fetcher.py's per-URL failure isolation. `status="real"`
    once at least one Document was produced; `status="unavailable"`
    only when every pair failed (or `pairs` was empty).

    Not currently used by anything in this codebase — multi-candidate
    fetching is still out of scope (see module docstring) — but is
    provided so a future caller doing that doesn't need to reinvent the
    "convert each independently, keep the successes" aggregation.
    """
    documents: list[Document] = []
    failures = 0

    for candidate, fetch_result in pairs:
        result = build_common_crawl_document(candidate, fetch_result)
        if result.status == "real":
            documents.extend(result.documents)
        else:
            failures += 1

    if not documents:
        return CommonCrawlDocumentResult(
            status="unavailable",
            reason="No Common Crawl candidate could be converted into a Document.",
        )

    return CommonCrawlDocumentResult(
        status="real",
        reason=f"Converted {len(documents)} Common Crawl candidate(s) into Document(s) ({failures} failed).",
        documents=tuple(documents),
    )
