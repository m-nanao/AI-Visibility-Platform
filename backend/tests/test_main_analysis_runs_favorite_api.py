"""Verifies PATCH /analysis-runs/{id}/favorite (see main.py's
set_analysis_run_favorite(), services.analysis_history_repository.
set_analysis_run_favorite()), added by feature/history-favorite-flag so
a saved analysis history entry can be marked/unmarked as a favorite,
independent of the existing important flag.

Authorization was tightened by fix/history-read-token-write-isolation
(pre-demo audit issue B2): this endpoint is now JWT-only, with no
HISTORY_READ_TOKEN fallback of any kind — mirrors
tests/test_main_tags_categories_api.py's auth-test conventions exactly.

Mirrors tests/test_main_analysis_runs_important_api.py's conventions
exactly, since this endpoint shares its authorization gate and
response shape: never touches a real database
(main.repository_set_analysis_run_favorite is monkeypatched), and mocks
main.verify_supabase_jwt/can_user_access_analysis_run directly rather
than re-deriving JWT/DB behavior already covered elsewhere.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from services.analysis_history_repository import AnalysisHistoryReadError
from services.jwt_auth import AuthenticatedUser, JWTAuthError

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


def _patch(favorite: bool = True, headers: dict[str, str] | None = None):
    return client.patch(
        f"/analysis-runs/{RUN_ID}/favorite",
        json={"isFavorite": favorite},
        headers=headers or {},
    )


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


def test_favorite_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = _patch(headers=_auth_headers())

    assert response.status_code == 503


def test_favorite_rejected_when_jwt_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 503


# --- HISTORY_READ_TOKEN is no longer a valid credential for this
# endpoint (fix/history-read-token-write-isolation) --------------------


def test_favorite_rejected_with_history_read_token_alone(monkeypatch):
    """A correct HISTORY_READ_TOKEN, with no Authorization header at
    all, must never be enough to change the favorite flag — previously
    this succeeded unconditionally (pre-demo audit issue B2)."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_favorite",
        lambda run_id, *, is_favorite: update_calls.append(run_id),
    )

    response = _patch(headers=_auth_headers())

    assert response.status_code == 401
    assert update_calls == []


def test_favorite_rejected_with_no_credentials_at_all(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = _patch()

    assert response.status_code == 401


def test_favorite_token_value_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_favorite",
        lambda run_id, *, is_favorite: True,
    )

    response = _patch(headers={**_jwt_headers(), **_auth_headers()})

    assert TEST_TOKEN not in response.text


def test_favorite_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)

    def raising_set(run_id, *, is_favorite):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_set_analysis_run_favorite", raising_set)

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 503


# --- JWT-authenticated: access-checked by run id before updating ------


def test_favorite_jwt_mode_success_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_favorite",
        lambda run_id, *, is_favorite: True,
    )

    response = _patch(favorite=True, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json() == {"analysisRunId": RUN_ID, "isFavorite": True}


def test_favorite_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling repository_set_analysis_run_favorite() — a
    caller who can't see a run (e.g. a different project) must not be
    able to favorite it either."""
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_favorite",
        lambda run_id, *, is_favorite: update_calls.append(run_id),
    )

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 403
    assert update_calls == []


def test_favorite_jwt_mode_returns_404_when_accessible_but_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_favorite",
        lambda run_id, *, is_favorite: False,
    )

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 404


def test_favorite_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id="user-1")
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())

    def raising_access_check(conn, uid, run_id):
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(main, "can_user_access_analysis_run", raising_access_check)

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 503


def test_favorite_rejected_with_invalid_jwt(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    def raising_verify(token, settings):
        raise JWTAuthError("expired", "token expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raising_verify)

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 401
