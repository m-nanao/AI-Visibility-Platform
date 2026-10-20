"""Verifies POST /analyze's requestId-based idempotency for the
authenticated path (Task 6-B3, feature/sync-analyze-jwt-project-auth)
— main.py's _analyze_authenticated_idempotent(), on top of
create_running_analysis_run()/complete_analysis_job() (mocked here;
their own query logic is covered by
tests/test_sync_analysis_idempotency_repository.py, and real-DB
concurrency by tests/test_sync_analysis_idempotency_integration.py).

Never touches a real database and never calls a real external
provider (main.run_analysis_pipeline is monkeypatched in every test
that reaches past the reservation step).
"""

from fastapi.testclient import TestClient

import main
from main import app
from services.analysis_history_repository import (
    AnalysisHistoryReadError,
    AnalysisJobCancelledConflictError,
    AnalysisJobCreateConflictError,
    SyncAnalysisPreviouslyFailedError,
    SyncAnalysisRunReservation,
    SyncAnalysisStillRunningError,
)
from services.jwt_auth import AuthenticatedUser

client = TestClient(app)

RUN_ID = "11111111-1111-1111-1111-111111111111"


class _FakeHistoryDbConnection:
    def __enter__(self):
        return "fake-conn"

    def __exit__(self, exc_type, exc, tb):
        return False


def _mock_authenticated(monkeypatch, *, user_id: str = "user-1"):
    monkeypatch.setenv("ANALYZE_AUTH_REQUIRED", "true")
    monkeypatch.setattr(main, "is_jwt_verification_configured", lambda settings: True)
    monkeypatch.setattr(
        main, "verify_supabase_jwt", lambda token, settings: AuthenticatedUser(user_id=user_id)
    )
    monkeypatch.setattr(main, "open_history_db_connection", lambda: _FakeHistoryDbConnection())
    monkeypatch.setattr(main, "can_user_access_project", lambda conn, uid, project_id: True)


def _jwt_headers(token: str = "a.b.c") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post(body: dict):
    return client.post("/analyze", json=body, headers=_jwt_headers())


# --- requestId validation ------------------------------------------------


def test_missing_request_id_returns_400(monkeypatch):
    _mock_authenticated(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1"})

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_required"


def test_blank_request_id_returns_400(monkeypatch):
    """A whitespace-only requestId is technically "present" (non-empty
    before trimming), so this is classified as invalid rather than
    missing — either way it's a 400 the caller must fix."""
    _mock_authenticated(monkeypatch)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "   "})

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_invalid"


def test_overlong_request_id_returns_400(monkeypatch):
    _mock_authenticated(monkeypatch)

    response = _post(
        {"brandName": "サイボウズ", "projectId": "p1", "requestId": "a" * 201}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_invalid"


def test_request_id_with_disallowed_characters_returns_400(monkeypatch):
    _mock_authenticated(monkeypatch)

    response = _post(
        {"brandName": "サイボウズ", "projectId": "p1", "requestId": "has a space"}
    )

    assert response.status_code == 400
    assert response.json()["code"] == "request_id_invalid"


def test_uuid_shaped_request_id_is_accepted(monkeypatch):
    _mock_authenticated(monkeypatch)
    reservation_calls = []

    def fake_create_running(**kwargs):
        reservation_calls.append(kwargs)
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        ),
    )
    monkeypatch.setattr(main, "complete_analysis_job", lambda run_id, **kwargs: True)

    response = _post(
        {
            "brandName": "サイボウズ",
            "projectId": "p1",
            "requestId": "11111111-2222-3333-4444-555555555555",
        }
    )

    assert response.status_code == 200
    assert reservation_calls[0]["idempotency_key"] == "11111111-2222-3333-4444-555555555555"


# --- new reservation -> pipeline -> completion ---------------------------


def test_new_request_id_runs_pipeline_once_and_completes(monkeypatch):
    _mock_authenticated(monkeypatch)
    pipeline_calls = []
    complete_calls = []

    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        ),
    )

    def fake_pipeline(**kwargs):
        pipeline_calls.append(kwargs)
        return main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="real",
            source_summary={},
        )

    def fake_complete(run_id, **kwargs):
        complete_calls.append({"run_id": run_id, **kwargs})
        return True

    monkeypatch.setattr(main, "run_analysis_pipeline", fake_pipeline)
    monkeypatch.setattr(main, "complete_analysis_job", fake_complete)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["analysisRunId"] == RUN_ID
    assert len(pipeline_calls) == 1
    assert len(complete_calls) == 1
    assert complete_calls[0]["worker_id"] == "sync:tok"
    assert complete_calls[0]["status"] == "completed"


def test_unavailable_cooccurrence_completes_as_partial(monkeypatch):
    _mock_authenticated(monkeypatch)
    complete_calls = []

    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        ),
    )
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        ),
    )
    monkeypatch.setattr(
        main,
        "complete_analysis_job",
        lambda run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    assert complete_calls[0]["status"] == "partial"


def test_pipeline_input_error_marks_run_failed_and_returns_400(monkeypatch):
    _mock_authenticated(monkeypatch)
    complete_calls = []

    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        ),
    )

    def raising_pipeline(**kwargs):
        raise main.AnalysisPipelineInputError("urls must not be empty")

    monkeypatch.setattr(main, "run_analysis_pipeline", raising_pipeline)
    monkeypatch.setattr(
        main,
        "complete_analysis_job",
        lambda run_id, **kwargs: complete_calls.append(kwargs) or True,
    )

    response = _post(
        {"brandName": "サイボウズ", "urls": [], "projectId": "p1", "requestId": "req-1"}
    )

    assert response.status_code == 400
    assert complete_calls[0]["status"] == "failed"
    assert complete_calls[0]["worker_id"] == "sync:tok"


