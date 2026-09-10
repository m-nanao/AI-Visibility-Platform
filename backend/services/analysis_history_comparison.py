"""Pure comparison logic backing GET /analysis-runs/{id}/comparison
(see docs/25_analysis_history_comparison_design.md).

Deliberately separate from services/analysis_history_repository.py's
DB access, so the diff logic itself can be unit-tested without any
DB/psycopg involvement — mirrors the existing DB-access/pure-logic
split elsewhere in this backend (e.g. services/cooccurrence.py's
compute_cooccurrence_ranking() vs the DB code in main.py's /analyze
handler).

build_comparison_response() takes two already-fetched, already
DB-shape-normalized "run" dicts — {"id": str, "startedAt": str | None,
"result": dict | None} — rather than raw DB rows or Pydantic models,
so this module only ever deals with plain Python data and has no
knowledge of psycopg, FastAPI, or backend/models.py. main.py's route
handler owns normalizing repository output into this shape and turning
this function's return value into an AnalysisRunComparisonResponse.

`result` is the analysis_results.result_json blob (loosely, an
AnalysisResult-shaped dict) — never assumed to exactly match the
current AnalysisResult schema, since it may be an older snapshot (see
docs/22_analysis_history_detail_ui_design.md's equivalent
result_json-is-a-snapshot caveat). Every extraction helper below
tolerates a missing/malformed `result` by returning None/empty rather
than raising, and INCOMPATIBLE_RESULT_WARNING is added when that
happens.
"""

from __future__ import annotations

from typing import Any

# Only the top TOP_N co-occurrence terms (by their existing rank order
# in result_json's cooccurrenceRanking — see
# services/cooccurrence.py's compute_cooccurrence_ranking(), which
# already returns terms most-common-first) are compared — see
# docs/25_analysis_history_comparison_design.md "11. 共起語ランキング
# 比較の扱い".
TOP_N = 10

INSUFFICIENT_HISTORY_WARNING = "比較できる過去履歴がまだありません。"
INCOMPATIBLE_RESULT_WARNING = "一部の比較項目を表示できません。"
PROVIDER_MISMATCH_WARNING = "取得条件が異なる可能性があるため、比較には注意が必要です。"


def _extract_visibility_score(result: dict[str, Any] | None) -> int | None:
    if not isinstance(result, dict):
        return None
    summary = result.get("summary")
    if not isinstance(summary, dict):
        return None
    score = summary.get("visibilityScore")
    return score if isinstance(score, int) else None


