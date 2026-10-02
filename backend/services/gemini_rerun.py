"""Gemini-only re-run of one saved analysis run's Gemini observation
card — POST /analysis-runs/{id}/rerun/gemini (main.py).

Added per a依頼者 request: once Gemini's output is suspected of having
been cut off mid-way (`AIOverviewComparisonItem.isTruncated`), getting
a fresh Gemini observation previously required re-running the whole
`/analyze` request — which also re-calls DataForSEO/ChatGPT/Claude and
re-fetches Common Crawl/web pages, none of which had anything to do
with the problem being investigated. This module calls **only**
Gemini (via the exact same services/gemini_provider.py entry point
`/analyze` itself uses, so prompt/settings/request-limit/max-tokens
are identical) and returns an updated result_json/meta_json for the
caller (main.py) to persist — it never touches the database itself,
and never calls any other provider.

Deliberately a pure function (no DB access, no FastAPI Request/
Response) so the "only Gemini is called, nothing else" and
"card replace vs. add" and "failure doesn't corrupt existing data"
behaviors can be unit-tested directly without a database — see
backend/tests/test_gemini_rerun.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from models import AIOverviewComparisonItem, CooccurrenceKeyword, GeminiProviderInfo, WebAiGapResult
from services.gemini_provider import GEMINI_PLATFORM_LABEL, build_gemini_observation, resolve_gemini_mode
from services.web_ai_gap import rebuild_web_ai_gap_for_updated_ai_contexts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeminiRerunOutcome:
    """Result of attempting a Gemini-only re-run.

    `success=False` means no external call succeeded (Gemini disabled
    in this environment, credentials/request-limit gate not satisfied,
    or the API call itself failed) — `result_json`/`meta_json` are both
    None in that case, and the caller (main.py) must not write anything
    to the database, leaving the previously saved result untouched.
    `reason` is always a short, safe-to-display string (never an API
    key, token, or raw provider error payload) — the same kind of
    string services/gemini_provider.py already surfaces via
    `meta.geminiProvider.reason`.
    """

    success: bool
    reason: str
    result_json: dict[str, Any] | None = None
    meta_json: dict[str, Any] | None = None


def rerun_gemini_for_analysis_run(
    *,
    brand_name: str,
    input_snapshot: dict[str, Any] | None,
    result_json: dict[str, Any],
    meta_json: dict[str, Any] | None,
) -> GeminiRerunOutcome:
    """Calls Gemini once (via build_gemini_observation(), the same
    function `/analyze` uses) and, only on success, returns an updated
    copy of `result_json`/`meta_json` with the Gemini card
    replaced/added and `geminiProvider` refreshed.

    `gemini_mode` is resolved from the saved `input_snapshot`'s
    `geminiMode` field (the override the original /analyze request
    actually used, if any) exactly like `/analyze` resolves it from the
    live request body — so a re-run reproduces the same
    enabled/disabled decision the original analysis made, rather than
    always using the current environment default regardless of what
    this particular run was configured with. `resolve_gemini_mode()`
    still enforces `ALLOW_GEMINI_MODE_OVERRIDE` itself, so this can
    never turn on a disabled environment's Gemini calls just because an
    old input_snapshot happens to contain `"geminiMode": "google"`.
    """
    gemini_mode = resolve_gemini_mode((input_snapshot or {}).get("geminiMode"))
    item, status, reason, environment = build_gemini_observation(brand_name, gemini_mode)

    if item is None:
        # Nothing called successfully — never touch result_json/meta_json,
        # so the caller has nothing to persist and the existing saved
        # result stays exactly as it was (see module docstring).
        return GeminiRerunOutcome(success=False, reason=reason)

    existing_cards = list(result_json.get("aiOverviewComparison") or [])
    new_card = item.model_dump()
    updated_cards: list[dict[str, Any]] = []
    replaced = False
    for card in existing_cards:
        if card.get("platform") == GEMINI_PLATFORM_LABEL:
            updated_cards.append(new_card)
            replaced = True
        else:
            updated_cards.append(card)
    if not replaced:
        updated_cards.append(new_card)

    updated_result_json = dict(result_json)
    updated_result_json["aiOverviewComparison"] = updated_cards
    updated_result_json["webAiGap"] = _rebuild_web_ai_gap_best_effort(
        brand_name, result_json, updated_cards
    )

    updated_meta_json = dict(meta_json or {})
    updated_meta_json["geminiProvider"] = GeminiProviderInfo(
        mode=gemini_mode, status=status, reason=reason, environment=environment
    ).model_dump()

    return GeminiRerunOutcome(
        success=True,
        reason=reason,
        result_json=updated_result_json,
        meta_json=updated_meta_json,
    )


def _rebuild_web_ai_gap_best_effort(
    brand_name: str,
    result_json: dict[str, Any],
    updated_ai_overview_cards: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Best-effort wrapper around
    services.web_ai_gap.rebuild_web_ai_gap_for_updated_ai_contexts() —
    returns the original (unparsed) `webAiGap` dict unchanged whenever
    it's missing, or doesn't parse as a WebAiGapResult (e.g. a very old
    saved run from before this field existed), rather than raising and
    aborting the whole re-run over this best-effort section. See that
    function's docstring for when an update is actually attempted."""
    existing_web_ai_gap = result_json.get("webAiGap")
    if existing_web_ai_gap is None:
        return None

    try:
        existing = WebAiGapResult(**existing_web_ai_gap)
        cooccurrence_ranking = [
            CooccurrenceKeyword(**keyword)
            for keyword in (result_json.get("cooccurrenceRanking") or [])
        ]
        updated_ai_overview_comparison = [
            AIOverviewComparisonItem(**card) for card in updated_ai_overview_cards
        ]
        updated = rebuild_web_ai_gap_for_updated_ai_contexts(
            brand_name, existing, cooccurrence_ranking, updated_ai_overview_comparison
        )
        return updated.model_dump()
    except Exception:
        logger.exception(
            "Failed to update webAiGap after Gemini rerun; leaving it unchanged"
        )
        return existing_web_ai_gap
