"""Verifies PATCH /analysis-runs/{id}/important (see main.py's
set_analysis_run_important(), services.analysis_history_repository.
set_analysis_run_important()), added by feature/history-important-flag
(docs/38_history_marking_design.md 案A) so a saved analysis history
entry can be marked/unmarked as important for easier review later.

Mirrors tests/test_main_analysis_runs_delete_api.py's conventions
exactly, since this endpoint shares its authorization gate: never
touches a real database (main.repository_set_analysis_run_important is
monkeypatched), and mocks main.verify_supabase_jwt/
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


def _patch(important: bool = True, headers: dict[str, str] | None = None):
    return client.patch(
        f"/analysis-runs/{RUN_ID}/important",
        json={"isImportant": important},
        headers=headers or {},
    )


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
    # _resolve_history_access() always resolves accessible projects for
    # every JWT-mode request, regardless of which endpoint called it —
    # must be mocked here too, not just can_user_access_analysis_run.
    monkeypatch.setattr(main, "get_accessible_project_ids", lambda conn, uid: [])
    monkeypatch.setattr(
        main, "can_user_access_analysis_run", lambda conn, uid, run_id: can_access_run
    )


# --- disabled / unconfigured / unauthorized → same gate as DELETE ----------


def test_important_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = _patch(headers=_auth_headers())

    assert response.status_code == 503


def test_important_returns_403_when_token_header_missing(monkeypatch):
    _enable_read_env(monkeypatch)

    response = _patch()

    assert response.status_code == 403


def test_important_returns_403_when_token_header_mismatched(monkeypatch):
    _enable_read_env(monkeypatch)

    response = _patch(headers=_auth_headers("wrong-token"))

    assert response.status_code == 403


def test_important_token_value_never_appears_in_response_body(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: True,
    )

    response = _patch(headers=_auth_headers())

    assert TEST_TOKEN not in response.text


# --- HISTORY_READ_TOKEN mode: unrestricted, matches existing DELETE gate ---


def test_important_history_token_mode_marks_true(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: True,
    )

    response = _patch(important=True, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"analysisRunId": RUN_ID, "isImportant": True}


def test_important_history_token_mode_unmarks_false(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: True,
    )

    response = _patch(important=False, headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"analysisRunId": RUN_ID, "isImportant": False}


def test_important_history_token_mode_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: False,
    )

    response = _patch(headers=_auth_headers())

    assert response.status_code == 404


def test_important_history_token_mode_passes_through_the_requested_values(monkeypatch):
    _enable_read_env(monkeypatch)
    received = []

    def fake_set(run_id, *, is_important):
        received.append((run_id, is_important))
        return True

    monkeypatch.setattr(main, "repository_set_analysis_run_important", fake_set)

    _patch(important=True, headers=_auth_headers())

    assert received == [(RUN_ID, True)]


def test_important_returns_503_when_repository_raises(monkeypatch):
    _enable_read_env(monkeypatch)

    def raising_set(run_id, *, is_important):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "repository_set_analysis_run_important", raising_set)

    response = _patch(headers=_auth_headers())

    assert response.status_code == 503


# --- AUTH_JWT_ENABLED=true: access-checked by run id before updating ------


def test_important_jwt_mode_success_when_accessible(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: True,
    )

    response = _patch(important=True, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json() == {"analysisRunId": RUN_ID, "isImportant": True}


def test_important_jwt_mode_returns_403_when_run_inaccessible(monkeypatch):
    """False from can_user_access_analysis_run() must produce 403
    without ever calling repository_set_analysis_run_important() — a
    caller who can't see a run must not be able to mark it either."""
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=False)
    update_calls = []
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: update_calls.append(run_id),
    )

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 403
    assert update_calls == []


def test_important_jwt_mode_returns_404_when_accessible_but_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    _mock_jwt_dependencies(monkeypatch, can_access_run=True)
    monkeypatch.setattr(
        main,
        "repository_set_analysis_run_important",
        lambda run_id, *, is_important: False,
    )

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 404


def test_important_jwt_mode_returns_503_when_access_check_fails(monkeypatch):
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

    response = _patch(headers=_jwt_headers())

    assert response.status_code == 503
