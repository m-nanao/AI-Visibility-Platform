"""Task 6-D-4A-2 (feature/claude-websearch-supplement): decides
*whether* to attempt Claude's conditional Web-search supplement for
one /analyze request, and orchestrates the attempt — mirrors
services/chatgpt_websearch_provider.py's split of responsibilities
(gating logic here, the actual Anthropic HTTP call in
services/claude_websearch_client.py) and, per this task's own
"命名は既存ChatGPT実装との整合性を優先する" instruction, the same gate
order, status values, and quota-reservation mechanics.

**Must only ever be called while the given `analysis_run_id` is still
'running'** — i.e. from backend/main.py, at the exact same point
services/chatgpt_websearch_provider.py's
attempt_chatgpt_websearch_supplement() is called: strictly after
run_analysis_pipeline() has returned the no-search Claude
observation's recognitionLevel and strictly before
complete_analysis_job() marks the run completed/partial/failed. Never
called from run_analysis_pipeline() itself (see that function's own
docstring: no database access) — this is reachable only from the
synchronous, authenticated path, exactly like the ChatGPT websearch
supplement.

**Reuses services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() unmodified**, with
metric="anthropic_websearch" — that metric and migration 010's
reservation-marker table already accept it (Task 6-D-2A/6-D-2B), so no
quota/reservation code changes were needed for this task.

Every rejection reason is reported as a distinct `ClaudeWebsearchStatus`
value (see that Literal's own docstring in models.py) — this module
never silently returns "nothing happened" without saying why.
"""

import logging

from models import (
    AIOverviewComparisonItem,
    AIOverviewReference,
    ClaudeWebsearchCitationAnnotation,
    ClaudeWebsearchProviderInfo,
    RecognitionLevel,
)
from services.claude_settings import get_claude_credentials
from services.claude_websearch_client import fetch_claude_websearch_observation
from services.claude_websearch_settings import (
    get_claude_websearch_max_output_tokens,
    get_claude_websearch_model,
    is_claude_websearch_supplement_enabled,
)
from services.analyze_quota_settings import load_analyze_quota_settings
from services.websearch_quota_reservation import (
    AnalysisQuotaExceededError,
    WebsearchQuotaAccessDeniedError,
    WebsearchQuotaAlreadyReservedError,
    WebsearchQuotaInvalidMetricError,
    WebsearchQuotaLeaseInvalidError,
    WebsearchQuotaReservationError,
    WebsearchQuotaRunNotFoundError,
    WebsearchQuotaRunNotRunningError,
    reserve_websearch_quota_for_analysis_run,
)

logger = logging.getLogger(__name__)

CLAUDE_WEBSEARCH_METRIC = "anthropic_websearch"

# Deliberately distinct from services/claude_provider.py's
# CLAUDE_PLATFORM_LABEL ("Claude (Anthropic API)") — mirrors
# CHATGPT_WEBSEARCH_PLATFORM_LABEL's own reasoning: a human-readable
# cue only, never relied on by any code path to distinguish the two
# cards (AIOverviewComparisonItem.observationMethod is the actual
# stable discriminator).
CLAUDE_WEBSEARCH_PLATFORM_LABEL = "Claude (Anthropic API, Web検索補完)"

# Task 6-D-4A-2 item 4: same three eligible recognitionLevels as
# services/chatgpt_websearch_provider.py's own
# _ELIGIBLE_RECOGNITION_LEVELS — duplicated here rather than imported
# (mirrors this whole module's "deliberately a separate module" design
# so services/chatgpt_websearch_provider.py is never affected by a
# change made for Claude).
_ELIGIBLE_RECOGNITION_LEVELS: frozenset[RecognitionLevel] = frozenset(
    {"partial_knowledge", "unidentified", "name_inference_only"}
)


def _recognition_not_eligible_reason(recognition_level: RecognitionLevel) -> str:
    if recognition_level == "specific_knowledge":
        return (
            "no-search Claude observation already reported specific_knowledge; "
            "no websearch supplement needed."
        )
    if recognition_level == "indeterminate":
        return (
            "no-search Claude observation's recognitionLevel was indeterminate "
            "(self-report label could not be parsed) — not auto-searched by policy "
            "in this phase."
        )
    return f"recognitionLevel {recognition_level!r} is not eligible for the websearch supplement."


