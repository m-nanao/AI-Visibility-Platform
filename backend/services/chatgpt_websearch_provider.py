"""Task 6-D-3 (feature/chatgpt-websearch-supplement): decides
*whether* to attempt ChatGPT's conditional Web-search supplement for
one /analyze request, and orchestrates the attempt — mirrors
services/chatgpt_provider.py's split of responsibilities (gating logic
here, the actual OpenAI HTTP call in
services/chatgpt_websearch_client.py) for the same reason: a single,
thoroughly-tested gate in one place is safer than duplicating gate
logic.

**Must only ever be called while the given `analysis_run_id` is still
'running'** — i.e. from backend/main.py's
_analyze_authenticated_idempotent(), strictly after
run_analysis_pipeline() has returned the no-search observation's
recognitionLevel and strictly before complete_analysis_job() marks the
run completed/partial/failed. Never called from
run_analysis_pipeline() itself, which has no database access at all
(see that function's own docstring) and is shared by the async worker
— this keeps that invariant intact and means this feature is reachable
only from the synchronous, authenticated path (satisfying Task 6-D-3
item C's "未認証・権限不足・run不整合で検索しない" by construction: the
anonymous path never has an analysis_run_id/project_id/user_id to pass
here at all).

Every rejection reason is reported as a distinct
`ChatGptWebsearchStatus` value (see that Literal's own docstring in
models.py) — this module never silently returns "nothing happened"
without saying why.
"""

import logging

from models import (
    AIOverviewComparisonItem,
    AIOverviewReference,
    ChatGptWebsearchProviderInfo,
    RecognitionLevel,
)
from services.chatgpt_settings import get_chatgpt_credentials, get_chatgpt_settings
from services.chatgpt_websearch_client import fetch_chatgpt_websearch_observation
from services.chatgpt_websearch_settings import is_chatgpt_websearch_supplement_enabled
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

CHATGPT_WEBSEARCH_METRIC = "openai_websearch"

# Deliberately distinct from chatgpt_provider.py's
# CHATGPT_PLATFORM_LABEL ("ChatGPT (OpenAI API)") — a human-readable
# cue for anyone glancing at the two cards, but never relied on by any
# code path to tell them apart (see AIOverviewComparisonItem.
# observationMethod, the actual stable discriminator — Task 6-D-3 item
# G explicitly forbids branching on this string).
CHATGPT_WEBSEARCH_PLATFORM_LABEL = "ChatGPT (OpenAI API, Web検索補完)"

# Task 6-D-3 item B: only these three recognitionLevels are eligible
# for an automatic websearch supplement.
# - "specific_knowledge" is excluded: the no-search observation already
#   identified the brand specifically — no supplement needed.
# - "indeterminate" is excluded: the self-report label itself couldn't
#   be parsed — this is a parsing-failure state, not a "the model
#   doesn't know" state, and item B's own policy is to never
#   auto-search on it in this first phase (the reason string below
#   makes that distinction visible rather than looking identical to
#   "specific_knowledge, no need").
_ELIGIBLE_RECOGNITION_LEVELS: frozenset[RecognitionLevel] = frozenset(
    {"partial_knowledge", "unidentified", "name_inference_only"}
)


def _recognition_not_eligible_reason(recognition_level: RecognitionLevel) -> str:
    if recognition_level == "specific_knowledge":
        return (
            "no-search ChatGPT observation already reported specific_knowledge; "
            "no websearch supplement needed."
        )
    if recognition_level == "indeterminate":
        return (
            "no-search ChatGPT observation's recognitionLevel was indeterminate "
            "(self-report label could not be parsed) — not auto-searched by policy "
            "in this phase."
        )
    return f"recognitionLevel {recognition_level!r} is not eligible for the websearch supplement."


