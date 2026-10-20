"""Verifies services.analysis_history_repository.create_running_analysis_run()
(Task 6-B3, feature/sync-analyze-jwt-project-auth) without ever
touching a real database — mirrors tests/test_analysis_jobs_repository.py's
in-memory fake DB pattern (psycopg/Jsonb monkeypatched at module level),
extended with a `locked_by`/`lease_expires_at`/`attempt_count` on each
run and a results table keyed by run id (for replay).

IMPORTANT (same caveat as tests/test_analysis_jobs_repository.py): this
file proves query/branching *logic*, not genuine concurrent-connection
safety — a fake cursor executes everything sequentially in one Python
thread. The real-concurrency proof is
tests/test_sync_analysis_idempotency_integration.py (real PostgreSQL,
skipped when TEST_DATABASE_URL is unset).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from services import analysis_history_repository as repo


class _FakeJsonb:
    def __init__(self, value):
        self.value = value


class _FakeUniqueViolation(Exception):
    pass


class _SyncFakeDB:
    def __init__(self):
        self.brands: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.advisory_lock_calls: list[tuple[int, str]] = []
        self.force_unique_violation_once = False

    def next_id(self) -> str:
        return str(uuid.uuid4())


class _FakeCursor:
    def __init__(self, db: _SyncFakeDB):
        self.db = db
        self._last_query = ""
        self._last_params: tuple = ()
        self._pending_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self._last_query = " ".join(query.strip().lower().split())
        self._last_params = params or ()
        q = self._last_query

        if "pg_advisory_xact_lock" in q:
            seed = 0 if "hashtextextended(%s, 0)" in q else 1
            self.db.advisory_lock_calls.append((seed, self._last_params[0]))
            self._pending_result = (None,)
            return

        if q.startswith("select id, status, input_snapshot"):
            project_id, created_by_user_id, idempotency_key = self._last_params
            for run_id, run in self.db.runs.items():
                if (
                    run["project_id"] == project_id
                    and run["created_by_user_id"] == created_by_user_id
                    and run["idempotency_key"] == idempotency_key
                ):
                    self._pending_result = (
                        run_id,
                        run["status"],
                        run["input_snapshot"],
                        run["deleted_at"],
                    )
                    return
            self._pending_result = None
            return

        if q.startswith("update analysis_runs") and "lease_expires_at < now()" in q:
            (run_id,) = self._last_params
            run = self.db.runs.get(run_id)
            now = datetime.now(timezone.utc)
            if (
                run is not None
                and run["status"] == "running"
                and run["lease_expires_at"] is not None
                and run["lease_expires_at"] < now
            ):
                run["status"] = "failed"
                run["completed_at"] = now
                run["error_message"] = (
                    "worker lease expired (possible partial execution, not auto-retried)"
                )
                self._pending_result = (run_id,)
            else:
                self._pending_result = None
            return

        if q.startswith("select id from brands"):
            name, project_id = self._last_params
            for brand_id, brand in self.db.brands.items():
                if brand["name"] == name and brand["project_id"] == project_id:
                    self._pending_result = (brand_id,)
                    return
            self._pending_result = None
            return

        if q.startswith("insert into brands"):
            name, project_id = self._last_params
            brand_id = self.db.next_id()
            self.db.brands[brand_id] = {"name": name, "project_id": project_id}
            self._pending_result = (brand_id,)
            return

        if q.startswith("insert into analysis_runs"):
            if self.db.force_unique_violation_once:
                self.db.force_unique_violation_once = False
                raise _FakeUniqueViolation("duplicate key")
            (
                brand_id,
                project_id,
                input_snapshot,
                created_by_user_id,
                idempotency_key,
                locked_by,
                lease_seconds,
            ) = self._last_params
            run_id = self.db.next_id()
            now = datetime.now(timezone.utc)
            self.db.runs[run_id] = {
                "brand_id": brand_id,
                "project_id": project_id,
                "status": "running",
                "input_snapshot": input_snapshot.value
                if isinstance(input_snapshot, _FakeJsonb)
                else input_snapshot,
                "created_by_user_id": created_by_user_id,
                "idempotency_key": idempotency_key,
                "locked_by": locked_by,
                "locked_at": now,
                "lease_expires_at": now + timedelta(seconds=lease_seconds),
                "attempt_count": 1,
                "completed_at": None,
                "error_message": None,
                "deleted_at": None,
            }
            self._pending_result = (run_id,)
            return

        if q.startswith("insert into analysis_results"):
            run_id, result_json = self._last_params
            self.db.results[run_id] = {
                "result_json": result_json.value
                if isinstance(result_json, _FakeJsonb)
                else result_json,
                "meta_json": None,
            }
            self._pending_result = None
            return

        if q.startswith("select result_json, meta_json from analysis_results"):
            (run_id,) = self._last_params
            result = self.db.results.get(run_id)
            self._pending_result = (
                (result["result_json"], result["meta_json"]) if result is not None else None
            )
            return

        raise AssertionError(f"unexpected query in test fake: {query!r}")

    def fetchone(self):
        return self._pending_result


class _FakeConnection:
    def __init__(self, db: _SyncFakeDB):
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
    def __init__(self, db: _SyncFakeDB):
        self.db = db

    def connect(self, database_url, connect_timeout=None):
        return _FakeConnection(self.db)


def _configure(monkeypatch, db: _SyncFakeDB):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    monkeypatch.setattr(repo, "psycopg", _FakePsycopg(db))
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)
    monkeypatch.setattr(repo, "UniqueViolation", _FakeUniqueViolation)


BASE_KWARGS = dict(
    project_id="project-1",
    created_by_user_id="user-1",
    idempotency_key="req-1",
    brand_name="サイボウズ",
    documents=None,
    urls=None,
    common_crawl_mode=None,
    common_crawl_domain=None,
    ai_overview_mode=None,
    chatgpt_mode=None,
    claude_mode=None,
    gemini_mode=None,
    lease_seconds=180,
)


def test_new_request_id_creates_a_running_row_directly_never_queued(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    result = repo.create_running_analysis_run(**BASE_KWARGS)

    assert result.created is True
    assert result.status == "running"
    assert result.locked_by is not None
    run = db.runs[result.analysis_run_id]
    assert run["status"] == "running"
    # Never even momentarily 'queued' — structurally invisible to
    # claim_next_queued_analysis_run()'s `where status = 'queued'` query.
    assert run["locked_by"] == result.locked_by
    assert run["lease_expires_at"] is not None


def test_advisory_locks_acquired_in_fixed_project_then_user_order(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    repo.create_running_analysis_run(**BASE_KWARGS)

    assert db.advisory_lock_calls == [(0, "project-1"), (1, "user-1")]


def test_replay_of_completed_run_returns_saved_result_without_creating_new_row(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    db.runs[first.analysis_run_id]["status"] = "completed"
    db.results[first.analysis_run_id] = {
        "result_json": {"brandName": "サイボウズ"},
        "meta_json": {"documentsSource": "development_sample"},
    }

    second = repo.create_running_analysis_run(**BASE_KWARGS)

    assert second.created is False
    assert second.status == "completed"
    assert second.analysis_run_id == first.analysis_run_id
    assert second.result_json == {"brandName": "サイボウズ"}
    assert second.locked_by is None
    assert len(db.runs) == 1


def test_replay_of_partial_run_returns_saved_result(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    db.runs[first.analysis_run_id]["status"] = "partial"
    db.results[first.analysis_run_id] = {"result_json": {"brandName": "サイボウズ"}, "meta_json": None}

    second = repo.create_running_analysis_run(**BASE_KWARGS)

    assert second.created is False
    assert second.status == "partial"
    assert second.result_json == {"brandName": "サイボウズ"}


def test_still_running_with_unexpired_lease_raises_still_running_error(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    # Lease is still in the future (just created with lease_seconds=180).

    try:
        repo.create_running_analysis_run(**BASE_KWARGS)
        assert False, "expected SyncAnalysisStillRunningError"
    except repo.SyncAnalysisStillRunningError as exc:
        assert exc.existing_analysis_run_id == first.analysis_run_id


def test_running_with_expired_lease_is_lazily_failed_and_rejected_as_previously_failed(
    monkeypatch,
):
    """Render停止を想定した中断ケース: no background sweep needed — the
    very next call to this function (even with no worker process
    running at all) discovers the dead lease and transitions it to
    'failed' right there, then refuses to treat it as replayable."""
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    # Simulate a lease that already expired (e.g. the process was
    # killed mid-request on Render).
    db.runs[first.analysis_run_id]["lease_expires_at"] = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )

    try:
        repo.create_running_analysis_run(**BASE_KWARGS)
        assert False, "expected SyncAnalysisPreviouslyFailedError"
    except repo.SyncAnalysisPreviouslyFailedError as exc:
        assert exc.existing_analysis_run_id == first.analysis_run_id

    # The row itself was actually transitioned to 'failed' as a side
    # effect — never silently left 'running' forever, and never
    # resurrected back to 'queued'/'running' automatically.
    assert db.runs[first.analysis_run_id]["status"] == "failed"


def test_already_failed_run_is_rejected_without_retry(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    db.runs[first.analysis_run_id]["status"] = "failed"

    try:
        repo.create_running_analysis_run(**BASE_KWARGS)
        assert False, "expected SyncAnalysisPreviouslyFailedError"
    except repo.SyncAnalysisPreviouslyFailedError as exc:
        assert exc.existing_analysis_run_id == first.analysis_run_id

    # No second row was created — the caller must obtain a fresh
    # requestId instead of silently retrying this one.
    assert len(db.runs) == 1


def test_different_input_with_same_request_id_is_rejected(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    repo.create_running_analysis_run(**BASE_KWARGS)

    different_kwargs = dict(BASE_KWARGS, brand_name="別のブランド")
    try:
        repo.create_running_analysis_run(**different_kwargs)
        assert False, "expected AnalysisJobCreateConflictError"
    except repo.AnalysisJobCreateConflictError:
        pass


def test_deleted_run_is_permanently_rejected(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)
    db.runs[first.analysis_run_id]["deleted_at"] = datetime.now(timezone.utc)

    try:
        repo.create_running_analysis_run(**BASE_KWARGS)
        assert False, "expected AnalysisJobCancelledConflictError"
    except repo.AnalysisJobCancelledConflictError:
        pass


def test_different_user_or_project_does_not_collide_on_the_same_request_id(monkeypatch):
    db = _SyncFakeDB()
    _configure(monkeypatch, db)

    first = repo.create_running_analysis_run(**BASE_KWARGS)

    other_user_kwargs = dict(BASE_KWARGS, created_by_user_id="user-2")
    second = repo.create_running_analysis_run(**other_user_kwargs)
    assert second.created is True
    assert second.analysis_run_id != first.analysis_run_id

    other_project_kwargs = dict(BASE_KWARGS, project_id="project-2")
    third = repo.create_running_analysis_run(**other_project_kwargs)
    assert third.created is True
    assert third.analysis_run_id not in (first.analysis_run_id, second.analysis_run_id)


def test_resolve_sync_run_after_unique_violation_replays_the_winning_rows_result(monkeypatch):
    """Defense-in-depth path: exercised directly, since simulating "two
    connections genuinely race past the same advisory lock" isn't
    representable with this fake's single-threaded, sequential
    execution (the pre-insert lookup inside
    create_running_analysis_run() would always find the row first).
    Mirrors create_queued_analysis_run()'s own equivalent test for
    _resolve_job_after_unique_violation()."""
    db = _SyncFakeDB()
    _configure(monkeypatch, db)
    first = repo.create_running_analysis_run(**BASE_KWARGS)
    db.runs[first.analysis_run_id]["status"] = "completed"
    db.results[first.analysis_run_id] = {"result_json": {"brandName": "サイボウズ"}, "meta_json": None}

    canonical_input = repo._canonicalize_job_input(
        brand_name=BASE_KWARGS["brand_name"],
        documents=BASE_KWARGS["documents"],
        urls=BASE_KWARGS["urls"],
        common_crawl_mode=BASE_KWARGS["common_crawl_mode"],
        common_crawl_domain=BASE_KWARGS["common_crawl_domain"],
        ai_overview_mode=BASE_KWARGS["ai_overview_mode"],
        chatgpt_mode=BASE_KWARGS["chatgpt_mode"],
        claude_mode=BASE_KWARGS["claude_mode"],
        gemini_mode=BASE_KWARGS["gemini_mode"],
    )
    result = repo._resolve_sync_run_after_unique_violation(
        "postgresql://user:pass@host/db",
        project_id=BASE_KWARGS["project_id"],
        created_by_user_id=BASE_KWARGS["created_by_user_id"],
        idempotency_key=BASE_KWARGS["idempotency_key"],
        canonical_input=canonical_input,
    )
    assert result.created is False
    assert result.analysis_run_id == first.analysis_run_id
    assert result.result_json == {"brandName": "サイボウズ"}
