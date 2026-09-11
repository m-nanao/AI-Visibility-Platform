"""FastAPI app for the LLMO / AI Visibility Platform analysis engine.

This mirrors the shape of the TypeScript `AnalysisResult` type
(`app/lib/types.ts`), so that Next.js's `/api/analyze` route can call
this service directly without any response transformation.

The `cooccurrenceRanking`, `contextAnalysis`, `summary`, and
`improvements` fields are computed for real (see
services/cooccurrence.py, services/context_analysis.py,
services/brand_summary.py, and services/improvement_suggestions.py)
from one of, in priority order:
1. `documents` supplied in the request
2. text fetched from `urls` supplied in the request (services/web_fetcher.py)
3. development sample documents (services/sample_documents.py), if
   neither of the above is given

All three sources are wrapped as Document[] (see
docs/11_architecture_v1.md "4. Document Pipeline") before reaching the
Analyzer, so `analyze()` never branches on source type past that point.
The Document[] is also split into DocumentChunk[] (services/document_chunker.py,
the Pipeline's "Chunker" stage) — `contextAnalysis` is the first
Analyzer logic that actually reads chunks (a lightweight, rule-based
categorization, no AI/LLM calls); `cooccurrenceRanking` still reads
whole Document.text directly. `summary` (brand-summary-lite) is built
on top of the other two sections' already-computed output (mention
counts, cooccurrence keywords, context categories), and `improvements`
(improvement-suggestions-lite) is built on top of all three — again no
AI/LLM/DataForSEO calls anywhere in this chain, just simple
counting/bucketing/condition rules with an explainable reason attached
to each suggestion.

`aiOverviewComparison` is fixed placeholder data by default, but is
served through a swappable provider (see
services/ai_overview_provider.py) rather than being hardcoded here:
mode is "mock" (default), "off" (section disabled), or "dataforseo"
(connects to DataForSEO **Sandbox only** — Live is deliberately never
called, see services/ai_overview_provider.py and
services/dataforseo_client.py), selected via the
AI_OVERVIEW_PROVIDER_MODE env var and optionally overridden per-request
via `aiOverviewMode` only when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true.
`meta.sections` reports the resulting status per-section so callers
don't have to guess; `meta.aiOverviewProvider` additionally reports
which mode actually ran and why. See docs/05_tasks.md (Phase 4) for
what's next (a real DataForSEO Live connection, still unimplemented).

`aiOverviewComparison` may also gain one extra "ChatGPT (OpenAI API)"
card (see services/chatgpt_provider.py) — an independent, optional
single OpenAI API call, off by default (`CHATGPT_PROVIDER_MODE=off`),
skipped whenever `aiOverviewMode` resolves to "mock", and reported via
`meta.chatgptProvider`. This never replaces the Google AI Mode/AI
Overview card above; the two providers don't know about each other.

The primary Document[] above may also gain one supplementary Document
from Common Crawl (see services/common_crawl_index.py /
common_crawl_warc.py / common_crawl_document_provider.py and
docs/13_common_crawl_mvp_design.md) via `_build_common_crawl_documents()`
below — off by default (`commonCrawlMode` omitted or "off", and even
when "domain" is requested, only runs when `COMMON_CRAWL_ENABLED=true`).
When it runs, a domain (from `commonCrawlDomain`, or else `urls[0]`'s
hostname) is searched against Common Crawl's Index API, and up to
COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE candidates are fetched/converted
into Documents (trying at most COMMON_CRAWL_MAX_CANDIDATES_TO_TRY
candidates in order, skipping any that fail), which are appended to
the primary Document[] before cooccurrence/chunking/analysis — so
existing Analyzer logic sees it like any other Document, with no
special-casing. A Common Crawl failure never raises and never affects
`documentsSource`/the section statuses; it's only reflected in
`meta.commonCrawlProvider`. No UI exists for this yet — it's reachable
only by sending `commonCrawlMode`/`commonCrawlDomain` directly in the
POST body.
"""

import hmac
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models import (
    MAX_BRAND_NAME_LENGTH,
    MAX_DOCUMENT_LENGTH,
    MAX_DOCUMENTS_COUNT,
    MAX_TOTAL_DOCUMENTS_LENGTH,
    MAX_URLS,
    AIOverviewProviderInfo,
    AnalysisMeta,
    AnalysisResult,
    AnalysisRunBrand,
    AnalysisRunComparisonResponse,
    AnalysisRunDetailResponse,
    AnalysisRunInfo,
    AnalysisRunListItem,
    AnalysisRunListResponse,
    AnalysisSectionStatuses,
    AnalyzeRequest,
    ChatGptProviderInfo,
    CommonCrawlProviderInfo,
    CommonCrawlProviderMode,
    Document,
    DocumentsSource,
    SectionStatus,
    UrlFetchResult,
)
from services.ai_overview_provider import build_ai_overview_comparison, resolve_ai_overview_mode
from services.analysis_history_comparison import build_comparison_response
from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    get_analysis_run as repository_get_analysis_run,
    get_connection as open_history_db_connection,
    get_previous_analysis_run_for_brand as repository_get_previous_analysis_run_for_brand,
    list_analysis_runs as repository_list_analysis_runs,
    save_analysis_history,
)
from services.auth_settings import load_auth_settings
from services.jwt_auth import JWTAuthError, extract_bearer_token, verify_supabase_jwt
from services.project_access import can_user_access_analysis_run, get_accessible_project_ids
from services.brand_summary import build_brand_summary
from services.chatgpt_provider import build_chatgpt_observation, resolve_chatgpt_mode
from services.common_crawl_document_provider import build_common_crawl_document
from services.common_crawl_index import search_common_crawl_domain
from services.common_crawl_settings import load_common_crawl_settings
from services.common_crawl_warc import fetch_common_crawl_warc_record
from services.context_analysis import analyze_contexts
from services.improvement_suggestions import build_improvement_suggestions
from services.cooccurrence import (
    compute_cooccurrence_ranking_from_documents,
    get_tokenizer_mode,
)
from services.db_settings import load_db_settings
from services.document_chunker import chunk_documents
from services.document_normalizer import normalize_text
from services.mock_analysis import build_dummy_analysis
from services.sample_documents import build_sample_documents_as_documents
from services.web_fetcher import fetch_url_texts, to_documents as fetch_results_to_documents

