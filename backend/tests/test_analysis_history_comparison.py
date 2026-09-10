"""Unit tests for services/analysis_history_comparison.py's pure diff
logic (see docs/25_analysis_history_comparison_design.md). No DB/psycopg
involvement — build_comparison_response() takes plain dicts.
"""

from services.analysis_history_comparison import (
    INCOMPATIBLE_RESULT_WARNING,
    INSUFFICIENT_HISTORY_WARNING,
    PROVIDER_MISMATCH_WARNING,
    build_comparison_response,
)


def _result(
    visibility_score=80,
    cooccurrence=None,
    improvements_count=3,
    ai_overview_mode="mock",
):
    return {
        "summary": {"visibilityScore": visibility_score},
        "cooccurrenceRanking": cooccurrence if cooccurrence is not None else [],
        "improvements": [{"title": f"t{i}"} for i in range(improvements_count)],
        "meta": {"aiOverviewProvider": {"mode": ai_overview_mode}},
    }


def _run(run_id="run-1", started_at="2026-09-10T00:00:00+09:00", result=None):
    return {"id": run_id, "startedAt": started_at, "result": result}


# --- no previous history ----------------------------------------------------


def test_no_previous_run_returns_null_previous_and_diff_with_warning():
    current = _run(result=_result(visibility_score=91))

    response = build_comparison_response(current, None)

    assert response["current"] == {
        "id": "run-1",
        "startedAt": "2026-09-10T00:00:00+09:00",
        "visibilityScore": 91,
    }
    assert response["previous"] is None
    assert response["diff"] is None
    assert response["warnings"] == [INSUFFICIENT_HISTORY_WARNING]


def test_current_summary_visibility_score_is_none_when_result_missing():
    current = _run(result=None)

    response = build_comparison_response(current, None)

    assert response["current"]["visibilityScore"] is None


# --- visibilityScore diff ----------------------------------------------------


def test_visibility_score_delta_positive():
    current = _run(run_id="current", result=_result(visibility_score=91))
    previous = _run(run_id="previous", result=_result(visibility_score=86))

    response = build_comparison_response(current, previous)

    assert response["diff"]["visibilityScore"] == {
        "current": 91,
        "previous": 86,
        "delta": 5,
    }


def test_visibility_score_delta_negative():
    current = _run(result=_result(visibility_score=84))
    previous = _run(result=_result(visibility_score=91))

    response = build_comparison_response(current, previous)

    assert response["diff"]["visibilityScore"]["delta"] == -7


def test_visibility_score_delta_zero():
    current = _run(result=_result(visibility_score=86))
    previous = _run(result=_result(visibility_score=86))

    response = build_comparison_response(current, previous)

    assert response["diff"]["visibilityScore"]["delta"] == 0


def test_visibility_score_delta_is_none_when_either_side_missing():
    current = _run(result={"summary": {}})
    previous = _run(result=_result(visibility_score=86))

    response = build_comparison_response(current, previous)

    diff = response["diff"]["visibilityScore"]
    assert diff["current"] is None
    assert diff["previous"] == 86
    assert diff["delta"] is None


# --- cooccurrence diff --------------------------------------------------------


def _term(keyword, count):
    return {"keyword": keyword, "count": count}


def test_cooccurrence_new_term():
    current = _run(result=_result(cooccurrence=[_term("ChatGPT", 12)]))
    previous = _run(result=_result(cooccurrence=[]))

    response = build_comparison_response(current, previous)

    cooccurrence = response["diff"]["cooccurrence"]
    assert cooccurrence["newTerms"] == [{"term": "ChatGPT", "rank": 1, "score": 12}]
    assert cooccurrence["removedTerms"] == []
    assert cooccurrence["changedTerms"] == []


def test_cooccurrence_removed_term():
    current = _run(result=_result(cooccurrence=[]))
    previous = _run(result=_result(cooccurrence=[_term("広告", 5)]))

    response = build_comparison_response(current, previous)

    cooccurrence = response["diff"]["cooccurrence"]
    assert cooccurrence["newTerms"] == []
    assert cooccurrence["removedTerms"] == [{"term": "広告", "rank": 1, "score": 5}]
    assert cooccurrence["changedTerms"] == []


