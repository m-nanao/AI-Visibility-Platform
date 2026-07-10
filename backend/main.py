"""FastAPI app for the LLMO / AI Visibility Platform analysis engine.

This mirrors the shape of the TypeScript `AnalysisResult` type
(`app/lib/types.ts`), so that Next.js's `/api/analyze` route can call
this service directly without any response transformation.

Common Crawl / DataForSEO / database integrations are intentionally
not wired in yet — see docs/05_tasks.md (Phase 4) for what's next.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from models import MAX_BRAND_NAME_LENGTH, AnalysisResult, AnalyzeRequest
from services.mock_analysis import build_dummy_analysis

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

    return build_dummy_analysis(brand_name)