def attempt_claude_websearch_supplement(
    *,
    brand_name: str,
    recognition_level: RecognitionLevel | None,
    analysis_run_id: str,
    project_id: str,
    user_id: str,
    async_worker_id: str | None = None,
) -> tuple[AIOverviewComparisonItem | None, ClaudeWebsearchProviderInfo]:
    """Decides whether to attempt Claude's websearch supplement for
    this request, and does so if every gate holds. Returns
    (item, provider_info) — `item` is None whenever no card should be
    appended to aiOverviewComparison; the caller (main.py) simply
    skips appending in that case, exactly like every other provider in
    this codebase.

    **No "official site URL" is ever passed to the prompt** — same
    reasoning as services/chatgpt_websearch_provider.py's own
    docstring: this codebase has no dedicated, verified "brand's
    official site URL" field, so this function always calls
    fetch_claude_websearch_observation() with official_url=None.

    Gate order (cheapest/least-side-effecting first; no DB call at all
    for the first four) — mirrors
    services/chatgpt_websearch_provider.py's own order exactly:
    1. `recognition_level` is not None.
    2. CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED is true.
    3. This request's quota enforcement is enabled.
    4. `recognition_level` is one of _ELIGIBLE_RECOGNITION_LEVELS.
    5. CLAUDE_API_KEY is configured.

    Only once all five hold does this call
    reserve_websearch_quota_for_analysis_run() with
    metric="anthropic_websearch". Only a *successful* reservation leads
    to an actual Anthropic API call
    (fetch_claude_websearch_observation(), exactly once, no retry). An
    API failure after a successful reservation still reports
    status="unavailable" — the reserved quota slot is never refunded.

    `async_worker_id` (Task 6-D-5C-4G): omitted by every synchronous
    caller (default `None`, unaffected). Passed through as-is to
    reserve_websearch_quota_for_analysis_run() — see that function's
    own docstring for what this additionally validates and why.
    """
    model = get_claude_websearch_model()

    if recognition_level is None:
        return None, ClaudeWebsearchProviderInfo(
            status="not_attempted",
            reason=(
                "no-search Claude observation did not run or did not produce a "
                "recognitionLevel; nothing to evaluate for a websearch supplement."
            ),
        )

    if not is_claude_websearch_supplement_enabled():
        return None, ClaudeWebsearchProviderInfo(
            status="disabled",
            reason="CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED is not set to true.",
            recognitionLevelAtTrigger=recognition_level,
        )

    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled:
        return None, ClaudeWebsearchProviderInfo(
            status="quota_enforcement_disabled",
            reason=(
                "ANALYZE_QUOTA_ENFORCEMENT_ENABLED is not true for this request; "
                "the websearch supplement never runs without quota enforcement."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )

    if recognition_level not in _ELIGIBLE_RECOGNITION_LEVELS:
        return None, ClaudeWebsearchProviderInfo(
            status="recognition_level_not_eligible",
            reason=_recognition_not_eligible_reason(recognition_level),
            recognitionLevelAtTrigger=recognition_level,
        )

    credentials = get_claude_credentials()
    if credentials is None:
        return None, ClaudeWebsearchProviderInfo(
            status="no_credentials",
            reason="Anthropic API key is not configured.",
            recognitionLevelAtTrigger=recognition_level,
        )

    try:
        reserve_websearch_quota_for_analysis_run(
            analysis_run_id=analysis_run_id,
            project_id=project_id,
            user_id=user_id,
            metric=CLAUDE_WEBSEARCH_METRIC,
            async_worker_id=async_worker_id,
        )
    except AnalysisQuotaExceededError as exc:
        return None, ClaudeWebsearchProviderInfo(
            status="quota_rejected",
            reason=(
                f"websearch quota already reached its {exc.period_type} limit "
                f"({exc.limit}) for this project."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaAlreadyReservedError:
        return None, ClaudeWebsearchProviderInfo(
            status="already_reserved",
            reason="this analysis run has already reserved the websearch supplement once.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
        WebsearchQuotaLeaseInvalidError,
    ) as exc:
        logger.warning("Websearch quota reservation rejected the run/project/user: %s", exc)
        return None, ClaudeWebsearchProviderInfo(
            status="run_invalid",
            reason="this analysis run/project/user combination is not valid for a websearch reservation.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaInvalidMetricError:
        # Should never happen — CLAUDE_WEBSEARCH_METRIC is a fixed,
        # valid constant — but never silently treated as "reserved".
        logger.exception("Websearch quota reservation rejected a hardcoded metric constant")
        return None, ClaudeWebsearchProviderInfo(
            status="reservation_error",
            reason="internal error while reserving websearch quota.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaReservationError as exc:
        logger.warning("Websearch quota reservation failed: %s", exc)
        return None, ClaudeWebsearchProviderInfo(
            status="reservation_error",
            reason="failed to reserve websearch quota due to a database error.",
            recognitionLevelAtTrigger=recognition_level,
        )

    max_output_tokens = get_claude_websearch_max_output_tokens()
    result = fetch_claude_websearch_observation(
        credentials,
        brand_name,
        None,  # official_url — see this function's own docstring for why.
        model=model,
        max_output_tokens=max_output_tokens,
    )

    if not result.success:
        return None, ClaudeWebsearchProviderInfo(
            status="unavailable",
            reason=result.reason,
            recognitionLevelAtTrigger=recognition_level,
            searched=result.searched,
            searchErrorCode=result.search_error_code,
            model=model,
        )

    references = (
        [AIOverviewReference(url=c.url, title=c.title) for c in result.citations]
        if result.citations
        else None
    )
    citation_annotations = (
        [
            ClaudeWebsearchCitationAnnotation(url=a.url, title=a.title, citedText=a.cited_text)
            for a in result.citation_annotations
        ]
        if result.citation_annotations
        else None
    )
    item = AIOverviewComparisonItem(
        platform=CLAUDE_WEBSEARCH_PLATFORM_LABEL,
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
        claudeCitationAnnotations=citation_annotations,
        claudeCitationAnnotationsTotalCount=(
            result.citation_annotations_total_count if citation_annotations else None
        ),
        # Task 6-D-4A-2 final review item 1 — see
        # AIOverviewComparisonItem.model's own docstring in models.py.
        model=model,
    )
    return item, ClaudeWebsearchProviderInfo(
        status="real",
        reason=result.reason,
        recognitionLevelAtTrigger=recognition_level,
        searched=result.searched,
        searchErrorCode=result.search_error_code,
        model=model,
    )