def test_cooccurrence_changed_term_rank_improved_is_negative_rank_delta():
    # "SEO" moves from rank 5 (previous) to rank 2 (current) — an
    # improvement, which should show as a *negative* rankDelta per
    # docs/25_analysis_history_comparison_design.md "11.".
    current = _run(
        result=_result(
            cooccurrence=[_term("AI検索", 20), _term("SEO", 18), _term("other1", 10)]
        )
    )
    previous = _run(
        result=_result(
            cooccurrence=[
                _term("a", 30),
                _term("b", 25),
                _term("c", 20),
                _term("d", 15),
                _term("SEO", 12),
            ]
        )
    )

    response = build_comparison_response(current, previous)

    changed = response["diff"]["cooccurrence"]["changedTerms"]
    seo_entry = next(entry for entry in changed if entry["term"] == "SEO")
    assert seo_entry == {
        "term": "SEO",
        "currentRank": 2,
        "previousRank": 5,
        "rankDelta": -3,
        "currentScore": 18,
        "previousScore": 12,
        "scoreDelta": 6,
    }


def test_cooccurrence_only_top_n_terms_are_considered():
    # 11 current terms, 11 previous terms, all identical keywords —
    # only the top 10 of each side should be compared, so the 11th
    # term should not appear anywhere in the diff.
    current_terms = [_term(f"term{i}", 100 - i) for i in range(11)]
    previous_terms = [_term(f"term{i}", 100 - i) for i in range(11)]
    current = _run(result=_result(cooccurrence=current_terms))
    previous = _run(result=_result(cooccurrence=previous_terms))

    response = build_comparison_response(current, previous)

    cooccurrence = response["diff"]["cooccurrence"]
    assert cooccurrence["topN"] == 10
    all_terms = {entry["term"] for entry in cooccurrence["changedTerms"]}
    assert "term10" not in all_terms
    assert len(cooccurrence["changedTerms"]) == 10


# --- improvements diff --------------------------------------------------------


def test_improvements_count_delta_positive():
    current = _run(result=_result(improvements_count=4))
    previous = _run(result=_result(improvements_count=3))

    response = build_comparison_response(current, previous)

    assert response["diff"]["improvements"] == {
        "currentCount": 4,
        "previousCount": 3,
        "delta": 1,
    }


def test_improvements_count_defaults_to_zero_when_missing():
    current = _run(result={"summary": {}})
    previous = _run(result=_result(improvements_count=3))

    response = build_comparison_response(current, previous)

    improvements = response["diff"]["improvements"]
    assert improvements["currentCount"] == 0
    assert improvements["delta"] == -3


# --- warnings ------------------------------------------------------------------


def test_incompatible_result_warning_when_result_is_missing():
    current = _run(result=None)
    previous = _run(result=_result())

    response = build_comparison_response(current, previous)

    assert INCOMPATIBLE_RESULT_WARNING in response["warnings"]


def test_no_warnings_when_both_results_present_and_provider_mode_matches():
    current = _run(result=_result(ai_overview_mode="mock"))
    previous = _run(result=_result(ai_overview_mode="mock"))

    response = build_comparison_response(current, previous)

    assert response["warnings"] == []


def test_provider_mismatch_warning_when_ai_overview_mode_differs():
    current = _run(result=_result(ai_overview_mode="dataforseo_sandbox"))
    previous = _run(result=_result(ai_overview_mode="mock"))

    response = build_comparison_response(current, previous)

    assert PROVIDER_MISMATCH_WARNING in response["warnings"]


def test_no_provider_mismatch_warning_when_mode_cannot_be_determined():
    current = _run(result={"summary": {"visibilityScore": 90}})
    previous = _run(result=_result())

    response = build_comparison_response(current, previous)

    assert PROVIDER_MISMATCH_WARNING not in response["warnings"]