# --- replay (completed/partial) -----------------------------------------


def test_replay_of_completed_run_never_calls_pipeline(monkeypatch):
    _mock_authenticated(monkeypatch)
    pipeline_calls = []

    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID,
            created=False,
            status="completed",
            locked_by=None,
            result_json=main.build_dummy_analysis("サイボウズ").model_dump(),
            meta_json=None,
        ),
    )
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    assert response.json()["analysisRunId"] == RUN_ID
    assert pipeline_calls == []


def test_replay_of_partial_run_never_calls_pipeline(monkeypatch):
    _mock_authenticated(monkeypatch)
    pipeline_calls = []

    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID,
            created=False,
            status="partial",
            locked_by=None,
            result_json=main.build_dummy_analysis("サイボウズ").model_dump(),
            meta_json=None,
        ),
    )
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 200
    assert pipeline_calls == []


# --- running / failed / conflict / cancelled -> 409 ----------------------


def test_still_running_returns_409_without_calling_pipeline(monkeypatch):
    _mock_authenticated(monkeypatch)
    pipeline_calls = []

    def raising_create(**kwargs):
        raise SyncAnalysisStillRunningError(RUN_ID)

    monkeypatch.setattr(main, "create_running_analysis_run", raising_create)
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 409
    assert response.json()["code"] == "analysis_still_running"
    assert pipeline_calls == []


def test_previously_failed_returns_409_without_retrying(monkeypatch):
    _mock_authenticated(monkeypatch)
    pipeline_calls = []

    def raising_create(**kwargs):
        raise SyncAnalysisPreviouslyFailedError(RUN_ID)

    monkeypatch.setattr(main, "create_running_analysis_run", raising_create)
    monkeypatch.setattr(
        main, "run_analysis_pipeline", lambda **kwargs: pipeline_calls.append(kwargs)
    )

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 409
    assert response.json()["code"] == "analysis_previously_failed"
    assert pipeline_calls == []


def test_different_input_same_request_id_returns_409(monkeypatch):
    _mock_authenticated(monkeypatch)

    def raising_create(**kwargs):
        raise AnalysisJobCreateConflictError(RUN_ID)

    monkeypatch.setattr(main, "create_running_analysis_run", raising_create)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 409
    assert response.json()["code"] == "analysis_request_conflict"


def test_cancelled_request_id_returns_409(monkeypatch):
    _mock_authenticated(monkeypatch)

    def raising_create(**kwargs):
        raise AnalysisJobCancelledConflictError(RUN_ID)

    monkeypatch.setattr(main, "create_running_analysis_run", raising_create)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 409
    assert response.json()["code"] == "analysis_request_cancelled"


def test_reservation_db_failure_returns_503(monkeypatch):
    _mock_authenticated(monkeypatch)

    def raising_create(**kwargs):
        raise AnalysisHistoryReadError("db unreachable")

    monkeypatch.setattr(main, "create_running_analysis_run", raising_create)

    response = _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert response.status_code == 503


# --- separation from different users/projects (end-to-end through the
# endpoint, not just the repository layer) --------------------------------


def test_different_users_pass_distinct_created_by_user_id_to_reservation(monkeypatch):
    reservation_calls = []

    def fake_create_running(**kwargs):
        reservation_calls.append(kwargs)
        return SyncAnalysisRunReservation(
            analysis_run_id=RUN_ID, created=True, status="running", locked_by="sync:tok"
        )

    monkeypatch.setattr(main, "create_running_analysis_run", fake_create_running)
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        ),
    )
    monkeypatch.setattr(main, "complete_analysis_job", lambda run_id, **kwargs: True)

    _mock_authenticated(monkeypatch, user_id="user-a")
    _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    _mock_authenticated(monkeypatch, user_id="user-b")
    _post({"brandName": "サイボウズ", "projectId": "p1", "requestId": "req-1"})

    assert reservation_calls[0]["created_by_user_id"] == "user-a"
    assert reservation_calls[1]["created_by_user_id"] == "user-b"


# --- flag OFF (anonymous) never touches any of this ----------------------


def test_anonymous_mode_never_calls_create_running_analysis_run(monkeypatch):
    monkeypatch.delenv("ANALYZE_AUTH_REQUIRED", raising=False)
    reservation_calls = []
    monkeypatch.setattr(
        main,
        "create_running_analysis_run",
        lambda **kwargs: reservation_calls.append(kwargs),
    )
    monkeypatch.setattr(
        main,
        "run_analysis_pipeline",
        lambda **kwargs: main.AnalysisPipelineOutcome(
            result=main.build_dummy_analysis(kwargs["brand_name"]),
            cooccurrence_status="unavailable",
            source_summary={},
        ),
    )
    monkeypatch.setattr(main, "save_analysis_history", lambda **kwargs: None)

    # Even with a requestId sent, the anonymous path must never touch
    # create_running_analysis_run() at all.
    response = client.post(
        "/analyze", json={"brandName": "サイボウズ", "requestId": "req-1"}
    )

    assert response.status_code == 200
    assert reservation_calls == []
