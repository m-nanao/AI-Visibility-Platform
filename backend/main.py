"""FastAPI app for the LLMO / AI Visibility Platform analysis engine.

This mirrors the shape of the TypeScript `AnalysisResult` type
(`app/lib/types.ts`), so that Next.js's `/api/analyze` route can call
this service directly without any response transformation.

The `cooccurrenceRanking` field is now computed for real from
`documents` (see services/cooccurrence.py). `summary`, `contextAnalysis`,
`aiOverviewComparison`, and `improvements` are still fixed placeholder
data — see docs/05_tasks.md (Phase 4) for what's next.
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models import MAX_BRAND_NAME_LENGTH, AnalysisMeta, AnalysisResult, AnalyzeRequest
from services.cooccurrence import compute_cooccurrence_ranking
from services.mock_analysis import build_dummy_analysis
from services.sample_documents import build_sample_documents

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


@app.post("/analyze", response_model=AnalysisResult)
def analyze(payload: AnalyzeRequest):
    brand_name = (payload.brandName or "").strip()

    if not brand_name:
        return error_response("brandName is required")

    if len(brand_name) > MAX_BRAND_NAME_LENGTH:
        return error_response(
            f"brandName must be {MAX_BRAND_NAME_LENGTH} characters or fewer"
        )

    documents = payload.documents
    if documents is None:
        documents = build_sample_documents(brand_name)
        logger.info(
            "documents not provided for brandName=%r; using %d development sample document(s)",
            brand_name,
            len(documents),
        )

    result = build_dummy_analysis(brand_name)
    result.cooccurrenceRanking = compute_cooccurrence_ranking(brand_name, documents)
    result.meta = AnalysisMeta(
        source="real_analysis",
        isMock=False,
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )
    return result
