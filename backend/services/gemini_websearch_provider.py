"""Task 6-D-4B-2 (feature/gemini-websearch-supplement): decides
*whether* to attempt Gemini's conditional Google Search grounding
supplement for one /analyze request, and orchestrates the attempt —
mirrors services/claude_websearch_provider.py's split of
responsibilities (gating logic here, the actual Gemini HTTP call in
services/gemini_websearch_client.py), with one additional gate neither
the ChatGPT nor Claude websearch supplements need: a closed model
allowlist (see services/gemini_websearch_settings.py's own docstring
for why — Gemini 3+'s unbounded, uncapped per-query billing makes any
model other than `gemini-2.5-flash` unsafe for this feature today).

**Must only ever be called while the given `analysis_run_id` is still
'running'** — i.e. from backend/main.py, at the exact same point
services/claude_websearch_provider.py's
attempt_claude_websearch_supplement() is called: strictly after
run_analysis_pipeline() has returned the no-search Gemini
observation's recognitionLevel and strictly before
complete_analysis_job() marks the run completed/partial/failed.

**Reuses services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() unmodified**, with
metric="google_websearch" — that metric and migration 010's
reservation-marker table already accept it (Task 6-D-2A/6-D-2B), so no
quota/reservation code changes were needed for this task.

Every rejection reason is reported as a distinct `GeminiWebsearchStatus`
value (see that Literal's own docstring in models.py) — this module
never silently returns "nothing happened" without saying why.
"""

import logging

