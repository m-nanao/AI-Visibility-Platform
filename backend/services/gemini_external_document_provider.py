"""Task 6-D-4C-2 (feature/gemini-external-document-supplement): decides
*whether* to attempt Gemini's conditional external-document supplement
for one /analyze request, and orchestrates the attempt — mirrors
services/gemini_websearch_provider.py's split of responsibilities
(gating logic here, the actual Gemini HTTP call in
services/gemini_external_document_client.py), with two gates neither
the Google-Search-grounding supplement nor the ChatGPT/Claude websearch
supplements need:

1. A **document-availability gate** (`"no_documents"`) — this feature
   has no provider-side search to fall back on if nothing was fetched;
   if this request's `urls[]` produced zero successfully-fetched
   `web_fetch` Documents, there is nothing to hand Gemini, and quota
   must never be reserved for an attempt that cannot possibly produce
   a card (Task 6-D-4C-2 item 7: "文書0件の場合は、quotaを予約せずAPIを
   呼ばない").
2. A **document source filter** — only `Document`s with
   `sourceType == "web_fetch"` are ever considered, explicitly
   excluding `user_provided`/`development_sample`/`common_crawl`/
   `dataforseo`-sourced Documents (Task 6-D-4C-2 item 2's own list).
   This module re-derives that filter itself from whatever `documents`
   its caller passes, rather than trusting the caller to have already
   filtered — see `_web_fetch_documents()` below.

**Must only ever be called while the given `analysis_run_id` is still
'running'** — i.e. from backend/main.py, at the exact same point
services/gemini_websearch_provider.py's
attempt_gemini_websearch_supplement() is called: strictly after
run_analysis_pipeline() has returned (both the no-search Gemini
observation's recognitionLevel, and the fetched Document[] themselves
— see main.py's AnalysisPipelineOutcome.webFetchDocuments) and strictly
before complete_analysis_job() marks the run completed/partial/failed.

**Reuses services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() unmodified**, with
metric="gemini_external_document" — that metric was added to
WEBSEARCH_METRICS and to migrations/011_add_gemini_external_document_metric.sql's
widened CHECK constraint specifically for this task; no other change
to that module was needed.

Every rejection reason is reported as a distinct
`GeminiExternalDocumentStatus` value (see that Literal's own docstring
in models.py) — this module never silently returns "nothing happened"
without saying why.
"""

import logging

from models import (
    AIOverviewComparisonItem,
    Document,
    GeminiExternalDocumentProviderInfo,
    GeminiExternalDocumentSource,
    RecognitionLevel,
)
from services.gemini_settings import get_gemini_credentials
from services.gemini_external_document_client import fetch_gemini_external_document_observation
from services.gemini_external_document_settings import (
    GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS,
    get_gemini_external_document_max_output_tokens,
    get_gemini_external_document_model,
    is_gemini_external_document_supplement_enabled,
)
from services.analyze_quota_settings import load_analyze_quota_settings
from services.websearch_quota_reservation import (
    AnalysisQuotaExceededError,
    WebsearchQuotaAccessDeniedError,
    WebsearchQuotaAlreadyReservedError,
    WebsearchQuotaInvalidMetricError,
    WebsearchQuotaReservationError,
    WebsearchQuotaRunNotFoundError,
    WebsearchQuotaRunNotRunningError,
    reserve_websearch_quota_for_analysis_run,
)

logger = logging.getLogger(__name__)

GEMINI_EXTERNAL_DOCUMENT_METRIC = "gemini_external_document"

# Deliberately distinct from services/gemini_provider.py's
# GEMINI_PLATFORM_LABEL ("Gemini (Google API)") and from
# services/gemini_websearch_provider.py's
# GEMINI_WEBSEARCH_PLATFORM_LABEL ("Gemini (Google API, Web検索補完)")
# — this card used neither the no-search path nor Google's search
# grounding tool, so it gets its own, distinctly-worded label. Never
# relied on by any code path to distinguish the three cards from one
# another — AIOverviewComparisonItem.observationMethod is the actual
# stable discriminator.
GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL = "Gemini (Google API, 外部文書補完)"

# Task 6-D-4C-2 item 7: same three eligible recognitionLevels as every
# other websearch/document supplement in this codebase — duplicated
# here rather than imported (mirrors this whole module's "deliberately
# a separate module" design).
_ELIGIBLE_RECOGNITION_LEVELS: frozenset[RecognitionLevel] = frozenset(
    {"partial_knowledge", "unidentified", "name_inference_only"}
)


