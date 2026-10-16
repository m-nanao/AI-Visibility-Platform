"""Verifies POST /analysis-jobs, GET /analysis-jobs/{id}, and GET
/analysis-jobs/{id}/result (see main.py,
docs/40_async_analysis_jobs_design.md) — Phase 1 only, no worker.

These tests never touch a real database — main's own imported names
(main.create_queued_analysis_run / main.get_analysis_job_status /
main.get_analysis_job_result / main.can_user_access_project /
main.can_user_access_analysis_run / main.verify_supabase_jwt /
main.open_history_db_connection) are monkeypatched directly, mirroring
the existing tests/test_main_analysis_history_read_api.py pattern.
create_queued_analysis_run()'s own query logic (idempotency lookup,
limit checks, advisory lock) is covered by
tests/test_analysis_jobs_repository.py; this file's job is to verify
main.py's auth wiring, feature-flag gate, input validation, and
status-code mapping — and that no AI-provider function is ever called
on this path (see test_create_job_never_calls_any_ai_provider below).

IMPORTANT: these tests cannot prove that two truly concurrent requests
never create duplicate jobs — a FastAPI TestClient call is synchronous
and single-threaded, so "sending two requests" in a test is really
"sending one request, then another, strictly in sequence." The actual
concurrency guarantee (the advisory lock + unique index) can only be
verified against a real PostgreSQL instance — see
tests/test_analysis_jobs_repository_integration.py, which documents
why it's skipped in this environment.
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import (
    AnalysisJobCreateConflictError,
    AnalysisJobCreateResult,
    AnalysisJobLimitExceededError,
)
from services.jwt_auth import AuthenticatedUser, JWTAuthError

client = TestClient(app)


def _clear_jobs_env(monkeypatch):
    monkeypatch.delenv("ANALYSIS_JOBS_ENABLED", raising=False)
    monkeypatch.delenv("AUTH_JWT_ENABLED", raising=False)
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)
    monkeypatch.delenv("ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT", raising=False)
    monkeypatch.delenv("ANALYSIS_JOBS_MAX_QUEUED_PER_USER", raising=False)


def _enable_jobs_env(monkeypatch):
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://example.test/jwks.json")


class _FakeJobsDbConnection:
    """Stand-in for main.open_history_db_connection()'s return value —
    only used as a `with ... as conn:` context manager; `conn` itself
    is never inspected since can_user_access_project()/
    can_user_access_analysis_run() are mocked too."""

    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_auth(monkeypatch, *, user_id: str = "user-1"):
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeJobsDbConnection())


def _auth_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


VALID_CREATE_BODY = {
    "projectId": "project-1",
    "idempotencyKey": "key-1",
    "brandName": "Acme",
    "urls": ["https://example.com"],
}


def _never_call(*args, **kwargs):
    raise AssertionError("this AI provider function must not be called in Phase 1")


# --- feature flag -----------------------------------------------------------


def test_create_job_returns_404_when_flag_unset(monkeypatch):
    _clear_jobs_env(monkeypatch)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 404


def test_create_job_returns_404_when_flag_explicitly_false(monkeypatch):
    _clear_jobs_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "false")

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 404


def test_get_job_status_returns_404_when_flag_unset(monkeypatch):
    _clear_jobs_env(monkeypatch)

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 404


# --- authentication ----------------------------------------------------------


def test_create_job_returns_401_without_authorization_header(monkeypatch):
    _enable_jobs_env(monkeypatch)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY)

    assert response.status_code == 401


def test_create_job_returns_401_for_invalid_jwt(monkeypatch):
    _enable_jobs_env(monkeypatch)

    def raise_invalid(token, settings):
        raise JWTAuthError("invalid_signature", "bad signature")

    monkeypatch.setattr(main, "verify_supabase_jwt", raise_invalid)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 401


def test_create_job_returns_503_when_jwt_verification_not_configured(monkeypatch):
    _clear_jobs_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "true")
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    monkeypatch.delenv("SUPABASE_JWKS_URL", raising=False)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 503


def test_create_job_never_falls_back_to_history_read_token(monkeypatch):
    """A caller cannot substitute X-History-Read-Token for a JWT on
    this endpoint — see docs/40_async_analysis_jobs_design.md "8.1"."""
    _enable_jobs_env(monkeypatch)

    response = client.post(
        "/analysis-jobs",
        json=VALID_CREATE_BODY,
        headers={"X-History-Read-Token": "whatever"},
    )

    assert response.status_code == 401


# --- project membership -------------------------------------------------------


def test_create_job_returns_403_when_user_not_project_member(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: False)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 403


# --- input validation ---------------------------------------------------------


def test_create_job_requires_project_id(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)

    body = dict(VALID_CREATE_BODY)
    body["projectId"] = ""

    response = client.post("/analysis-jobs", json=body, headers=_auth_headers())

    assert response.status_code == 400


def test_create_job_requires_idempotency_key(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)

    body = dict(VALID_CREATE_BODY)
    body["idempotencyKey"] = ""

    response = client.post("/analysis-jobs", json=body, headers=_auth_headers())

    assert response.status_code == 400


def test_create_job_requires_brand_name(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)

    body = dict(VALID_CREATE_BODY)
    body["brandName"] = "  "

    response = client.post("/analysis-jobs", json=body, headers=_auth_headers())

    assert response.status_code == 400


def test_create_job_rejects_empty_urls_list(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)

    body = dict(VALID_CREATE_BODY)
    body["urls"] = []

    response = client.post("/analysis-jobs", json=body, headers=_auth_headers())

    assert response.status_code == 400


# --- successful creation + idempotency + limits -------------------------------


def test_create_job_returns_202_and_queued_status(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)
    monkeypatch.setattr(
        main,
        "create_queued_analysis_run",
        lambda **kwargs: AnalysisJobCreateResult(
            analysis_run_id="11111111-1111-1111-1111-111111111111",
            status="queued",
            created=True,
        ),
    )

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 202
    assert response.json() == {
        "analysisRunId": "11111111-1111-1111-1111-111111111111",
        "status": "queued",
    }


def test_create_job_idempotent_replay_returns_same_job_without_error(monkeypatch):
    """Mirrors create_queued_analysis_run()'s created=False contract —
    main.py must still respond 202 with the existing job, not treat a
    replay as a new acceptance or an error. True concurrent-request
    safety is a repository/DB-level guarantee (see module docstring),
    not something this API-level test can demonstrate."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)
    monkeypatch.setattr(
        main,
        "create_queued_analysis_run",
        lambda **kwargs: AnalysisJobCreateResult(
            analysis_run_id="11111111-1111-1111-1111-111111111111",
            status="queued",
            created=False,
        ),
    )

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 202
    assert response.json()["analysisRunId"] == "11111111-1111-1111-1111-111111111111"


