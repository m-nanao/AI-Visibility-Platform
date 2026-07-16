"""FastAPI app for the LLMO / AI Visibility Platform analysis engine.

This mirrors the shape of the TypeScript `AnalysisResult` type
(`app/lib/types.ts`), so that Next.js's `/api/analyze` route can call
this service directly without any response transformation.

The `cooccurrenceRanking`, `contextAnalysis`, and `summary` fields are
computed for real (see services/cooccurrence.py,
services/context_analysis.py, and services/brand_summary.py) from one
of, in priority order:
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
counts, cooccurrence keywords, context categories) — again no AI/LLM
calls, just simple counting/bucketing rules.

`aiOverviewComparison` and `improvements` are still fixed placeholder
data — `meta.sections` reports this per-section so callers don't have
to guess. See docs/05_tasks.md (Phase 4) for what's next.
"""

import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models import (
    MAX_BRAND_NAME_LENGTH,
    MAX_DOCUMENT_LENGTH,
    MAX_DOCUMENTS_COUNT,
    MAX_TOTAL_DOCUMENTS_LENGTH,
    MAX_URLS,
    AnalysisMeta,
    AnalysisResult,
    AnalysisSectionStatuses,
    AnalyzeRequest,
    Document,
    DocumentsSource,
    SectionStatus,
    UrlFetchResult,
)
from services.brand_summary import build_brand_summary
from services.context_analysis import analyze_contexts
from services.cooccurrence import (
    compute_cooccurrence_ranking_from_documents,
    get_tokenizer_mode,
)
from services.document_chunker import chunk_documents
from services.document_normalizer import normalize_text
from services.mock_analysis import build_dummy_analysis
from services.sample_documents import build_sample_documents_as_documents
from services.web_fetcher import fetch_url_texts, to_documents as fetch_results_to_documents

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

    result.meta = AnalysisMeta(
        sections=AnalysisSectionStatuses(
            summary=cooccurrence_status,
            cooccurrenceRanking=cooccurrence_status,
            contextAnalysis=cooccurrence_status,
            aiOverviewComparison="mock",
            improvements="mock",
        ),
        documentsSource=documents_source,
        generatedAt=datetime.now(timezone.utc).isoformat(),
        urlFetchResults=url_fetch_results,
        documentCount=document_count,
        sourceTypes=source_types,
        chunkCount=len(chunks),
    )
    return result
