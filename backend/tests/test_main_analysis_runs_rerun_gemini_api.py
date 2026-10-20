"""Verifies POST /analysis-runs/{id}/rerun/gemini (see main.py's
rerun_gemini_observation(), services.gemini_rerun.
rerun_gemini_for_analysis_run()) — added so a suspected mid-way-
truncated Gemini answer can be re-fetched without re-running the whole
/analyze request.

Authorization was tightened by fix/history-read-token-write-isolation
(pre-demo audit issue B2): this endpoint is now JWT-only, with no
HISTORY_READ_TOKEN fallback of any kind — mirrors
tests/test_main_tags_categories_api.py's auth-test conventions exactly.
Never calls the real Gemini API here either way (main.
rerun_gemini_for_analysis_run is monkeypatched in every test, so no
test accidentally exercises the external call) — JWT/project-access
behavior is already covered by tests/test_jwt_auth.py and
tests/test_analysis_history_repository.py, and the Gemini-call logic
itself by tests/test_gemini_rerun.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from services.analysis_history_repository import AnalysisHistoryReadError
from services.gemini_rerun import GeminiRerunOutcome
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
RUN_ID = "11111111-1111-1111-1111-111111111111"

RERUN_PATH = f"/analysis-runs/{RUN_ID}/rerun/gemini"


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
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(
        main, "can_user_access_analysis_run", lambda conn, uid, run_id: can_access_run
    )


def _fake_detail() -> dict:
    return {
        "id": RUN_ID,
        "brand": {"id": "brand-1", "name": "Acme", "canonicalDomain": None},
        "run": {
            "status": "completed",
            "inputSnapshot": {"brandName": "Acme", "geminiMode": "google"},
            "sourceSummary": None,
            "startedAt": "2026-10-01T00:00:00+00:00",
            "completedAt": "2026-10-01T00:00:10+00:00",
        },
        "result": {"aiOverviewComparison": []},
        "meta": {},
        "projectId": "project-1",
    }


def _mock_successful_rerun(monkeypatch, *, updated_result: dict | None = None):
    result_json = updated_result or {
        "aiOverviewComparison": [{"platform": "Gemini (Google API)", "summary": "new"}]
    }
    monkeypatch.setattr(
        main,
        "rerun_gemini_for_analysis_run",
        lambda **kwargs: GeminiRerunOutcome(
            success=True, reason="ok", result_json=result_json, meta_json={"geminiProvider": {}}
        ),
    )
    return result_json


def _mock_failed_rerun(monkeypatch, reason: str = "Gemini API key is not configured."):
    monkeypatch.setattr(
        main,
        "rerun_gemini_for_analysis_run",
        lambda **kwargs: GeminiRerunOutcome(success=False, reason=reason),
    )


# --- disabled / unconfigured -------------------------------------------


def test_rerun_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.post(RERUN_PATH, headers=_auth_headers())

    assert response.status_code == 503


def test_rerun_rejected_when_jwt_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 503


# --- HISTORY_READ_TOKEN is no longer a valid credential for this
# endpoint (fix/history-read-token-write-isolation) --------------------


def test_rerun_rejected_with_history_read_token_alone(monkeypatch):
    """A correct HISTORY_READ_TOKEN, with no Authorization header at
    all, must never be enough to trigger a Gemini re-run (and
    therefore never consume the Gemini API budget on behalf of an
    unauthenticated caller) — previously this succeeded unconditionally
    (pre-demo audit issue B2)."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    rerun_calls = []
    monkeypatch.setattr(
        main,
        "rerun_gemini_for_analysis_run",
        lambda **kwargs: rerun_calls.append(kwargs),
    )

    response = client.post(RERUN_PATH, headers=_auth_headers())

    assert response.status_code == 401
    assert rerun_calls == []


def test_rerun_rejected_with_no_credentials_at_all(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.post(RERUN_PATH)

    assert response.status_code == 401


def test_rerun_token_value_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_rerun(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(RERUN_PATH, headers={**_jwt_headers(), **_auth_headers()})

    assert TEST_TOKEN not in response.text


def test_rerun_passes_through_brand_name_and_input_snapshot(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    received_kwargs = {}

    def fake_rerun(**kwargs):
        received_kwargs.update(kwargs)
        return GeminiRerunOutcome(success=True, reason="ok", result_json={}, meta_json={})

    monkeypatch.setattr(main, "rerun_gemini_for_analysis_run", fake_rerun)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    client.post(RERUN_PATH, headers=_jwt_headers())

    assert received_kwargs["brand_name"] == "Acme"
    assert received_kwargs["input_snapshot"] == {"brandName": "Acme", "geminiMode": "google"}


def test_rerun_failure_returns_502_and_does_not_write_to_db(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_failed_rerun(monkeypatch, reason="Gemini API key is not configured.")
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_update_analysis_result",
        lambda run_id, **kw: update_calls.append(run_id) or True,
    )

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 502
    assert response.json() == {"error": "Gemini API key is not configured."}
    assert update_calls == []


def test_rerun_returns_503_when_repository_update_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_rerun(monkeypatch)

    def raising_update(run_id, **kw):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_update_analysis_result", raising_update)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 503


def test_rerun_returns_404_when_update_reports_run_vanished(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_rerun(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: False)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 404


def test_rerun_returns_503_when_get_analysis_run_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)

    def raising_get(run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_get_analysis_run", raising_get)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 503


# --- JWT-authenticated: access-checked by run id before anything else --


def test_rerun_jwt_mode_success_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: _fake_detail())
    _mock_successful_rerun(monkeypatch)
    monkeypatch.setattr(main, "repository_update_analysis_result", lambda run_id, **kw: True)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json()["updated"] is True


def test_rerun_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling the Gemini API or touching the DB — this is
    what keeps a user who can't see a run (e.g. a different project)
    from triggering a billable call for it."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    rerun_calls = []
    monkeypatch.setattr(
        main,
        "rerun_gemini_for_analysis_run",
        lambda **kwargs: rerun_calls.append(kwargs)
        or GeminiRerunOutcome(success=True, reason="ok", result_json={}, meta_json={}),
    )

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 403
    assert rerun_calls == []


def test_rerun_jwt_mode_returns_404_when_accessible_but_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_get_analysis_run", lambda run_id: None)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 404


def test_rerun_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())

    def raising_access_check(conn, uid, run_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_analysis_run", raising_access_check)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 503


def test_rerun_rejected_with_invalid_jwt(monkeypatch):
    """A verification failure (expired/bad signature/etc.) must also
    never reach rerun_gemini_for_analysis_run() — no external API call
    happens here either."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    rerun_calls = []
    monkeypatch.setattr(
        main,
        "rerun_gemini_for_analysis_run",
        lambda **kwargs: rerun_calls.append(kwargs),
    )

    def raising_verify(token, settings):
        raise JWTAuthError("expired", "token expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raising_verify)

    response = client.post(RERUN_PATH, headers=_jwt_headers())

    assert response.status_code == 401
    assert rerun_calls == []
