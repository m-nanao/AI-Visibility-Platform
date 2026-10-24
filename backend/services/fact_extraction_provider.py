"""Task 6-D-5C-2 (feature/claude-fact-extraction-mvp): decides
*whether* to attempt Claude-based fact extraction for one analysis
run, and orchestrates the attempt — mirrors
services/gemini_external_document_provider.py's split of
responsibilities (gating logic here, the actual Claude HTTP call in
services/fact_extraction_client.py, the span-verification/not_mentioned
split in services/fact_extraction.py, all reused unmodified).

**MVP scope, per this task's own instruction**: at most one
`AIOverviewComparisonItem` card is ever considered per analysis run —
the no-search ChatGPT card specifically (`observationMethod` `None` or
`"single_call_no_search"`, platform ==
services.chatgpt_provider.CHATGPT_PLATFORM_LABEL). No other card (the
ChatGPT Web-search-supplement card, Claude, Gemini, AI Overview) is
ever eligible yet — see `_select_mvp_card()` below, which reuses
services/fact_extraction.py's own allowlist (`classify_eligible_card()`)
and then narrows it further to exactly this one combination. There is
no automatic fallback to another card if the ChatGPT no-search card is
absent or ineligible — the attempt is simply skipped
(`status="no_eligible_card"`).

**Must only ever be called while the given `analysis_run_id` is still
'running'** — same timing constraint as every other quota-gated
supplement in this codebase (strictly after run_analysis_pipeline()
has returned, strictly before complete_analysis_job() marks the run
completed/partial/failed). See backend/main.py's authenticated sync
path and services/analysis_job_worker.py's async path for the two call
sites — both are covered (Task 6-D-5C-2's own "同期・非同期実行経路の
両方を検証する"), unlike every earlier websearch/external-document
supplement in this codebase (which are sync-path only; extending those
is explicitly out of this task's scope).

**Sync-path timing analysis (Task 6-D-5C-2A final review item 1)** —
why this still runs on the authenticated sync `/analyze` path, not
only the async job worker:

- The sync path's own DB-level "running" lease
  (`backend/main.py`'s `SYNC_ANALYSIS_LEASE_SECONDS`, 180s) has ample
  headroom for this attempt's own 20s ceiling
  (`services/fact_extraction_settings.py`'s `REQUEST_TIMEOUT_SECONDS`)
  — the lease is never the binding constraint.
- The binding constraint is `app/api/analyze/route.ts`'s own
  `PYTHON_API_TIMEOUT_MS` (55s), a Next.js-side AbortController around
  the whole `/analyze` request — shared with every no-search
  observation and any already-enabled Web-search/external-document
  supplement ahead of this one in the same request. This is a
  **pre-existing, already-accepted risk** this feature adds to, not a
  new category of problem: the four existing quota-gated supplements
  (ChatGPT/Claude/Gemini Web-search, Gemini external-document) already
  stack sequentially in that same window with their own 30-45s
  ceilings each, and that route's own comment explicitly documents
  that 55s is sized for "a realistic full-ON request", not every
  provider simultaneously hitting its own worst case.
- If that 55s abort does fire, the frontend sees a stale dummy-
  fallback response **while FastAPI keeps running the request to
  completion in the background and still saves the real result
  (including `factExtraction`) to history** — see that route file's
  own comment for this already-documented, already-accepted
  degradation mode. No data is lost or corrupted; the on-screen result
  is simply stale until the user reloads/revisits history.
- Given this, skipping the sync path entirely was considered and
  rejected: this feature is off by default
  (`FACT_EXTRACTION_ENABLED=false`) and additionally gated behind
  quota enforcement + a non-zero quota limit, both already requiring
  deliberate operator opt-in — the same opt-in model every other
  quota-gated supplement in this codebase already uses. An operator
  who wants to avoid this shared-budget risk entirely already has that
  option today, independent of this feature: enabling
  `NEXT_PUBLIC_ENABLE_ASYNC_ANALYSIS` routes ordinary Web UI analysis
  through `POST /analysis-jobs` instead, where this same function runs
  under the worker's 180s+ (heartbeat-extended) lease with no
  caller-facing HTTP timeout at all. This is the recommended
  configuration for any environment that turns this feature on for
  real; see this task's completion report item 12.
- `REQUEST_TIMEOUT_SECONDS` was tightened from an initial 30s to 20s
  specifically to shrink this feature's own worst-case contribution to
  the shared sync budget (matching the no-search observation clients'
  own ceiling, well under the 45s the existing Web-search supplements
  already accept).

**Reuses services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() unmodified**, with
metric="fact_extraction" — see
migrations/012_add_fact_extraction_metric.sql for the widened CHECK
constraint this required. A successful reservation is required before
the one Claude API call this function ever makes; a rejected/failed
reservation never calls Claude at all, and zero API calls happen for
any gate failure before that point either (Task 6-D-5C-2 item 7: "未
対象・入力不足のケースではquotaを消費しない").

**A Claude API failure never fails the overall analysis run** — this
function never raises for an ordinary attempt failure (network error,
non-2xx, unparseable JSON); it always returns a `FactExtractionResult`
with a status describing what happened, and the caller (main.py /
analysis_job_worker.py) simply sets `result.factExtraction` to it. A
genuinely unexpected exception is still possible (a bug) — both call
sites wrap this function in their own defensive try/except, mirroring
every other supplement's call site.

Every rejection/failure reason is reported as a distinct
`FactExtractionStatus` value (see that Literal's own docstring in
models.py) — this module never silently returns "nothing happened"
without saying why.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from models import (
    AIOverviewComparisonItem,
    FactExtractionResult,
    ObservationMethod,
)
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.claude_settings import get_claude_credentials
from services.fact_extraction import resolve_original_text, verify_and_build_claims
from services.fact_extraction_client import fetch_fact_extraction
from services.fact_extraction_settings import (
    FACT_EXTRACTION_ALLOWED_MODELS,
    get_fact_extraction_max_output_tokens,
    get_fact_extraction_model,
    is_fact_extraction_enabled,
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

FACT_EXTRACTION_METRIC = "fact_extraction"

# Observation methods treated as "the plain no-search ChatGPT card" —
# `None` covers saved history/cards that predate observationMethod
# existing at all (see models.py's ObservationMethod docstring).
_CHATGPT_NO_SEARCH_METHODS: frozenset[ObservationMethod | None] = frozenset(
    {None, "single_call_no_search"}
)


def _select_mvp_card(items: list[AIOverviewComparisonItem]) -> AIOverviewComparisonItem | None:
    """Finds the one card this MVP ever considers: the no-search
    ChatGPT card. Returns None if absent — never falls back to any
    other card."""
    for item in items:
        if item.platform == CHATGPT_PLATFORM_LABEL and item.observationMethod in _CHATGPT_NO_SEARCH_METHODS:
            return item
    return None


def _deterministic_claim_id(
    analysis_run_id: str,
    source_platform: str,
    observation_method: str | None,
    claim_category: str,
    start: int | None,
    end: int | None,
) -> str:
    """A stable identifier derived only from fields that uniquely
    locate one claim within one analysis run — same inputs always
    produce the same id. Chosen over a random uuid4 specifically so
    that if this same card were ever re-extracted for the same run
    (not something any code path does today — see module docstring,
    'redisplaying a run never re-calls the API'), the resulting claim
    would carry the same id rather than appearing as a brand-new one.
    Uses uuid5 (deterministic, namespace-based) rather than a raw hash
    string so the shape still looks like every other id in this
    codebase.
    """
    key = f"{analysis_run_id}:{source_platform}:{observation_method}:{claim_category}:{start}:{end}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def attempt_fact_extraction(
    *,
    brand_name: str,
    ai_overview_comparison: list[AIOverviewComparisonItem],
    analysis_run_id: str,
    project_id: str,
    user_id: str,
    async_worker_id: str | None = None,
) -> FactExtractionResult:
    """Decides whether to attempt Claude-based fact extraction for
    this analysis run, and does so if every gate holds. Always returns
    a `FactExtractionResult` — never None, never raises for an
    ordinary gate failure or attempt failure.

    Gate order (cheapest/least-side-effecting first; no DB call at all
    until the reservation step, no API call until credentials/model
    are both validated):
    1. FACT_EXTRACTION_ENABLED is true.
    2. This request's quota enforcement is enabled.
    3. A no-search ChatGPT card exists in `ai_overview_comparison`
       (`_select_mvp_card()`).
    4. `brand_name` is non-blank.
    5. The card's original text (fullSummary, falling back to
       summary) is non-blank.
    6. That text does not exceed MAX_FACT_ORIGINAL_TEXT_CHARS — a
       too-long card is skipped entirely, never silently truncated and
       sent (Task 6-D-5C-2's own "文字数上限超過でskip").
    7. The configured model is on FACT_EXTRACTION_ALLOWED_MODELS.
    8. CLAUDE_API_KEY is configured.

    Only once all eight hold does this call
    reserve_websearch_quota_for_analysis_run() with
    metric="fact_extraction". Only a *successful* reservation leads to
    an actual Claude API call (fetch_fact_extraction(), exactly once,
    no retry) — mirrors
    services/gemini_external_document_provider.py's identical
    structure.

    `async_worker_id` (Task 6-D-5C-4G): omitted by every synchronous
    caller (default `None`, unaffected). Passed through as-is to
    reserve_websearch_quota_for_analysis_run() — see that function's
    own docstring for what this additionally validates and why.
    """
    model = get_fact_extraction_model()

    if not is_fact_extraction_enabled():
        return FactExtractionResult(status="disabled", note="FACT_EXTRACTION_ENABLED is not set to true.")

    quota_settings = load_analyze_quota_settings()
    if not quota_settings.enforcement_enabled:
        return FactExtractionResult(
            status="quota_enforcement_disabled",
            note=(
                "ANALYZE_QUOTA_ENFORCEMENT_ENABLED is not true for this request; "
                "fact extraction never runs without quota enforcement."
            ),
        )

    card = _select_mvp_card(ai_overview_comparison)
    if card is None:
        return FactExtractionResult(
            status="no_eligible_card",
            note="no no-search ChatGPT card was found in this request's aiOverviewComparison.",
        )

    # Every branch from here on found exactly one eligible card — fold
    # the fields describing it into one dict reused by every return
    # below, so none of them can drift out of sync with each other.
    common_fields = dict(
        sourcePlatform="chatgpt",
        observationMethod=card.observationMethod,
        sourceModel=card.model,
        eligibleCardCount=1,
    )

    if not brand_name or not brand_name.strip():
        return FactExtractionResult(
            status="insufficient_input", note="brandName is blank.", **common_fields
        )

    resolution = resolve_original_text(card)
    common_fields["sourceFallbackToSummary"] = resolution.isFallbackSummary

    if not resolution.text.strip():
        return FactExtractionResult(
            status="insufficient_input",
            note="the eligible card's original text (fullSummary/summary) is blank.",
            **common_fields,
        )

    if resolution.isTruncated:
        return FactExtractionResult(
            status="input_too_long",
            note="the eligible card's original text exceeds the per-attempt character limit.",
            **common_fields,
        )

    if model not in FACT_EXTRACTION_ALLOWED_MODELS:
        logger.warning(
            "Fact extraction rejected model %r (not on the allowlist %s)",
            model,
            sorted(FACT_EXTRACTION_ALLOWED_MODELS),
        )
        return FactExtractionResult(
            status="model_not_allowed",
            note=f"configured model {model!r} is not on the allowlist.",
            **common_fields,
        )

    credentials = get_claude_credentials()
    if credentials is None:
        return FactExtractionResult(
            status="no_credentials", note="Claude API key is not configured.", **common_fields
        )

    try:
        reserve_websearch_quota_for_analysis_run(
            analysis_run_id=analysis_run_id,
            project_id=project_id,
            user_id=user_id,
            metric=FACT_EXTRACTION_METRIC,
            async_worker_id=async_worker_id,
        )
    except AnalysisQuotaExceededError as exc:
        return FactExtractionResult(
            status="quota_rejected",
            note=(
                f"fact extraction quota already reached its {exc.period_type} limit "
                f"({exc.limit}) for this project."
            ),
            **common_fields,
        )
    except WebsearchQuotaAlreadyReservedError:
        return FactExtractionResult(
            status="already_reserved",
            note="this analysis run has already reserved fact-extraction quota once.",
            **common_fields,
        )
    except (
        WebsearchQuotaRunNotFoundError,
        WebsearchQuotaRunNotRunningError,
        WebsearchQuotaAccessDeniedError,
        WebsearchQuotaLeaseInvalidError,
    ) as exc:
        logger.warning("Fact extraction quota reservation rejected the run/project/user: %s", exc)
        return FactExtractionResult(
            status="run_invalid",
            note="this analysis run/project/user combination is not valid for a quota reservation.",
            **common_fields,
        )
    except WebsearchQuotaInvalidMetricError:
        logger.exception("Fact extraction quota reservation rejected a hardcoded metric constant")
        return FactExtractionResult(
            status="reservation_error", note="internal error while reserving quota.", **common_fields
        )
    except WebsearchQuotaReservationError as exc:
        logger.warning("Fact extraction quota reservation failed: %s", exc)
        return FactExtractionResult(
            status="reservation_error",
            note="failed to reserve fact-extraction quota due to a database error.",
            **common_fields,
        )

    # From this point on exactly one Claude API request is made (see
    # services/fact_extraction_client.py's own "no retry" guarantee) —
    # the reservation above has already happened, so apiRequestCount
    # below is always 1 regardless of what this call returns.
    client_result = fetch_fact_extraction(
        credentials,
        brand_name,
        resolution.text,
        model=model,
        max_output_tokens=get_fact_extraction_max_output_tokens(),
    )

    generated_at = datetime.now(timezone.utc).isoformat()

    if not client_result.success:
        return FactExtractionResult(
            status="parse_error" if client_result.reason not in {"network_error", "http_error"} else "api_error",
            note=f"fact extraction attempt failed: {client_result.reason}",
            extractionModel=model,
            apiRequestCount=1,
            generatedAt=generated_at,
            **common_fields,
        )

    batch = verify_and_build_claims(
        client_result.candidates,
        original_text=resolution.text,
        source_platform="chatgpt",
        observation_method=card.observationMethod,
        source_model=card.model,
        extraction_model=model,
        brand_name=brand_name,
    )

    claims = []
    for claim in batch.claims:
        claim_id = _deterministic_claim_id(
            analysis_run_id,
            claim.sourcePlatform,
            claim.observationMethod,
            claim.claimCategory,
            claim.sourceStartIndex,
            claim.sourceEndIndex,
        )
        claims.append(claim.model_copy(update={"claimId": claim_id}))

    # Task 6-D-5C-2 item 6: "主張が存在するカテゴリと未言及カテゴリを重複
    # させない" — Claude's own output is asked (SYSTEM_PROMPT) never to
    # do this, but this is enforced defensively anyway: a real claim
    # for a category always wins over a not_mentioned entry for that
    # same category, never the reverse (a genuinely found fact is
    # strictly more informative than "not mentioned"). The dropped
    # not_mentioned entry is counted as rejected, never silently
    # discarded without a trace.
    claimed_categories = {claim.claimCategory for claim in claims}
    not_mentioned_categories = [
        category_state
        for category_state in batch.notMentionedCategories
        if category_state.claimCategory not in claimed_categories
    ]
    overlap_dropped_count = len(batch.notMentionedCategories) - len(not_mentioned_categories)

    rejected_count = (
        batch.rejectedCount + client_result.malformed_candidate_count + overlap_dropped_count
    )
    # Task 6-D-5C-2A final review item 5: "notMentionedCategoriesが抽出
    # 成功を過大に示さない" — `status="real"` requires at least one
    # genuine, source-grounded `claims` entry. A response where
    # Claude's output survived verification but produced ONLY
    # notMentionedCategories (no actual fact found at all) is reported
    # as "partial", not "real" — notMentionedCategories alone is not
    # evidence of a substantively successful extraction, even though
    # it did reflect a real, non-empty Claude response.
    status = "real" if claims else "partial"

    if status == "real":
        note = None
    elif not_mentioned_categories:
        note = (
            "the extraction attempt completed and Claude's response was used, but it "
            "reported only not_mentioned categories — no source-grounded claim was found."
        )
    else:
        note = "the extraction attempt completed, but no candidate survived verification."

    return FactExtractionResult(
        status=status,
        note=note,
        claims=claims,
        notMentionedCategories=not_mentioned_categories,
        rejectedCount=rejected_count,
        claimsTruncated=batch.truncated,
        extractionModel=model,
        apiRequestCount=1,
        generatedAt=generated_at,
        **common_fields,
    )