def _extract_cooccurrence_ranking(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Returns cooccurrenceRanking's `keyword`/`count` items in their
    existing (already most-common-first) order, ignoring any entry
    missing either field. Empty (not None) when `result` itself is
    missing/malformed, so callers can treat "no ranking data" and "no
    result at all" the same way for diffing purposes.
    """
    if not isinstance(result, dict):
        return []
    ranking = result.get("cooccurrenceRanking")
    if not isinstance(ranking, list):
        return []
    return [
        item
        for item in ranking
        if isinstance(item, dict) and isinstance(item.get("keyword"), str) and isinstance(item.get("count"), int)
    ]


def _extract_improvements_count(result: dict[str, Any] | None) -> int | None:
    if not isinstance(result, dict):
        return None
    improvements = result.get("improvements")
    if not isinstance(improvements, list):
        return None
    return len(improvements)


def _extract_ai_overview_provider_mode(result: dict[str, Any] | None) -> str | None:
    if not isinstance(result, dict):
        return None
    meta = result.get("meta")
    if not isinstance(meta, dict):
        return None
    provider = meta.get("aiOverviewProvider")
    if not isinstance(provider, dict):
        return None
    mode = provider.get("mode")
    return mode if isinstance(mode, str) else None


def _build_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": run["id"],
        "startedAt": run.get("startedAt"),
        "visibilityScore": _extract_visibility_score(run.get("result")),
    }


def _diff_visibility_score(current_score: int | None, previous_score: int | None) -> dict[str, Any]:
    delta = current_score - previous_score if current_score is not None and previous_score is not None else None
    return {"current": current_score, "previous": previous_score, "delta": delta}


def _diff_cooccurrence(
    current_ranking: list[dict[str, Any]],
    previous_ranking: list[dict[str, Any]],
    top_n: int = TOP_N,
) -> dict[str, Any]:
    """Classifies the top `top_n` terms on each side into new/removed/
    changed — see docs/25_analysis_history_comparison_design.md "11.
    共起語ランキング比較の扱い". `rankDelta`/`scoreDelta` are
    current-minus-previous, so `rankDelta` is negative when a term's
    rank *improved* (moved to a lower/better rank number).
    """
    current_by_term = {
        item["keyword"]: {"rank": index + 1, "score": item["count"]}
        for index, item in enumerate(current_ranking[:top_n])
    }
    previous_by_term = {
        item["keyword"]: {"rank": index + 1, "score": item["count"]}
        for index, item in enumerate(previous_ranking[:top_n])
    }

    new_terms = [
        {"term": term, "rank": data["rank"], "score": data["score"]}
        for term, data in current_by_term.items()
        if term not in previous_by_term
    ]
    removed_terms = [
        {"term": term, "rank": data["rank"], "score": data["score"]}
        for term, data in previous_by_term.items()
        if term not in current_by_term
    ]
    changed_terms = [
        {
            "term": term,
            "currentRank": current_data["rank"],
            "previousRank": previous_by_term[term]["rank"],
            "rankDelta": current_data["rank"] - previous_by_term[term]["rank"],
            "currentScore": current_data["score"],
            "previousScore": previous_by_term[term]["score"],
            "scoreDelta": current_data["score"] - previous_by_term[term]["score"],
        }
        for term, current_data in current_by_term.items()
        if term in previous_by_term
    ]

    return {
        "topN": top_n,
        "newTerms": new_terms,
        "removedTerms": removed_terms,
        "changedTerms": changed_terms,
    }


def _diff_improvements(current_count: int | None, previous_count: int | None) -> dict[str, Any]:
    """Count-only diff — see docs/25_analysis_history_comparison_design.md
    "12. 文脈分析・改善提案の比較"「初期は件数差分のみでよい」. Missing
    data on either side (incompatible/absent result) is treated as 0
    rather than surfaced as null, since INCOMPATIBLE_RESULT_WARNING
    already flags that case at the top level.
    """
    current = current_count if current_count is not None else 0
    previous = previous_count if previous_count is not None else 0
    return {"currentCount": current, "previousCount": previous, "delta": current - previous}


def build_comparison_response(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """Builds the full GET /analysis-runs/{id}/comparison response
    body from two normalized run dicts, each shaped
    {"id": str, "startedAt": str | None, "result": dict | None}.

    `previous` is None when the same brand has no earlier run yet —
    in that case `previous`/`diff` are both None in the response and
    `warnings` explains why (matches
    docs/25_analysis_history_comparison_design.md "7. API設計案"'s
    "previousがない場合" example).

    Returns a plain dict matching AnalysisRunComparisonResponse's
    field names exactly, so main.py can pass it straight into
    AnalysisRunComparisonResponse(**build_comparison_response(...)).
    """
    current_summary = _build_run_summary(current)

    if previous is None:
        return {
            "current": current_summary,
            "previous": None,
            "diff": None,
            "warnings": [INSUFFICIENT_HISTORY_WARNING],
        }

    previous_summary = _build_run_summary(previous)

    current_result = current.get("result")
    previous_result = previous.get("result")

    warnings: list[str] = []
    if not isinstance(current_result, dict) or not isinstance(previous_result, dict):
        warnings.append(INCOMPATIBLE_RESULT_WARNING)

    current_provider_mode = _extract_ai_overview_provider_mode(current_result)
    previous_provider_mode = _extract_ai_overview_provider_mode(previous_result)
    if (
        current_provider_mode is not None
        and previous_provider_mode is not None
        and current_provider_mode != previous_provider_mode
    ):
        warnings.append(PROVIDER_MISMATCH_WARNING)

    diff = {
        "visibilityScore": _diff_visibility_score(
            current_summary["visibilityScore"], previous_summary["visibilityScore"]
        ),
        "cooccurrence": _diff_cooccurrence(
            _extract_cooccurrence_ranking(current_result),
            _extract_cooccurrence_ranking(previous_result),
        ),
        "improvements": _diff_improvements(
            _extract_improvements_count(current_result),
            _extract_improvements_count(previous_result),
        ),
    }

    return {
        "current": current_summary,
        "previous": previous_summary,
        "diff": diff,
        "warnings": warnings,
    }
