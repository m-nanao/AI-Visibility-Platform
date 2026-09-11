"""Verifies GET /analysis-runs/{id}/comparison (see main.py,
docs/25_analysis_history_comparison_design.md).

Mirrors tests/test_main_analysis_history_read_api.py's structure and
monkeypatch pattern: main.repository_get_analysis_run and
main.repository_get_previous_analysis_run_for_brand are monkeypatched
so these tests never touch a real database. The HISTORY_READ_TOKEN
gate itself (shared with the other two read endpoints via
main._check_history_read_access()) is exercised again here as a
belt-and-suspenders check, but its full behavior is already covered by
tests/test_main_analysis_history_read_api.py. The pure diff logic is
covered in depth by tests/test_analysis_history_comparison.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER
from main import app
from services.analysis_history_repository import AnalysisHistoryReadError

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
CURRENT_ID = "11111111-1111-1111-1111-111111111111"


def _clear_read_env(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)


def _enable_read_env(monkeypatch, token: str = TEST_TOKEN):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("HISTORY_READ_TOKEN", token)


def _auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    return {HISTORY_READ_TOKEN_HEADER: token}


def _fake_current_run(result=None):
    return {
        "id": CURRENT_ID,
        "brand": {"id": "brand-1", "name": "サイボウズ", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {},
            "sourceSummary": None,
            "startedAt": "2026-09-10T00:00:00+09:00",
            "completedAt": "2026-09-10T00:00:10+09:00",
        },
        "result": result if result is not None else {"summary": {"visibilityScore": 91}},
        "meta": None,
    }


def _fake_previous_run(result=None):
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "startedAt": "2026-09-01T00:00:00+09:00",
        "result": result if result is not None else {"summary": {"visibilityScore": 86}},
    }


# --- gate behavior (same messages/order as the other read endpoints) -------


def test_returns_503_when_read_history_disabled(monkeypatch):
    _clear_read_env(monkeypatch)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read API is not enabled"}


def test_returns_503_when_history_read_token_not_configured(monkeypatch):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison")

    assert response.status_code == 503
    assert response.json() == {"error": "analysis history read token is not configured"}


def test_returns_403_when_token_header_missing(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison")

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


def test_returns_403_when_token_header_mismatched(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.get(
        f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers("wrong-token")
    )

    assert response.status_code == 403
    assert response.json() == {"error": "analysis history read access denied"}


# --- current not found -------------------------------------------------------


def test_returns_404_when_current_run_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: None)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 404
    assert response.json() == {"error": "analysis run not found"}


def test_does_not_query_previous_run_when_current_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: None)
    previous_calls = []
    monkeypatch.setattr(
        main,
        "repository_get_previous_analysis_run_for_brand",
        lambda analysis_run_id, project_id=None: previous_calls.append(analysis_run_id),
    )

    client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert previous_calls == []


# --- DB errors ----------------------------------------------------------------


def test_returns_503_when_current_lookup_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_get(analysis_run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 503


def test_returns_503_when_previous_lookup_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: _fake_current_run())

    def raising_get_previous(analysis_run_id, project_id=None):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_previous_analysis_run_for_brand", raising_get_previous)

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 503


# --- success: no previous run --------------------------------------------------


def test_success_with_no_previous_run(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: _fake_current_run())
    monkeypatch.setattr(
        main,
        "repository_get_previous_analysis_run_for_brand",
        lambda analysis_run_id, project_id=None: None,
    )

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["current"]["id"] == CURRENT_ID
    assert body["current"]["visibilityScore"] == 91
    assert body["previous"] is None
    assert body["diff"] is None
    assert body["warnings"] == ["比較できる過去履歴がまだありません。"]


# --- success: with previous run ------------------------------------------------


def test_success_with_previous_run_includes_diff(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: _fake_current_run())
    monkeypatch.setattr(
        main,
        "repository_get_previous_analysis_run_for_brand",
        lambda analysis_run_id, project_id=None: _fake_previous_run(),
    )

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["current"]["visibilityScore"] == 91
    assert body["previous"]["visibilityScore"] == 86
    assert body["diff"]["visibilityScore"] == {"current": 91, "previous": 86, "delta": 5}
    assert body["diff"]["cooccurrence"] == {
        "topN": 10,
        "newTerms": [],
        "removedTerms": [],
        "changedTerms": [],
    }
    assert body["diff"]["improvements"] == {"currentCount": 0, "previousCount": 0, "delta": 0}
    assert body["warnings"] == []


def test_success_passes_current_result_and_started_at_through(monkeypatch):
    current_result = {
        "summary": {"visibilityScore": 91},
        "cooccurrenceRanking": [{"keyword": "ChatGPT", "count": 12, "trend": "flat"}],
        "improvements": [{"title": "a"}, {"title": "b"}],
    }
    monkeypatch_current = _fake_current_run(result=current_result)
    previous_result = {
        "summary": {"visibilityScore": 86},
        "cooccurrenceRanking": [],
        "improvements": [{"title": "a"}],
    }

    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: monkeypatch_current)
    monkeypatch.setattr(
        main,
        "repository_get_previous_analysis_run_for_brand",
        lambda analysis_run_id, project_id=None: _fake_previous_run(result=previous_result),
    )

    response = client.get(f"/analysis-runs/{CURRENT_ID}/comparison", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["current"]["startedAt"] == "2026-09-10T00:00:00+09:00"
    assert body["diff"]["cooccurrence"]["newTerms"] == [
        {"term": "ChatGPT", "rank": 1, "score": 12}
    ]
    assert body["diff"]["improvements"] == {"currentCount": 2, "previousCount": 1, "delta": 1}


# --- /analyze, /analysis-runs, /analysis-runs/{id} are unaffected -----------


def test_analyze_unaffected_by_comparison_route(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.post("/analyze", json={"brandName": "サイボウズ"})

    assert response.status_code == 200


def test_detail_route_still_reachable_and_unaffected(monkeypatch):
    """GET /analysis-runs/{id} (no /comparison suffix) must still route
    to get_analysis_run(), not be swallowed by the new
    /analysis-runs/{id}/comparison route."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda analysis_run_id: _fake_current_run())

    response = client.get(f"/analysis-runs/{CURRENT_ID}", headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert "diff" not in body
    assert "warnings" not in body
