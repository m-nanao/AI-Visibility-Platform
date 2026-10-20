"""Verifies the tags/categories endpoints added by
feature/history-tags-categories (see main.py's "Tags / categories"
section and services/analysis_history_repository.py's same-named
section). Never touches a real database — every repository function
is monkeypatched directly, same convention as
tests/test_main_analysis_runs_favorite_api.py.

Focus: this task's explicit "HISTORY_READ_TOKENだけでの変更は禁止" —
every *mutating* endpoint must require a valid JWT with no
HISTORY_READ_TOKEN fallback, plus project/run access; the *read*
endpoints (GET /tags, GET /categories) must keep working with either
credential, exactly like GET /analysis-runs.
"""

from fastapi.testclient import TestClient

import main
from main import HISTORY_READ_TOKEN_HEADER, app
from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    AnalysisRunStatusConflictError,
    CategoryNameConflictError,
    CategoryNameInvalidError,
    CategoryNotAssignableError,
    CategoryRequiresProjectError,
    TagNameConflictError,
    TagNameInvalidError,
    TagNotAssignableError,
)
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

TEST_TOKEN = "test-history-read-token"
RUN_ID = "11111111-1111-1111-1111-111111111111"
TAG_ID = "22222222-2222-2222-2222-222222222222"
CATEGORY_ID = "33333333-3333-3333-3333-333333333333"
PROJECT_ID = "44444444-4444-4444-4444-444444444444"


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


def _mock_jwt_auth(monkeypatch, *, user_id: str = "user-1"):
    """Makes JWT verification succeed for every endpoint that uses
    _resolve_tag_category_auth()/_resolve_project_write_access() —
    these are JWT-only, with no AUTH_JWT_ENABLED gate of their own
    (unlike _resolve_history_access()), so just mocking
    verify_supabase_jwt is enough; the JWT-configuration check
    (is_jwt_verification_configured) is handled by also setting a
    SUPABASE_JWKS_URL-shaped env below where needed, but we bypass it
    directly by monkeypatching is_jwt_verification_configured instead,
    mirroring the existing /favorite test file's approach for the
    plain JWT case.
    """
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())


# --- GET /tags / GET /categories: compatible with either credential -------


def test_list_tags_works_with_history_read_token(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "list_tags", lambda **kwargs: [])

    response = client.get("/tags", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"tags": []}


def test_list_tags_returns_503_when_read_history_disabled(monkeypatch):
    monkeypatch.delenv("READ_HISTORY_ENABLED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("HISTORY_READ_TOKEN", raising=False)

    response = client.get("/tags", headers=_auth_headers())

    assert response.status_code == 503


def test_list_categories_works_with_history_read_token(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "list_categories", lambda **kwargs: [])

    response = client.get("/categories", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json() == {"categories": []}


# --- POST /tags: JWT required, project access required -------------------


def test_create_tag_rejected_with_history_read_token_alone(monkeypatch):
    """The whole point of this task's auth requirement: a correct
    HISTORY_READ_TOKEN, with no Authorization header at all, must
    never be enough to create a tag."""
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(main, "create_tag", lambda **kwargs: {"id": TAG_ID, "projectId": PROJECT_ID, "name": "x"})

    response = client.post(
        "/tags",
        json={"projectId": PROJECT_ID, "name": "新規タグ"},
        headers=_auth_headers(),
    )

    assert response.status_code == 401


def test_create_tag_rejected_when_jwt_not_configured(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: False)

    response = client.post(
        "/tags", json={"projectId": PROJECT_ID, "name": "新規タグ"}, headers=_jwt_headers()
    )

    assert response.status_code == 503


def test_create_tag_rejected_when_project_inaccessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: False)
    create_calls = []
    monkeypatch.setattr(
        main, "create_tag", lambda **kwargs: create_calls.append(kwargs) or {}
    )

    response = client.post(
        "/tags", json={"projectId": PROJECT_ID, "name": "新規タグ"}, headers=_jwt_headers()
    )

    assert response.status_code == 403
    assert create_calls == []


def test_create_tag_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)
    monkeypatch.setattr(
        main,
        "create_tag",
        lambda **kwargs: {"id": TAG_ID, "projectId": kwargs["project_id"], "name": kwargs["name"]},
    )

    response = client.post(
        "/tags", json={"projectId": PROJECT_ID, "name": "新規タグ"}, headers=_jwt_headers()
    )

    assert response.status_code == 201
    assert response.json() == {"id": TAG_ID, "projectId": PROJECT_ID, "name": "新規タグ"}