# Common Crawl's Index API can return up to settings.max_results
# candidates, but /analyze only tries this many of them (in order)
# looking for ones that fetch into a usable Document — kept small and
# independent of settings.max_results so a single /analyze call never
# issues an excessive number of WARC fetch requests (see
# docs/13_common_crawl_mvp_design.md's "件数" policy).
COMMON_CRAWL_MAX_CANDIDATES_TO_TRY = 5

# At most this many Common Crawl-sourced Documents are ever added to
# one /analyze call, even if more candidates than this succeed — kept
# small out of consideration for Render's free tier (each additional
# Document is another WARC fetch/parse) and for /analyze's own
# response-time budget. See docs/13_common_crawl_mvp_design.md's "件数"
# policy.
COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE = 3

# Without this, INFO-level logs (e.g. the sample-document notice below)
# are silently dropped: uvicorn's default logging config only sets up
# its own "uvicorn.*" loggers, not the root logger, and Python's
# logging module otherwise only surfaces WARNING+ by default.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# No CORSMiddleware is added deliberately: only the Next.js Route
# Handler (app/api/analyze/route.ts, running server-side) calls this
# API, never the browser directly. Adding a permissive CORS policy
# here would let arbitrary websites call this API straight from a
# user's browser, which is unnecessary exposure for no functional
# benefit. See docs/09_deployment.md for the deployment topology.
app = FastAPI(title="LLMO Analysis API")


