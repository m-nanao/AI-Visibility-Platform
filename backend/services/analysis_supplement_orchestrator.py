"""Task 6-D-5C-4B (feature/shared-analysis-supplement-orchestrator):
shared orchestration for the four existing, independently-flagged
"supplement" providers that may add extra cards to an
AnalysisResult.aiOverviewComparison after the core no-search ChatGPT/
Claude/Gemini observations have already run:

1. ChatGPT Web-search supplement (services/chatgpt_websearch_provider.py)
2. Claude Web-search supplement (services/claude_websearch_provider.py)
3. Gemini Google-Search-grounding supplement
   (services/gemini_websearch_provider.py) — default OFF for Google
   ToS/policy reasons; this module does not change that default and
   must never be used to loosen it.
4. Gemini external-document supplement
   (services/gemini_external_document_provider.py)

This module is a **pure extraction** of the block that previously lived
inline in backend/main.py's `_analyze_authenticated_idempotent()` (Task
6-D-3 / 6-D-4A-2 / 6-D-4B-2 / 6-D-4C-2). It changes no behavior: the
call order, the per-provider defensive try/except isolation, the exact
arguments passed to each provider, and the exact fields mutated on
`result` are all unchanged from the original inline code. The intent is
only to make this block callable from more than one place (today: only
backend/main.py's synchronous authenticated path; a future task may
call it from the async job worker as well — see
docs/claude-task-handoff.md's Task 6-D-5C-4A design notes) without
duplicating the logic.

**Timing invariant (unchanged from the original inline code; must be
preserved by every caller):** this function must only ever be called
while `analysis_run_id` is still genuinely `'running'` in
`analysis_runs` — i.e. strictly after the core observation/Document
Pipeline step (`run_analysis_pipeline()`) has returned, and strictly
before `complete_analysis_job()` marks the run
`completed`/`partial`/`failed`. Each provider's own
`reserve_websearch_quota_for_analysis_run()` call re-validates this via
a DB read and raises if it does not hold — see
services/websearch_quota_reservation.py. This module does not add, flag
over, or bypass that guard.

**Not touched by this module at all:** Claude fact extraction
(services/fact_extraction_provider.py) — it already has its own
MVP-scoped call site in both backend/main.py and
services/analysis_job_worker.py (Task 6-D-5C-2) and is out of scope for
this task.

**Quota/safety invariants preserved, not reimplemented here:** each
provider function below is solely responsible for its own feature-flag
gate, quota reservation (skip-the-API-call-if-reservation-fails), and
credential checks. This module never reserves quota itself and never
adds a fallback that calls a provider's API when its own reservation
failed.
"""

from __future__ import annotations

import logging

from models import AnalysisResult, Document
from services.chatgpt_websearch_provider import attempt_chatgpt_websearch_supplement
from services.claude_websearch_provider import attempt_claude_websearch_supplement
from services.gemini_external_document_provider import (
    attempt_gemini_external_document_supplement,
)
from services.gemini_websearch_provider import attempt_gemini_websearch_supplement

logger = logging.getLogger(__name__)


def run_sync_supplement_providers(
    *,
    brand_name: str,
    result: AnalysisResult,
    web_fetch_documents: list[Document],
    analysis_run_id: str,
    project_id: str,
    user_id: str,
) -> None:
    """Attempts all four supplement providers, in the same fixed order
    as the original inline code, mutating `result` in place exactly as
    the original code did:

    - appends an `AIOverviewComparisonItem` to
      `result.aiOverviewComparison` for each provider that returns one
      (never for one that returns `None`)
    - always sets the corresponding `result.meta.*WebsearchProvider` /
      `result.meta.geminiExternalDocumentProvider` field, regardless of
      outcome

    Each provider attempt is wrapped in its own `try/except Exception`
    (unchanged from the original inline code): an unexpected failure in
    one provider never discards the already-successful no-search result
    or affects any other provider's attempt, in either direction.

    Callers must only invoke this while `analysis_run_id` is still
    `'running'` (see module docstring above).
    """

    # Task 6-D-3 (feature/chatgpt-websearch-supplement).
    try:
        chatgpt_recognition_level = (
            result.meta.chatgptProvider.recognitionLevel if result.meta.chatgptProvider else None
        )
        websearch_item, websearch_provider_info = attempt_chatgpt_websearch_supplement(
            brand_name=brand_name,
            recognition_level=chatgpt_recognition_level,
            analysis_run_id=analysis_run_id,
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

    # Task 6-D-4A-2 (feature/claude-websearch-supplement).
    try:
        claude_recognition_level = (
            result.meta.claudeProvider.recognitionLevel if result.meta.claudeProvider else None
        )
        claude_websearch_item, claude_websearch_provider_info = attempt_claude_websearch_supplement(
            brand_name=brand_name,
            recognition_level=claude_recognition_level,
            analysis_run_id=analysis_run_id,
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

    # Task 6-D-4B-2 (feature/gemini-websearch-supplement) — Google
    # Search grounding, default OFF for Google ToS/policy reasons. This
    # orchestrator does not change that default.
    try:
        gemini_recognition_level = (
            result.meta.geminiProvider.recognitionLevel if result.meta.geminiProvider else None
        )
        gemini_websearch_item, gemini_websearch_provider_info = attempt_gemini_websearch_supplement(
            brand_name=brand_name,
            recognition_level=gemini_recognition_level,
            analysis_run_id=analysis_run_id,
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

    # Task 6-D-4C-2 (feature/gemini-external-document-supplement).
    # Reuses `web_fetch_documents` (the Document[] already fetched by
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
            documents=web_fetch_documents,
            analysis_run_id=analysis_run_id,
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