def test_create_job_returns_409_on_idempotency_conflict(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raise_conflict(**kwargs):
        raise AnalysisJobCreateConflictError("existing-id")

    monkeypatch.setattr(main, "create_queued_analysis_run", raise_conflict)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 409


def test_create_job_returns_429_on_limit_exceeded(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)

    def raise_limit(**kwargs):
        raise AnalysisJobLimitExceededError("project", 5)

    monkeypatch.setattr(main, "create_queued_analysis_run", raise_limit)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 429


# --- GET /analysis-jobs/{id} --------------------------------------------------


def test_get_job_status_returns_403_for_inaccessible_job(monkeypatch):
    """Covers both "belongs to a different project" and "does not
    exist" — can_user_access_analysis_run() returns False for either,
    and main.py deliberately does not distinguish them (same
    existence-leak avoidance as the existing GET /analysis-runs/{id})."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: False)

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 403


def test_get_job_status_returns_404_for_soft_deleted_job(monkeypatch):
    """A soft-deleted job the caller *does* belong to the project of
    (can_user_access_analysis_run has no deleted_at filter) still
    404s, because get_analysis_job_status() itself filters
    deleted_at is null."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(main, "get_analysis_job_status", lambda rid: None)

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 404


def test_get_job_status_returns_queued_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "get_analysis_job_status",
        lambda rid: {
            "id": rid,
            "status": "queued",
            "startedAt": "2026-01-01T00:00:00+00:00",
            "completedAt": None,
            "errorMessage": None,
        },
    )

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert "result" not in response.json()


# --- GET /analysis-jobs/{id}/result ------------------------------------------


def test_get_job_result_returns_409_for_queued_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "get_analysis_job_result",
        lambda rid: {
            "id": rid,
            "status": "queued",
            "errorMessage": None,
            "result": None,
            "meta": None,
        },
    )

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111/result", headers=_auth_headers()
    )

    assert response.status_code == 409
    assert response.json()["status"] == "queued"


def test_get_job_result_never_returns_placeholder_as_real_result(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "get_analysis_job_result",
        lambda rid: {
            "id": rid,
            "status": "running",
            "errorMessage": None,
            "result": None,
            "meta": None,
        },
    )

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111/result", headers=_auth_headers()
    )

    assert response.status_code == 409


def test_get_job_result_returns_result_for_completed_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "get_analysis_job_result",
        lambda rid: {
            "id": rid,
            "status": "completed",
            "errorMessage": None,
            "result": {"brandName": "Acme"},
            "meta": {"sections": {}},
        },
    )

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111/result", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert response.json()["result"] == {"brandName": "Acme"}


