"""FastAPI app for the LLMO / AI Visibility Platform analysis engine.

This mirrors the shape of the TypeScript `AnalysisResult` type
(`app/lib/types.ts`), so that Next.js's `/api/analyze` route can call
this service directly without any response transformation.

The `cooccurrenceRanking` field is computed for real (see
services/cooccurrence.py) from one of, in priority order:
1. `documents` supplied in the request
2. text fetched from `urls` supplied in the request (services/web_fetcher.py)
3. development sample documents (services/sample_documents.py), if
   neither of the above is given

`summary`, `contextAnalysis`, `aiOverviewComparison`, and
`improvements` are still fixed placeholder data — `meta.sections`
reports this per-section so callers don't have to guess. See
docs/05_tasks.md (Phase 4) for what's next.
"""

import logging
from datetime import datetime, timezone

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
    DocumentsSource,
    UrlFetchResult,
)
from services.cooccurrence import compute_cooccurrence_ranking
from services.mock_analysis import build_dummy_analysis
from services.sample_documents import build_sample_documents
from services.web_fetcher import fetch_url_texts

# Without this, INFO-level logs (e.g. the sample-document notice below)
# are silently dropped: uvicorn's default logging config only sets up
# its own "uvicorn.*" loggers, not the root logger, and Python's
# logging module otherwise only surfaces WARNING+ by default.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


@app.post("/analyze", response_model=AnalysisResult)
def analyze(payload: AnalyzeRequest):
    brand_name = (payload.brandName or "").strip()

    if not brand_name:
        return error_response("brandName is required")

    if len(brand_name) > MAX_BRAND_NAME_LENGTH:
        return error_response(
            f"brandName must be {MAX_BRAND_NAME_LENGTH} characters or fewer"
        )

    url_fetch_results: list[UrlFetchResult] | None = None
    documents_source: DocumentsSource

    # Priority: documents > urls > development sample.
    if payload.documents is not None:
        documents = payload.documents
        validation_error = _validate_documents(documents)
        if validation_error:
            return error_response(validation_error)
        documents_source = "user_provided"

    elif payload.urls is not None:
        if len(payload.urls) > MAX_URLS:
            return error_response(f"urls must contain {MAX_URLS} or fewer entries")

        fetch_results = fetch_url_texts(payload.urls)
        url_fetch_results = [
            UrlFetchResult(url=r.url, success=r.success, error=r.error)
            for r in fetch_results
        ]
        documents = [r.text for r in fetch_results if r.success]
        documents_source = "web_fetch"

        failed = [r for r in fetch_results if not r.success]
        if failed:
            logger.info(
                "%d of %d url(s) failed to fetch for brandName=%r: %s",
                len(failed),
                len(fetch_results),
                brand_name,
                "; ".join(f"{r.url} ({r.error})" for r in failed),
            )

    else:
        documents = build_sample_documents(brand_name)
        documents_source = "development_sample"
        logger.info(
            "documents/urls not provided for brandName=%r; using %d development sample document(s)",
            brand_name,
            len(documents),
        )

    result = build_dummy_analysis(brand_name)
    result.cooccurrenceRanking = compute_cooccurrence_ranking(brand_name, documents)
    result.meta = AnalysisMeta(
        sections=AnalysisSectionStatuses(
            summary="mock",
            cooccurrenceRanking="real",
            contextAnalysis="mock",
            aiOverviewComparison="mock",
            improvements="mock",
        ),
        documentsSource=documents_source,
        generatedAt=datetime.now(timezone.utc).isoformat(),
        urlFetchResults=url_fetch_results,
    )
    return result