def error_response(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Reshape FastAPI/Pydantic's default 422 body (e.g. malformed JSON,
    # or a brandName of the wrong type) into the same {"error": "..."}
    # shape used by the manual checks in analyze() below.
    return error_response("invalid request body")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _validate_documents(documents: list[str]) -> str | None:
    """Returns an error message, or None if documents are within limits."""
    if len(documents) > MAX_DOCUMENTS_COUNT:
        return f"documents must contain {MAX_DOCUMENTS_COUNT} or fewer entries"

    if any(len(doc) > MAX_DOCUMENT_LENGTH for doc in documents):
        return f"each document must be {MAX_DOCUMENT_LENGTH} characters or fewer"

    if sum(len(doc) for doc in documents) > MAX_TOTAL_DOCUMENTS_LENGTH:
        return f"documents must total {MAX_TOTAL_DOCUMENTS_LENGTH} characters or fewer"

    return None


def _documents_from_strings(texts: list[str]) -> list[Document]:
    """Wraps caller-supplied `documents` (POST /analyze) as Document[]
    (see docs/11_architecture_v1.md "4. Document Pipeline"). Each
    text is run through the Normalizer stage (normalize_text()) so
    user_provided text goes through the same Unicode/whitespace
    cleanup as web_fetch text, before either reaches the Analyzer.
    Blank strings are kept as-is (normalize_text("") == "") —
    compute_cooccurrence_ranking() already skips blank documents, and
    not filtering here keeps documentCount honest about what was
    actually submitted.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    return [
        Document(
            id=str(uuid4()),
            sourceType="user_provided",
            fetchedAt=fetched_at,
            text=normalize_text(text),
        )
        for text in texts
    ]


def _resolve_common_crawl_domain(
    requested_domain: str | None, urls: list[str] | None
) -> str | None:
    """Picks the domain to search Common Crawl for: the request's
    explicit `commonCrawlDomain` if given, otherwise the hostname of
    `urls[0]`. Returns None if neither yields anything usable — the
    caller reports that as "unavailable" rather than guessing.

    This does not itself reject dangerous/malformed input — whatever
    string this returns is still passed through
    services/common_crawl_index.py's `search_common_crawl_domain()`,
    which normalizes and validates it against a strict hostname
    allow-list before any HTTP request is made.
    """
    if requested_domain and requested_domain.strip():
        return requested_domain.strip()

    if urls:
        hostname = urlparse(urls[0]).hostname
        if hostname:
            return hostname

    return None


def _build_common_crawl_documents(
    common_crawl_mode: CommonCrawlProviderMode,
    requested_domain: str | None,
    urls: list[str] | None,
) -> tuple[list[Document], CommonCrawlProviderInfo]:
    """Runs the Common Crawl "補完" (supplementary) flow described in
    docs/13_common_crawl_mvp_design.md: resolve a domain, search the
    Index API, then try up to COMMON_CRAWL_MAX_CANDIDATES_TO_TRY
    candidates (in order), skipping any that fail to fetch/convert,
    until COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE Documents have been
    collected or every candidate has been tried.

    Never raises, and never lets a Common Crawl failure affect the rest
    of /analyze — every failure path (mode is "off", Common Crawl is
    disabled, the domain can't be determined, the Index search fails or
    finds nothing, or every candidate fails to fetch/convert) returns an
    empty Document[] plus a CommonCrawlProviderInfo describing why. At
    most COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE Documents are ever
    returned (see docs/13_common_crawl_mvp_design.md's "件数" policy).
    On a "real" result, `CommonCrawlProviderInfo.analyzedUrls` lists the
    source URL of every Document actually added (de-duplicated, never
    including a candidate that failed to fetch/convert) so the UI/依頼者
    can see exactly which pages were analyzed — never HTML/WARC body
    text. None of `search_common_crawl_domain()`/
    `fetch_common_crawl_warc_record()`/`build_common_crawl_document()`
    themselves do any COMMON_CRAWL_ENABLED gating (see their module
    docstrings) — that gating happens here, once, before any of them
    are called.
    """
    if common_crawl_mode == "off":
        return [], CommonCrawlProviderInfo(
            mode="off",
            status="off",
            reason="Common Crawl integration is off.",
        )

    settings = load_common_crawl_settings()
    if not settings.enabled:
        return [], CommonCrawlProviderInfo(
            mode=common_crawl_mode,
            status="off",
            reason="Common Crawl is disabled (COMMON_CRAWL_ENABLED is not true).",
        )

    domain = _resolve_common_crawl_domain(requested_domain, urls)
    if domain is None:
        return [], CommonCrawlProviderInfo(
            mode=common_crawl_mode,
            status="unavailable",
            reason="Common Crawl domain could not be determined from commonCrawlDomain or urls.",
        )

    index_result = search_common_crawl_domain(domain, settings)
    if index_result.status != "real":
        return [], CommonCrawlProviderInfo(
            mode=common_crawl_mode,
            status="unavailable",
            reason=index_result.reason,
            domain=domain,
            crawlIndex=index_result.crawl_index,
        )

    candidate_count = len(index_result.candidates)
    documents: list[Document] = []
    for candidate in index_result.candidates[:COMMON_CRAWL_MAX_CANDIDATES_TO_TRY]:
        if len(documents) >= COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE:
            break

        fetch_result = fetch_common_crawl_warc_record(candidate, settings)
        if fetch_result.status != "real":
            continue

        document_result = build_common_crawl_document(candidate, fetch_result)
        if document_result.status == "real":
            documents.extend(document_result.documents)

    if documents:
        if len(documents) >= COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE:
            reason = f"Common Crawl added {len(documents)} document(s) for {domain}."
        else:
            reason = (
                f"Common Crawl completed with partial results "
                f"({len(documents)} document(s) for {domain})."
            )
        # De-duplicated in insertion order — see CommonCrawlProviderInfo's
        # docstring for why (defensive against the Index API returning
        # more than one capture of the same URL among the candidates
        # that were successfully fetched/converted).
        analyzed_urls: list[str] = []
        seen_urls: set[str] = set()
        for document in documents:
            if document.sourceUrl and document.sourceUrl not in seen_urls:
                seen_urls.add(document.sourceUrl)
                analyzed_urls.append(document.sourceUrl)

        return documents, CommonCrawlProviderInfo(
            mode=common_crawl_mode,
            status="real",
            reason=reason,
            domain=domain,
            crawlIndex=index_result.crawl_index,
            candidateCount=candidate_count,
            documentCount=len(documents),
            analyzedUrls=analyzed_urls,
        )

    return [], CommonCrawlProviderInfo(
        mode=common_crawl_mode,
        status="unavailable",
        reason="Common Crawl found candidates but none could be fetched into a usable document.",
        domain=domain,
        crawlIndex=index_result.crawl_index,
        candidateCount=candidate_count,
    )


@app.post("/analyze", response_model=AnalysisResult)
def analyze(payload: AnalyzeRequest):
    brand_name = (payload.brandName or "").strip()

    if not brand_name:
        return error_response("brandName is required")

    if len(brand_name) > MAX_BRAND_NAME_LENGTH:
        return error_response(
            f"brandName must be {MAX_BRAND_NAME_LENGTH} characters or fewer"
        )

    # Minimal diagnostic logging around each stage of /analyze — added
    # to narrow down where a Render free-tier request was dying (past
    # url fetch, but before any "POST /analyze ... 200/500" completion
    # log ever appeared). Counts/timings only; never document text.
    logger.info("analyze start brandName=%r", brand_name)

    url_fetch_results: list[UrlFetchResult] | None = None
    documents_source: DocumentsSource
    # Document[] actually processed (see docs/11_architecture_v1.md "4.
    # Document Pipeline") — every branch below assigns this, since
    # documents/urls/development_sample are all wrapped as Document[]
    # before reaching the Analyzer.
    documents_list: list[Document]
    # "real" unless the urls path finds zero usable documents (every
    # fetch failed) — see the urls branch below. documents:[] is
    # deliberately *not* treated as unavailable (see docs/07_decisions.md):
    # it's a valid "analyze zero documents" request, not a failure to
    # obtain input.
    cooccurrence_status: SectionStatus = "real"

    # Priority: documents > urls > development sample.
    if payload.documents is not None:
        documents = payload.documents
        validation_error = _validate_documents(documents)
        if validation_error:
            return error_response(validation_error)
        documents_source = "user_provided"
        documents_list = _documents_from_strings(documents)

    elif payload.urls is not None:
        if len(payload.urls) == 0:
            # Unlike documents:[], an empty urls list has no reasonable
            # interpretation as "fetch zero pages on purpose" — it's
            # far more likely to be a caller mistake, so this is a 400
            # rather than a silently-empty analysis.
            return error_response("urls must not be empty")

        if len(payload.urls) > MAX_URLS:
            return error_response(f"urls must contain {MAX_URLS} or fewer entries")

        fetch_results = fetch_url_texts(payload.urls)
        url_fetch_results = [
            UrlFetchResult(url=r.url, success=r.success, error=r.error)
            for r in fetch_results
        ]
        # Failed fetches are never turned into Documents (see
        # web_fetcher.to_documents) — they're already tracked above via
        # url_fetch_results.
        documents_list = fetch_results_to_documents(fetch_results)
        documents_source = "web_fetch"

        logger.info(
            "url fetch complete: %d succeeded, %d failed",
            sum(1 for r in fetch_results if r.success),
            sum(1 for r in fetch_results if not r.success),
        )

        failed = [r for r in fetch_results if not r.success]
        if failed:
            # Full reasons (which may include resolved IPs, connection
            # errors, etc.) go to the server log only — the API
            # response exposes them per-URL via url_fetch_results, but
            # callers building a UI on top of this should not surface
            # the raw `error` text verbatim to end users.
            logger.info(
                "%d of %d url(s) failed to fetch for brandName=%r: %s",
                len(failed),
                len(fetch_results),
                brand_name,
                "; ".join(f"{r.url} ({r.error})" for r in failed),
            )

        if len(documents_list) == 0:
            # Every URL failed: there is nothing to compute
            # cooccurrenceRanking from. This is different from a
            # successful analysis that happens to find no keywords, so
            # it gets its own status instead of "real".
            cooccurrence_status = "unavailable"
            logger.info(
                "all %d url(s) failed to fetch for brandName=%r; cooccurrenceRanking is unavailable",
                len(fetch_results),
                brand_name,
            )

    else:
        documents_list = build_sample_documents_as_documents(brand_name)
        documents_source = "development_sample"
        logger.info(
            "documents/urls not provided for brandName=%r; using %d development sample document(s)",
            brand_name,
            len(documents_list),
        )

    # Common Crawl "補完" (supplementary) Document — independent of, and
    # never affecting the status of, the primary documents/urls/
    # development_sample source above (see
    # docs/13_common_crawl_mvp_design.md). Off by default
    # (commonCrawlMode omitted or "off"); when requested, at most one
    # extra Document is appended before it's counted/chunked/analyzed
    # below, so cooccurrenceRanking/contextAnalysis/summary/improvements
    # all see it exactly like any other Document. A Common Crawl
    # failure never raises and never changes documents_source/
    # cooccurrence_status — it's only reflected in
    # meta.commonCrawlProvider.
    common_crawl_mode: CommonCrawlProviderMode = payload.commonCrawlMode or "off"
    common_crawl_documents, common_crawl_provider = _build_common_crawl_documents(
        common_crawl_mode, payload.commonCrawlDomain, payload.urls
    )
    if common_crawl_documents:
        documents_list = [*documents_list, *common_crawl_documents]
    logger.info(
        "common crawl integration complete: mode=%s status=%s documents=%d",
        common_crawl_mode,
        common_crawl_provider.status,
        len(common_crawl_documents),
    )

    logger.info(
        "document count=%d source=%s",
        len(documents_list),
        documents_source,
    )

    result = build_dummy_analysis(brand_name)
    logger.info("cooccurrence start: mode=%s", get_tokenizer_mode())
    result.cooccurrenceRanking = compute_cooccurrence_ranking_from_documents(
        brand_name, documents_list
    )
    document_count = len(documents_list)
    source_types = sorted({document.sourceType for document in documents_list})
    logger.info("cooccurrence complete: %d keyword(s)", len(result.cooccurrenceRanking))

    # Chunker stage (see docs/11_architecture_v1.md "4. Document
    # Pipeline"): splits Document[] into DocumentChunk[]. Used below by
    # context_analysis.analyze_contexts() — the first Analyzer logic to
    # actually consume Chunker output, rather than just reporting a
    # count. compute_cooccurrence_ranking_from_documents() above still
    # reads whole Document.text directly and is unaffected.
    chunks = chunk_documents(documents_list)
    logger.info("chunking complete: %d chunk(s)", len(chunks))

    # contextAnalysis: lightweight, rule-based (no AI/LLM calls — see
    # services/context_analysis.py). Shares cooccurrence_status with
    # cooccurrenceRanking above since both are derived from the same
    # Document[]/chunk pipeline: "unavailable" when every url fetch
    # failed (nothing to chunk), "real" otherwise (including the
    # documents: [] case, which legitimately analyzes zero chunks).
    result.contextAnalysis = analyze_contexts(brand_name, chunks)
    logger.info("context analysis complete: %d context(s)", len(result.contextAnalysis))

    # brandSummary ("summary" in AnalysisResult): lightweight, rule-based
    # (no AI/LLM calls — see services/brand_summary.py), built from the
    # Document[]/cooccurrenceRanking/contextAnalysis already computed
    # above. Shares cooccurrence_status with the other two sections for
    # the same reason contextAnalysis does: all three are derived from
    # the same Document[]/chunk pipeline.
    result.summary = build_brand_summary(
        brand_name, documents_list, chunks, result.cooccurrenceRanking, result.contextAnalysis
    )
    logger.info("brand summary complete: visibilityScore=%d", result.summary.visibilityScore)

    # aiOverviewComparison: swappable provider (see
    # services/ai_overview_provider.py), independent of the
    # Document[]/cooccurrence_status pipeline above — its mode comes
    # from AI_OVERVIEW_PROVIDER_MODE (env, default "mock"), optionally
    # overridden per-request only when ALLOW_AI_OVERVIEW_MODE_OVERRIDE=true.
    # payload.urls is passed through only so a DataForSEO success can set
    # AIOverviewComparisonItem.ownDomainReferenced (comparing reference
    # domains against the request's own input urls) — it has no effect
    # on which provider/environment runs. Computed before improvements
    # below so build_improvement_suggestions() can look at
    # ownDomainReferenced/referenceSummary for a lightweight suggestion.
    ai_overview_mode = resolve_ai_overview_mode(payload.aiOverviewMode)
    (
        result.aiOverviewComparison,
        ai_overview_status,
        ai_overview_reason,
        ai_overview_environment,
    ) = build_ai_overview_comparison(brand_name, ai_overview_mode, payload.urls)
    logger.info(
        "ai overview comparison complete: mode=%s status=%s",
        ai_overview_mode,
        ai_overview_status,
    )

    # improvements: lightweight, rule-based (no AI/LLM/DataForSEO calls —
    # see services/improvement_suggestions.py), built from the
    # cooccurrenceRanking/contextAnalysis/summary already computed
    # above, plus result.aiOverviewComparison (for at most one
    # suggestion about AI Overview reference state — see
    # services/improvement_suggestions.py's _ai_overview_reference_suggestion;
    # a no-op unless aiOverviewComparison actually ran in "dataforseo"
    # mode) and common_crawl_provider (for at most one suggestion about
    # Common Crawl's fetch outcome — see _common_crawl_suggestion; a
    # no-op when Common Crawl is off, see
    # docs/14_common_crawl_improvement_policy.md for the policy this
    # follows). Shares cooccurrence_status with the other three sections
    # for the same reason they do. Unlike those, build_improvement_suggestions()
    # always returns at least one (fallback) suggestion for genuinely
    # empty input, so when the status is "unavailable" (every url
    # failed) we skip calling it and report [] directly instead —
    # otherwise the fallback suggestion would render as if a
    # computation had actually happened.
    if cooccurrence_status == "unavailable":
        result.improvements = []
    else:
        result.improvements = build_improvement_suggestions(
            brand_name,
            result.summary,
            result.cooccurrenceRanking,
            result.contextAnalysis,
            document_count=document_count,
            source_types=source_types,
            ai_overview_items=result.aiOverviewComparison,
            common_crawl_provider=common_crawl_provider,
        )
    logger.info("improvement suggestions complete: %d suggestion(s)", len(result.improvements))

    # ChatGPT-equivalent observation (see services/chatgpt_provider.py):
    # an independent, optional single OpenAI API call whose result (if
    # any) is appended as an *extra* card to aiOverviewComparison,
    # never replacing the Google AI Mode/AI Overview card computed
    # above. Deliberately skipped whenever aiOverviewMode is "mock" —
    # build_dummy_analysis()'s fixed aiOverviewComparison fixture
    # already has its own "ChatGPT" card, so adding a second, real one
    # here would be a confusing duplicate rather than an enrichment
    # (see services/chatgpt_provider.py's module docstring).
    if ai_overview_mode == "mock":
        chatgpt_mode = "off"
        chatgpt_item = None
        chatgpt_status = "off"
        chatgpt_reason = "ChatGPT observation is disabled while aiOverviewMode is mock."
        chatgpt_environment = "off"
    else:
        chatgpt_mode = resolve_chatgpt_mode(payload.chatgptMode)
        (
            chatgpt_item,
            chatgpt_status,
            chatgpt_reason,
            chatgpt_environment,
        ) = build_chatgpt_observation(brand_name, chatgpt_mode)

    if chatgpt_item is not None:
        result.aiOverviewComparison = [*result.aiOverviewComparison, chatgpt_item]
    logger.info(
        "chatgpt observation complete: mode=%s status=%s",
        chatgpt_mode,
        chatgpt_status,
    )

    result.meta = AnalysisMeta(
        sections=AnalysisSectionStatuses(
            summary=cooccurrence_status,
            cooccurrenceRanking=cooccurrence_status,
            contextAnalysis=cooccurrence_status,
            aiOverviewComparison=ai_overview_status,
            improvements=cooccurrence_status,
        ),
        documentsSource=documents_source,
        generatedAt=datetime.now(timezone.utc).isoformat(),
        urlFetchResults=url_fetch_results,
        documentCount=document_count,
        sourceTypes=source_types,
        chunkCount=len(chunks),
        aiOverviewProvider=AIOverviewProviderInfo(
            mode=ai_overview_mode,
            status=ai_overview_status,
            reason=ai_overview_reason,
            environment=ai_overview_environment,
        ),
        chatgptProvider=ChatGptProviderInfo(
            mode=chatgpt_mode,
            status=chatgpt_status,
            reason=chatgpt_reason,
            environment=chatgpt_environment,
        ),
        commonCrawlProvider=common_crawl_provider,
    )

    # Best-effort DB save (see services/analysis_history_repository.py,
    # docs/19_minimum_db_migration_design.md). Entirely optional and
    # non-blocking: skipped outright when DB_SAVE_ENABLED/DATABASE_URL
    # aren't both set (services/db_settings.py), and
    # save_analysis_history() itself never raises — but the call is
    # still wrapped here as a second layer of defense, so a bug in that
    # module can never turn into a failed /analyze response. The
    # created analysis_runs.id is surfaced as result.analysisRunId when
    # (and only when) the save succeeds — null otherwise (disabled,
    # unconfigured, or failed) — see
    # docs/23_analysis_run_id_and_post_analyze_link_design.md.
    try:
        history_result = save_analysis_history(
            brand_name=brand_name,
            canonical_domain=None,
            input_snapshot={
                "brandName": payload.brandName,
                "urls": payload.urls,
                "commonCrawlMode": payload.commonCrawlMode,
                "commonCrawlDomain": payload.commonCrawlDomain,
                "aiOverviewMode": payload.aiOverviewMode,
                "chatgptMode": payload.chatgptMode,
            },
            source_summary=dict(Counter(document.sourceType for document in documents_list)),
            result_json=result.model_dump(),
            visibility_score=result.summary.visibilityScore,
            meta_json=result.meta.model_dump(),
            status="partial" if cooccurrence_status == "unavailable" else "completed",
        )
    except Exception:
        logger.exception("Unexpected error while saving analysis history")
        history_result = None
    logger.info(
        "analysis history save %s",
        "succeeded" if history_result is not None else "skipped or failed",
    )
    result.analysisRunId = (
        history_result.analysis_run_id if history_result is not None else None
    )

    return result


# --- Analysis history read API (GET /analysis-runs, GET
# /analysis-runs/{id}, GET /analysis-runs/{id}/comparison) — see
# docs/20_analysis_history_read_api_design.md. Entirely separate from
# /analyze above: no request/response field of /analyze is touched by
# anything below (AnalysisResult.analysisRunId is set above, inside the
# /analyze handler itself — nothing here adds to it). Gated by
# READ_HISTORY_ENABLED (a flag independent of DB_SAVE_ENABLED, since
# saving is an internal write with no external caller while these
# endpoints are reachable by anyone who can call this service) *and*,
# on top of that, one of two authorization paths — see
# _resolve_history_access() below and
# docs/32_backend_jwt_verification_design.md "20. JWT/project権限判定
# の優先化" (the priority these two paths are checked in):
#
# 1. AUTH_JWT_ENABLED=true and an Authorization header is present —
#    a Supabase Auth access token in Authorization: Bearer is
#    verified, then always scoped to the caller's accessible projects
#    via services.project_access.py. A JWT is *never* sufficient on
#    its own to see any history; project scoping is mandatory
#    whenever this path is taken. This path is authoritative whenever
#    it applies: a broken/expired JWT or a JWT-verification
#    misconfiguration surfaces as 401/503 and never falls back to
#    HISTORY_READ_TOKEN, even if that header is also present and
#    correct.
# 2. Otherwise (AUTH_JWT_ENABLED=false, or no Authorization header at
#    all), the existing shared-secret HISTORY_READ_TOKEN in the
#    X-History-Read-Token header
#    (docs/24_auth_rls_history_access_design.md "7. backend APIでの
#    アクセス制御案") — unrestricted, exactly as before this feature
#    existed. An unauthenticated caller (no Authorization header) can
#    only ever take this path.
#
# READ_HISTORY_ENABLED=true alone still isn't enough to serve a
# request either way.
HISTORY_READ_TOKEN_HEADER = "X-History-Read-Token"
AUTHORIZATION_HEADER = "Authorization"
HISTORY_READ_NOT_CONFIGURED_MESSAGE = "analysis history read API is not enabled"
HISTORY_READ_DB_NOT_CONFIGURED_MESSAGE = "analysis history read API is not configured"
HISTORY_READ_TOKEN_NOT_CONFIGURED_MESSAGE = "analysis history read token is not configured"
HISTORY_READ_ACCESS_DENIED_MESSAGE = "analysis history read access denied"
HISTORY_READ_INVALID_TOKEN_MESSAGE = "invalid or expired authentication token"
HISTORY_READ_JWT_NOT_CONFIGURED_MESSAGE = "analysis history JWT verification is not configured"
HISTORY_READ_FAILED_MESSAGE = "failed to read analysis history"

# JWTAuthError.reason values (see services/jwt_auth.py) that mean "this
# server can't verify any JWT right now" rather than "this particular
# token is bad" — mapped to 503, not 401, so an operator can tell a
# missing/misconfigured SUPABASE_JWKS_URL (or an unreachable JWKS
# endpoint) apart from an actually-invalid caller token.
_JWT_UNAVAILABLE_REASONS = frozenset({"not_configured", "jwks_fetch_failed"})


@dataclass(frozen=True)
class HistoryAccessContext:
    """Result of successfully authorizing a history-read request — see
    docs/32_backend_jwt_verification_design.md "15. project権限判定の
    実装状況" and "16"/"17" for how this connects the JWT verification
    and project-access helpers built in earlier tasks.

    mode="history_token": the existing X-History-Read-Token gate
    passed. Behaves exactly as before this feature existed — no
    project scoping, `user_id`/`project_ids` are both None. Only
    reached when AUTH_JWT_ENABLED=false, or the request has no
    Authorization header at all (see _resolve_history_access()'s
    docstring) — a request that also carries an Authorization header
    while AUTH_JWT_ENABLED=true takes the JWT path below instead,
    regardless of whether HISTORY_READ_TOKEN is also present/correct.

    mode="jwt": a valid Supabase Auth JWT was presented (with
    AUTH_JWT_ENABLED=true). `user_id` is always set; `project_ids` is
    the caller's accessible project id list from
    services.project_access.get_accessible_project_ids() — this can be
    an empty list, meaning "no accessible projects". Callers must
    always apply `project_ids` as a filter (or an explicit membership
    check) and must never treat mode="jwt" alone as "show everything".
    """

    mode: Literal["history_token", "jwt"]
    user_id: str | None = None
    project_ids: list[str] | None = None


def _resolve_history_access(request: Request) -> HistoryAccessContext | JSONResponse:
    """Returns a HistoryAccessContext once the request is authorized to
    proceed, or a JSONResponse to return immediately otherwise. Checked
    first thing by all three read API endpoints below — supersedes the
    old _check_history_read_access() (same READ_HISTORY_ENABLED/
    DATABASE_URL/HISTORY_READ_TOKEN checks, now also resolving a JWT).

    Resolution order (see docs/32_backend_jwt_verification_design.md
    "20. JWT/project権限判定の優先化" for the migration this
    implements):
    1. READ_HISTORY_ENABLED=false -> 503 (feature off) -> DATABASE_URL
       unset -> 503 (misconfigured) -> HISTORY_READ_TOKEN unset -> 503
       (misconfigured) — identical to before this task, regardless of
       AUTH_JWT_ENABLED or any Authorization header.
    2. AUTH_JWT_ENABLED=true and an Authorization header is present
       (non-empty) -> the JWT path is authoritative and
       HISTORY_READ_TOKEN is *not* consulted at all, even if the
       header is also present and correct: parse and verify the JWT
       (services/jwt_auth.py), then resolve the caller's accessible
       projects (services/project_access.py) -> mode="jwt". A
       malformed Authorization header or a JWT that fails
       verification for any reason -> 401, except when this server
       itself can't verify any JWT right now (SUPABASE_JWKS_URL
       unset, or its JWKS endpoint unreachable) -> 503, and a DB
       failure while resolving accessible projects -> 503 (fails
       closed). None of these failures ever fall back to
       HISTORY_READ_TOKEN — a present-but-broken JWT must surface as
       an error, not silently degrade to the legacy path, or a
       production JWT/project-access regression would be
       undetectable as long as the frontend also keeps sending
       HISTORY_READ_TOKEN.
    3. Otherwise (AUTH_JWT_ENABLED=false, or no Authorization header
       at all) -> X-History-Read-Token header correct ->
       mode="history_token", unrestricted — identical to before this
       task. This is the only path a request with no Authorization
       header (e.g. an unauthenticated caller, or an internal/legacy
       caller) can take.
    4. Otherwise (no usable credentials of either kind) -> 403,
       identical to before this task.

    The HISTORY_READ_TOKEN comparison uses hmac.compare_digest() to
    avoid a timing side-channel. Neither HISTORY_READ_TOKEN nor a JWT
    (or any part of one) is ever included in a response body or
    logged.
    """
    settings = load_db_settings()

    if not settings.read_history_enabled:
        return error_response(HISTORY_READ_NOT_CONFIGURED_MESSAGE, status_code=503)

    if settings.database_url is None:
        return error_response(HISTORY_READ_DB_NOT_CONFIGURED_MESSAGE, status_code=503)

    if settings.history_read_token is None:
        return error_response(HISTORY_READ_TOKEN_NOT_CONFIGURED_MESSAGE, status_code=503)

    auth_settings = load_auth_settings()
    authorization_header = request.headers.get(AUTHORIZATION_HEADER)

    if auth_settings.jwt_enabled and authorization_header:
        try:
            token = extract_bearer_token(authorization_header)
            authenticated_user = verify_supabase_jwt(token, auth_settings)
        except JWTAuthError as exc:
            if exc.reason in _JWT_UNAVAILABLE_REASONS:
                return error_response(HISTORY_READ_JWT_NOT_CONFIGURED_MESSAGE, status_code=503)
            return error_response(HISTORY_READ_INVALID_TOKEN_MESSAGE, status_code=401)

        try:
            with open_history_db_connection() as conn:
                project_ids = get_accessible_project_ids(conn, authenticated_user.user_id)
        except Exception:
            logger.exception("Failed to resolve accessible projects for JWT-authenticated request")
            return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

        return HistoryAccessContext(
            mode="jwt", user_id=authenticated_user.user_id, project_ids=project_ids
        )

    provided_token = request.headers.get(HISTORY_READ_TOKEN_HEADER, "")
    if provided_token and hmac.compare_digest(provided_token, settings.history_read_token):
        return HistoryAccessContext(mode="history_token")

    return error_response(HISTORY_READ_ACCESS_DENIED_MESSAGE, status_code=403)


@app.get("/analysis-runs", response_model=AnalysisRunListResponse)
def list_analysis_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    brand: str | None = None,
    status: str | None = None,
):
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    try:
        if access.mode == "jwt":
            # project_ids is always passed explicitly here (never
            # omitted) — an empty list means "no accessible projects"
            # and list_analysis_runs() short-circuits to [] without
            # touching the DB, rather than this ever falling back to
            # the unrestricted call below.
            items = repository_list_analysis_runs(
                limit=limit,
                offset=offset,
                brand=brand,
                status=status,
                project_ids=access.project_ids,
            )
        else:
            items = repository_list_analysis_runs(
                limit=limit, offset=offset, brand=brand, status=status
            )
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    return AnalysisRunListResponse(
        items=[AnalysisRunListItem(**item) for item in items],
        limit=limit,
        offset=offset,
    )


@app.get(
    "/analysis-runs/{analysis_run_id}/comparison",
    response_model=AnalysisRunComparisonResponse,
)
def get_analysis_run_comparison(analysis_run_id: str, request: Request):
    """Compares `analysis_run_id` against the same brand's immediately
    preceding run — see docs/25_analysis_history_comparison_design.md.
    Defined *before* GET /analysis-runs/{analysis_run_id} below so that
    a request for .../comparison is never captured by the shorter
    path's {analysis_run_id} parameter (Starlette's router already
    disambiguates these by segment count, but the explicit ordering
    keeps the intent obvious and matches this file's existing
    most-specific-route-first convention).

    In JWT mode, access is checked against `analysis_run_id` (the
    *current* run) before anything is fetched — a caller who can't see
    the current run gets 403 without learning whether it even exists,
    same as the detail endpoint below. The previous run is then looked
    up scoped to the current run's own project_id (see
    services.analysis_history_repository.get_previous_analysis_run_for_brand()'s
    `project_id` parameter), so a comparison can never surface a run
    from a project other than the one already authorized above — see
    docs/32_backend_jwt_verification_design.md "project境界".
    """
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    if access.mode == "jwt":
        try:
            with open_history_db_connection() as conn:
                allowed = can_user_access_analysis_run(
                    conn, access.user_id, analysis_run_id
                )
        except Exception:
            logger.exception(
                "Failed to check analysis run access for JWT-authenticated request"
            )
            return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)
        if not allowed:
            return error_response(HISTORY_READ_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        current = repository_get_analysis_run(analysis_run_id)
        if current is None:
            return error_response("analysis run not found", status_code=404)

        previous = repository_get_previous_analysis_run_for_brand(
            analysis_run_id,
            project_id=current["projectId"] if access.mode == "jwt" else None,
        )
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    current_run = {
        "id": current["id"],
        "startedAt": current["run"]["startedAt"],
        "result": current["result"],
    }

    return AnalysisRunComparisonResponse(
        **build_comparison_response(current_run, previous)
    )


@app.get("/analysis-runs/{analysis_run_id}", response_model=AnalysisRunDetailResponse)
def get_analysis_run(analysis_run_id: str, request: Request):
    """In JWT mode, access is checked against `analysis_run_id` before
    the detail is even fetched — a caller who can't see this run gets
    403 without learning whether it exists (a nonexistent id and an
    inaccessible id are indistinguishable in that mode, by design; see
    docs/32_backend_jwt_verification_design.md "10. エラー設計"'s note
    on not leaking existence). The `analysis run not found` 404 below
    is still reachable in JWT mode only for the unlikely race where the
    run is deleted between the access check and the fetch; it remains
    the primary path, unchanged, for the history_token mode."""
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    if access.mode == "jwt":
        try:
            with open_history_db_connection() as conn:
                allowed = can_user_access_analysis_run(
                    conn, access.user_id, analysis_run_id
                )
        except Exception:
            logger.exception(
                "Failed to check analysis run access for JWT-authenticated request"
            )
            return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)
        if not allowed:
            return error_response(HISTORY_READ_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        detail = repository_get_analysis_run(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    if detail is None:
        return error_response("analysis run not found", status_code=404)

    return AnalysisRunDetailResponse(
        id=detail["id"],
        brand=AnalysisRunBrand(**detail["brand"]),
        run=AnalysisRunInfo(**detail["run"]),
        result=detail["result"],
        meta=detail["meta"],
    )
