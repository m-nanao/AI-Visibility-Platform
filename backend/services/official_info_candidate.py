"""Task 6-D-5B (feature/official-info-candidate): fetches
`AnalyzeRequest.officialUrl` — a user-specified "official site"
candidate for a future fact-comparison task (Task 6-D-5C) — and
reduces the outcome to `models.OfficialInfoCandidate`.

**This module never decides whether `officialUrl` is trustworthy or
authentic.** It only records "the caller supplied this URL, and this
application was (or wasn't) able to fetch *something* from it" — see
models.OfficialInfoCandidate's own docstring for the full "candidate,
never verified" contract. No ownership/authenticity check of any kind
is performed, by design, matching every other provider's own
`official_url` parameter in this codebase (chatgpt_websearch_provider.py,
claude_websearch_provider.py, gemini_external_document_provider.py),
all of which are always called with `None` today for the identical
reason.

**Deliberately reuses services/web_fetcher.py's existing fetch/clean
pipeline unchanged** — same SSRF protections (`_is_safe_url()`: http(s)
only, no private/loopback/link-local/reserved IPs, no redirect
following), same timeout (`FETCH_TIMEOUT_SECONDS`), same cleaned-text
cap (`document_cleaner.MAX_BODY_TEXT_LENGTH`, 5000 chars). This module
adds no new fetch mechanism and no new network-facing code at all.

**Never adds the fetched Document to the request's own `documents_list`**
— `officialUrl` is a separate concept from `urls[]` (Task 6-D-5B item
1's own requirement: "既存のurls[]とは役割を区別"), so a URL fetched
only because of `officialUrl` must never silently start participating
in co-occurrence ranking/context analysis, which read `documents_list`
directly. The returned `OfficialInfoCandidate` carries only metadata
(`hasText`, `title`, `fetchedAt`, `documentId`) — never the document's
own text — see models.OfficialInfoCandidate's own docstring for why
that is a deliberate, scoped omission, not an oversight.

**Reuses an already-fetched Document when `officialUrl` happens to
also appear in this same request's `urls[]`** (Task 6-D-5B item 2's
own requirement) — this avoids a second HTTP request to the same
origin within one analysis. The match is an **exact string comparison
only** (`document.sourceUrl == official_url`) — no normalization
(trailing slash, query string, scheme-casing, etc.) is attempted, so a
semantically-identical but textually-different URL is treated as a
distinct fetch. This mirrors this codebase's general convention of
never guessing/inferring equivalence it cannot verify.
"""

from models import Document, OfficialInfoCandidate
from services.web_fetcher import fetch_url_texts, to_documents


def build_official_info_candidate(
    official_url: str | None,
    documents_list: list[Document],
) -> OfficialInfoCandidate | None:
    """Returns `None` when `official_url` is falsy (not provided) —
    preserving every existing behavior exactly as before this feature
    existed (Task 6-D-5B item 1's own backward-compatibility
    requirement). Otherwise always returns an `OfficialInfoCandidate`
    with `status` set to `"success"` or `"failed"` — never raises, and
    never fabricates a success result when the fetch itself failed.
    """
    if not official_url:
        return None

    existing = next(
        (
            document
            for document in documents_list
            if document.sourceType == "web_fetch" and document.sourceUrl == official_url
        ),
        None,
    )
    if existing is not None:
        return OfficialInfoCandidate(
            requestedUrl=official_url,
            status="success",
            fetchedUrl=existing.sourceUrl,
            title=existing.title,
            fetchedAt=existing.fetchedAt,
            hasText=bool(existing.text),
            documentId=existing.id,
        )

    results = fetch_url_texts([official_url])
    fetched_documents = to_documents(results)
    if not fetched_documents:
        error = results[0].error if results else "official URL fetch returned no result."
        return OfficialInfoCandidate(
            requestedUrl=official_url,
            status="failed",
            error=error,
        )

    document = fetched_documents[0]
    return OfficialInfoCandidate(
        requestedUrl=official_url,
        status="success",
        fetchedUrl=document.sourceUrl,
        title=document.title,
        fetchedAt=document.fetchedAt,
        hasText=bool(document.text),
        # documentId is intentionally left unset (None) for a freshly
        # independent fetch — see OfficialInfoCandidate's own
        # docstring: this field only ever identifies a Document that
        # was *also* one of this request's own `urls[]` fetches, never
        # a newly-minted id for a standalone officialUrl-only fetch.
    )
