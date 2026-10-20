"""Verifies DELETE /analysis-runs/{id} (see main.py's
delete_analysis_run(), services.analysis_history_repository.
soft_delete_analysis_run()), added by feature/history-delete-and-mode-badges
so a依頼者 can clear repeated full-ON/single-ON verification runs out of
the history list.

Authorization was tightened by fix/history-read-token-write-isolation
(pre-demo audit issue B2): this endpoint is now JWT-only, with no
HISTORY_READ_TOKEN fallback of any kind — mirrors
tests/test_main_tags_categories_api.py's auth-test conventions exactly
(_mock_jwt_auth-equivalent helper monkeypatches
main.is_jwt_verification_configured directly rather than requiring a
real SUPABASE_JWKS_URL-shaped env).

Mirrors tests/test_main_analysis_history_read_api.py's conventions:
never touches a real database (main.repository_soft_delete_analysis_run
is monkeypatched), and mocks main.verify_supabase_jwt/
can_user_access_analysis_run directly rather than re-deriving JWT/DB
behavior already covered by tests/test_jwt_auth.py and
tests/test_analysis_history_repository.py.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
RUN_ID = "11111111-1111-1111-1111-111111111111"


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


# --- disabled / unconfigured -------------------------------------------


def test_delete_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_auth_headers())

    assert response.status_code == 503


def test_delete_rejected_when_jwt_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 503


# --- HISTORY_READ_TOKEN is no longer a valid credential for this
# endpoint (fix/history-read-token-write-isolation) --------------------


def test_delete_rejected_with_history_read_token_alone(monkeypatch):
    """The whole point of this fix: a correct HISTORY_READ_TOKEN, with
    no Authorization header at all, must never be enough to delete a
    run — previously this succeeded unconditionally (pre-demo audit
    issue B2)."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    delete_calls = []
    monkeypatch.setattr(
        main, "repository_soft_delete_analysis_run", lambda run_id: delete_calls.append(run_id)
    )

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_auth_headers())

    assert response.status_code == 401
    assert delete_calls == []


def test_delete_rejected_with_no_credentials_at_all(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.delete(f"/analysis-runs/{RUN_ID}")

    assert response.status_code == 401


def test_delete_token_value_never_appears_in_response_body(monkeypatch):
    """A caller may still send the (now-ignored) X-History-Read-Token
    header alongside a valid JWT — its value must never leak back,
    success or failure."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_soft_delete_analysis_run", lambda run_id: True)

    response = client.delete(
        f"/analysis-runs/{RUN_ID}", headers={**_jwt_headers(), **_auth_headers()}
    )

    assert TEST_TOKEN not in response.text


def test_delete_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)

    def raising_delete(run_id):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_soft_delete_analysis_run", raising_delete)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 503


# --- JWT-authenticated: access-checked by run id before deleting ------


def test_delete_jwt_mode_success_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_soft_delete_analysis_run", lambda run_id: True)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": True}


def test_delete_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling repository_soft_delete_analysis_run() — a
    caller who can't see a run (e.g. it belongs to a different
    project) must not be able to delete it either."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    delete_calls = []
    monkeypatch.setattr(
        main,
        "repository_soft_delete_analysis_run",
        lambda run_id: delete_calls.append(run_id),
    )

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 403
    assert delete_calls == []


def test_delete_jwt_mode_returns_404_when_accessible_but_not_found(monkeypatch):
    """can_user_access_analysis_run() only checks org membership, not
    whether the run still exists/is already deleted — the repository
    call is still the source of truth for "not found"."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(main, "repository_soft_delete_analysis_run", lambda run_id: False)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 404


def test_delete_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())

    def raising_access_check(conn, uid, run_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_analysis_run", raising_access_check)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 503


def test_delete_rejected_with_invalid_jwt(monkeypatch):
    from services.jwt_auth import JWTAuthError

    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    def raising_verify(token, settings):
        raise JWTAuthError("expired", "token expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raising_verify)

    response = client.delete(f"/analysis-runs/{RUN_ID}", headers=_jwt_headers())

    assert response.status_code == 401