def attempt_chatgpt_websearch_supplement(
    *,
    brand_name: str,
    recognition_level: RecognitionLevel | None,
    analysis_run_id: str,
    project_id: str,
    user_id: str,
) -> tuple[AIOverviewComparisonItem | None, ChatGptWebsearchProviderInfo]:
    """Decides whether to attempt ChatGPT's websearch supplement for
    this request, and does so if every gate holds. Returns
    (item, provider_info) — `item` is None whenever no card should be
    appended to aiOverviewComparison (not attempted, or an attempt that
    didn't succeed); the caller (main.py) simply skips appending in
    that case, exactly like every other provider in this codebase.

    **No "official site URL" is ever passed to the prompt.** This
    codebase has no dedicated, verified "brand's official site URL"
    field (`brands.canonical_domain` exists in the schema but is never
    actually populated by any code path). `AnalyzeRequest.urls` is the
    caller's list of pages to fetch as Web-side source documents for
    an entirely different section of the analysis — it may contain the
    brand's official site, a competitor's page, a news article, or
    nothing related at all, so treating any entry in it as "the
    official site" would be an unverified guess. This function
    therefore always calls fetch_chatgpt_websearch_observation() with
    official_url=None — the prompt proceeds on brand name alone (see
    services/chatgpt_websearch_client.py's build_websearch_user_prompt(),
    which is written to read naturally either way). A dedicated,
    explicitly-confirmed official-URL field is left to a future task;
    this function's `official_url` plumbing through to the client is
    kept so that future task only needs to supply a real value here,
    not re-thread a new parameter through this whole call chain.

    Gate order (cheapest/least-side-effecting first; no DB call at all
    for the first four):
    1. `recognition_level` is not None (the no-search observation must
       have actually run and classified something).
    2. CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED is true.
    3. This request's quota enforcement is enabled — Task 6-D-3 item C:
       "quota enforcementが無効な環境で、検索専用制限を迂回して実行で
       きる仕様にはしない". The ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA dev/
       test escape hatch (which lets normal analysis quota be skipped)
       never implicitly enables this feature either.
    4. `recognition_level` is one of _ELIGIBLE_RECOGNITION_LEVELS.
    5. OPENAI_API_KEY is configured.

    Only once all five hold does this call
    reserve_websearch_quota_for_analysis_run() (Task 6-D-2B) — see that
    function's own docstring for the run/project/user validation and
    atomic daily+monthly reservation it performs. Only a *successful*
    reservation leads to an actual OpenAI API call
    (fetch_chatgpt_websearch_observation(), exactly once, no retry).
    An API failure after a successful reservation still reports
    status="unavailable" — the reserved quota slot is never refunded
    (see services/websearch_quota_reservation.py's own docstring on
    why: refunding would make a failing/retried search free to repeat
    indefinitely).
    """
    if recognition_level is None:
        return None, ChatGptWebsearchProviderInfo(
            status="not_attempted",
            reason=(
                "no-search ChatGPT observation did not run or did not produce a "
                "recognitionLevel; nothing to evaluate for a websearch supplement."
            ),
        )

    if not is_chatgpt_websearch_supplement_enabled():
        return None, ChatGptWebsearchProviderInfo(
            status="disabled",
            reason="CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED is not set to true.",
            recognitionLevelAtTrigger=recognition_level,
        )

    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled:
        return None, ChatGptWebsearchProviderInfo(
            status="quota_enforcement_disabled",
            reason=(
                "ANALYZE_QUOTA_ENFORCEMENT_ENABLED is not true for this request; "
                "the websearch supplement never runs without quota enforcement."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )

    if recognition_level not in _ELIGIBLE_RECOGNITION_LEVELS:
        return None, ChatGptWebsearchProviderInfo(
            status="recognition_level_not_eligible",
            reason=_recognition_not_eligible_reason(recognition_level),
            recognitionLevelAtTrigger=recognition_level,
        )

    credentials = get_chatgpt_credentials()
    if credentials is None:
        return None, ChatGptWebsearchProviderInfo(
            status="no_credentials",
            reason="OpenAI API key is not configured.",
            recognitionLevelAtTrigger=recognition_level,
        )

    try:
        reserve_websearch_quota_for_analysis_run(
            analysis_run_id=analysis_run_id,
            project_id=project_id,
            user_id=user_id,
            metric=CHATGPT_WEBSEARCH_METRIC,
        )
    except AnalysisQuotaExceededError as exc:
        return None, ChatGptWebsearchProviderInfo(
            status="quota_rejected",
            reason=(
                f"websearch quota already reached its {exc.period_type} limit "
                f"({exc.limit}) for this project."
            ),
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaAlreadyReservedError:
        return None, ChatGptWebsearchProviderInfo(
            status="already_reserved",
            reason="this analysis run has already reserved the websearch supplement once.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
    ) as exc:
        logger.warning("Websearch quota reservation rejected the run/project/user: %s", exc)
        return None, ChatGptWebsearchProviderInfo(
            status="run_invalid",
            reason="this analysis run/project/user combination is not valid for a websearch reservation.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaInvalidMetricError:
        # Should never happen — CHATGPT_WEBSEARCH_METRIC is a fixed,
        # valid constant — but never silently treated as "reserved".
        logger.exception("Websearch quota reservation rejected a hardcoded metric constant")
        return None, ChatGptWebsearchProviderInfo(
            status="reservation_error",
            reason="internal error while reserving websearch quota.",
            recognitionLevelAtTrigger=recognition_level,
        )
    except WebsearchQuotaReservationError as exc:
        logger.warning("Websearch quota reservation failed: %s", exc)
        return None, ChatGptWebsearchProviderInfo(
            status="reservation_error",
            reason="failed to reserve websearch quota due to a database error.",
            recognitionLevelAtTrigger=recognition_level,
        )

    settings = get_chatgpt_settings()
    result = fetch_chatgpt_websearch_observation(
        credentials,
        brand_name,
        None,  # official_url — see this function's own docstring for why.
        model=settings.model,
        max_output_tokens=settings.max_output_tokens,
    )

    if not result.success:
        return None, ChatGptWebsearchProviderInfo(
            status="unavailable",
            reason=result.reason,
            recognitionLevelAtTrigger=recognition_level,
            searched=result.searched,
        )

    references = (
        [AIOverviewReference(url=c.url, title=c.title) for c in result.citations]
        if result.citations
        else None
    )
    item = AIOverviewComparisonItem(
        platform=CHATGPT_WEBSEARCH_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=references,
        referenceSummary=None,
        ownDomainReferenced=None,
        observationMethod="websearch_supplement",
    )
    return item, ChatGptWebsearchProviderInfo(
        status="real",
        reason=result.reason,
        recognitionLevelAtTrigger=recognition_level,
        searched=result.searched,
    )
