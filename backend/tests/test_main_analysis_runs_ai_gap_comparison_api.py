"""Verifies POST /analysis-runs/{id}/web-ai-gap/ai-comparison (see
main.py's generate_web_ai_gap_ai_comparison(),
services.ai_gap_comparison.generate_ai_gap_comparison()) — added so a
依頼者 can generate an AI-powered Web/AI gap comparison on demand from
the history detail screen.

Mirrors tests/test_main_analysis_runs_rerun_gemini_api.py's
conventions: never touches a real database
(main.repository_get_analysis_run/repository_update_analysis_result
are monkeypatched) and never calls the real Anthropic API
(main.generate_ai_gap_comparison is monkeypatched) — JWT/project-access
behavior is already covered by tests/test_jwt_auth.py and
tests/test_analysis_history_repository.py, and the comparison-call
logic itself by tests/test_ai_gap_comparison.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from models import WebAiGapAiComparison
from services.ai_gap_comparison import AiGapComparisonOutcome
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
RUN_ID = "11111111-1111-1111-1111-111111111111"

AI_COMPARISON_PATH = f"/analysis-runs/{RUN_ID}/web-ai-gap/ai-comparison"


def _enable_read_env(monkeypatch, token: str = TEST_TOKEN):
    monkeypatch.setenv("READ_HISTORY_ENABLED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setenv("HISTORY_READ_TOKEN", token)


def _auth_headers(token: str = TEST_TOKEN) -> dict[str, str]:
    return {HISTORY_READ_TOKEN_HEADER: token}


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_jwt_dependencies(monkeypatch, *, user_id: str = "user-1", can_access_run: bool = True):
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "get_accessible_project_ids", lambda conn, uid: [])
    monkeypatch.setattr(
        main, "can_user_access_analysis_run", lambda conn, uid, run_id: can_access_run
    )


def _fake_detail(**result_overrides) -> dict:
    result = {
        "webAiGap": {
            "status": "real",
            "webContext": {"summary": "Web excerpt", "sourceType": "web_fetch", "sourceUrl": None},
            "aiContexts": [{"platform": "chatgpt", "summary": "AI excerpt", "status": "real"}],
            "gapSummary": "x",
            "suggestions": [],
            "note": "note",
        },
    }
    result.update(result_overrides)
    return {
        "id": RUN_ID,
        "brand": {"id": "brand-1", "name": "Acme", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "Acme"},
            "sourceSummary": None,
            "startedAt": "2026-10-01T00:00:00+00:00",
            "completedAt": "2026-10-01T00:00:10+00:00",
        },
        "result": result,
        "meta": {},
        "projectId": "project-1",
    }


def _comparison(**overrides) -> WebAiGapAiComparison:
    fields = {
        "matchedPoints": ["matched"],
        "webStrongAiWeak": ["web strong"],
        "aiStrongWebWeak": ["ai strong"],
        "gapSummary": "gap",
        "recommendations": ["recommend"],
        "caution": "AIによる比較であり、AIの内部認識を直接示すものではありません。",
    }
    fields.update(overrides)
    return WebAiGapAiComparison(**fields)


def _mock_successful_generation(monkeypatch, *, comparison: WebAiGapAiComparison | None = None):
    result = comparison or _comparison()
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: AiGapComparisonOutcome(success=True, reason="ok", comparison=result),
    )
    return result


def _mock_failed_generation(monkeypatch, *, reason: str = "boom", unavailable: bool = False):
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: AiGapComparisonOutcome(
            success=False, reason=reason, unavailable=unavailable
        ),
    )


# --- disabled / unconfigured / unauthorized → same gate as DELETE/rerun ----


def test_ai_comparison_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 503


def test_ai_comparison_returns_403_when_token_header_missing(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.post(AI_COMPARISON_PATH)

    assert response.status_code == 403


def test_ai_comparison_returns_403_when_token_header_mismatched(monkeypatch):
    _enable_read_env(monkeypatch)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers("wrong-token"))

    assert response.status_code == 403


def test_ai_comparison_token_value_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert TEST_TOKEN not in response.text


# --- HISTORY_READ_TOKEN mode: unrestricted, matches existing DELETE/rerun --


def test_ai_comparison_history_token_mode_success(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    comparison = _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["analysisRunId"] == RUN_ID
    assert body["webAiGapAiComparison"]["matchedPoints"] == comparison.matchedPoints
    assert body["webAiGapAiComparison"]["method"] == "ai_comparison"


def test_ai_comparison_history_token_mode_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: None)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 404


def test_ai_comparison_passes_through_brand_name_and_result_json(monkeypatch):
    _enable_read_env(monkeypatch)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    received_kwargs = {}

    def fake_generate(**kwargs):
        received_kwargs.update(kwargs)
        return AiGapComparisonOutcome(success=True, reason="ok", comparison=_comparison())

    monkeypatch.setattr(main, "generate_ai_gap_comparison", fake_generate)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert received_kwargs["brand_name"] == "Acme"
    assert received_kwargs["result_json"] == detail["result"]


def test_ai_comparison_saves_only_webAiGapAiComparison_and_does_not_overwrite_webAiGap(monkeypatch):
    _enable_read_env(monkeypatch)
    detail = _fake_detail()
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: detail)
    _mock_successful_generation(monkeypatch)
    saved = {}

    def fake_update(run_id, *, result_json, meta_json):
        saved["result_json"] = result_json
        saved["meta_json"] = meta_json
        return True

    monkeypatch.setattr(main, "repository_update_analysis_result", fake_update)

    client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert saved["result_json"]["webAiGap"] == detail["result"]["webAiGap"]
    assert "webAiGapAiComparison" in saved["result_json"]
    assert saved["meta_json"] == detail["meta"]


def test_ai_comparison_failure_not_attempted_returns_503_and_does_not_write_to_db(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(monkeypatch, reason="Anthropic API key is not configured.", unavailable=True)
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_update_analysis_result",
        lambda run_id, **kw: update_calls.append(run_id) or True,
    )

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 503
    assert response.json() == {"error": "Anthropic API key is not configured."}
    assert update_calls == []


def test_ai_comparison_failure_attempted_returns_502_and_does_not_write_to_db(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_generation(monkeypatch, reason="Anthropic API request failed with HTTP 500.", unavailable=False)
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_update_analysis_result",
        lambda run_id, **kw: update_calls.append(run_id) or True,
    )

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 502
    assert update_calls == []


def test_ai_comparison_returns_503_when_repository_update_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)

    def raising_update(run_id, **kw):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_update_analysis_result", raising_update)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 503


def test_ai_comparison_returns_404_when_update_reports_run_vanished(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: False)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 404


def test_ai_comparison_returns_503_when_get_analysis_run_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_get(run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.post(AI_COMPARISON_PATH, headers=_auth_headers())

    assert response.status_code == 503


# --- AUTH_JWT_ENABLED=true: access-checked by run id before anything else --


def test_ai_comparison_jwt_mode_success_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_generation(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == RUN_ID


def test_ai_comparison_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling the Anthropic API or touching the DB."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    generate_calls = []
    monkeypatch.setattr(
        main,
        "generate_ai_gap_comparison",
        lambda **kwargs: generate_calls.append(kwargs)
        or AiGapComparisonOutcome(success=True, reason="ok", comparison=_comparison()),
    )

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 403
    assert generate_calls == []


def test_ai_comparison_jwt_mode_returns_404_when_accessible_but_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: None)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 404


def test_ai_comparison_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "get_accessible_project_ids", lambda conn, uid: [])

    def raising_access_check(conn, uid, run_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_analysis_run", raising_access_check)

    response = client.post(AI_COMPARISON_PATH, headers=_jwt_headers())

    assert response.status_code == 503