def test_create_tag_requires_non_blank_project_id_and_name(monkeypatch):
    _enable_read_env(monkeypatch)

    missing_project = client.post("/tags", json={"projectId": "  ", "name": "x"}, headers=_jwt_headers())
    missing_name = client.post("/tags", json={"projectId": PROJECT_ID, "name": "   "}, headers=_jwt_headers())

    assert missing_project.status_code == 400
    assert missing_name.status_code == 400


def test_create_tag_returns_409_on_name_conflict(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raising_create(**kwargs):
        raise TagNameConflictError()

    monkeypatch.setattr(main, "create_tag", raising_create)

    response = client.post(
        "/tags", json={"projectId": PROJECT_ID, "name": "重複"}, headers=_jwt_headers()
    )

    assert response.status_code == 409


def test_create_tag_returns_400_on_name_invalid(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raising_create(**kwargs):
        raise TagNameInvalidError()

    monkeypatch.setattr(main, "create_tag", raising_create)

    response = client.post(
        "/tags", json={"projectId": PROJECT_ID, "name": "x" * 101}, headers=_jwt_headers()
    )

    assert response.status_code == 400


# --- PATCH/DELETE /tags/{id}: JWT + can_user_access_tag --------------------


def test_rename_tag_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.patch(f"/tags/{TAG_ID}", json={"name": "新しい名前"}, headers=_auth_headers())

    assert response.status_code == 401


def test_rename_tag_returns_404_when_tag_inaccessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_tag", lambda conn, uid, tid: False)

    response = client.patch(f"/tags/{TAG_ID}", json={"name": "新しい名前"}, headers=_jwt_headers())

    assert response.status_code == 404


def test_rename_tag_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_tag", lambda conn, uid, tid: True)
    monkeypatch.setattr(
        main,
        "rename_tag",
        lambda tag_id, *, name: {"id": tag_id, "projectId": PROJECT_ID, "name": name},
    )

    response = client.patch(f"/tags/{TAG_ID}", json={"name": "新しい名前"}, headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json()["name"] == "新しい名前"


def test_delete_tag_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.delete(f"/tags/{TAG_ID}", headers=_auth_headers())

    assert response.status_code == 401


def test_delete_tag_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_tag", lambda conn, uid, tid: True)
    monkeypatch.setattr(main, "delete_tag", lambda tag_id: True)

    response = client.delete(f"/tags/{TAG_ID}", headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": True}


def test_delete_tag_returns_404_when_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_tag", lambda conn, uid, tid: True)
    monkeypatch.setattr(main, "delete_tag", lambda tag_id: False)

    response = client.delete(f"/tags/{TAG_ID}", headers=_jwt_headers())

    assert response.status_code == 404


# --- POST /categories / PATCH / DELETE: mirrors tags above ----------------


def test_create_category_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.post(
        "/categories", json={"projectId": PROJECT_ID, "name": "製品A"}, headers=_auth_headers()
    )

    assert response.status_code == 401


def test_create_category_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)
    monkeypatch.setattr(
        main,
        "create_category",
        lambda **kwargs: {"id": CATEGORY_ID, "projectId": kwargs["project_id"], "name": kwargs["name"]},
    )

    response = client.post(
        "/categories", json={"projectId": PROJECT_ID, "name": "製品A"}, headers=_jwt_headers()
    )

    assert response.status_code == 201
    assert response.json() == {"id": CATEGORY_ID, "projectId": PROJECT_ID, "name": "製品A"}


def test_create_category_returns_409_on_name_conflict(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raising_create(**kwargs):
        raise CategoryNameConflictError()

    monkeypatch.setattr(main, "create_category", raising_create)

    response = client.post(
        "/categories", json={"projectId": PROJECT_ID, "name": "重複"}, headers=_jwt_headers()
    )

    assert response.status_code == 409


def test_create_category_returns_400_on_name_invalid(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raising_create(**kwargs):
        raise CategoryNameInvalidError()

    monkeypatch.setattr(main, "create_category", raising_create)

    response = client.post(
        "/categories", json={"projectId": PROJECT_ID, "name": "x" * 101}, headers=_jwt_headers()
    )

    assert response.status_code == 400


def test_rename_category_returns_404_when_inaccessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_category", lambda conn, uid, cid: False)

    response = client.patch(
        f"/categories/{CATEGORY_ID}", json={"name": "新しい名前"}, headers=_jwt_headers()
    )

    assert response.status_code == 404


def test_delete_category_success(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_category", lambda conn, uid, cid: True)
    monkeypatch.setattr(main, "delete_category", lambda category_id: True)

    response = client.delete(f"/categories/{CATEGORY_ID}", headers=_jwt_headers())

    assert response.status_code == 200
    assert response.json() == {"deleted": True}


# --- POST/DELETE /analysis-runs/{id}/tags, PUT .../category ---------------


def test_attach_tag_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_auth_headers()
    )

    assert response.status_code == 401


def test_attach_tag_returns_403_when_run_inaccessible(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: False)
    attach_calls = []
    monkeypatch.setattr(
        main, "attach_tag_to_analysis_run", lambda rid, tid: attach_calls.append((rid, tid)) or True
    )

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 403
    assert attach_calls == []


def test_attach_tag_success_returns_204(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(main, "attach_tag_to_analysis_run", lambda rid, tid: True)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 204


def test_attach_tag_returns_404_when_run_not_found(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(main, "attach_tag_to_analysis_run", lambda rid, tid: False)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 404


def test_attach_tag_returns_409_when_run_is_queued_or_running(monkeypatch):
    """This task's explicit backend-level (not just frontend) block on
    editing a queued/running run's tags."""
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_attach(rid, tid):
        raise AnalysisRunStatusConflictError("queued")

    monkeypatch.setattr(main, "attach_tag_to_analysis_run", raising_attach)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 409


def test_attach_tag_returns_404_when_tag_not_assignable(monkeypatch):
    """Tag doesn't exist, or belongs to a different project than the
    run — both collapse into 404."""
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_attach(rid, tid):
        raise TagNotAssignableError()

    monkeypatch.setattr(main, "attach_tag_to_analysis_run", raising_attach)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 404


def test_attach_tag_returns_503_on_repository_failure(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_attach(rid, tid):
        raise AnalysisHistoryReadError("boom")

    monkeypatch.setattr(main, "attach_tag_to_analysis_run", raising_attach)

    response = client.post(
        f"/analysis-runs/{RUN_ID}/tags", json={"tagId": TAG_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 503


def test_detach_tag_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.delete(f"/analysis-runs/{RUN_ID}/tags/{TAG_ID}", headers=_auth_headers())

    assert response.status_code == 401


def test_detach_tag_success_returns_204(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(main, "detach_tag_from_analysis_run", lambda rid, tid: True)

    response = client.delete(f"/analysis-runs/{RUN_ID}/tags/{TAG_ID}", headers=_jwt_headers())

    assert response.status_code == 204


def test_set_category_rejected_with_history_read_token_alone(monkeypatch):
    _enable_read_env(monkeypatch)
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": CATEGORY_ID}, headers=_auth_headers()
    )

    assert response.status_code == 401


def test_set_category_success_returns_204(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(main, "set_analysis_run_category", lambda rid, cid: True)

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": CATEGORY_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 204


def test_set_category_clear_with_null(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    received = []
    monkeypatch.setattr(
        main,
        "set_analysis_run_category",
        lambda rid, cid: received.append((rid, cid)) or True,
    )

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": None}, headers=_jwt_headers()
    )

    assert response.status_code == 204
    assert received == [(RUN_ID, None)]


def test_set_category_returns_404_when_category_not_assignable(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_set(rid, cid):
        raise CategoryNotAssignableError()

    monkeypatch.setattr(main, "set_analysis_run_category", raising_set)

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": CATEGORY_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 404


def test_set_category_returns_400_when_run_has_no_project(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_set(rid, cid):
        raise CategoryRequiresProjectError()

    monkeypatch.setattr(main, "set_analysis_run_category", raising_set)

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": CATEGORY_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 400


def test_set_category_returns_409_when_run_is_queued_or_running(monkeypatch):
    _enable_read_env(monkeypatch)
    _mock_jwt_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)

    def raising_set(rid, cid):
        raise AnalysisRunStatusConflictError("running")

    monkeypatch.setattr(main, "set_analysis_run_category", raising_set)

    response = client.put(
        f"/analysis-runs/{RUN_ID}/category", json={"categoryId": CATEGORY_ID}, headers=_jwt_headers()
    )

    assert response.status_code == 409
