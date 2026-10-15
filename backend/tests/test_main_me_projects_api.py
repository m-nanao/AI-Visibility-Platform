"""Verifies GET /me/projects (see main.py,
docs/40_async_analysis_jobs_design.md "Phase 3") — a minimal,
read-only, JWT-only lookup so the frontend can learn which project(s)
the current user may pass as POST /analysis-jobs' required
`projectId`.

These tests never touch a real database — main's own imported names
(main.verify_supabase_jwt / main.open_history_db_connection /
main.get_accessible_project_ids) are monkeypatched directly, mirroring
the existing tests/test_main_analysis_history_read_api.py and
tests/test_main_analysis_jobs_api.py patterns.
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)


class _FakeDbConnection:
    """Stand-in for main.open_history_db_connection()'s return value —
    only used as a `with ... as conn:` context manager; `conn` itself
    is never inspected since get_accessible_project_ids() is mocked
    too."""

    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _clear_jwt_env(monkeypatch):
    monkeypatch.delenv("AUTH_JWT_ENABLED", raising=False)
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)


def _enable_jwt_env(monkeypatch):
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.test/jwks.json")


def _auth_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mock_auth(monkeypatch, *, user_id: str = "user-1"):
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeDbConnection())


# --- authentication ----------------------------------------------------------


def test_returns_401_without_authorization_header(monkeypatch):
    _enable_jwt_env(monkeypatch)

    response = client.get("/me/projects")

    assert response.status_code == 401


def test_returns_401_for_invalid_jwt(monkeypatch):
    _enable_jwt_env(monkeypatch)

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_signature", "bad signature")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 401


def test_returns_401_for_expired_jwt(monkeypatch):
    _enable_jwt_env(monkeypatch)

    def raise_expired(token, settings):
        raise JWTAuthError("expired", "token has expired")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_expired)

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 401


def test_returns_503_when_jwt_verification_not_configured(monkeypatch):
    _clear_jwt_env(monkeypatch)

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 503


def test_never_falls_back_to_history_read_token(monkeypatch):
    """Unlike the existing GET /analysis-runs family, this endpoint has
    no HISTORY_READ_TOKEN path at all — a caller cannot substitute it
    for a JWT."""
    _enable_jwt_env(monkeypatch)

    response = client.get("/me/projects", headers={"X-History-Read-Token": "whatever"})

    assert response.status_code == 401


def test_jwt_is_never_echoed_back_in_the_response_body(monkeypatch):
    _enable_jwt_env(monkeypatch)

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_signature", "bad signature")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)
    secret_token = "super-secret-token-value"

    response = client.get("/me/projects", headers=_auth_headers(secret_token))

    assert secret_token not in response.text


# --- successful lookup --------------------------------------------------------


def test_returns_accessible_project_ids(monkeypatch):
    _enable_jwt_env(monkeypatch)
    _mock_auth(monkeypatch, user_id="user-1")
    monkeypatch.setattr(
        main, "get_accessible_project_ids", lambda conn, uid: ["project-a", "project-b"]
    )

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"projects": [{"id": "project-a"}, {"id": "project-b"}]}


def test_returns_empty_list_for_user_with_no_projects(monkeypatch):
    """Zero accessible projects is a valid, successful response — not
    an error — so the frontend can distinguish "you have no project
    yet" from an actual failure."""
    _enable_jwt_env(monkeypatch)
    _mock_auth(monkeypatch, user_id="user-1")
    monkeypatch.setattr(main, "get_accessible_project_ids", lambda conn, uid: [])

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"projects": []}


def test_passes_the_authenticated_users_own_id_to_the_lookup(monkeypatch):
    """Confirms this endpoint can never be tricked into returning a
    different user's projects — get_accessible_project_ids() is always
    called with the id from the verified JWT, never anything
    caller-supplied."""
    _enable_jwt_env(monkeypatch)
    _mock_auth(monkeypatch, user_id="the-real-authenticated-user")

    seen_user_ids = []

    def fake_get_accessible_project_ids(conn, uid):
        seen_user_ids.append(uid)
        return []

    monkeypatch.setattr(main, "get_accessible_project_ids", fake_get_accessible_project_ids)

    client.get("/me/projects", headers=_auth_headers())

    assert seen_user_ids == ["the-real-authenticated-user"]


def test_returns_503_when_project_lookup_fails(monkeypatch):
    _enable_jwt_env(monkeypatch)
    _mock_auth(monkeypatch, user_id="user-1")

    def raise_error(conn, uid):
        raise RuntimeError("db connection lost")

    monkeypatch.setattr(main, "get_accessible_project_ids", raise_error)

    response = client.get("/me/projects", headers=_auth_headers())

    assert response.status_code == 503
