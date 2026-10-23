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

It may similarly gain a "Claude (Anthropic API)" card (see
services/claude_provider.py, off by default via
`CLAUDE_PROVIDER_MODE=off`, reported via `meta.claudeProvider`) and a
"Gemini (Google API)" card (see services/gemini_provider.py, off by
default via `GEMINI_PROVIDER_MODE=off`, reported via
`meta.geminiProvider`). Unlike ChatGPT, neither is skipped when
`aiOverviewMode` is "mock" — see services/claude_provider.py's module
docstring for why. Each of the four observation providers here
(Google AI Mode/AI Overview, ChatGPT, Claude, Gemini) is fully
independent — a single non-browsing text-generation observation, not a
guarantee about that AI service's overall behavior — see
docs/36_multi_ai_comparison_design.md.

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
import re
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models import (
    MAX_BRAND_NAME_LENGTH,
    MAX_DOCUMENT_LENGTH,
    MAX_DOCUMENTS_COUNT,
    MAX_TOTAL_DOCUMENTS_LENGTH,
    MAX_URLS,
    AIOverviewProviderInfo,
    AnalysisJobAcceptedResponse,
    AnalysisJobCreateRequest,
    AnalysisJobResultResponse,
    AnalysisJobStatusResponse,
    AnalysisMeta,
    AnalysisResult,
    AnalysisRunBrand,
    AnalysisRunComparisonResponse,
    AnalysisRunDetailResponse,
    AnalysisRunInfo,
    AnalysisRunCategorySetRequest,
    AnalysisRunFavoriteRequest,
    AnalysisRunFavoriteResponse,
    AnalysisRunImportantRequest,
    AnalysisRunImportantResponse,
    AnalysisRunListItem,
    AnalysisRunListResponse,
    AnalysisRunTagAttachRequest,
    AnalysisSectionStatuses,
    AnalyzeRequest,
    CategoryCreateRequest,
    CategoryItem,
    CategoryListResponse,
    CategoryRenameRequest,
    ChatGptProviderInfo,
    ClaudeProviderInfo,
    CommonCrawlProviderInfo,
    CommonCrawlProviderMode,
    Document,
    DocumentsSource,
    GeminiProviderInfo,
    GeminiRerunResponse,
    MeProjectItem,
    MeProjectsResponse,
    SectionStatus,
    TagCreateRequest,
    TagItem,
    TagListResponse,
    TagRenameRequest,
    UrlFetchResult,
    WebAiGapAiComparisonResponse,
)
from services.ai_overview_provider import (
    build_ai_overview_comparison,
    resolve_ai_overview_mode,
    resolve_dataforseo_environment,
)
from services.analyze_quota_settings import load_analyze_quota_settings
from services.dataforseo_settings import get_dataforseo_settings
from services.analysis_history_comparison import build_comparison_response
from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    AnalysisJobCancelledConflictError,
    AnalysisJobCreateConflictError,
    AnalysisJobLimitExceededError,
    AnalysisQuotaExceededError,
    AnalysisRunStatusConflictError,
    CategoryNameConflictError,
    CategoryNameInvalidError,
    CategoryNotAssignableError,
    CategoryRequiresProjectError,
    SyncAnalysisPreviouslyFailedError,
    SyncAnalysisStillRunningError,
    TagNameConflictError,
    TagNameInvalidError,
    TagNotAssignableError,
    UsageCounterRequirement,
    attach_tag_to_analysis_run,
    cancel_queued_analysis_run,
    complete_analysis_job,
    count_analysis_runs as repository_count_analysis_runs,
    create_category,
    create_queued_analysis_run,
    create_running_analysis_run,
    create_tag,
    daily_period_start,
    delete_category,
    delete_tag,
    detach_tag_from_analysis_run,
    get_analysis_job_result,
    get_analysis_job_status,
    get_analysis_run as repository_get_analysis_run,
    get_connection as open_history_db_connection,
    get_previous_analysis_run_for_brand as repository_get_previous_analysis_run_for_brand,
    list_analysis_runs as repository_list_analysis_runs,
    list_categories,
    list_tags,
    monthly_period_start,
    rename_category,
    rename_tag,
    save_analysis_history,
    set_analysis_run_category,
    set_analysis_run_favorite as repository_set_analysis_run_favorite,
    set_analysis_run_important as repository_set_analysis_run_important,
    soft_delete_analysis_run as repository_soft_delete_analysis_run,
    update_analysis_result as repository_update_analysis_result,
)
from services.ai_gap_comparison import generate_ai_gap_comparison
from services.gemini_rerun import rerun_gemini_for_analysis_run
from services.analysis_jobs_settings import load_analysis_jobs_settings
from services.analyze_auth_settings import load_analyze_auth_settings
from services.auth_settings import is_jwt_verification_configured, load_auth_settings
from services.jwt_auth import (
    AuthenticatedUser,
    JWTAuthError,
    extract_bearer_token,
    verify_supabase_jwt,
)
from services.project_access import (
    ProjectAccessError,
    can_user_access_analysis_run,
    can_user_access_category,
    can_user_access_project,
    can_user_access_tag,
    can_user_cancel_analysis_run,
    get_accessible_project_ids,
)
from services.brand_summary import build_brand_summary
from services.chatgpt_provider import build_chatgpt_observation, resolve_chatgpt_mode
from services.chatgpt_websearch_provider import attempt_chatgpt_websearch_supplement
from services.claude_websearch_provider import attempt_claude_websearch_supplement
from services.gemini_websearch_provider import attempt_gemini_websearch_supplement
from services.gemini_external_document_provider import attempt_gemini_external_document_supplement
from services.official_info_candidate import build_official_info_candidate
from services.claude_provider import build_claude_observation, resolve_claude_mode
from services.gemini_provider import build_gemini_observation, resolve_gemini_mode
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
from services.web_ai_gap import build_web_ai_gap
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Starts/stops Phase 2's background analysis-job worker alongside
    this app's own lifecycle — see
    docs/40_async_analysis_jobs_design.md "12.1". `services.analysis_job_worker`
    is imported here, lazily (inside this function, not at this
    module's top level), specifically so that module's own
    `from main import run_analysis_pipeline` (needed to execute a
    claimed job — see services/analysis_job_worker.py's
    process_one_job()) can safely resolve: by the time a FastAPI
    lifespan actually *runs* (app startup), this module has already
    fully finished loading, unlike at this file's own import time —
    this ordering is what avoids a circular import between this module
    and the worker module.

    Gated end-to-end by ANALYSIS_JOBS_WORKER_ENABLED (default False,
    see services/analysis_jobs_settings.py) — when off,
    start_worker() creates no task and nothing in this process ever
    calls claim_next_queued_analysis_run()/complete_analysis_job()/
    fail_expired_running_analysis_runs(), so deploying this code with
    the flag off is indistinguishable (to this process's behavior, and
    to the database) from not having it at all — even against a
    database that hasn't had migration 006 applied yet.
    """
    from services.analysis_job_worker import start_worker, stop_worker

    worker_handle = start_worker()
    try:
        yield
    finally:
        await stop_worker(worker_handle)


app = FastAPI(title="LLMO Analysis API", lifespan=lifespan)


def error_response(
    message: str,
    status_code: int = 400,
    *,
    code: str | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """`code`, added for Task 7 (feature/sync-analyze-jwt-project-auth,
    "認証エラーの処理改善"), is an optional stable, machine-readable
    identifier alongside the existing human-readable `message` — only
    included in the body when a caller actually passes one (every
    pre-existing call site in this file omits it, so their response
    shape is completely unchanged). Added specifically so a caller
    like the Next.js proxy (app/api/analyze/route.ts) can distinguish
    error *causes* that happen to share the same HTTP status code
    (e.g. two different reasons for a 503) without matching this
    function's prose `message` text, which is free to be reworded
    later without silently breaking that check.

    `extra`, added for Task 6-B4's HTTP 429 usage-quota response, is
    an optional dict of additional top-level fields merged into the
    body (e.g. `{"quota": {...}}`) — never overwrites `error`/`code`
    even if a caller's `extra` happens to reuse those keys (this
    function always sets `error`/`code` last). Omitted (no `extra`
    passed) by every pre-existing call site, so their response shape
    is unchanged.
    """
    content: dict[str, Any] = {}
    if extra:
        content.update(extra)
    content["error"] = message
    if code is not None:
        content["code"] = code
    return JSONResponse(status_code=status_code, content=content)


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


class AnalysisPipelineInputError(Exception):
    """Raised by run_analysis_pipeline() for the same input problems
    POST /analyze has always rejected with a 400 (documents too
    many/long, urls empty/too many) — main.py's analyze() catches this
    and returns error_response(str(exc)), the exact same message as
    before this extraction. Phase 2's worker catches it too and marks
    the job 'failed' with this message instead, since there is no
    HTTP request left to reject by the time a queued job actually
    runs (this should essentially never fire there in practice, since
    POST /analysis-jobs already validates the same constraints at job
    creation time — see
    services.analysis_history_repository.create_queued_analysis_run()
    — but a stale/malformed input_snapshot is defended against anyway
    rather than trusted blindly)."""


@dataclass(frozen=True)
class AnalysisPipelineOutcome:
    """Returned by run_analysis_pipeline() — the full analysis result
    plus the pieces of information its callers need beyond the result
    itself: `cooccurrence_status` (used to decide "partial"/"completed"
    when saving to analysis_runs.status), `source_summary` (saved as
    analysis_runs.source_summary), and `web_fetch_documents` (Task
    6-D-4C-2, feature/gemini-external-document-supplement).

    `web_fetch_documents` is the subset of this request's Document[]
    whose `sourceType == "web_fetch"` — i.e. the Documents
    services/web_fetcher.py itself produced from this request's own
    `urls[]`, excluding `user_provided`/`development_sample`/
    `common_crawl`/`dataforseo`-sourced Documents. Exists so
    services/gemini_external_document_provider.py's
    attempt_gemini_external_document_supplement() (called later, from
    main.py's synchronous authenticated path, after this function has
    already returned) can reuse the exact Documents already fetched
    for this request instead of re-fetching the same URLs a second
    time — see that provider module's own docstring. Never sent to the
    frontend (not part of `result`/`AnalysisResult` at all — this
    whole dataclass is internal plumbing between this function and its
    Python callers).
    """

    result: AnalysisResult
    cooccurrence_status: SectionStatus
    source_summary: dict[str, int]
    # Defaulted (not a required positional field) so existing test code
    # that constructs AnalysisPipelineOutcome(...) directly (without
    # knowing about this task) keeps working unchanged — see this
    # field's own docstring above.
    web_fetch_documents: list[Document] = field(default_factory=list)


def run_analysis_pipeline(
    *,
    brand_name: str,
    documents: list[str] | None,
    urls: list[str] | None,
    common_crawl_mode: str | None,
    common_crawl_domain: str | None,
    ai_overview_mode_override: str | None,
    chatgpt_mode_override: str | None,
    claude_mode_override: str | None,
    gemini_mode_override: str | None,
    official_url: str | None = None,
) -> AnalysisPipelineOutcome:
    """The actual analysis pipeline — Common Crawl / cooccurrence /
    chunking / context analysis / brand summary / AI Overview /
    improvement suggestions / ChatGPT / Claude / Gemini / webAiGap /
    meta assembly — extracted out of POST /analyze (see
    docs/40_async_analysis_jobs_design.md "15. Phase 2") so Phase 2's
    worker (services/analysis_job_worker.py) can run the *exact same*
    logic for a queued job, not a reimplementation of it. AI analysis
    logic itself is unchanged by this extraction — every line below is
    moved verbatim out of the old /analyze handler, not rewritten.

    Still validates `documents`/`urls` exactly as POST /analyze always
    has (`_validate_documents()`, empty-urls, MAX_URLS) — identical to
    before this extraction, just raising AnalysisPipelineInputError
    instead of directly building a 400 response (this function has no
    HTTP request to respond to). `brand_name` itself is NOT
    re-validated here (MAX_BRAND_NAME_LENGTH/non-empty) — that check
    stays solely in analyze() above its call site, since it's about
    the caller's own `brand_name` argument rather than something this
    function derives; the worker validates it the same way before
    calling this. POST /analysis-jobs already validates the
    documents/urls constraints once at job-creation time too (see
    services.analysis_history_repository.create_queued_analysis_run())
    — this function's validation is a second, defensive check against
    a stale/malformed `input_snapshot` by the time a worker actually
    runs the job, not the primary place either constraint is enforced.

    Never performs any DB read/write and never raises for an AI
    provider failure (every provider call already reports its own
    failure via a status/reason, exactly as before this extraction) —
    besides AnalysisPipelineInputError, the only way this function
    raises is a genuinely unexpected bug, which callers should treat
    as a hard failure (main.py lets it propagate as an unhandled error
    for /analyze exactly as before this extraction; the worker catches
    it and marks the job 'failed').

    `official_url` (Task 6-D-5B, feature/official-info-candidate) is
    optional and defaulted to None so every existing caller keeps
    working unchanged. When given, services/official_info_candidate.py's
    build_official_info_candidate() is called once this function's own
    `documents_list` is finalized, and the result is set on
    `result.officialInfoCandidate` — see that module's own docstring
    for the full fetch/reuse contract. This never adds a Document to
    `documents_list` itself, so it has no effect on cooccurrence
    ranking/context analysis/source_summary/web_fetch_documents above.
    """
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
    if documents is not None:
        validation_error = _validate_documents(documents)
        if validation_error:
            raise AnalysisPipelineInputError(validation_error)
        documents_source = "user_provided"
        documents_list = _documents_from_strings(documents)

    elif urls is not None:
        if len(urls) == 0:
            # Unlike documents:[], an empty urls list has no reasonable
            # interpretation as "fetch zero pages on purpose" — it's
            # far more likely to be a caller mistake, so this is a 400
            # rather than a silently-empty analysis.
            raise AnalysisPipelineInputError("urls must not be empty")

        if len(urls) > MAX_URLS:
            raise AnalysisPipelineInputError(f"urls must contain {MAX_URLS} or fewer entries")

        fetch_results = fetch_url_texts(urls)
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
    common_crawl_mode = common_crawl_mode or "off"
    common_crawl_documents, common_crawl_provider = _build_common_crawl_documents(
        common_crawl_mode, common_crawl_domain, urls
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
    ai_overview_mode = resolve_ai_overview_mode(ai_overview_mode_override)
    (
        result.aiOverviewComparison,
        ai_overview_status,
        ai_overview_reason,
        ai_overview_environment,
    ) = build_ai_overview_comparison(brand_name, ai_overview_mode, urls)
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
        # Task 6-D-1 (feature/recognition-level-classification) — no
        # call happened, so nothing to classify/version either.
        chatgpt_recognition_level = None
        chatgpt_prompt_version = None
    else:
        chatgpt_mode = resolve_chatgpt_mode(chatgpt_mode_override)
        (
            chatgpt_item,
            chatgpt_status,
            chatgpt_reason,
            chatgpt_environment,
            chatgpt_recognition_level,
            chatgpt_prompt_version,
        ) = build_chatgpt_observation(brand_name, chatgpt_mode)

    if chatgpt_item is not None:
        result.aiOverviewComparison = [*result.aiOverviewComparison, chatgpt_item]
    logger.info(
        "chatgpt observation complete: mode=%s status=%s",
        chatgpt_mode,
        chatgpt_status,
    )

    # Claude observation (see services/claude_provider.py): an
    # independent, optional single Anthropic API call whose result (if
    # any) is appended as an *extra* card to aiOverviewComparison.
    # Deliberately NOT skipped when aiOverviewMode is "mock" — unlike
    # ChatGPT above, the mock aiOverviewComparison fixture has no
    # "Claude" card to collide with (see services/claude_provider.py's
    # module docstring).
    claude_mode = resolve_claude_mode(claude_mode_override)
    (
        claude_item,
        claude_status,
        claude_reason,
        claude_environment,
        claude_recognition_level,
        claude_prompt_version,
    ) = build_claude_observation(brand_name, claude_mode)
    if claude_item is not None:
        result.aiOverviewComparison = [*result.aiOverviewComparison, claude_item]
    logger.info(
        "claude observation complete: mode=%s status=%s",
        claude_mode,
        claude_status,
    )

    # Gemini observation (see services/gemini_provider.py): same design
    # as Claude above — independent, optional, single Google API call,
    # not skipped in mock mode (no "Gemini" mock card to collide with).
    gemini_mode = resolve_gemini_mode(gemini_mode_override)
    (
        gemini_item,
        gemini_status,
        gemini_reason,
        gemini_environment,
        gemini_recognition_level,
        gemini_prompt_version,
    ) = build_gemini_observation(brand_name, gemini_mode)
    if gemini_item is not None:
        result.aiOverviewComparison = [*result.aiOverviewComparison, gemini_item]
    logger.info(
        "gemini observation complete: mode=%s status=%s",
        gemini_mode,
        gemini_status,
    )

    # webAiGap ("Web上の説明とAI回答のズレ", see services/web_ai_gap.py):
    # a rule-based comparison between the Web-side Document[]
    # (documents_list, same list used for cooccurrenceRanking above)
    # and result.aiOverviewComparison (now that ChatGPT/Claude/Gemini
    # have all had a chance to append their cards above). No new
    # external API call — built entirely from data already computed in
    # this request.
    result.webAiGap = build_web_ai_gap(
        brand_name, documents_list, result.cooccurrenceRanking, result.aiOverviewComparison
    )
    logger.info("web/AI gap complete: status=%s", result.webAiGap.status)

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
            recognitionLevel=chatgpt_recognition_level,
            promptVersion=chatgpt_prompt_version,
        ),
        claudeProvider=ClaudeProviderInfo(
            mode=claude_mode,
            status=claude_status,
            reason=claude_reason,
            environment=claude_environment,
            recognitionLevel=claude_recognition_level,
            promptVersion=claude_prompt_version,
        ),
        geminiProvider=GeminiProviderInfo(
            mode=gemini_mode,
            status=gemini_status,
            reason=gemini_reason,
            environment=gemini_environment,
            recognitionLevel=gemini_recognition_level,
            promptVersion=gemini_prompt_version,
        ),
        commonCrawlProvider=common_crawl_provider,
    )

    source_summary = dict(Counter(document.sourceType for document in documents_list))

    # Task 6-D-5B (feature/official-info-candidate) — see this
    # function's own docstring above. Deliberately placed after
    # documents_list is final (so same-run urls[] reuse can work) and
    # never mutates documents_list itself.
    result.officialInfoCandidate = build_official_info_candidate(official_url, documents_list)

    return AnalysisPipelineOutcome(
        result=result,
        cooccurrence_status=cooccurrence_status,
        source_summary=source_summary,
        web_fetch_documents=[d for d in documents_list if d.sourceType == "web_fetch"],
    )


ANALYZE_AUTH_REQUIRED_MESSAGE = "authentication required"
ANALYZE_INVALID_TOKEN_MESSAGE = "invalid or expired authentication token"
ANALYZE_JWT_NOT_CONFIGURED_MESSAGE = "analyze JWT verification is not configured"
ANALYZE_ACCESS_DENIED_MESSAGE = "access denied to the specified project"
ANALYZE_PROJECT_ID_REQUIRED_MESSAGE = "projectId is required"
ANALYZE_PROJECT_CHECK_FAILED_MESSAGE = "failed to verify project access"

# Stable, machine-readable companions to the prose messages above
# (Task 7, feature/sync-analyze-jwt-project-auth "認証エラーの処理改善")
# — exposed in each error response's `code` field (see
# error_response()) so a caller like the Next.js proxy
# (app/api/analyze/route.ts) never has to match this file's exact
# English prose to tell these failures apart from an unrelated 503
# (e.g. PYTHON_ANALYSIS_API_URL misconfigured on the Next.js side, or
# a genuinely unreachable Python API) that this same endpoint's
# generic failure paths can also produce. "auth_unavailable" is
# deliberately shared by both 503 causes below (JWT verification
# itself unconfigured, and the project-access check failing) — from
# the caller's point of view both mean the same thing: retry later,
# this isn't the caller's fault, and it is specifically an auth-layer
# problem.
ANALYZE_AUTH_REQUIRED_CODE = "auth_required"
ANALYZE_INVALID_TOKEN_CODE = "invalid_token"
ANALYZE_AUTH_UNAVAILABLE_CODE = "auth_unavailable"
ANALYZE_ACCESS_DENIED_CODE = "project_access_denied"
ANALYZE_PROJECT_ID_REQUIRED_CODE = "project_id_required"

# --- Synchronous analysis idempotency (Task 6-B3,
# feature/sync-analyze-jwt-project-auth) — only reachable once
# ANALYZE_AUTH_REQUIRED=true (see analyze() below); the anonymous path
# never looks at `requestId` at all. See
# services/analysis_history_repository.py's "Synchronous analysis
# idempotency" section for the full mechanism this backs.

ANALYZE_REQUEST_ID_REQUIRED_MESSAGE = "requestId is required"
ANALYZE_REQUEST_ID_REQUIRED_CODE = "request_id_required"
ANALYZE_REQUEST_ID_INVALID_MESSAGE = (
    "requestId must be 1-200 characters, using only letters, digits, '-' or '_'"
)
ANALYZE_REQUEST_ID_INVALID_CODE = "request_id_invalid"
ANALYZE_STILL_RUNNING_MESSAGE = "an analysis for this requestId is still running"
ANALYZE_STILL_RUNNING_CODE = "analysis_still_running"
ANALYZE_PREVIOUSLY_FAILED_MESSAGE = (
    "the previous analysis for this requestId failed; start a new analysis "
    "with a new requestId"
)
ANALYZE_PREVIOUSLY_FAILED_CODE = "analysis_previously_failed"
ANALYZE_REQUEST_CONFLICT_MESSAGE = "requestId reused with a different request body"
ANALYZE_REQUEST_CONFLICT_CODE = "analysis_request_conflict"
ANALYZE_REQUEST_CANCELLED_MESSAGE = (
    "this requestId's analysis was deleted and cannot be reused"
)
ANALYZE_REQUEST_CANCELLED_CODE = "analysis_request_cancelled"
ANALYZE_RUN_FAILED_MESSAGE = "failed to run the analysis"
# Task 6-B audit fix (P1-1, feature/sync-analyze-jwt-project-auth):
# added so this one specific 503 (create_running_analysis_run() itself
# raised AnalysisHistoryReadError — a DB failure during the
# reservation attempt, before run_analysis_pipeline() is ever called)
# can be told apart from every other, unrelated 503 cause by a stable
# `code` rather than falling through un-coded. Without this, the
# Next.js proxy (app/api/analyze/route.ts) could not distinguish it
# from "Python API not configured"/"DB unreachable for an unrelated
# reason" and converted it into a 200 dummy-fallback response — making
# a reservation that never even started look like a successful
# analysis. See that route's ANALYZE_RUN_FAILED_CODE check.
ANALYZE_RUN_FAILED_CODE = "analysis_run_failed"

# Task 6-B4 (feature/sync-analyze-jwt-project-auth) usage-quota
# responses.
ANALYZE_QUOTA_EXCEEDED_MESSAGE = "利用上限に達しているため、分析を開始できません。"
ANALYZE_QUOTA_EXCEEDED_CODE = "analysis_quota_exceeded"
# Returned when ANALYZE_AUTH_REQUIRED=true but
# AnalyzeQuotaSettings.enforcement_enabled is false and the narrow
# ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA dev/test override isn't set either
# — see services/analyze_quota_settings.py's module docstring and
# Task 6-B4's design report "6" for why this combination is refused by
# default rather than silently running the authenticated (and
# therefore potentially paid) path with no cost protection at all.
ANALYZE_QUOTA_ENFORCEMENT_REQUIRED_MESSAGE = (
    "利用枠保護が有効化されていないため、認証必須モードでの分析を安全に実行できません。"
)
ANALYZE_QUOTA_ENFORCEMENT_REQUIRED_CODE = "quota_enforcement_required"

# Task 6-B4 metric names — must match services/analyze_quota_settings.py's
# _METRIC_ENV_SUFFIXES keys and migration 009's analysis_usage_counters.metric
# values exactly.
ANALYZE_QUOTA_METRIC_ALL_ANALYSES = "all_analyses"

# Generous relative to the ~100s worst-case full-ON pipeline duration
# documented in app/api/analyze/route.ts's PYTHON_API_TIMEOUT_MS
# comment — this lease only needs to outlive a single synchronous
# request's own pipeline execution, never a worker's poll cycle.
SYNC_ANALYSIS_LEASE_SECONDS = 180

MAX_REQUEST_ID_LENGTH = 200
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _validate_request_id(raw: str | None) -> str | None:
    """Returns the trimmed, validated requestId, or None if it's
    missing/malformed — the caller decides the exact 400 response
    (missing vs. invalid get distinct messages/codes). Deliberately
    restrictive (letters/digits/hyphen/underscore only, matching a
    typical UUID's own character set) since this value is stored
    verbatim as `analysis_runs.idempotency_key` and never needs to be
    anything fancier than an opaque client-generated token."""
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    if not value or len(value) > MAX_REQUEST_ID_LENGTH:
        return None
    if not _REQUEST_ID_PATTERN.match(value):
        return None
    return value


def _resolve_analyze_project_auth(
    request: Request, payload: AnalyzeRequest
) -> tuple[str, str] | None | JSONResponse:
    """Resolves POST /analyze's authorization requirement (Task 6-B2,
    feature/sync-analyze-jwt-project-auth).

    - ANALYZE_AUTH_REQUIRED=false (the default): returns None
      immediately, without even looking at the Authorization header or
      `payload.projectId` — analyze() then falls through to the
      existing anonymous/default-project path, completely unchanged
      from before this task.
    - ANALYZE_AUTH_REQUIRED=true: requires a verified Supabase JWT (via
      the shared _verify_jwt_bearer() helper added in Task 6-A — no new
      JWT-verification logic is duplicated here) and a `projectId` the
      caller can access (via the existing can_user_access_project(),
      the same helper POST /tags and POST /categories already use for
      exactly this check). On success, returns `(user_id, project_id)`
      — both already verified — for analyze() to pass into Task 6-B3's
      idempotency reservation. On any failure, returns a JSONResponse
      to return immediately — the caller must never proceed to
      run_analysis_pipeline() or any save path in that case, so no
      external provider is ever called and nothing is ever saved for
      an unauthorized request.

    A failed/misconfigured JWT or project check never falls back to
    the anonymous default-project path merely because this flag
    happens to be true — it only skips authorization entirely when the
    flag itself is false.
    """
    analyze_auth_settings = load_analyze_auth_settings()
    if not analyze_auth_settings.auth_required:
        return None

    auth_result = _verify_jwt_bearer(
        request,
        auth_required_message=ANALYZE_AUTH_REQUIRED_MESSAGE,
        invalid_token_message=ANALYZE_INVALID_TOKEN_MESSAGE,
        jwt_not_configured_message=ANALYZE_JWT_NOT_CONFIGURED_MESSAGE,
        auth_required_code=ANALYZE_AUTH_REQUIRED_CODE,
        invalid_token_code=ANALYZE_INVALID_TOKEN_CODE,
        jwt_not_configured_code=ANALYZE_AUTH_UNAVAILABLE_CODE,
    )
    if isinstance(auth_result, JSONResponse):
        return auth_result

    project_id = (payload.projectId or "").strip()
    if not project_id:
        return error_response(
            ANALYZE_PROJECT_ID_REQUIRED_MESSAGE,
            status_code=400,
            code=ANALYZE_PROJECT_ID_REQUIRED_CODE,
        )

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_project(conn, auth_result.user_id, project_id)
    except Exception:
        logger.exception("Failed to check project access for POST /analyze")
        return error_response(
            ANALYZE_PROJECT_CHECK_FAILED_MESSAGE,
            status_code=503,
            code=ANALYZE_AUTH_UNAVAILABLE_CODE,
        )

    if not allowed:
        return error_response(
            ANALYZE_ACCESS_DENIED_MESSAGE, status_code=403, code=ANALYZE_ACCESS_DENIED_CODE
        )

    return auth_result.user_id, project_id


@app.post("/analyze", response_model=AnalysisResult)
def analyze(payload: AnalyzeRequest, request: Request):
    brand_name = (payload.brandName or "").strip()

    if not brand_name:
        return error_response("brandName is required")

    if len(brand_name) > MAX_BRAND_NAME_LENGTH:
        return error_response(
            f"brandName must be {MAX_BRAND_NAME_LENGTH} characters or fewer"
        )

    auth_outcome = _resolve_analyze_project_auth(request, payload)
    if isinstance(auth_outcome, JSONResponse):
        return auth_outcome
    # None when ANALYZE_AUTH_REQUIRED=false (legacy/anonymous path,
    # handled by _analyze_anonymous() below, completely unchanged);
    # otherwise the caller's own, already JWT-verified user id and
    # access-checked project id, handled by
    # _analyze_authenticated_idempotent() (Task 6-B3).
    if auth_outcome is None:
        return _analyze_anonymous(payload, brand_name)

    verified_user_id, verified_project_id = auth_outcome
    return _analyze_authenticated_idempotent(
        payload, brand_name, user_id=verified_user_id, project_id=verified_project_id
    )


def _analyze_anonymous(payload: AnalyzeRequest, brand_name: str):
    """ANALYZE_AUTH_REQUIRED=false path — byte-for-byte the same
    behavior as before Task 6-B2/6-B3 existed: no idempotency, no
    JWT/project concept, always saves (best-effort) to the fixed
    default project. `payload.requestId`, even if sent, is never read
    here — see services/analysis_history_repository.py's "Synchronous
    analysis idempotency" section for why this path is deliberately
    left alone rather than extended to cover it too.
    """
    # Minimal diagnostic logging around each stage of /analyze — added
    # to narrow down where a Render free-tier request was dying (past
    # url fetch, but before any "POST /analyze ... 200/500" completion
    # log ever appeared). Counts/timings only; never document text.
    logger.info("analyze start brandName=%r", brand_name)

    try:
        outcome = run_analysis_pipeline(
            brand_name=brand_name,
            documents=payload.documents,
            urls=payload.urls,
            common_crawl_mode=payload.commonCrawlMode,
            common_crawl_domain=payload.commonCrawlDomain,
            ai_overview_mode_override=payload.aiOverviewMode,
            chatgpt_mode_override=payload.chatgptMode,
            claude_mode_override=payload.claudeMode,
            gemini_mode_override=payload.geminiMode,
            official_url=payload.officialUrl,
        )
    except AnalysisPipelineInputError as exc:
        return error_response(str(exc))

    result = outcome.result
    cooccurrence_status = outcome.cooccurrence_status

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
                "claudeMode": payload.claudeMode,
                "geminiMode": payload.geminiMode,
                "officialUrl": payload.officialUrl,
            },
            source_summary=outcome.source_summary,
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


def _resolve_required_usage_counters(
    payload: AnalyzeRequest, *, user_id: str, project_id: str
) -> list[UsageCounterRequirement]:
    """Task 6-B4: builds the list of usage-quota counters this request
    must atomically reserve, using each provider's *resolved* mode
    (ALLOW_*_MODE_OVERRIDE already applied) — never the raw per-request
    override alone, so a provider that's actually off (either by its
    own env default or because override isn't allowed) never consumes
    its paid-provider counter. Deliberately mirrors
    run_analysis_pipeline()'s own mode resolution exactly (same inputs,
    same pure functions, same "ai_overview_mode==mock skips chatgpt"
    rule) so the two can never disagree within one request — see this
    task's design report "5"/"6" for why that's a structural guarantee
    here (same process, same env, same payload, no time gap) rather
    than something that needs its own synchronization.

    Always includes the three "all_analyses" counters (user daily,
    project daily, project monthly) — these apply even to a pure
    mock/off analysis. Only adds a paid-provider counter (daily +
    monthly) for a provider whose resolved mode indicates it will
    actually be called.
    """
    quota_settings = load_analyze_quota_settings()
    now = datetime.now(timezone.utc)
    daily_start = daily_period_start(now)
    monthly_start = monthly_period_start(now)

    counters = [
        UsageCounterRequirement(
            scope_type="user",
            scope_id=user_id,
            metric=ANALYZE_QUOTA_METRIC_ALL_ANALYSES,
            period_type="daily",
            period_start=daily_start,
            limit=quota_settings.max_user_daily,
        ),
        UsageCounterRequirement(
            scope_type="project",
            scope_id=project_id,
            metric=ANALYZE_QUOTA_METRIC_ALL_ANALYSES,
            period_type="daily",
            period_start=daily_start,
            limit=quota_settings.max_project_daily,
        ),
        UsageCounterRequirement(
            scope_type="project",
            scope_id=project_id,
            metric=ANALYZE_QUOTA_METRIC_ALL_ANALYSES,
            period_type="monthly",
            period_start=monthly_start,
            limit=quota_settings.max_project_monthly,
        ),
    ]

    def _add_provider_counter(metric: str) -> None:
        counters.append(
            UsageCounterRequirement(
                scope_type="project",
                scope_id=project_id,
                metric=metric,
                period_type="daily",
                period_start=daily_start,
                limit=quota_settings.max_project_daily_by_metric[metric],
            )
        )
        counters.append(
            UsageCounterRequirement(
                scope_type="project",
                scope_id=project_id,
                metric=metric,
                period_type="monthly",
                period_start=monthly_start,
                limit=quota_settings.max_project_monthly_by_metric[metric],
            )
        )

    resolved_ai_overview_mode = resolve_ai_overview_mode(payload.aiOverviewMode)
    dataforseo_environment = resolve_dataforseo_environment(
        resolved_ai_overview_mode, get_dataforseo_settings()
    )
    if dataforseo_environment is not None:
        _add_provider_counter(f"dataforseo_{dataforseo_environment}")

    # Mirrors run_analysis_pipeline()'s own exact rule: ChatGPT is
    # skipped entirely (never resolved/called) when aiOverviewMode is
    # "mock", to avoid duplicating the mock fixture's own ChatGPT card.
    resolved_chatgpt_mode = (
        "off" if resolved_ai_overview_mode == "mock" else resolve_chatgpt_mode(payload.chatgptMode)
    )
    if resolved_chatgpt_mode == "openai":
        _add_provider_counter("openai")

    if resolve_claude_mode(payload.claudeMode) == "anthropic":
        _add_provider_counter("anthropic")

    if resolve_gemini_mode(payload.geminiMode) == "google":
        _add_provider_counter("google")

    return counters


def _analyze_authenticated_idempotent(
    payload: AnalyzeRequest, brand_name: str, *, user_id: str, project_id: str
):
    """ANALYZE_AUTH_REQUIRED=true path (Task 6-B3/6-B4) — requires a
    valid `requestId`, then atomically reserves this request's
    execution slot (and, when quota enforcement is enabled, every
    usage-quota counter it needs) via create_running_analysis_run()
    *before* ever calling run_analysis_pipeline() (processing order
    mandated by Task 6-B3's "6. 二重課金防止" / Task 6-B4's "3.
    原子的な利用枠確保": JWT/project auth -> requestId validation -> DB
    idempotency + quota reservation -> only then the actual analysis).

    A replay (already completed/partial) returns the saved result
    immediately, without calling run_analysis_pipeline() or any save
    function again — no new external provider call, no new row, no
    new counter increment.
    """
    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled and not quota_settings.allow_auth_without_quota:
        # Task 6-B4 "6": AUTH ON / QUOTA OFF is refused by default —
        # running the authenticated (and therefore potentially paid)
        # path with no cost protection at all is never a safe implicit
        # state. The only way around this is the narrow, explicitly
        # named dev/test-only ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA
        # override (see services/analyze_quota_settings.py).
        return error_response(
            ANALYZE_QUOTA_ENFORCEMENT_REQUIRED_MESSAGE,
            status_code=503,
            code=ANALYZE_QUOTA_ENFORCEMENT_REQUIRED_CODE,
        )
    if not quota_settings.enforcement_enabled and quota_settings.allow_auth_without_quota:
        logger.warning(
            "ANALYZE_AUTH_REQUIRED=true but ANALYZE_QUOTA_ENFORCEMENT_ENABLED=false; "
            "proceeding UNMETERED because ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA=true "
            "(dev/test override only — this must never be set in production)"
        )

    request_id = _validate_request_id(payload.requestId)
    if request_id is None:
        if not payload.requestId:
            return error_response(
                ANALYZE_REQUEST_ID_REQUIRED_MESSAGE,
                status_code=400,
                code=ANALYZE_REQUEST_ID_REQUIRED_CODE,
            )
        return error_response(
            ANALYZE_REQUEST_ID_INVALID_MESSAGE,
            status_code=400,
            code=ANALYZE_REQUEST_ID_INVALID_CODE,
        )

    required_counters = (
        _resolve_required_usage_counters(payload, user_id=user_id, project_id=project_id)
        if quota_settings.enforcement_enabled
        else []
    )

    try:
        reservation = create_running_analysis_run(
            project_id=project_id,
            created_by_user_id=user_id,
            idempotency_key=request_id,
            brand_name=brand_name,
            documents=payload.documents,
            urls=payload.urls,
            common_crawl_mode=payload.commonCrawlMode,
            common_crawl_domain=payload.commonCrawlDomain,
            ai_overview_mode=payload.aiOverviewMode,
            chatgpt_mode=payload.chatgptMode,
            claude_mode=payload.claudeMode,
            gemini_mode=payload.geminiMode,
            lease_seconds=SYNC_ANALYSIS_LEASE_SECONDS,
            required_counters=required_counters,
            official_url=payload.officialUrl,
        )
    except SyncAnalysisStillRunningError:
        return error_response(
            ANALYZE_STILL_RUNNING_MESSAGE, status_code=409, code=ANALYZE_STILL_RUNNING_CODE
        )
    except SyncAnalysisPreviouslyFailedError:
        return error_response(
            ANALYZE_PREVIOUSLY_FAILED_MESSAGE,
            status_code=409,
            code=ANALYZE_PREVIOUSLY_FAILED_CODE,
        )
    except AnalysisJobCreateConflictError:
        return error_response(
            ANALYZE_REQUEST_CONFLICT_MESSAGE,
            status_code=409,
            code=ANALYZE_REQUEST_CONFLICT_CODE,
        )
    except AnalysisJobCancelledConflictError:
        return error_response(
            ANALYZE_REQUEST_CANCELLED_MESSAGE,
            status_code=409,
            code=ANALYZE_REQUEST_CANCELLED_CODE,
        )
    except AnalysisQuotaExceededError as exc:
        period_length_days = 1 if exc.period_type == "daily" else None
        if period_length_days is not None:
            next_period_start = exc.period_start + timedelta(days=period_length_days)
        else:
            # monthly — advance to the 1st of the next calendar month.
            year = exc.period_start.year + (1 if exc.period_start.month == 12 else 0)
            month = 1 if exc.period_start.month == 12 else exc.period_start.month + 1
            next_period_start = exc.period_start.replace(year=year, month=month)
        return error_response(
            ANALYZE_QUOTA_EXCEEDED_MESSAGE,
            status_code=429,
            code=ANALYZE_QUOTA_EXCEEDED_CODE,
            extra={
                "quota": {
                    "scope": exc.scope_type,
                    "metric": exc.metric,
                    "period": exc.period_type,
                    "availableAt": next_period_start.isoformat(),
                }
            },
        )
    except AnalysisHistoryReadError:
        # The reservation attempt itself failed (e.g. a DB connectivity
        # issue, or — if ANALYZE_QUOTA_ENFORCEMENT_ENABLED=true were
        # ever turned on before migration 009 is applied —
        # analysis_usage_counters simply not existing yet) —
        # run_analysis_pipeline() is never reached in this branch, so
        # no external provider call happens either. `code` (Task 6-B
        # audit fix P1-1) lets the Next.js proxy tell this apart from
        # every other, unrelated 503 cause and report it as a real
        # failure instead of silently falling back to dummy data.
        return error_response(
            ANALYZE_RUN_FAILED_MESSAGE, status_code=503, code=ANALYZE_RUN_FAILED_CODE
        )

    if not reservation.created:
        # Replay: a 'completed'/'partial' run for this exact requestId
        # (same input) already exists — return its saved result as-is,
        # never re-running the pipeline or writing anything new.
        result = AnalysisResult(**reservation.result_json)
        result.analysisRunId = reservation.analysis_run_id
        return result

    # Newly reserved as 'running' — this request now owns it exclusively
    # (via reservation.locked_by) until SYNC_ANALYSIS_LEASE_SECONDS
    # elapses. Any exception below is caught so the row is always
    # finalized (never left dangling as 'running' longer than
    # necessary) before this function returns or re-raises.
    try:
        outcome = run_analysis_pipeline(
            brand_name=brand_name,
            documents=payload.documents,
            urls=payload.urls,
            common_crawl_mode=payload.commonCrawlMode,
            common_crawl_domain=payload.commonCrawlDomain,
            ai_overview_mode_override=payload.aiOverviewMode,
            chatgpt_mode_override=payload.chatgptMode,
            claude_mode_override=payload.claudeMode,
            gemini_mode_override=payload.geminiMode,
            official_url=payload.officialUrl,
        )
    except AnalysisPipelineInputError as exc:
        try:
            complete_analysis_job(
                reservation.analysis_run_id,
                worker_id=reservation.locked_by,
                status="failed",
                result_json=None,
                meta_json=None,
                error_message=str(exc),
            )
        except AnalysisHistoryReadError:
            logger.exception(
                "Failed to mark synchronous analysis run as failed after input error"
            )
        return error_response(str(exc))
    except Exception:
        logger.exception("Unexpected error while running synchronous analysis pipeline")
        try:
            complete_analysis_job(
                reservation.analysis_run_id,
                worker_id=reservation.locked_by,
                status="failed",
                result_json=None,
                meta_json=None,
                error_message="unexpected error during analysis pipeline execution",
            )
        except AnalysisHistoryReadError:
            logger.exception(
                "Failed to mark synchronous analysis run as failed after unexpected error"
            )
        raise

    result = outcome.result
    cooccurrence_status = outcome.cooccurrence_status
    final_status = "partial" if cooccurrence_status == "unavailable" else "completed"

    # Task 6-D-3 (feature/chatgpt-websearch-supplement): attempted only
    # here — strictly after run_analysis_pipeline() has returned the
    # no-search ChatGPT observation's recognitionLevel, and strictly
    # before complete_analysis_job() below marks this run completed/
    # partial/failed, so reservation.analysis_run_id is still
    # genuinely 'running' in the database for the whole duration of
    # this call (see services/chatgpt_websearch_provider.py's module
    # docstring for why it must never be called from inside
    # run_analysis_pipeline() itself, which has no database access).
    # Never reached by the anonymous path (_analyze_anonymous() never
    # has a project_id/user_id/analysis_run_id to pass here at all).
    # Wrapped defensively: any unexpected failure in this new path must
    # never discard the already-successful no-search result above.
    try:
        chatgpt_recognition_level = (
            result.meta.chatgptProvider.recognitionLevel if result.meta.chatgptProvider else None
        )
        websearch_item, websearch_provider_info = attempt_chatgpt_websearch_supplement(
            brand_name=brand_name,
            recognition_level=chatgpt_recognition_level,
            analysis_run_id=reservation.analysis_run_id,
            project_id=project_id,
            user_id=user_id,
        )
        result.meta.chatgptWebsearchProvider = websearch_provider_info
        if websearch_item is not None:
            result.aiOverviewComparison = [*result.aiOverviewComparison, websearch_item]
        logger.info(
            "chatgpt websearch supplement complete: status=%s", websearch_provider_info.status
        )
    except Exception:
        logger.exception("Unexpected error while attempting the ChatGPT websearch supplement")

    # Task 6-D-4A-2 (feature/claude-websearch-supplement): same timing
    # constraint and defensive wrapping as the ChatGPT websearch
    # supplement above — see services/claude_websearch_provider.py's
    # module docstring. Independent of the ChatGPT attempt above: a
    # failure or skip here never affects the ChatGPT result, and vice
    # versa (each only ever appends its own card to
    # result.aiOverviewComparison and sets its own meta field).
    try:
        claude_recognition_level = (
            result.meta.claudeProvider.recognitionLevel if result.meta.claudeProvider else None
        )
        claude_websearch_item, claude_websearch_provider_info = attempt_claude_websearch_supplement(
            brand_name=brand_name,
            recognition_level=claude_recognition_level,
            analysis_run_id=reservation.analysis_run_id,
            project_id=project_id,
            user_id=user_id,
        )
        result.meta.claudeWebsearchProvider = claude_websearch_provider_info
        if claude_websearch_item is not None:
            result.aiOverviewComparison = [*result.aiOverviewComparison, claude_websearch_item]
        logger.info(
            "claude websearch supplement complete: status=%s",
            claude_websearch_provider_info.status,
        )
    except Exception:
        logger.exception("Unexpected error while attempting the Claude websearch supplement")

    # Task 6-D-4B-2 (feature/gemini-websearch-supplement): same timing
    # constraint and defensive wrapping as the ChatGPT/Claude websearch
    # supplements above — see services/gemini_websearch_provider.py's
    # module docstring. Independent of both: a failure or skip here
    # never affects the ChatGPT/Claude results, and vice versa.
    try:
        gemini_recognition_level = (
            result.meta.geminiProvider.recognitionLevel if result.meta.geminiProvider else None
        )
        gemini_websearch_item, gemini_websearch_provider_info = attempt_gemini_websearch_supplement(
            brand_name=brand_name,
            recognition_level=gemini_recognition_level,
            analysis_run_id=reservation.analysis_run_id,
            project_id=project_id,
            user_id=user_id,
        )
        result.meta.geminiWebsearchProvider = gemini_websearch_provider_info
        if gemini_websearch_item is not None:
            result.aiOverviewComparison = [*result.aiOverviewComparison, gemini_websearch_item]
        logger.info(
            "gemini websearch supplement complete: status=%s",
            gemini_websearch_provider_info.status,
        )
    except Exception:
        logger.exception("Unexpected error while attempting the Gemini websearch supplement")

    # Task 6-D-4C-2 (feature/gemini-external-document-supplement): same
    # timing constraint and defensive wrapping as the ChatGPT/Claude/
    # Gemini-websearch supplements above — see
    # services/gemini_external_document_provider.py's module
    # docstring. Independent of all three: a failure or skip here never
    # affects their results, and vice versa. Reuses
    # outcome.web_fetch_documents (the Document[] already fetched by
    # run_analysis_pipeline() for this same request) rather than
    # re-fetching urls[] a second time.
    try:
        gemini_external_document_recognition_level = (
            result.meta.geminiProvider.recognitionLevel if result.meta.geminiProvider else None
        )
        (
            gemini_external_document_item,
            gemini_external_document_provider_info,
        ) = attempt_gemini_external_document_supplement(
            brand_name=brand_name,
            recognition_level=gemini_external_document_recognition_level,
            documents=outcome.web_fetch_documents,
            analysis_run_id=reservation.analysis_run_id,
            project_id=project_id,
            user_id=user_id,
        )
        result.meta.geminiExternalDocumentProvider = gemini_external_document_provider_info
        if gemini_external_document_item is not None:
            result.aiOverviewComparison = [*result.aiOverviewComparison, gemini_external_document_item]
        logger.info(
            "gemini external-document supplement complete: status=%s",
            gemini_external_document_provider_info.status,
        )
    except Exception:
        logger.exception("Unexpected error while attempting the Gemini external-document supplement")

    try:
        completed = complete_analysis_job(
            reservation.analysis_run_id,
            worker_id=reservation.locked_by,
            status=final_status,
            result_json=result.model_dump(),
            meta_json=result.meta.model_dump(),
            error_message=None,
        )
        if not completed:
            # The lease already expired (e.g. this request ran longer
            # than SYNC_ANALYSIS_LEASE_SECONDS, or Render stopped/
            # restarted this process and another request's lazy-expiry
            # check already swept this row to 'failed') — the row's
            # own state already reflects that; this result is simply
            # discarded, never force-written over whatever the row
            # already says, and never retried automatically.
            #
            # Task 6-B3 audit fix (不具合B): `reservation.analysis_run_id`
            # now unambiguously identifies a 'failed' run with no saved
            # result (complete_analysis_job()'s own WHERE clause
            # guarantees this row was never overwritten back to
            # completed/partial — see that function's docstring). The
            # caller here still received a real, successfully computed
            # `result`, so it is still returned as-is — only
            # `analysisRunId` is cleared, mirroring the anonymous
            # path's own existing convention of only ever setting it
            # when the save actually succeeded (see _analyze_anonymous()
            # above). This prevents the history detail screen (which
            # correctly reports this run as "failed", per
            # resolveHistoryDetailFetchOutcome()'s status check) from
            # ever being reachable from what looks like a successful
            # on-screen result — the screen simply shows no "view in
            # history" link for this response (see
            # app/lib/analysis-history.ts's resolvePostAnalyzeHistoryLink(),
            # which already treats a null analysisRunId as "no link").
            logger.warning(
                "Synchronous analysis run %s's lease expired before completion; "
                "result discarded, analysisRunId omitted from the response",
                reservation.analysis_run_id,
            )
            result.analysisRunId = None
            return result
    except AnalysisHistoryReadError:
        # Task 6-B audit fix (P1-2): whether complete_analysis_job()'s
        # write actually reached the DB is unknown here (a connection
        # failure mid-UPDATE could mean nothing was written, or that
        # the write succeeded but the response was lost) — this is
        # *less* certain than the `not completed` branch above, which
        # at least got a definitive answer, so it must be treated at
        # least as conservatively: never report `analysisRunId` as if
        # the save were confirmed. Falling through to the unconditional
        # `result.analysisRunId = reservation.analysis_run_id` below
        # would claim a save that was never confirmed — exactly the
        # gap this fix closes, for the same reasons as the
        # `not completed` branch's own Task 6-B3 audit fix comment
        # above.
        logger.exception("Failed to save synchronous analysis result")
        result.analysisRunId = None
        return result

    result.analysisRunId = reservation.analysis_run_id
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


def _verify_jwt_bearer(
    request: Request,
    *,
    auth_required_message: str,
    invalid_token_message: str,
    jwt_not_configured_message: str,
    auth_required_code: str | None = None,
    invalid_token_code: str | None = None,
    jwt_not_configured_code: str | None = None,
) -> AuthenticatedUser | JSONResponse:
    """Verifies a Supabase Auth JWT from the Authorization header, with
    no HISTORY_READ_TOKEN fallback of any kind — the one piece of
    JWT-verification logic shared by every JWT-only auth gate in this
    file (_resolve_tag_category_auth(), _resolve_jwt_only_auth(),
    _resolve_job_auth(), _resolve_history_write_auth() below all call
    this instead of repeating it). Messages are injected by the caller
    so each gate keeps its own wording, while the verification logic
    itself — and the _JWT_UNAVAILABLE_REASONS classification — lives
    in exactly one place (fix/history-read-token-write-isolation).

    The `*_code` parameters (added for Task 7,
    feature/sync-analyze-jwt-project-auth) are optional stable,
    machine-readable identifiers passed straight through to
    error_response()'s own `code` field — see that function's
    docstring. None of this function's pre-existing callers pass them,
    so their response body shape is completely unchanged; only
    callers that need a caller-side disambiguation more robust than
    matching `message`'s exact prose (e.g. _resolve_analyze_project_auth()
    below, whose 503 shares a status code with an unrelated,
    pre-existing "Python API misconfigured" 503 from a different code
    path) need to pass one.
    """
    auth_settings = load_auth_settings()
    if not is_jwt_verification_configured(auth_settings):
        return error_response(
            jwt_not_configured_message, status_code=503, code=jwt_not_configured_code
        )

    authorization_header = request.headers.get(AUTHORIZATION_HEADER)
    try:
        token = extract_bearer_token(authorization_header)
        return verify_supabase_jwt(token, auth_settings)
    except JWTAuthError as exc:
        if exc.reason in _JWT_UNAVAILABLE_REASONS:
            return error_response(
                jwt_not_configured_message, status_code=503, code=jwt_not_configured_code
            )
        if exc.reason in {"missing_header", "invalid_header"}:
            return error_response(
                auth_required_message, status_code=401, code=auth_required_code
            )
        return error_response(invalid_token_message, status_code=401, code=invalid_token_code)


HISTORY_WRITE_AUTH_REQUIRED_MESSAGE = "authentication required"


def _resolve_history_write_auth(
    request: Request, *, analysis_run_id: str
) -> AuthenticatedUser | JSONResponse:
    """JWT-only authorization for every *mutating* /analysis-runs/{id}/...
    endpoint (DELETE, PATCH .../important, PATCH .../favorite, POST
    .../rerun/gemini, POST .../web-ai-gap/ai-comparison).

    Replaces the previous pattern of calling _resolve_history_access()
    (the GET endpoints' gate) and only checking project ownership
    `if access.mode == "jwt"` — that left HISTORY_READ_TOKEN alone
    sufficient to delete/modify *any* run across every project with no
    scoping at all, which is broader than what a "read token" should
    grant (found during the pre-demo audit, issue B2). This function
    requires a verified Supabase JWT unconditionally; HISTORY_READ_TOKEN
    is never consulted here, regardless of whether it's also present
    and correct.

    Still gated by READ_HISTORY_ENABLED/DATABASE_URL first — these
    endpoints remain part of the "history" feature and have nothing to
    act on if it's off/unconfigured — but the credential itself is
    always the caller's JWT (via _verify_jwt_bearer() above), plus the
    exact same can_user_access_analysis_run() ownership check every
    JWT-mode caller of these endpoints already had to pass. A caller
    with no Authorization header, an invalid/expired JWT, or a JWT for
    a project that doesn't own `analysis_run_id` is rejected before
    anything is read or written — identical to the JWT-mode behavior
    these endpoints already had; only the HISTORY_READ_TOKEN bypass is
    removed.
    """
    settings = load_db_settings()
    if not settings.read_history_enabled:
        return error_response(HISTORY_READ_NOT_CONFIGURED_MESSAGE, status_code=503)
    if settings.database_url is None:
        return error_response(HISTORY_READ_DB_NOT_CONFIGURED_MESSAGE, status_code=503)

    auth_result = _verify_jwt_bearer(
        request,
        auth_required_message=HISTORY_WRITE_AUTH_REQUIRED_MESSAGE,
        invalid_token_message=HISTORY_READ_INVALID_TOKEN_MESSAGE,
        jwt_not_configured_message=HISTORY_READ_JWT_NOT_CONFIGURED_MESSAGE,
    )
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, auth_result.user_id, analysis_run_id
            )
    except Exception:
        logger.exception(
            "Failed to check analysis run access for JWT-authenticated request"
        )
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(HISTORY_READ_ACCESS_DENIED_MESSAGE, status_code=403)

    return auth_result


def _parse_history_list_boundary(
    raw: str | None, *, field_name: str
) -> datetime | str | None:
    """Parses one of GET /analysis-runs's `startedFrom`/`startedTo`
    query params into a timezone-aware datetime for
    list_analysis_runs()/count_analysis_runs(), or returns an error
    message string on failure (never raises) — see
    feature/history-server-side-search-pagination's "日付境界と
    timezoneを明確に定義する". `raw` is expected to be a full ISO-8601
    instant *with* an explicit UTC offset (e.g.
    "2026-10-01T00:00:00+09:00") — the frontend is responsible for
    converting a JST calendar-date boundary into this exact shape (see
    app/lib/analysis-history.ts's jstDateStringToRangeBoundary()) so
    this backend function only ever compares already-unambiguous
    instants, never a bare date it would have to guess a timezone for.
    A naive (no-offset) string is deliberately rejected rather than
    assumed to be UTC or JST — guessing either way here could silently
    shift a day boundary by 9 hours from what the caller intended.
    """
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return f"{field_name} must be a valid ISO-8601 datetime"
    if parsed.tzinfo is None:
        return f"{field_name} must include a UTC offset"
    return parsed


# GET /analysis-runs's aiOverviewObservation/chatgptObservation/
# claudeObservation/geminiObservation query params — see
# services/analysis_history_repository.py's "AI観測状態フィルター"
# section for what each of these 5 values means and how they're
# computed. Kept here (not imported from that module) since it's
# purely an API-input-validation concern, same as
# _parse_history_list_boundary() above.
_OBSERVATION_FILTER_VALUES = ("mentioned", "not_mentioned", "off", "unavailable", "unknown")


def _parse_observation_filter(
    raw: str | None, *, field_name: str
) -> tuple[str | None, str | None]:
    """Validates one of the 4 AI-observation filter query params.
    Returns `(value, error_message)` — exactly one of the two is
    non-None, unlike _parse_history_list_boundary() above, since here
    both the "no filter" and "valid filter" outcomes are themselves
    `str | None`, so a single return value couldn't tell them apart
    from an error message the way that function's `datetime | str`
    return type could. `raw is None` (the param omitted) always means
    "no filter" and returns `(None, None)` directly, without checking
    it against _OBSERVATION_FILTER_VALUES.
    """
    if raw is None:
        return None, None
    if raw not in _OBSERVATION_FILTER_VALUES:
        return None, f"{field_name} must be one of {list(_OBSERVATION_FILTER_VALUES)}"
    return raw, None


@app.get("/analysis-runs", response_model=AnalysisRunListResponse)
def list_analysis_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    brand: str | None = None,
    status: str | None = None,
    search: str | None = None,
    important: bool | None = None,
    startedFrom: str | None = None,
    startedTo: str | None = None,
    aiOverviewObservation: str | None = None,
    chatgptObservation: str | None = None,
    claudeObservation: str | None = None,
    geminiObservation: str | None = None,
    favorite: bool | None = None,
    tagIds: str | None = None,
    categoryId: str | None = None,
    uncategorizedOnly: bool | None = None,
    sort: str = "newest",
):
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    if uncategorizedOnly and categoryId is not None:
        return error_response("categoryId and uncategorizedOnly must not both be set")

    # Comma-separated list, e.g. "tagIds=<uuid>,<uuid>" — blank/empty
    # entries are dropped rather than passed through as a (never
    # matching) empty-string tag id. `None` (the param omitted
    # entirely, or resolving to no non-blank entries) means "no tag
    # filter", same as every other optional filter here.
    tag_ids = (
        [part.strip() for part in tagIds.split(",") if part.strip()]
        if tagIds
        else None
    )
    if tag_ids == []:
        tag_ids = None

    started_from = _parse_history_list_boundary(startedFrom, field_name="startedFrom")
    if isinstance(started_from, str):
        return error_response(started_from)
    started_to = _parse_history_list_boundary(startedTo, field_name="startedTo")
    if isinstance(started_to, str):
        return error_response(started_to)

    ai_overview_observation, err = _parse_observation_filter(
        aiOverviewObservation, field_name="aiOverviewObservation"
    )
    if err:
        return error_response(err)
    chatgpt_observation, err = _parse_observation_filter(
        chatgptObservation, field_name="chatgptObservation"
    )
    if err:
        return error_response(err)
    claude_observation, err = _parse_observation_filter(
        claudeObservation, field_name="claudeObservation"
    )
    if err:
        return error_response(err)
    gemini_observation, err = _parse_observation_filter(
        geminiObservation, field_name="geminiObservation"
    )
    if err:
        return error_response(err)

    sort_order = "oldest" if sort == "oldest" else "newest"

    # project_ids is always passed explicitly in JWT mode (never
    # omitted) — an empty list means "no accessible projects" and
    # list_analysis_runs()/count_analysis_runs() short-circuit to
    # []/0 without touching the DB, rather than either ever falling
    # back to the unrestricted call below. Shared between the list
    # and count calls so the two can never see a different set of
    # accessible projects than each other.
    project_ids = access.project_ids if access.mode == "jwt" else None

    shared_filter_kwargs = dict(
        brand=brand,
        status=status,
        project_ids=project_ids,
        search=search,
        important=important,
        started_from=started_from,
        started_to=started_to,
        ai_overview_observation=ai_overview_observation,
        chatgpt_observation=chatgpt_observation,
        claude_observation=claude_observation,
        gemini_observation=gemini_observation,
        favorite=favorite,
        tag_ids=tag_ids,
        category_id=categoryId,
        uncategorized_only=bool(uncategorizedOnly),
    )

    try:
        items = repository_list_analysis_runs(
            limit=limit, offset=offset, sort=sort_order, **shared_filter_kwargs
        )
        total = repository_count_analysis_runs(**shared_filter_kwargs)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    return AnalysisRunListResponse(
        items=[AnalysisRunListItem(**item) for item in items],
        limit=limit,
        offset=offset,
        total=total,
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
        isImportant=detail.get("isImportant", False),
        isFavorite=detail.get("isFavorite", False),
        projectId=detail.get("projectId"),
        tags=detail.get("tags", []),
        category=detail.get("category"),
    )


@app.delete("/analysis-runs/{analysis_run_id}")
def delete_analysis_run(analysis_run_id: str, request: Request):
    """Soft-deletes one saved analysis run (see
    services.analysis_history_repository.soft_delete_analysis_run()) —
    added so repeated full-ON/single-ON provider verification runs can
    be cleared out of the history list without losing them permanently
    (analysis_results/brands are untouched; `deleted_at` can be cleared
    manually later if a delete needs undoing).

    Requires a verified Supabase JWT whose caller can access this run's
    project (see _resolve_history_write_auth()) — HISTORY_READ_TOKEN is
    never sufficient to delete a run, regardless of project
    (fix/history-read-token-write-isolation, pre-demo audit issue B2).
    """
    auth_result = _resolve_history_write_auth(request, analysis_run_id=analysis_run_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        deleted = repository_soft_delete_analysis_run(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    if not deleted:
        return error_response("analysis run not found", status_code=404)

    return {"deleted": True}


IMPORTANT_UPDATE_FAILED_MESSAGE = "failed to update analysis history"


@app.patch(
    "/analysis-runs/{analysis_run_id}/important",
    response_model=AnalysisRunImportantResponse,
)
def set_analysis_run_important(
    analysis_run_id: str, body: AnalysisRunImportantRequest, request: Request
):
    """Marks (or unmarks) one saved analysis run as important — see
    docs/38_history_marking_design.md 案A and "7. API設計案". Backed by
    services.analysis_history_repository.set_analysis_run_important(),
    which sets `analysis_runs.is_important` directly (backend/migrations/
    004_add_is_important_to_analysis_runs.sql).

    Requires a verified Supabase JWT whose caller can access this run's
    project (see _resolve_history_write_auth()) — HISTORY_READ_TOKEN is
    never sufficient to mark a run important, regardless of project
    (fix/history-read-token-write-isolation, pre-demo audit issue B2).
    """
    auth_result = _resolve_history_write_auth(request, analysis_run_id=analysis_run_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        updated = repository_set_analysis_run_important(
            analysis_run_id, is_important=body.isImportant
        )
    except AnalysisHistoryReadError:
        return error_response(IMPORTANT_UPDATE_FAILED_MESSAGE, status_code=503)

    if not updated:
        return error_response("analysis run not found", status_code=404)

    return AnalysisRunImportantResponse(
        analysisRunId=analysis_run_id, isImportant=body.isImportant
    )


FAVORITE_UPDATE_FAILED_MESSAGE = "failed to update analysis history"


@app.patch(
    "/analysis-runs/{analysis_run_id}/favorite",
    response_model=AnalysisRunFavoriteResponse,
)
def set_analysis_run_favorite(
    analysis_run_id: str, body: AnalysisRunFavoriteRequest, request: Request
):
    """Marks (or unmarks) one saved analysis run as a favorite —
    feature/history-favorite-flag, independent of the existing
    important flag above. Backed by
    services.analysis_history_repository.set_analysis_run_favorite(),
    which sets `analysis_runs.is_favorite` directly (backend/migrations/
    007_add_is_favorite_to_analysis_runs.sql).

    Mirrors set_analysis_run_important() above exactly, including
    authorization: requires a verified Supabase JWT whose caller can
    access this run's project (see _resolve_history_write_auth()) —
    HISTORY_READ_TOKEN is never sufficient, regardless of project
    (fix/history-read-token-write-isolation, pre-demo audit issue B2).
    Same queued/running restriction policy as before — there is
    deliberately no status check here either; like the important flag,
    this endpoint itself never blocks on `analysis_runs.status`, and a
    queued/running job's favorite toggle is instead kept out of reach
    by the frontend never rendering the button for those statuses (see
    app/lib/analysis-history.ts's canManageHistoryListItem(), reused
    unchanged for favorite).
    """
    auth_result = _resolve_history_write_auth(request, analysis_run_id=analysis_run_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        updated = repository_set_analysis_run_favorite(
            analysis_run_id, is_favorite=body.isFavorite
        )
    except AnalysisHistoryReadError:
        return error_response(FAVORITE_UPDATE_FAILED_MESSAGE, status_code=503)

    if not updated:
        return error_response("analysis run not found", status_code=404)

    return AnalysisRunFavoriteResponse(
        analysisRunId=analysis_run_id, isFavorite=body.isFavorite
    )


GEMINI_RERUN_FAILED_MESSAGE = "failed to update analysis result after Gemini rerun"


@app.post(
    "/analysis-runs/{analysis_run_id}/rerun/gemini",
    response_model=GeminiRerunResponse,
)
def rerun_gemini_observation(analysis_run_id: str, request: Request):
    """Re-runs **only** the Gemini observation for one saved analysis
    run, and persists the updated card in place — added so a suspected
    mid-way-truncated Gemini answer can be re-fetched without re-running
    the rest of `/analyze` (which would also re-call DataForSEO/ChatGPT/
    Claude and re-fetch Common Crawl/web pages, consuming their request
    budgets for no reason related to the problem being investigated).
    See services/gemini_rerun.py for what is and isn't touched.

    Requires a verified Supabase JWT whose caller can access this run's
    project (see _resolve_history_write_auth()) — HISTORY_READ_TOKEN is
    never sufficient to trigger a Gemini re-run, regardless of project
    (fix/history-read-token-write-isolation, pre-demo audit issue B2).

    Never calls DataForSEO/ChatGPT/Claude/Common Crawl/web fetch — only
    services/gemini_provider.py's build_gemini_observation(), the same
    function `/analyze` itself uses. A failed or disabled Gemini call
    (see GeminiRerunOutcome.success) returns 502 without writing
    anything, so the previously saved result is never corrupted or
    cleared by a failed re-run.
    """
    auth_result = _resolve_history_write_auth(request, analysis_run_id=analysis_run_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        detail = repository_get_analysis_run(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    if detail is None:
        return error_response("analysis run not found", status_code=404)

    outcome = rerun_gemini_for_analysis_run(
        brand_name=detail["brand"]["name"],
        input_snapshot=detail["run"]["inputSnapshot"],
        result_json=detail["result"],
        meta_json=detail["meta"],
    )
    if not outcome.success:
        # outcome.reason is always a short, safe-to-display string (see
        # GeminiRerunOutcome's docstring) — never an API key/token, and
        # already the same kind of text meta.geminiProvider.reason
        # surfaces from a normal /analyze call.
        return error_response(outcome.reason, status_code=502)

    try:
        updated = repository_update_analysis_result(
            analysis_run_id,
            result_json=outcome.result_json,
            meta_json=outcome.meta_json,
        )
    except AnalysisHistoryReadError:
        return error_response(GEMINI_RERUN_FAILED_MESSAGE, status_code=503)

    if not updated:
        return error_response("analysis run not found", status_code=404)

    return GeminiRerunResponse(
        updated=True,
        analysisRunId=analysis_run_id,
        result=outcome.result_json,
    )


AI_GAP_COMPARISON_FAILED_MESSAGE = "failed to update analysis result after AI comparison"


@app.post(
    "/analysis-runs/{analysis_run_id}/web-ai-gap/ai-comparison",
    response_model=WebAiGapAiComparisonResponse,
)
def generate_web_ai_gap_ai_comparison(analysis_run_id: str, request: Request):
    """Generates an AI-powered (not rule-based) comparison of one saved
    analysis run's Web excerpt and AI observation summaries, and
    persists it alongside (never over) the existing rule-based
    `webAiGap` — see services/ai_gap_comparison.py and
    docs/39_ai_gap_comparison_design.md. Manual/on-demand only: never
    called from `/analyze` itself.

    Requires a verified Supabase JWT whose caller can access this run's
    project (see _resolve_history_write_auth()) — HISTORY_READ_TOKEN is
    never sufficient to trigger an AI-gap comparison generation,
    regardless of project (fix/history-read-token-write-isolation,
    pre-demo audit issue B2).

    Never calls DataForSEO/ChatGPT/Claude observation/Gemini
    observation/Common Crawl/web fetch — only
    services/ai_gap_comparison.py's generate_ai_gap_comparison(), whose
    only external call is a single Anthropic Messages API request built
    entirely from the already-saved result_json. A failure that was
    never attempted (missing/insufficient input, or Anthropic API key
    not configured — see AiGapComparisonOutcome.unavailable) returns
    503; a failure where the Anthropic call was attempted and failed
    returns 502. Either way, nothing is written — the previously saved
    result (including any earlier webAiGapAiComparison) is unchanged.
    """
    auth_result = _resolve_history_write_auth(request, analysis_run_id=analysis_run_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        detail = repository_get_analysis_run(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    if detail is None:
        return error_response("analysis run not found", status_code=404)

    outcome = generate_ai_gap_comparison(
        brand_name=detail["brand"]["name"],
        result_json=detail["result"],
        analysis_run_id=analysis_run_id,
    )
    if not outcome.success:
        status_code = 503 if outcome.unavailable else 502
        # Adds a `reason` field (one of services/ai_gap_comparison.py's
        # safe REASON_* codes) alongside the existing `error` message —
        # never a secret or the raw Claude output, see that module's
        # docstring — so a developer can tell failure stages apart from
        # the HTTP response alone, without needing Render log access.
        # error_response() itself is left untouched since it's shared
        # by every other endpoint in this file.
        return JSONResponse(
            status_code=status_code,
            content={"error": outcome.reason, "reason": outcome.internal_reason},
        )

    updated_result_json = dict(detail["result"])
    updated_result_json["webAiGapAiComparison"] = outcome.comparison.model_dump()

    try:
        updated = repository_update_analysis_result(
            analysis_run_id,
            result_json=updated_result_json,
            meta_json=detail["meta"],
        )
    except AnalysisHistoryReadError:
        return error_response(AI_GAP_COMPARISON_FAILED_MESSAGE, status_code=503)

    if not updated:
        return error_response("analysis run not found", status_code=404)

    return WebAiGapAiComparisonResponse(
        analysisRunId=analysis_run_id,
        webAiGapAiComparison=outcome.comparison,
    )


# --- Tags / categories (feature/history-tags-categories) -----------------
#
# See backend/migrations/008_add_tags_and_categories.sql and
# services/analysis_history_repository.py's own "Tags / categories"
# section for the full schema/constraint design and the exceptions
# this section's endpoints map to HTTP statuses.
#
# Authorization is deliberately stricter than is_important/is_favorite
# above for every *mutating* endpoint in this section: Supabase JWT is
# required with no HISTORY_READ_TOKEN fallback of any kind (this
# task's explicit "HISTORY_READ_TOKENだけでの変更は禁止"), plus an
# explicit project-membership (for /tags, /categories) or
# run-accessibility (for the /analysis-runs/{id}/... endpoints) check
# — reusing can_user_access_project()/can_user_access_analysis_run()/
# can_user_access_tag()/can_user_access_category() exactly as the
# existing JWT-mode read paths already do. GET /tags and GET
# /categories (read, listing) are the one exception: they use the
# existing `_resolve_history_access()` gate instead, so they remain
# compatible with both JWT and HISTORY_READ_TOKEN callers, exactly
# like GET /analysis-runs — this task's "読み取りAPIは既存の認証方式と
# の互換性を維持".

TAG_CATEGORY_AUTH_REQUIRED_MESSAGE = "authentication required"
TAG_CATEGORY_INVALID_TOKEN_MESSAGE = "invalid or expired authentication token"
TAG_CATEGORY_JWT_NOT_CONFIGURED_MESSAGE = "JWT verification is not configured"
TAG_CATEGORY_ACCESS_DENIED_MESSAGE = "access denied"
TAG_CATEGORY_FAILED_MESSAGE = "failed to update tags or categories"
TAG_NOT_FOUND_MESSAGE = "tag not found"
CATEGORY_NOT_FOUND_MESSAGE = "category not found"
TAG_NAME_CONFLICT_MESSAGE = "a tag with this name already exists in this project"
CATEGORY_NAME_CONFLICT_MESSAGE = "a category with this name already exists in this project"
TAG_NAME_INVALID_MESSAGE = (
    "tag name must be between 1 and 100 characters after trimming whitespace"
)
CATEGORY_NAME_INVALID_MESSAGE = (
    "category name must be between 1 and 100 characters after trimming whitespace"
)
ANALYSIS_RUN_NOT_FOUND_FOR_EDIT_MESSAGE = "analysis run not found"
ANALYSIS_RUN_STATUS_CONFLICT_MESSAGE = (
    "this analysis run is still in progress and cannot be edited yet"
)
CATEGORY_REQUIRES_PROJECT_MESSAGE = (
    "this analysis run has no project and cannot be assigned a category"
)


def _resolve_tag_category_auth(request: Request) -> AuthenticatedUser | JSONResponse:
    """Verifies a Supabase Auth JWT with no HISTORY_READ_TOKEN fallback
    of any kind, via the shared _verify_jwt_bearer() helper — structurally
    identical to _resolve_jwt_only_auth()/_resolve_job_auth() below,
    with this section's own error messages. Shared by every *mutating*
    tags/categories endpoint (never by the GET list endpoints, which
    use `_resolve_history_access()` instead — see this section's
    module docstring)."""
    return _verify_jwt_bearer(
        request,
        auth_required_message=TAG_CATEGORY_AUTH_REQUIRED_MESSAGE,
        invalid_token_message=TAG_CATEGORY_INVALID_TOKEN_MESSAGE,
        jwt_not_configured_message=TAG_CATEGORY_JWT_NOT_CONFIGURED_MESSAGE,
    )


def _resolve_project_write_access(
    request: Request, *, project_id: str
) -> AuthenticatedUser | JSONResponse:
    """_resolve_tag_category_auth() plus an explicit
    can_user_access_project() check against `project_id` — shared by
    POST /tags and POST /categories (the two endpoints that create a
    new project-scoped resource directly from a caller-supplied
    `projectId`, rather than inheriting it from an already-existing
    tag/category/analysis run)."""
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_project(conn, auth_result.user_id, project_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check project access for tag/category write")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not allowed:
        return error_response(TAG_CATEGORY_ACCESS_DENIED_MESSAGE, status_code=403)

    return auth_result


@app.get("/tags", response_model=TagListResponse)
def list_tags_endpoint(request: Request, projectId: str | None = None):
    """Lists tags — uses the existing `_resolve_history_access()` gate
    (JWT or HISTORY_READ_TOKEN), same compatibility story as GET
    /analysis-runs. In JWT mode, always scoped to the caller's
    accessible projects (`access.project_ids`); `projectId` further
    narrows to one specific project (in either mode) — a JWT caller
    who passes a `projectId` they don't have access to simply sees an
    empty list, the same "scoped, never an information leak" shape
    GET /analysis-runs already has for `project_ids`."""
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    project_ids = access.project_ids if access.mode == "jwt" else None

    try:
        tags = list_tags(project_ids=project_ids, project_id=projectId)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    return TagListResponse(tags=[TagItem(**tag) for tag in tags])


@app.post("/tags", response_model=TagItem, status_code=201)
def create_tag_endpoint(payload: TagCreateRequest, request: Request):
    project_id = (payload.projectId or "").strip()
    if not project_id:
        return error_response("projectId is required")
    name = (payload.name or "").strip()
    if not name:
        return error_response(TAG_NAME_INVALID_MESSAGE)

    auth_result = _resolve_project_write_access(request, project_id=project_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        tag = create_tag(project_id=project_id, name=name)
    except TagNameConflictError:
        return error_response(TAG_NAME_CONFLICT_MESSAGE, status_code=409)
    except TagNameInvalidError:
        return error_response(TAG_NAME_INVALID_MESSAGE)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    return TagItem(**tag)


@app.patch("/tags/{tag_id}", response_model=TagItem)
def rename_tag_endpoint(tag_id: str, payload: TagRenameRequest, request: Request):
    name = (payload.name or "").strip()
    if not name:
        return error_response(TAG_NAME_INVALID_MESSAGE)

    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_tag(conn, auth_result.user_id, tag_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check tag access")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(TAG_NOT_FOUND_MESSAGE, status_code=404)

    try:
        tag = rename_tag(tag_id, name=name)
    except TagNameConflictError:
        return error_response(TAG_NAME_CONFLICT_MESSAGE, status_code=409)
    except TagNameInvalidError:
        return error_response(TAG_NAME_INVALID_MESSAGE)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if tag is None:
        return error_response(TAG_NOT_FOUND_MESSAGE, status_code=404)
    return TagItem(**tag)


@app.delete("/tags/{tag_id}")
def delete_tag_endpoint(tag_id: str, request: Request):
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_tag(conn, auth_result.user_id, tag_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check tag access")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(TAG_NOT_FOUND_MESSAGE, status_code=404)

    try:
        deleted = delete_tag(tag_id)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not deleted:
        return error_response(TAG_NOT_FOUND_MESSAGE, status_code=404)
    return {"deleted": True}


@app.get("/categories", response_model=CategoryListResponse)
def list_categories_endpoint(request: Request, projectId: str | None = None):
    """Mirrors list_tags_endpoint() above exactly, one table
    swapped."""
    access = _resolve_history_access(request)
    if isinstance(access, JSONResponse):
        return access

    project_ids = access.project_ids if access.mode == "jwt" else None

    try:
        categories = list_categories(project_ids=project_ids, project_id=projectId)
    except AnalysisHistoryReadError:
        return error_response(HISTORY_READ_FAILED_MESSAGE, status_code=503)

    return CategoryListResponse(categories=[CategoryItem(**c) for c in categories])


@app.post("/categories", response_model=CategoryItem, status_code=201)
def create_category_endpoint(payload: CategoryCreateRequest, request: Request):
    project_id = (payload.projectId or "").strip()
    if not project_id:
        return error_response("projectId is required")
    name = (payload.name or "").strip()
    if not name:
        return error_response(CATEGORY_NAME_INVALID_MESSAGE)

    auth_result = _resolve_project_write_access(request, project_id=project_id)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        category = create_category(project_id=project_id, name=name)
    except CategoryNameConflictError:
        return error_response(CATEGORY_NAME_CONFLICT_MESSAGE, status_code=409)
    except CategoryNameInvalidError:
        return error_response(CATEGORY_NAME_INVALID_MESSAGE)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    return CategoryItem(**category)


@app.patch("/categories/{category_id}", response_model=CategoryItem)
def rename_category_endpoint(
    category_id: str, payload: CategoryRenameRequest, request: Request
):
    name = (payload.name or "").strip()
    if not name:
        return error_response(CATEGORY_NAME_INVALID_MESSAGE)

    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_category(conn, auth_result.user_id, category_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check category access")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(CATEGORY_NOT_FOUND_MESSAGE, status_code=404)

    try:
        category = rename_category(category_id, name=name)
    except CategoryNameConflictError:
        return error_response(CATEGORY_NAME_CONFLICT_MESSAGE, status_code=409)
    except CategoryNameInvalidError:
        return error_response(CATEGORY_NAME_INVALID_MESSAGE)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if category is None:
        return error_response(CATEGORY_NOT_FOUND_MESSAGE, status_code=404)
    return CategoryItem(**category)


@app.delete("/categories/{category_id}")
def delete_category_endpoint(category_id: str, request: Request):
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_category(conn, auth_result.user_id, category_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check category access")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(CATEGORY_NOT_FOUND_MESSAGE, status_code=404)

    try:
        deleted = delete_category(category_id)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not deleted:
        return error_response(CATEGORY_NOT_FOUND_MESSAGE, status_code=404)
    return {"deleted": True}


@app.post("/analysis-runs/{analysis_run_id}/tags", status_code=204)
def attach_tag_endpoint(
    analysis_run_id: str, payload: AnalysisRunTagAttachRequest, request: Request
):
    """Attaches one tag to one run — idempotent (see
    attach_tag_to_analysis_run()). Access is checked against
    `analysis_run_id` itself (can_user_access_analysis_run()), exactly
    like PATCH /analysis-runs/{id}/important's existing JWT-mode
    check, but with no HISTORY_READ_TOKEN fallback at all (see this
    section's module docstring) — unlike /important/, this endpoint
    always requires a JWT.
    """
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, auth_result.user_id, analysis_run_id
            )
    except Exception:
        logger.exception("Failed to check analysis run access for tag attach")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(TAG_CATEGORY_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        attached = attach_tag_to_analysis_run(analysis_run_id, payload.tagId)
    except AnalysisRunStatusConflictError:
        return error_response(ANALYSIS_RUN_STATUS_CONFLICT_MESSAGE, status_code=409)
    except TagNotAssignableError:
        return error_response(TAG_NOT_FOUND_MESSAGE, status_code=404)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not attached:
        return error_response(ANALYSIS_RUN_NOT_FOUND_FOR_EDIT_MESSAGE, status_code=404)
    return Response(status_code=204)


@app.delete("/analysis-runs/{analysis_run_id}/tags/{tag_id}", status_code=204)
def detach_tag_endpoint(analysis_run_id: str, tag_id: str, request: Request):
    """Detaches one tag from one run — idempotent (see
    detach_tag_from_analysis_run()). Same access/auth shape as
    attach_tag_endpoint() above."""
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, auth_result.user_id, analysis_run_id
            )
    except Exception:
        logger.exception("Failed to check analysis run access for tag detach")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(TAG_CATEGORY_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        detached = detach_tag_from_analysis_run(analysis_run_id, tag_id)
    except AnalysisRunStatusConflictError:
        return error_response(ANALYSIS_RUN_STATUS_CONFLICT_MESSAGE, status_code=409)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not detached:
        return error_response(ANALYSIS_RUN_NOT_FOUND_FOR_EDIT_MESSAGE, status_code=404)
    return Response(status_code=204)


@app.put("/analysis-runs/{analysis_run_id}/category", status_code=204)
def set_analysis_run_category_endpoint(
    analysis_run_id: str, payload: AnalysisRunCategorySetRequest, request: Request
):
    """Sets or clears (`categoryId: null`) one run's category. Same
    access/auth shape as attach_tag_endpoint() above."""
    auth_result = _resolve_tag_category_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, auth_result.user_id, analysis_run_id
            )
    except Exception:
        logger.exception("Failed to check analysis run access for category set")
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)
    if not allowed:
        return error_response(TAG_CATEGORY_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        updated = set_analysis_run_category(analysis_run_id, payload.categoryId)
    except AnalysisRunStatusConflictError:
        return error_response(ANALYSIS_RUN_STATUS_CONFLICT_MESSAGE, status_code=409)
    except CategoryNotAssignableError:
        return error_response(CATEGORY_NOT_FOUND_MESSAGE, status_code=404)
    except CategoryRequiresProjectError:
        return error_response(CATEGORY_REQUIRES_PROJECT_MESSAGE, status_code=400)
    except AnalysisHistoryReadError:
        return error_response(TAG_CATEGORY_FAILED_MESSAGE, status_code=503)

    if not updated:
        return error_response(ANALYSIS_RUN_NOT_FOUND_FOR_EDIT_MESSAGE, status_code=404)
    return Response(status_code=204)


# --- GET /me/projects — see docs/40_async_analysis_jobs_design.md
# "Phase 3". A minimal, read-only, JWT-only endpoint (no
# HISTORY_READ_TOKEN fallback, mirroring the job endpoints below) so
# the frontend can learn which project(s) the current user may pass
# as POST /analysis-jobs' required `projectId` — nothing else in this
# API ever told a caller that. Deliberately NOT gated by
# ANALYSIS_JOBS_ENABLED: this is a general "list my accessible
# projects" lookup, not part of the job feature itself, and reveals
# nothing beyond project ids the caller already has access to.

ME_PROJECTS_AUTH_REQUIRED_MESSAGE = "authentication required"
ME_PROJECTS_INVALID_TOKEN_MESSAGE = "invalid or expired authentication token"
ME_PROJECTS_JWT_NOT_CONFIGURED_MESSAGE = "JWT verification is not configured"
ME_PROJECTS_FAILED_MESSAGE = "failed to list accessible projects"


def _resolve_jwt_only_auth(request: Request) -> AuthenticatedUser | JSONResponse:
    """Verifies a Supabase Auth JWT with no HISTORY_READ_TOKEN
    fallback of any kind, via the shared _verify_jwt_bearer() helper —
    shared by GET /me/projects. Structurally identical to
    _resolve_job_auth() below minus the ANALYSIS_JOBS_ENABLED gate
    (this endpoint isn't part of that feature)."""
    return _verify_jwt_bearer(
        request,
        auth_required_message=ME_PROJECTS_AUTH_REQUIRED_MESSAGE,
        invalid_token_message=ME_PROJECTS_INVALID_TOKEN_MESSAGE,
        jwt_not_configured_message=ME_PROJECTS_JWT_NOT_CONFIGURED_MESSAGE,
    )


@app.get("/me/projects", response_model=MeProjectsResponse)
def get_my_projects(request: Request):
    """Returns the ids of every project the caller (identified by
    their verified JWT) belongs to — reuses
    services.project_access.get_accessible_project_ids() verbatim, the
    exact same helper the JWT-mode history read APIs already use to
    scope what a caller may see. Never returns another user's
    projects. An empty list is a valid, successful response (the user
    belongs to no project yet) — callers must handle 0 results rather
    than treating it as an error."""
    auth_result = _resolve_jwt_only_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    authenticated_user = auth_result

    try:
        with open_history_db_connection() as conn:
            project_ids = get_accessible_project_ids(conn, authenticated_user.user_id)
    except Exception:
        logger.exception("Failed to list accessible projects for /me/projects")
        return error_response(ME_PROJECTS_FAILED_MESSAGE, status_code=503)

    return MeProjectsResponse(projects=[MeProjectItem(id=project_id) for project_id in project_ids])


# --- Async analysis jobs, Phase 1 only (POST /analysis-jobs, GET
# /analysis-jobs/{id}, GET /analysis-jobs/{id}/result) — see
# docs/40_async_analysis_jobs_design.md. Entirely separate from
# POST /analyze above: no request/response field of /analyze is
# touched by anything below, and /analyze itself is unchanged.
#
# Phase 1 only ever creates a 'queued' row and returns it — there is no
# worker yet (that is Phase 2), so a job created today sits in
# 'queued' forever. Gated end-to-end by ANALYSIS_JOBS_ENABLED (see
# services/analysis_jobs_settings.py), which defaults to False and
# must stay False in production until Phase 2/3 ship (docs/40 "15").
#
# Authentication is Supabase Auth JWT only (see _resolve_job_auth()
# below) — unlike _resolve_history_access() above, there is no
# HISTORY_READ_TOKEN fallback for any of these three endpoints, and no
# dependency on READ_HISTORY_ENABLED (an unrelated flag for the
# existing history list/detail APIs).

ANALYSIS_JOBS_NOT_ENABLED_MESSAGE = "analysis jobs API is not enabled"
ANALYSIS_JOBS_AUTH_REQUIRED_MESSAGE = "authentication required"
ANALYSIS_JOBS_INVALID_TOKEN_MESSAGE = "invalid or expired authentication token"
ANALYSIS_JOBS_JWT_NOT_CONFIGURED_MESSAGE = "analysis jobs JWT verification is not configured"
ANALYSIS_JOBS_ACCESS_DENIED_MESSAGE = "analysis job access denied"
ANALYSIS_JOBS_FAILED_MESSAGE = "failed to process analysis job request"
ANALYSIS_JOBS_NOT_FOUND_MESSAGE = "analysis job not found"
ANALYSIS_JOBS_NOT_READY_MESSAGE = "analysis job is not finished yet"
ANALYSIS_JOBS_CONFLICT_MESSAGE = (
    "an analysis job with this idempotency key already exists with different input"
)
ANALYSIS_JOBS_CANCELLED_CONFLICT_MESSAGE = (
    "this idempotency key belongs to a cancelled analysis job"
)
ANALYSIS_JOBS_LIMIT_MESSAGE = "too many queued analysis jobs"
ANALYSIS_JOBS_NOT_CANCELLABLE_MESSAGE = "analysis job can no longer be cancelled"


def _resolve_job_auth(request: Request) -> AuthenticatedUser | JSONResponse:
    """Authenticates a caller for POST/GET /analysis-jobs* — see
    docs/40_async_analysis_jobs_design.md "8.1". Returns the
    AuthenticatedUser on success, or a JSONResponse to return
    immediately otherwise:

    - ANALYSIS_JOBS_ENABLED is not set -> 404 (the endpoint behaves as
      though it doesn't exist at all — docs/40 "7.1" — rather than
      revealing that a disabled feature exists via a more specific
      error).
    - JWT verification itself isn't configured (AUTH_JWT_ENABLED=false
      or SUPABASE_JWKS_URL unset), or this server can't reach its JWKS
      endpoint right now -> 503.
    - Authorization header missing/malformed, or the token fails
      verification for any other reason (expired, bad signature,
      wrong issuer/audience, no subject) -> 401.

    Reuses the same `_JWT_UNAVAILABLE_REASONS` classification as
    _resolve_history_access() above, since the underlying JWT
    verification call (services/jwt_auth.verify_supabase_jwt()) is the
    same function and raises the same JWTAuthError.reason values.
    """
    jobs_settings = load_analysis_jobs_settings()
    if not jobs_settings.enabled:
        return error_response(ANALYSIS_JOBS_NOT_ENABLED_MESSAGE, status_code=404)

    return _verify_jwt_bearer(
        request,
        auth_required_message=ANALYSIS_JOBS_AUTH_REQUIRED_MESSAGE,
        invalid_token_message=ANALYSIS_JOBS_INVALID_TOKEN_MESSAGE,
        jwt_not_configured_message=ANALYSIS_JOBS_JWT_NOT_CONFIGURED_MESSAGE,
    )


@app.post("/analysis-jobs", response_model=AnalysisJobAcceptedResponse, status_code=202)
def create_analysis_job(payload: AnalysisJobCreateRequest, request: Request):
    """Phase 1 of docs/40_async_analysis_jobs_design.md — accepts a
    job and persists it as a 'queued' analysis_runs row (see
    services.analysis_history_repository.create_queued_analysis_run()),
    but never executes any analysis. No AI/external-provider call of
    any kind happens on this path.

    Validates the same brandName/documents/urls shape POST /analyze
    already enforces (MAX_BRAND_NAME_LENGTH/_validate_documents()/
    MAX_URLS), plus the two fields unique to a job: `projectId` (the
    caller must be a member of the organization owning it, checked via
    services.project_access.can_user_access_project() — the same
    membership check the existing read APIs use, reused here as the
    stand-in for "may create" since this project has no finer-grained
    per-action permission model yet) and `idempotencyKey` (required,
    see docs/40 "10").
    """
    auth_result = _resolve_job_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    authenticated_user = auth_result

    project_id = (payload.projectId or "").strip()
    if not project_id:
        return error_response("projectId is required")

    idempotency_key = (payload.idempotencyKey or "").strip()
    if not idempotency_key:
        return error_response("idempotencyKey is required")

    brand_name = (payload.brandName or "").strip()
    if not brand_name:
        return error_response("brandName is required")
    if len(brand_name) > MAX_BRAND_NAME_LENGTH:
        return error_response(
            f"brandName must be {MAX_BRAND_NAME_LENGTH} characters or fewer"
        )

    if payload.documents is not None:
        validation_error = _validate_documents(payload.documents)
        if validation_error:
            return error_response(validation_error)
    elif payload.urls is not None:
        if len(payload.urls) == 0:
            return error_response("urls must not be empty")
        if len(payload.urls) > MAX_URLS:
            return error_response(f"urls must contain {MAX_URLS} or fewer entries")

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_project(conn, authenticated_user.user_id, project_id)
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check project access for analysis job creation")
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if not allowed:
        return error_response(ANALYSIS_JOBS_ACCESS_DENIED_MESSAGE, status_code=403)

    jobs_settings = load_analysis_jobs_settings()

    try:
        result = create_queued_analysis_run(
            project_id=project_id,
            created_by_user_id=authenticated_user.user_id,
            idempotency_key=idempotency_key,
            brand_name=brand_name,
            documents=payload.documents,
            urls=payload.urls,
            common_crawl_mode=payload.commonCrawlMode,
            common_crawl_domain=payload.commonCrawlDomain,
            ai_overview_mode=payload.aiOverviewMode,
            chatgpt_mode=payload.chatgptMode,
            claude_mode=payload.claudeMode,
            gemini_mode=payload.geminiMode,
            max_queued_per_project=jobs_settings.max_queued_per_project,
            max_queued_per_user=jobs_settings.max_queued_per_user,
            official_url=payload.officialUrl,
        )
    except AnalysisJobCreateConflictError:
        return error_response(ANALYSIS_JOBS_CONFLICT_MESSAGE, status_code=409)
    except AnalysisJobCancelledConflictError:
        return error_response(ANALYSIS_JOBS_CANCELLED_CONFLICT_MESSAGE, status_code=409)
    except AnalysisJobLimitExceededError:
        return error_response(ANALYSIS_JOBS_LIMIT_MESSAGE, status_code=429)
    except AnalysisHistoryReadError:
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    return AnalysisJobAcceptedResponse(
        analysisRunId=result.analysis_run_id, status=result.status
    )


@app.get("/analysis-jobs/{analysis_run_id}", response_model=AnalysisJobStatusResponse)
def get_analysis_job(analysis_run_id: str, request: Request):
    """GET /analysis-jobs/{id} — see docs/40_async_analysis_jobs_design.md
    "7.2". Uses the same JWT-mode authorization pattern as the existing
    GET /analysis-runs/{id}: access is checked against
    `analysis_run_id` itself (via can_user_access_analysis_run()) before
    anything else is fetched, so a nonexistent id and an inaccessible
    id are indistinguishable (both 403) — same existence-leak avoidance
    as the existing history detail endpoint."""
    auth_result = _resolve_job_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    authenticated_user = auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, authenticated_user.user_id, analysis_run_id
            )
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check analysis run access for analysis job status")
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if not allowed:
        return error_response(ANALYSIS_JOBS_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        job = get_analysis_job_status(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if job is None:
        return error_response(ANALYSIS_JOBS_NOT_FOUND_MESSAGE, status_code=404)

    return AnalysisJobStatusResponse(
        analysisRunId=job["id"],
        status=job["status"],
        startedAt=job["startedAt"],
        completedAt=job["completedAt"],
        errorMessage=job["errorMessage"],
    )


@app.get(
    "/analysis-jobs/{analysis_run_id}/result", response_model=AnalysisJobResultResponse
)
def get_analysis_job_result_endpoint(analysis_run_id: str, request: Request):
    """GET /analysis-jobs/{id}/result — see
    docs/40_async_analysis_jobs_design.md "13.2". `queued`/`running`
    jobs return 409 (no result-shaped body exists yet, and the
    placeholder result_json='{}' Phase 1 writes at creation time is
    never returned as if it were a real result — see
    services.analysis_history_repository.get_analysis_job_result()).
    `completed`/`partial`/`failed` all return 200 with this endpoint's
    normal response model; a `failed` job has `result`/`meta` both
    None and `errorMessage` set instead."""
    auth_result = _resolve_job_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    authenticated_user = auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_access_analysis_run(
                conn, authenticated_user.user_id, analysis_run_id
            )
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check analysis run access for analysis job result")
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if not allowed:
        return error_response(ANALYSIS_JOBS_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        job = get_analysis_job_result(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if job is None:
        return error_response(ANALYSIS_JOBS_NOT_FOUND_MESSAGE, status_code=404)

    if job["status"] in ("queued", "running"):
        return JSONResponse(
            status_code=409,
            content={"error": ANALYSIS_JOBS_NOT_READY_MESSAGE, "status": job["status"]},
        )

    return AnalysisJobResultResponse(
        analysisRunId=job["id"],
        status=job["status"],
        errorMessage=job["errorMessage"],
        result=job["result"],
        meta=job["meta"],
    )


@app.delete("/analysis-jobs/{analysis_run_id}")
def cancel_analysis_job(analysis_run_id: str, request: Request):
    """DELETE /analysis-jobs/{id} — cancels a job while it is still
    'queued', so a worker never picks it up (see
    services.analysis_history_repository.cancel_queued_analysis_run()
    for the atomic DB-level mechanics this relies on).

    Auth is JWT-only (same `_resolve_job_auth()` as every other
    /analysis-jobs* endpoint, no HISTORY_READ_TOKEN fallback), but the
    authorization check is deliberately *stricter* than every other
    endpoint in this group: `can_user_cancel_analysis_run()` requires
    the caller to be the job's *creator* (`created_by_user_id`), not
    merely a member of its project — cancelling is scoped to "undo
    your own not-yet-started request", not something any project
    member may do to anyone else's job. A caller who isn't the
    creator gets 403, indistinguishable from a nonexistent id (same
    existence-leak avoidance as GET /analysis-jobs/{id} above).

    This can never report success for a job that has already started
    running: once claimed, nothing in this process can safely
    interrupt it (see services/analysis_job_worker.py's
    asyncio.to_thread() docstring), so a 'running' (or already
    terminal) job is reported as 409 — this endpoint never pretends to
    have stopped work that is already in flight or finished.
    """
    auth_result = _resolve_job_auth(request)
    if isinstance(auth_result, JSONResponse):
        return auth_result
    authenticated_user = auth_result

    try:
        with open_history_db_connection() as conn:
            allowed = can_user_cancel_analysis_run(
                conn, authenticated_user.user_id, analysis_run_id
            )
    except (AnalysisHistoryReadError, ProjectAccessError):
        logger.exception("Failed to check analysis run access for analysis job cancel")
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if not allowed:
        return error_response(ANALYSIS_JOBS_ACCESS_DENIED_MESSAGE, status_code=403)

    try:
        result = cancel_queued_analysis_run(analysis_run_id)
    except AnalysisHistoryReadError:
        return error_response(ANALYSIS_JOBS_FAILED_MESSAGE, status_code=503)

    if result.outcome == "not_found":
        return error_response(ANALYSIS_JOBS_NOT_FOUND_MESSAGE, status_code=404)

    if result.outcome == "not_cancellable":
        return JSONResponse(
            status_code=409,
            content={
                "error": ANALYSIS_JOBS_NOT_CANCELLABLE_MESSAGE,
                "status": result.status,
            },
        )

    # "cancelled" or "already_cancelled" — both are a successful,
    # idempotent outcome from the caller's point of view (mirrors
    # DELETE /analysis-runs/{id}'s existing "repeat delete succeeds"
    # convention above).
    return {"cancelled": True}