def test_get_job_result_returns_200_with_error_for_failed_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "get_analysis_job_result",
        lambda rid: {
            "id": rid,
            "status": "failed",
            "errorMessage": "worker lease expired",
            "result": None,
            "meta": None,
        },
    )

    response = client.get(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111/result", headers=_auth_headers()
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["result"] is None
    assert body["errorMessage"] == "worker lease expired"


# --- no AI provider calls on this path ----------------------------------------


def test_create_job_never_calls_any_ai_provider(monkeypatch):
    """Phase 1 must never execute any analysis — asserts that every
    AI-provider entry point this backend has is never invoked while
    creating a job (see docs/40_async_analysis_jobs_design.md "4")."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, pid: True)
    monkeypatch.setattr(
        main,
        "create_queued_analysis_run",
        lambda **kwargs: AnalysisJobCreateResult(
            analysis_run_id="11111111-1111-1111-1111-111111111111",
            status="queued",
            created=True,
        ),
    )
    monkeypatch.setattr(main, "build_chatgpt_observation", _never_call)
    monkeypatch.setattr(main, "build_claude_observation", _never_call)
    monkeypatch.setattr(main, "build_gemini_observation", _never_call)
    monkeypatch.setattr(main, "build_ai_overview_comparison", _never_call)
    monkeypatch.setattr(main, "search_common_crawl_domain", _never_call)
    monkeypatch.setattr(main, "fetch_url_texts", _never_call)

    response = client.post("/analysis-jobs", json=VALID_CREATE_BODY, headers=_auth_headers())

    assert response.status_code == 202


# --- DELETE /analysis-jobs/{id} (cancel a queued job) -------------------------
#
# cancel_queued_analysis_run()'s own DB-level atomicity/race-safety is
# covered by tests/test_analysis_jobs_repository_integration.py; this
# file's job is to verify main.py's auth wiring and status-code mapping,
# mirroring the GET /analysis-jobs/{id} tests above exactly.

from services.analysis_history_repository import CancelQueuedAnalysisJobResult


def test_cancel_job_returns_404_when_flag_unset(monkeypatch):
    _clear_jobs_env(monkeypatch)

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 404


def test_cancel_job_returns_401_without_a_token(monkeypatch):
    _enable_jobs_env(monkeypatch)

    response = client.delete("/analysis-jobs/11111111-1111-1111-1111-111111111111")

    assert response.status_code == 401


def test_cancel_job_returns_403_for_inaccessible_job(monkeypatch):
    """Covers both "belongs to a different project" and "does not
    exist" — same existence-leak avoidance as GET /analysis-jobs/{id}."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: False)

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 403


def test_cancel_job_rejects_other_project_without_touching_it(monkeypatch):
    """A caller who is not a member of the job's project must never
    reach cancel_queued_analysis_run() at all."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: False)
    monkeypatch.setattr(main, "cancel_queued_analysis_run", _never_call)

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 403


def test_cancel_job_returns_200_when_cancelled(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "cancel_queued_analysis_run",
        lambda rid: CancelQueuedAnalysisJobResult(outcome="cancelled"),
    )

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}


def test_cancel_job_is_idempotent_for_an_already_cancelled_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "cancel_queued_analysis_run",
        lambda rid: CancelQueuedAnalysisJobResult(outcome="already_cancelled"),
    )

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 200
    assert response.json() == {"cancelled": True}


def test_cancel_job_returns_409_for_a_running_job_without_claiming_to_stop_it(monkeypatch):
    """The explicit requirement: a running job is never reported as
    successfully cancelled."""
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "cancel_queued_analysis_run",
        lambda rid: CancelQueuedAnalysisJobResult(outcome="not_cancellable", status="running"),
    )

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 409
    assert response.json()["status"] == "running"


def test_cancel_job_returns_409_for_a_completed_job(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "cancel_queued_analysis_run",
        lambda rid: CancelQueuedAnalysisJobResult(outcome="not_cancellable", status="completed"),
    )

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 409
    assert response.json()["status"] == "completed"


def test_cancel_job_returns_404_when_repository_reports_not_found(monkeypatch):
    _enable_jobs_env(monkeypatch)
    _mock_auth(monkeypatch)
    monkeypatch.setattr(main, "can_user_access_analysis_run", lambda conn, uid, rid: True)
    monkeypatch.setattr(
        main,
        "cancel_queued_analysis_run",
        lambda rid: CancelQueuedAnalysisJobResult(outcome="not_found"),
    )

    response = client.delete(
        "/analysis-jobs/11111111-1111-1111-1111-111111111111", headers=_auth_headers()
    )

    assert response.status_code == 404