from models import (
    AIOverviewComparisonItem,
    AIOverviewReference,
    GeminiWebsearchGroundingChunk,
    GeminiWebsearchGroundingSupport,
    GeminiWebsearchProviderInfo,
    RecognitionLevel,
)
from services.gemini_settings import get_gemini_credentials
from services.gemini_websearch_client import fetch_gemini_websearch_observation
from services.gemini_websearch_settings import (
    GEMINI_WEBSEARCH_ALLOWED_MODELS,
    get_gemini_websearch_max_output_tokens,
    get_gemini_websearch_model,
    is_gemini_websearch_supplement_enabled,
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

GEMINI_WEBSEARCH_METRIC = "google_websearch"

# Deliberately distinct from services/gemini_provider.py's
# GEMINI_PLATFORM_LABEL ("Gemini (Google API)") — mirrors
# CLAUDE_WEBSEARCH_PLATFORM_LABEL's own reasoning: a human-readable cue
# only, never relied on by any code path to distinguish the two cards
# (AIOverviewComparisonItem.observationMethod is the actual stable
# discriminator).
GEMINI_WEBSEARCH_PLATFORM_LABEL = "Gemini (Google API, Web検索補完)"

# Task 6-D-4B-2 item 2: same three eligible recognitionLevels as
# services/chatgpt_websearch_provider.py's/claude_websearch_provider.py's
# own set — duplicated here rather than imported (mirrors this whole
# module's "deliberately a separate module" design).
_ELIGIBLE_RECOGNITION_LEVELS: frozenset[RecognitionLevel] = frozenset(
    {"partial_knowledge", "unidentified", "name_inference_only"}
)


def _recognition_not_eligible_reason(recognition_level: RecognitionLevel) -> str:
    if recognition_level == "specific_knowledge":
        return (
            "no-search Gemini observation already reported specific_knowledge; "
            "no websearch supplement needed."
        )
    if recognition_level == "indeterminate":
        return (
            "no-search Gemini observation's recognitionLevel was indeterminate "
            "(self-report label could not be parsed) — not auto-searched by policy "
            "in this phase."
        )
    return f"recognitionLevel {recognition_level!r} is not eligible for the websearch supplement."


def attempt_gemini_websearch_supplement(
    *,
    brand_name: str,
    recognition_level: RecognitionLevel | None,
    analysis_run_id: str,
    project_id: str,
    user_id: str,
) -> tuple[AIOverviewComparisonItem | None, GeminiWebsearchProviderInfo]:
    """Decides whether to attempt Gemini's websearch supplement for
    this request, and does so if every gate holds. Returns
    (item, provider_info) — `item` is None whenever no card should be
    appended to aiOverviewComparison; the caller (main.py) simply
    skips appending in that case.

    **No "official site URL" is ever passed to the prompt** — same
    reasoning as services/claude_websearch_provider.py's own
    docstring.

    Gate order (cheapest/least-side-effecting first; no DB call at all
    until the reservation step):
    1. `recognition_level` is not None.
    2. GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED is true.
    3. This request's quota enforcement is enabled.
    4. `recognition_level` is one of _ELIGIBLE_RECOGNITION_LEVELS.
    5. The configured model is on GEMINI_WEBSEARCH_ALLOWED_MODELS —
       Task 6-D-4B-2's own requirement: any other configured value is
       rejected *before* any quota reservation or API call, never a
       silent fallback to the allowed model.
    6. GEMINI_API_KEY is configured.

    Only once all six hold does this call
    reserve_websearch_quota_for_analysis_run() with
    metric="google_websearch". Only a *successful* reservation leads
    to an actual Gemini API call
    (fetch_gemini_websearch_observation(), exactly once, no retry). An
    API failure after a successful reservation still reports
    status="unavailable" — the reserved quota slot is never refunded.
    """
    model = get_gemini_websearch_model()

    if recognition_level is None:
        return None, GeminiWebsearchProviderInfo(
            status="not_attempted",
            reason=(
                "no-search Gemini observation did not run or did not produce a "
                "recognitionLevel; nothing to evaluate for a websearch supplement."
            ),
        )

    if not is_gemini_websearch_supplement_enabled():
        return None, GeminiWebsearchProviderInfo(
            status="disabled",
            reason="GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED is not set to true.",
            recognitionLevelAtTrigger=recognition_level,
        )

    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled:
        return None, GeminiWebsearchProviderInfo(
            status="quota_enforcement_disabled",
            reason=(
                "ANALYZE_QUOTA_ENFORCEMENT_ENABLED is not true for this request; "
                "the websearch supplement never runs without quota enforcement."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )

    if recognition_level not in _ELIGIBLE_RECOGNITION_LEVELS:
        return None, GeminiWebsearchProviderInfo(
            status="recognition_level_not_eligible",
            reason=_recognition_not_eligible_reason(recognition_level),
            recognitionLevelAtTrigger=recognition_level,
        )

    if model not in GEMINI_WEBSEARCH_ALLOWED_MODELS:
        logger.warning(
            "Gemini websearch supplement rejected model %r (not on the allowlist %s)",
            model,
            sorted(GEMINI_WEBSEARCH_ALLOWED_MODELS),
        )
        return None, GeminiWebsearchProviderInfo(
            status="model_not_allowed",
            reason=(
                f"configured model {model!r} is not on the allowlist "
                f"{sorted(GEMINI_WEBSEARCH_ALLOWED_MODELS)!r}; the websearch supplement "
                "never calls an unapproved model."
            ),
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )

    credentials = get_gemini_credentials()
    if credentials is None:
        return None, GeminiWebsearchProviderInfo(
            status="no_credentials",
            reason="Gemini API key is not configured.",
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )

    try:
        reserve_websearch_quota_for_analysis_run(
            analysis_run_id=analysis_run_id,
            project_id=project_id,
            user_id=user_id,
            metric=GEMINI_WEBSEARCH_METRIC,
        )
    except AnalysisQuotaExceededError as exc:
        return None, GeminiWebsearchProviderInfo(
            status="quota_rejected",
            reason=(
                f"websearch quota already reached its {exc.period_type} limit "
                f"({exc.limit}) for this project."
            ),
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )
    except WebsearchQuotaAlreadyReservedError:
        return None, GeminiWebsearchProviderInfo(
            status="already_reserved",
            reason="this analysis run has already reserved the websearch supplement once.",
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
    ) as exc:
        logger.warning("Websearch quota reservation rejected the run/project/user: %s", exc)
        return None, GeminiWebsearchProviderInfo(
            status="run_invalid",
            reason="this analysis run/project/user combination is not valid for a websearch reservation.",
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )
    except WebsearchQuotaInvalidMetricError:
        # Should never happen — GEMINI_WEBSEARCH_METRIC is a fixed,
        # valid constant — but never silently treated as "reserved".
        logger.exception("Websearch quota reservation rejected a hardcoded metric constant")
        return None, GeminiWebsearchProviderInfo(
            status="reservation_error",
            reason="internal error while reserving websearch quota.",
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )
    except WebsearchQuotaReservationError as exc:
        logger.warning("Websearch quota reservation failed: %s", exc)
        return None, GeminiWebsearchProviderInfo(
            status="reservation_error",
            reason="failed to reserve websearch quota due to a database error.",
            recognitionLevelAtTrigger=recognition_level,
            model=model,
        )

    max_output_tokens = get_gemini_websearch_max_output_tokens()
    result = fetch_gemini_websearch_observation(
        credentials,
        brand_name,
        None,  # official_url — see this function's own docstring for why.
        model=model,
        max_output_tokens=max_output_tokens,
    )

    if not result.success:
        return None, GeminiWebsearchProviderInfo(
            status="unavailable",
            reason=result.reason,
            recognitionLevelAtTrigger=recognition_level,
            searched=result.searched,
            groundingMetadataPresent=result.grounding_metadata_present,
            webSearchQueriesCount=result.web_search_queries_count,
            model=model,
        )

    references = (
        [AIOverviewReference(url=r.uri, title=r.title) for r in result.references]
        if result.references
        else None
    )
    grounding_chunks = (
        [
            GeminiWebsearchGroundingChunk(uri=c.uri, title=c.title, domain=c.domain)
            for c in result.grounding_chunks
        ]
        if result.grounding_chunks
        else None
    )
    grounding_supports = (
        [
            GeminiWebsearchGroundingSupport(
                startIndex=s.start_index,
                endIndex=s.end_index,
                text=s.text,
                groundingChunkIndices=s.grounding_chunk_indices,
                confidenceScores=s.confidence_scores,
            )
            for s in result.grounding_supports
        ]
        if result.grounding_supports
        else None
    )
    item = AIOverviewComparisonItem(
        platform=GEMINI_WEBSEARCH_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=references,
        referenceSummary=None,
        ownDomainReferenced=None,
        observationMethod="websearch_supplement",
        finishReason=result.finish_reason,
        isTruncated=result.is_truncated,
        note=result.note,
        fullSummaryTruncated=result.full_summary_truncated,
        citationsTruncated=result.citations_truncated,
        model=model,
        geminiGroundingChunks=grounding_chunks,
        geminiGroundingChunksTotalCount=(
            result.grounding_chunks_total_count if grounding_chunks else None
        ),
        geminiGroundingSupports=grounding_supports,
        geminiGroundingSupportsTotalCount=(
            result.grounding_supports_total_count if grounding_supports else None
        ),
        geminiSearchEntryPointRenderedContent=result.rendered_content,
        geminiSearchEntryPointRenderedContentTruncated=(
            result.rendered_content_truncated if result.rendered_content is not None else None
        ),
    )
    return item, GeminiWebsearchProviderInfo(
        status="real",
        reason=result.reason,
        recognitionLevelAtTrigger=recognition_level,
        searched=result.searched,
        groundingMetadataPresent=result.grounding_metadata_present,
        webSearchQueriesCount=result.web_search_queries_count,
        model=model,
    )
