"""Verifies services.analysis_history_repository's Phase 2 worker
functions (claim_next_queued_analysis_run() / complete_analysis_job() /
fail_expired_running_analysis_runs()) without ever touching a real
database — a dedicated, purpose-built fake DB (separate from
tests/test_analysis_jobs_repository.py's Phase 1 fake, which doesn't
model locked_by/locked_at/lease_expires_at/attempt_count at all).

IMPORTANT (same caveat as every other mocked-DB test file in this
backend): a fake cursor executes everything sequentially in a single
Python thread, so it can assert on *what SQL would run* but cannot by
itself prove the real `for update skip locked` claim query is safe
against two genuinely concurrent PostgreSQL connections, or that the
conditional UPDATE in complete_analysis_job() truly prevents a stale
worker from overwriting a newer state under a real race. Those
guarantees come only from
tests/test_analysis_jobs_repository_integration.py (real PostgreSQL;
see that file for whether it ran in this environment).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services import analysis_history_repository as repo


class _FakeJsonb:
    def __init__(self, value):
        self.value = value


class _WorkerFakeDB:
    def __init__(self):
        self.runs: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self._insertion_order: list[str] = []

    def add_queued_run(
        self, *, input_snapshot=None, created_at=None, project_id=None, created_by_user_id=None
    ) -> str:
        run_id = str(uuid.uuid4())
        self.runs[run_id] = {
            "status": "queued",
            "input_snapshot": input_snapshot or {"brandName": "Acme"},
            "locked_by": None,
            "locked_at": None,
            "lease_expires_at": None,
            "attempt_count": 0,
            "completed_at": None,
            "error_message": None,
            "created_at": created_at or datetime.now(timezone.utc),
            "project_id": project_id or str(uuid.uuid4()),
            "created_by_user_id": created_by_user_id or str(uuid.uuid4()),
        }
        self.results[run_id] = {"result_json": {}, "meta_json": None}
        self._insertion_order.append(run_id)
        return run_id

    def add_running_run(self, *, worker_id: str, lease_expires_at) -> str:
        run_id = str(uuid.uuid4())
        self.runs[run_id] = {
            "status": "running",
            "input_snapshot": {"brandName": "Acme"},
            "locked_by": worker_id,
            "locked_at": datetime.now(timezone.utc),
            "lease_expires_at": lease_expires_at,
            "attempt_count": 1,
            "completed_at": None,
            "error_message": None,
            "created_at": datetime.now(timezone.utc),
        }
        self.results[run_id] = {"result_json": {}, "meta_json": None}
        self._insertion_order.append(run_id)
        return run_id

    def oldest_queued(self) -> str | None:
        for run_id in self._insertion_order:
            if self.runs[run_id]["status"] == "queued":
                return run_id
        return None


class _FakeCursor:
    def __init__(self, db: _WorkerFakeDB):
        self.db = db
        self._pending_one = None
        self._pending_all: list[tuple] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        q = " ".join(query.strip().lower().split())
        params = params or ()

        if q.startswith("update analysis_runs set status = 'running'"):
            worker_id, lease_seconds = params
            run_id = self.db.oldest_queued()
            if run_id is None:
                self._pending_one = None
                return
            run = self.db.runs[run_id]
            run["status"] = "running"
            run["locked_by"] = worker_id
            run["locked_at"] = datetime.now(timezone.utc)
            run["lease_expires_at"] = datetime.now(timezone.utc) + timedelta(
                seconds=lease_seconds
            )
            run["attempt_count"] += 1
            self._pending_one = (
                run_id,
                run["input_snapshot"],
                run["attempt_count"],
                run.get("project_id"),
                run.get("created_by_user_id"),
            )
            return

        if q.startswith("update analysis_runs set status = %s"):
            status, error_message, analysis_run_id, worker_id = params
            run = self.db.runs.get(analysis_run_id)
            now = datetime.now(timezone.utc)
            if (
                run is not None
                and run["status"] == "running"
                and run["locked_by"] == worker_id
                and run["lease_expires_at"] is not None
                and run["lease_expires_at"] > now
            ):
                run["status"] = status
                run["completed_at"] = now
                run["error_message"] = error_message
                self._pending_one = (analysis_run_id,)
            else:
                self._pending_one = None
            return

        if q.startswith("update analysis_runs set lease_expires_at = "):
            lease_seconds, analysis_run_id, worker_id = params
            run = self.db.runs.get(analysis_run_id)
            now = datetime.now(timezone.utc)
            if (
                run is not None
                and run["status"] == "running"
                and run["locked_by"] == worker_id
                and run["lease_expires_at"] is not None
                and run["lease_expires_at"] > now
            ):
                run["lease_expires_at"] = now + timedelta(seconds=lease_seconds)
                self._pending_one = (analysis_run_id,)
            else:
                self._pending_one = None
            return

        if q.startswith("update analysis_results set result_json = %s, meta_json = %s"):
            result_json, meta_json, analysis_run_id = params
            self.db.results[analysis_run_id] = {
                "result_json": result_json.value,
                "meta_json": meta_json.value if meta_json is not None else None,
            }
            self._pending_one = None
            return

        if q.startswith("update analysis_runs set status = 'failed'"):
            now = datetime.now(timezone.utc)
            expired = []
            for run_id, run in self.db.runs.items():
                if (
                    run["status"] == "running"
                    and run["lease_expires_at"] is not None
                    and run["lease_expires_at"] < now
                ):
                    run["status"] = "failed"
                    run["completed_at"] = now
                    run["error_message"] = (
                        "worker lease expired (possible partial execution, not auto-retried)"
                    )
                    expired.append(run_id)
            self._pending_all = [(rid,) for rid in expired]
            return

        raise AssertionError(f"unexpected query in test fake: {query!r}")

    def fetchone(self):
        return self._pending_one

    def fetchall(self):
        return self._pending_all


class _FakeConnection:
    def __init__(self, db: _WorkerFakeDB):
        self.db = db
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return _FakeCursor(self.db)

    def commit(self):
        self.committed = True


class _FakePsycopg:
    def __init__(self, db: _WorkerFakeDB):
        self.db = db

    def connect(self, database_url, connect_timeout=None):
        return _FakeConnection(self.db)


@pytest.fixture
def worker_db(monkeypatch):
    db = _WorkerFakeDB()
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(db))
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)
    monkeypatch.setattr(
        repo,
        "load_db_settings",
        lambda: type("S", (), {"database_url": "postgresql://user:pass@host/db"})(),
    )
    return db


def _maybe_jsonb(value):
    return None if value is None else _FakeJsonb(value)


# --- claim_next_queued_analysis_run() ---------------------------------------


def test_claim_returns_none_when_nothing_queued(worker_db):
    assert repo.claim_next_queued_analysis_run(worker_id="w1", lease_seconds=180) is None


def test_claim_returns_oldest_queued_job_and_sets_lease(worker_db):
    run_id = worker_db.add_queued_run(input_snapshot={"brandName": "Acme"})

    claimed = repo.claim_next_queued_analysis_run(worker_id="w1", lease_seconds=180)

    assert claimed.analysis_run_id == run_id
    assert claimed.input_snapshot == {"brandName": "Acme"}
    assert claimed.attempt_count == 1
    run = worker_db.runs[run_id]
    assert run["status"] == "running"
    assert run["locked_by"] == "w1"
    assert run["lease_expires_at"] > datetime.now(timezone.utc)


def test_claim_picks_oldest_queued_job_first(worker_db):
    first = worker_db.add_queued_run()
    worker_db.add_queued_run()

    claimed = repo.claim_next_queued_analysis_run(worker_id="w1", lease_seconds=180)

    assert claimed.analysis_run_id == first


def test_claim_does_not_reclaim_an_already_running_job(worker_db):
    worker_db.add_running_run(
        worker_id="w0", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=180)
    )

    assert repo.claim_next_queued_analysis_run(worker_id="w1", lease_seconds=180) is None


def test_claim_increments_attempt_count_across_separate_queued_runs(worker_db):
    run_id = worker_db.add_queued_run()
    repo.claim_next_queued_analysis_run(worker_id="w1", lease_seconds=180)
    assert worker_db.runs[run_id]["attempt_count"] == 1


# --- complete_analysis_job() -------------------------------------------------


def test_complete_marks_completed_and_saves_result(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
    )

    ok = repo.complete_analysis_job(
        run_id,
        worker_id="w1",
        status="completed",
        result_json={"brandName": "Acme"},
        meta_json={"sections": {}},
        error_message=None,
    )

    assert ok is True
    assert worker_db.runs[run_id]["status"] == "completed"
    assert worker_db.runs[run_id]["completed_at"] is not None
    assert worker_db.results[run_id]["result_json"] == {"brandName": "Acme"}
    assert worker_db.results[run_id]["meta_json"] == {"sections": {}}


def test_complete_marks_failed_without_touching_placeholder_result(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
    )

    ok = repo.complete_analysis_job(
        run_id,
        worker_id="w1",
        status="failed",
        result_json=None,
        meta_json=None,
        error_message="unexpected error while running analysis",
    )

    assert ok is True
    assert worker_db.runs[run_id]["status"] == "failed"
    assert worker_db.runs[run_id]["error_message"] == "unexpected error while running analysis"
    # The placeholder result_json='{}' is left exactly as it was —
    # complete_analysis_job() never writes analysis_results when
    # result_json is None (see docs/40 "6.1"/"13.2").
    assert worker_db.results[run_id]["result_json"] == {}


def test_complete_rejects_wrong_worker_id(worker_db):
    """A stale worker (whose lease already expired and was reaped to
    'failed' by someone else, or who simply never owned this row)
    must not be able to overwrite the row — see docs/40 "11.5"."""
    run_id = worker_db.add_running_run(
        worker_id="the-real-owner", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
    )

    ok = repo.complete_analysis_job(
        run_id,
        worker_id="an-impostor",
        status="completed",
        result_json={"brandName": "should not be saved"},
        meta_json=None,
        error_message=None,
    )

    assert ok is False
    assert worker_db.runs[run_id]["status"] == "running"  # untouched
    assert worker_db.results[run_id]["result_json"] == {}  # untouched


def test_complete_rejects_job_that_already_left_running_state(worker_db):
    """If fail_expired_running_analysis_runs() (or anything else) has
    already moved the row out of 'running', a late completion write
    for the same worker_id must still be rejected — the condition is
    `status = 'running'`, not just `locked_by = worker_id`."""
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    repo.fail_expired_running_analysis_runs()
    assert worker_db.runs[run_id]["status"] == "failed"

    ok = repo.complete_analysis_job(
        run_id,
        worker_id="w1",
        status="completed",
        result_json={"brandName": "too late"},
        meta_json=None,
        error_message=None,
    )

    assert ok is False
    assert worker_db.runs[run_id]["status"] == "failed"  # still failed, not overwritten
    assert worker_db.results[run_id]["result_json"] == {}


def test_complete_does_not_save_result_when_update_matches_no_row(worker_db):
    """The analysis_results write must only happen when the
    analysis_runs update actually matched — never unconditionally."""
    run_id = worker_db.add_running_run(
        worker_id="real-owner", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
    )

    repo.complete_analysis_job(
        run_id,
        worker_id="impostor",
        status="completed",
        result_json={"should": "never appear"},
        meta_json=None,
        error_message=None,
    )

    assert worker_db.results[run_id]["result_json"] == {}


def test_complete_rejects_when_lease_already_expired_even_with_correct_owner(worker_db):
    """Problem 1 fix: locked_by + status='running' alone is not
    enough — a lease that has *already* expired but hasn't been swept
    to 'failed' yet by fail_expired_running_analysis_runs() (which
    runs on its own schedule, not synchronously with every write)
    must still reject a completion write from the very worker that
    owned it."""
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    ok = repo.complete_analysis_job(
        run_id,
        worker_id="w1",
        status="completed",
        result_json={"should": "never appear — lease already expired"},
        meta_json=None,
        error_message=None,
    )

    assert ok is False
    assert worker_db.runs[run_id]["status"] == "running"  # untouched — sweeper hasn't run yet
    assert worker_db.results[run_id]["result_json"] == {}


# --- extend_analysis_job_lease() (heartbeat) ---------------------------------


def test_extend_succeeds_for_valid_lease(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30)
    )

    extended = repo.extend_analysis_job_lease(run_id, worker_id="w1", lease_seconds=180)

    assert extended is True
    assert worker_db.runs[run_id]["lease_expires_at"] > datetime.now(timezone.utc) + timedelta(
        seconds=170
    )


def test_extend_rejects_wrong_worker_id(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="the-real-owner", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    original_lease = worker_db.runs[run_id]["lease_expires_at"]

    extended = repo.extend_analysis_job_lease(run_id, worker_id="an-impostor", lease_seconds=180)

    assert extended is False
    assert worker_db.runs[run_id]["lease_expires_at"] == original_lease  # untouched


def test_extend_does_not_revive_an_already_expired_lease(worker_db):
    """Explicit regression guard: a heartbeat must never resurrect a
    lease that has already passed, even if the owning worker_id still
    matches and the row is still technically 'running' (sweeper
    hasn't gotten to it yet) — see docs/40 "11.4"'s "no automatic
    revival" rule, which applies to the heartbeat exactly as much as
    it applies to fail_expired_running_analysis_runs() itself."""
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    original_lease = worker_db.runs[run_id]["lease_expires_at"]

    extended = repo.extend_analysis_job_lease(run_id, worker_id="w1", lease_seconds=180)

    assert extended is False
    assert worker_db.runs[run_id]["lease_expires_at"] == original_lease


def test_extend_rejects_job_that_already_left_running_state(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    repo.fail_expired_running_analysis_runs()
    assert worker_db.runs[run_id]["status"] == "failed"

    extended = repo.extend_analysis_job_lease(run_id, worker_id="w1", lease_seconds=180)

    assert extended is False


def test_extend_does_not_affect_other_jobs_leases(worker_db):
    """A heartbeat for one job must never touch any other job's
    lease, including another job owned by the *same* worker_id."""
    run_a = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    run_b = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30)
    )
    original_b_lease = worker_db.runs[run_b]["lease_expires_at"]

    repo.extend_analysis_job_lease(run_a, worker_id="w1", lease_seconds=180)

    assert worker_db.runs[run_b]["lease_expires_at"] == original_b_lease


# --- fail_expired_running_analysis_runs() ------------------------------------


def test_fail_expired_returns_empty_list_when_nothing_expired(worker_db):
    worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60)
    )

    assert repo.fail_expired_running_analysis_runs() == []


def test_fail_expired_transitions_expired_running_job_to_failed(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    expired_ids = repo.fail_expired_running_analysis_runs()

    assert expired_ids == [run_id]
    run = worker_db.runs[run_id]
    assert run["status"] == "failed"
    assert "worker lease expired" in run["error_message"]


def test_fail_expired_never_sets_status_back_to_queued(worker_db):
    """Explicit regression guard for docs/40 "11.4"'s core rule: an
    expired lease is always a terminal failure, never requeued for
    automatic re-execution."""
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
    )

    repo.fail_expired_running_analysis_runs()

    assert worker_db.runs[run_id]["status"] != "queued"
    assert worker_db.runs[run_id]["status"] == "failed"


def test_fail_expired_does_not_touch_queued_jobs(worker_db):
    queued_id = worker_db.add_queued_run()

    repo.fail_expired_running_analysis_runs()

    assert worker_db.runs[queued_id]["status"] == "queued"


def test_fail_expired_does_not_touch_jobs_with_remaining_lease(worker_db):
    run_id = worker_db.add_running_run(
        worker_id="w1", lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=120)
    )

    repo.fail_expired_running_analysis_runs()

    assert worker_db.runs[run_id]["status"] == "running"