def _recognition_not_eligible_reason(recognition_level: RecognitionLevel) -> str:
    if recognition_level == "specific_knowledge":
        return (
            "no-search Gemini observation already reported specific_knowledge; "
            "no external-document supplement needed."
        )
    if recognition_level == "indeterminate":
        return (
            "no-search Gemini observation's recognitionLevel was indeterminate "
            "(self-report label could not be parsed) — not auto-attempted by policy "
            "in this phase."
        )
    return f"recognitionLevel {recognition_level!r} is not eligible for the external-document supplement."


def _web_fetch_documents(documents: list[Document]) -> list[Document]:
    """Task 6-D-4C-2 item 2's own filter: only `web_fetch`-sourced
    Documents are ever considered — explicitly excludes
    `user_provided`/`development_sample`/`common_crawl`/`dataforseo`.
    Every `web_fetch` Document services/web_fetcher.py's own
    `to_documents()` produces already has a non-empty `sourceUrl`/
    `text` by construction, but this still defensively re-checks both
    rather than assuming it."""
    return [
        document
        for document in documents
        if document.sourceType == "web_fetch" and document.sourceUrl and document.text
    ]


def attempt_gemini_external_document_supplement(
    *,
    brand_name: str,
    recognition_level: RecognitionLevel | None,
    documents: list[Document],
    analysis_run_id: str,
    project_id: str,
    user_id: str,
) -> tuple[AIOverviewComparisonItem | None, GeminiExternalDocumentProviderInfo]:
    """Decides whether to attempt Gemini's external-document
    supplement for this request, and does so if every gate holds.
    Returns (item, provider_info) — `item` is None whenever no card
    should be appended to aiOverviewComparison; the caller (main.py)
    simply skips appending in that case.

    `documents` is expected to be the full Document[] this request's
    pipeline produced (any sourceType) — this function does its own
    `web_fetch`-only filtering (see `_web_fetch_documents()`), so
    callers do not need to pre-filter.

    Gate order (cheapest/least-side-effecting first; no DB call at all
    until the reservation step):
    1. `recognition_level` is not None.
    2. GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED is true.
    3. This request's quota enforcement is enabled.
    4. `recognition_level` is one of _ELIGIBLE_RECOGNITION_LEVELS.
    5. At least one `web_fetch` Document is available — Task 6-D-4C-2
       item 7's own requirement: zero documents means no quota
       reservation and no API call at all.
    6. The configured model is on GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS.
    7. GEMINI_API_KEY is configured.

    Only once all seven hold does this call
    reserve_websearch_quota_for_analysis_run() with
    metric="gemini_external_document". Only a *successful* reservation
    leads to an actual Gemini API call
    (fetch_gemini_external_document_observation(), exactly once, no
    retry). An API failure after a successful reservation still
    reports status="unavailable" — the reserved quota slot is never
    refunded.
    """
    model = get_gemini_external_document_model()

    if recognition_level is None:
        return None, GeminiExternalDocumentProviderInfo(
            status="not_attempted",
            reason=(
                "no-search Gemini observation did not run or did not produce a "
                "recognitionLevel; nothing to evaluate for an external-document supplement."
            ),
        )

    if not is_gemini_external_document_supplement_enabled():
        return None, GeminiExternalDocumentProviderInfo(
            status="disabled",
            reason="GEMINI_EXTERNAL_DOCUMENT_SUPPLEMENT_ENABLED is not set to true.",
            recognitionLevelAtTrigger=recognition_level,
        )

    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled:
        return None, GeminiExternalDocumentProviderInfo(
            status="quota_enforcement_disabled",
            reason=(
                "ANALYZE_QUOTA_ENFORCEMENT_ENABLED is not true for this request; "
                "the external-document supplement never runs without quota enforcement."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )

    if recognition_level not in _ELIGIBLE_RECOGNITION_LEVELS:
        return None, GeminiExternalDocumentProviderInfo(
            status="recognition_level_not_eligible",
            reason=_recognition_not_eligible_reason(recognition_level),
            recognitionLevelAtTrigger=recognition_level,
        )

    available_documents = _web_fetch_documents(documents)
    if not available_documents:
        return None, GeminiExternalDocumentProviderInfo(
            status="no_documents",
            reason=(
                "no successfully-fetched web_fetch Document was available for this "
                "request; the external-document supplement never reserves quota or "
                "calls the API without at least one document."
            ),
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=0,
        )

    if model not in GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS:
        logger.warning(
            "Gemini external-document supplement rejected model %r (not on the allowlist %s)",
            model,
            sorted(GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS),
        )
        return None, GeminiExternalDocumentProviderInfo(
            status="model_not_allowed",
            reason=(
                f"configured model {model!r} is not on the allowlist "
                f"{sorted(GEMINI_EXTERNAL_DOCUMENT_ALLOWED_MODELS)!r}; the external-document "
                "supplement never calls an unapproved model."
            ),
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )

    credentials = get_gemini_credentials()
    if credentials is None:
        return None, GeminiExternalDocumentProviderInfo(
            status="no_credentials",
            reason="Gemini API key is not configured.",
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )

    try:
        reserve_websearch_quota_for_analysis_run(
            analysis_run_id=analysis_run_id,
            project_id=project_id,
            user_id=user_id,
            metric=GEMINI_EXTERNAL_DOCUMENT_METRIC,
        )
    except AnalysisQuotaExceededError as exc:
        return None, GeminiExternalDocumentProviderInfo(
            status="quota_rejected",
            reason=(
                f"websearch quota already reached its {exc.period_type} limit "
                f"({exc.limit}) for this project."
            ),
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )
    except WebsearchQuotaAlreadyReservedError:
        return None, GeminiExternalDocumentProviderInfo(
            status="already_reserved",
            reason="this analysis run has already reserved the external-document supplement once.",
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
    ) as exc:
        logger.warning("Websearch quota reservation rejected the run/project/user: %s", exc)
        return None, GeminiExternalDocumentProviderInfo(
            status="run_invalid",
            reason="this analysis run/project/user combination is not valid for a websearch reservation.",
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )
    except WebsearchQuotaInvalidMetricError:
        # Should never happen — GEMINI_EXTERNAL_DOCUMENT_METRIC is a
        # fixed, valid constant — but never silently treated as
        # "reserved".
        logger.exception("Websearch quota reservation rejected a hardcoded metric constant")
        return None, GeminiExternalDocumentProviderInfo(
            status="reservation_error",
            reason="internal error while reserving websearch quota.",
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )
    except WebsearchQuotaReservationError as exc:
        logger.warning("Websearch quota reservation failed: %s", exc)
        return None, GeminiExternalDocumentProviderInfo(
            status="reservation_error",
            reason="failed to reserve websearch quota due to a database error.",
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            model=model,
        )

    max_output_tokens = get_gemini_external_document_max_output_tokens()
    result = fetch_gemini_external_document_observation(
        credentials,
        brand_name,
        available_documents,
        model=model,
        max_output_tokens=max_output_tokens,
    )

    documents_used_count = len(result.selected_documents)

    if not result.success:
        return None, GeminiExternalDocumentProviderInfo(
            status="unavailable",
            reason=result.reason,
            recognitionLevelAtTrigger=recognition_level,
            documentsConsideredCount=len(available_documents),
            documentsUsedCount=documents_used_count,
            model=model,
        )

    sources = (
        [
            GeminiExternalDocumentSource(
                sourceUrl=s.source_url,
                title=s.title,
                domain=s.domain,
                originalIndex=s.original_index,
                inputOrder=s.input_order,
                inputCharCount=s.input_char_count,
                truncated=s.truncated,
            )
            for s in result.selected_documents
        ]
        if result.selected_documents
        else None
    )
    item = AIOverviewComparisonItem(
        platform=GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=None,
        referenceSummary=None,
        ownDomainReferenced=None,
        observationMethod="external_document_supplement",
        finishReason=result.finish_reason,
        isTruncated=result.is_truncated,
        note=result.note,
        fullSummaryTruncated=result.full_summary_truncated,
        model=model,
        geminiExternalDocumentSources=sources,
        geminiExternalDocumentSourcesConsideredCount=(
            len(available_documents) if sources else None
        ),
    )
    return item, GeminiExternalDocumentProviderInfo(
        status="real",
        reason=result.reason,
        recognitionLevelAtTrigger=recognition_level,
        documentsConsideredCount=len(available_documents),
        documentsUsedCount=documents_used_count,
        model=model,
    )
