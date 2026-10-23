"""Verifies services.analysis_history_repository's Phase 1 async-job
functions (create_queued_analysis_run() / get_analysis_job_status() /
get_analysis_job_result() / _canonicalize_job_input()) without ever
touching a real database — mirrors the existing
tests/test_analysis_history_repository.py monkeypatch pattern
(psycopg/Jsonb are monkeypatched at the module level).

IMPORTANT: these mocked tests can verify this module's *query logic*
(what gets selected/inserted, and in what order) but cannot prove that
the advisory-lock + unique-index design is actually safe against two
real, concurrently-running database connections — a fake cursor
executes everything sequentially in a single Python thread, so there
is no genuine race for it to get wrong. That guarantee can only come
from a real PostgreSQL instance; see
tests/test_analysis_jobs_repository_integration.py, which is skipped
in this environment (no local PostgreSQL/docker available — see that
file's module docstring) and documents what it would otherwise prove.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from services import analysis_history_repository as repo


class _FakeJsonb:
    """Stand-in for psycopg.types.json.Jsonb — remembers the value it
    wrapped (mirrors tests/test_analysis_history_repository.py's
    _FakeJsonb) so a test can assert on exactly what would have been
    sent to the database."""

    def __init__(self, value):
        self.value = value


class _FakeUniqueViolation(Exception):
    """Stand-in for psycopg.errors.UniqueViolation."""


class _JobsFakeDB:
    """A tiny in-memory stand-in for the one `analysis_runs` /
    `analysis_results` / `brands` slice create_queued_analysis_run()
    touches. Shared across every psycopg.connect() call a test makes
    (like a real database would be), so sequential calls within one
    test can observe each other's writes — this is what lets the
    "idempotent replay returns the existing job" tests work without a
    real database, even though (see module docstring) it says nothing
    about concurrent-connection safety.
    """

    def __init__(self):
        self.brands: dict[str, dict] = {}
        self.runs: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.advisory_lock_calls: list[str] = []
        self.queries: list[tuple[str, tuple]] = []
        self.force_unique_violation_once = False

    def next_id(self) -> str:
        return str(uuid.uuid4())


class _FakeCursor:
    def __init__(self, db: _JobsFakeDB):
        self.db = db
        self._last_query = ""
        self._last_params: tuple = ()
        self._pending_result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=()):
        self.db.queries.append((query, params))
        self._last_query = " ".join(query.strip().lower().split())
        self._last_params = params or ()
        q = self._last_query

        if "pg_advisory_xact_lock" in q:
            # The lock namespace (0 for project, 1 for user) is baked
            # into the query text itself (hashtextextended(%s, 0) /
            # hashtextextended(%s, 1)), not passed as a bind
            # parameter — recover it from the query string so tests
            # can assert both which id was locked and in which
            # namespace.
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

        if "select count(*) from analysis_runs where project_id" in q:
            project_id = self._last_params[0]
            count = sum(
                1
                for run in self.db.runs.values()
                if run["project_id"] == project_id
                and run["status"] == "queued"
                and run["deleted_at"] is None
            )
            self._pending_result = (count,)
            return

        if "select count(*) from analysis_runs where created_by_user_id" in q:
            user_id = self._last_params[0]
            count = sum(
                1
                for run in self.db.runs.values()
                if run["created_by_user_id"] == user_id
                and run["status"] == "queued"
                and run["deleted_at"] is None
            )
            self._pending_result = (count,)
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
            if self.db.force_unique_violation_once:
                self.db.force_unique_violation_once = False
                raise _FakeUniqueViolation("duplicate key")
            name, project_id = self._last_params
            brand_id = self.db.next_id()
            self.db.brands[brand_id] = {"name": name, "project_id": project_id}
            self._pending_result = (brand_id,)
            return

        if q.startswith("insert into analysis_runs"):
            brand_id, project_id, input_snapshot, created_by_user_id, idempotency_key = (
                self._last_params
            )
            run_id = self.db.next_id()
            self.db.runs[run_id] = {
                "brand_id": brand_id,
                "project_id": project_id,
                "status": "queued",
                "input_snapshot": input_snapshot.value
                if isinstance(input_snapshot, _FakeJsonb)
                else input_snapshot,
                "created_by_user_id": created_by_user_id,
                "idempotency_key": idempotency_key,
                "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
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

        if q.startswith("select status, started_at, completed_at, error_message"):
            (run_id,) = self._last_params
            run = self.db.runs.get(run_id)
            if run is None or run["deleted_at"] is not None:
                self._pending_result = None
                return
            self._pending_result = (
                run["status"],
                run["started_at"],
                run["completed_at"],
                run["error_message"],
            )
            return

        if q.startswith("select ar.status, ar.error_message, res.result_json"):
            (run_id,) = self._last_params
            run = self.db.runs.get(run_id)
            if run is None or run["deleted_at"] is not None:
                self._pending_result = None
                return
            result = self.db.results.get(run_id, {"result_json": None, "meta_json": None})
            self._pending_result = (
                run["status"],
                run["error_message"],
                result["result_json"],
                result["meta_json"],
            )
            return

        raise AssertionError(f"unexpected query in test fake: {query!r}")

    def fetchone(self):
        return self._pending_result


class _FakeConnection:
    def __init__(self, db: _JobsFakeDB):
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
    def __init__(self, db: _JobsFakeDB):
        self.db = db
        self.connect_calls = 0
        self.errors = type("errors", (), {"UniqueViolation": _FakeUniqueViolation})

    def connect(self, database_url, connect_timeout=None):
        self.connect_calls += 1
        return _FakeConnection(self.db)


@pytest.fixture
def jobs_db(monkeypatch):
    db = _JobsFakeDB()
    fake_psycopg = _FakePsycopg(db)
    monkeypatch.setattr(repo, "psycopg", fake_psycopg)
    monkeypatch.setattr(repo, "Jsonb", _FakeJsonb)
    monkeypatch.setattr(repo, "UniqueViolation", _FakeUniqueViolation)
    monkeypatch.setattr(
        repo,
        "load_db_settings",
        lambda: type(
            "S", (), {"database_url": "postgresql://user:pass@host/db"}
        )(),
    )
    return db


BASE_KWARGS = dict(
    project_id="project-1",
    created_by_user_id="user-1",
    idempotency_key="key-1",
    brand_name="Acme",
    documents=None,
    urls=["https://example.com"],
    common_crawl_mode=None,
    common_crawl_domain=None,
    ai_overview_mode=None,
    chatgpt_mode=None,
    claude_mode=None,
    gemini_mode=None,
    max_queued_per_project=5,
    max_queued_per_user=5,
)


# --- _canonicalize_job_input() ---------------------------------------------


def test_canonicalize_strips_brand_name_and_blank_common_crawl_domain():
    result = repo._canonicalize_job_input(
        brand_name="  Acme  ",
        documents=None,
        urls=["https://example.com"],
        common_crawl_mode="domain",
        common_crawl_domain="   ",
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
    )
    assert result["brandName"] == "Acme"
    assert result["commonCrawlDomain"] is None


def test_canonicalize_does_not_reorder_urls_or_documents():
    """A caller sending the same key with reordered urls/documents must
    be treated as a *different* request, not silently normalized to
    the same one (see docs/40_async_analysis_jobs_design.md "10.1")."""
    a = repo._canonicalize_job_input(
        brand_name="Acme",
        documents=["doc-a", "doc-b"],
        urls=["https://b.example.com", "https://a.example.com"],
        common_crawl_mode=None,
        common_crawl_domain=None,
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
    )
    b = repo._canonicalize_job_input(
        brand_name="Acme",
        documents=["doc-b", "doc-a"],
        urls=["https://a.example.com", "https://b.example.com"],
        common_crawl_mode=None,
        common_crawl_domain=None,
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
    )
    assert a != b


def test_canonicalize_includes_official_url_and_defaults_to_none():
    """Task 6-D-5B (feature/official-info-candidate): officialUrl must
    be part of the canonicalized/stored shape (so a resubmission with
    a different officialUrl under the same idempotency key is treated
    as a genuinely different request), and omitting it must default
    to None rather than being dropped from the dict entirely (every
    other field here behaves the same way)."""
    without_official_url = repo._canonicalize_job_input(
        brand_name="Acme",
        documents=None,
        urls=["https://example.com"],
        common_crawl_mode=None,
        common_crawl_domain=None,
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
    )
    assert without_official_url["officialUrl"] is None

    with_official_url = repo._canonicalize_job_input(
        brand_name="Acme",
        documents=None,
        urls=["https://example.com"],
        common_crawl_mode=None,
        common_crawl_domain=None,
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
        official_url="https://acme.example.com",
    )
    assert with_official_url["officialUrl"] == "https://acme.example.com"
    assert without_official_url != with_official_url


# --- create_queued_analysis_run() ------------------------------------------


def test_create_queued_analysis_run_creates_new_job(jobs_db):
    result = repo.create_queued_analysis_run(**BASE_KWARGS)

    assert result.created is True
    assert result.status == "queued"
    assert result.analysis_run_id in jobs_db.runs
    run = jobs_db.runs[result.analysis_run_id]
    assert run["status"] == "queued"
    assert run["project_id"] == "project-1"
    assert run["created_by_user_id"] == "user-1"
    assert run["idempotency_key"] == "key-1"
    assert run["input_snapshot"]["urls"] == ["https://example.com"]
    assert jobs_db.results[result.analysis_run_id]["result_json"] == {}


def test_create_queued_analysis_run_acquires_advisory_locks_before_insert(jobs_db):
    """Both the project-scoped and user-scoped advisory locks must be
    acquired, in that fixed order, before anything is read/written —
    see docs/40_async_analysis_jobs_design.md "11.1"/"18" and the
    deadlock-avoidance reasoning in create_queued_analysis_run()'s
    docstring (a fixed global acquisition order rules out circular
    wait)."""
    repo.create_queued_analysis_run(**BASE_KWARGS)

    assert jobs_db.advisory_lock_calls == [(0, "project-1"), (1, "user-1")]


def test_create_queued_analysis_run_is_idempotent_for_same_input(jobs_db):
    first = repo.create_queued_analysis_run(**BASE_KWARGS)
    second = repo.create_queued_analysis_run(**BASE_KWARGS)

    assert second.created is False
    assert second.analysis_run_id == first.analysis_run_id
    assert len(jobs_db.runs) == 1


def test_create_queued_analysis_run_conflicts_on_same_key_different_input(jobs_db):
    repo.create_queued_analysis_run(**BASE_KWARGS)

    different = dict(BASE_KWARGS, urls=["https://different.example.com"])
    with pytest.raises(repo.AnalysisJobCreateConflictError):
        repo.create_queued_analysis_run(**different)

    # No second row was created.
    assert len(jobs_db.runs) == 1


def test_create_queued_analysis_run_rejects_replay_of_a_cancelled_job_key(jobs_db):
    """fix/async-job-cancel-safety's second fix: cancel_queued_analysis_run()
    deliberately keeps `idempotency_key` set (unlike the original fix,
    which cleared it) so this exact lookup keeps finding the cancelled
    row — and this must refuse the replay (409 at the API layer) rather
    than either resurrecting it or creating a second job for the same
    key, even when the resubmitted input is byte-identical."""
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["deleted_at"] = datetime.now(timezone.utc)

    with pytest.raises(repo.AnalysisJobCancelledConflictError) as exc_info:
        repo.create_queued_analysis_run(**BASE_KWARGS)

    assert exc_info.value.existing_analysis_run_id == created.analysis_run_id
    # No new row was created, and the cancelled row was left untouched.
    assert len(jobs_db.runs) == 1
    assert jobs_db.runs[created.analysis_run_id]["status"] == "queued"
    assert jobs_db.runs[created.analysis_run_id]["deleted_at"] is not None


def test_create_queued_analysis_run_rejects_replay_of_a_cancelled_job_key_even_with_different_input(
    jobs_db,
):
    """The cancelled-key check runs *before* the input comparison —
    a cancelled job's key is refused outright, never silently treated
    as "different input, so 409 conflict" vs "same input, so replay"."""
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["deleted_at"] = datetime.now(timezone.utc)

    different = dict(BASE_KWARGS, urls=["https://different.example.com"])
    with pytest.raises(repo.AnalysisJobCancelledConflictError):
        repo.create_queued_analysis_run(**different)

    assert len(jobs_db.runs) == 1


def test_create_queued_analysis_run_allows_a_fresh_key_after_cancellation(jobs_db):
    """A genuinely new "start analysis" operation (a different
    idempotency key, exactly what a client generates for an explicit
    new attempt) must succeed normally even though an earlier,
    cancelled job for the same project/user still exists."""
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["deleted_at"] = datetime.now(timezone.utc)

    fresh = dict(BASE_KWARGS, idempotency_key="a-brand-new-key")
    result = repo.create_queued_analysis_run(**fresh)

    assert result.created is True
    assert result.analysis_run_id != created.analysis_run_id
    assert len(jobs_db.runs) == 2


def test_create_queued_analysis_run_enforces_project_queued_limit(jobs_db):
    kwargs = dict(BASE_KWARGS, max_queued_per_project=1)
    repo.create_queued_analysis_run(**kwargs)

    kwargs_2 = dict(kwargs, idempotency_key="key-2")
    with pytest.raises(repo.AnalysisJobLimitExceededError) as exc_info:
        repo.create_queued_analysis_run(**kwargs_2)

    assert exc_info.value.scope == "project"
    assert len(jobs_db.runs) == 1


def test_create_queued_analysis_run_enforces_user_queued_limit(jobs_db):
    kwargs = dict(BASE_KWARGS, max_queued_per_user=1, max_queued_per_project=5)
    repo.create_queued_analysis_run(**kwargs)

    # Different project, same user, same idempotency key is fine to
    # reuse here because uniqueness is scoped per-project (see "10.1")
    # — this is a genuinely different job, not a replay.
    kwargs_2 = dict(kwargs, project_id="project-2")
    with pytest.raises(repo.AnalysisJobLimitExceededError) as exc_info:
        repo.create_queued_analysis_run(**kwargs_2)

    assert exc_info.value.scope == "user"
    assert len(jobs_db.runs) == 1


def test_create_queued_analysis_run_unique_violation_falls_back_safely(jobs_db):
    """Forces the brand-insert statement to raise UniqueViolation on a
    call whose idempotency key has no existing row at all (the
    pre-insert lookup legitimately finds nothing, so the INSERT path
    really is reached) — simulating the "defense in depth" case from
    create_queued_analysis_run()'s docstring: a UniqueViolation that
    the advisory lock should have prevented, but didn't. Since no row
    with the looked-up key exists for the fallback resolver to find
    either (this fake never actually wrote one), the function must
    surface a clear AnalysisHistoryReadError rather than letting the
    raw _FakeUniqueViolation leak out as an unexplained 500."""
    jobs_db.force_unique_violation_once = True

    with pytest.raises(repo.AnalysisHistoryReadError):
        repo.create_queued_analysis_run(**BASE_KWARGS)


# --- get_analysis_job_status() ---------------------------------------------


def test_get_analysis_job_status_returns_none_for_malformed_id(jobs_db):
    assert repo.get_analysis_job_status("not-a-uuid") is None


def test_get_analysis_job_status_returns_none_when_not_found(jobs_db):
    assert repo.get_analysis_job_status(str(uuid.uuid4())) is None


def test_get_analysis_job_status_returns_queued_job(jobs_db):
    created = repo.create_queued_analysis_run(**BASE_KWARGS)

    status = repo.get_analysis_job_status(created.analysis_run_id)

    assert status["status"] == "queued"
    assert status["completedAt"] is None
    assert status["errorMessage"] is None
    assert status["startedAt"] is not None


def test_get_analysis_job_status_returns_none_for_soft_deleted_job(jobs_db):
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["deleted_at"] = datetime.now(timezone.utc)

    assert repo.get_analysis_job_status(created.analysis_run_id) is None


# --- get_analysis_job_result() ---------------------------------------------


def test_get_analysis_job_result_returns_no_result_for_queued_job(jobs_db):
    created = repo.create_queued_analysis_run(**BASE_KWARGS)

    job = repo.get_analysis_job_result(created.analysis_run_id)

    assert job["status"] == "queued"
    assert job["result"] is None
    assert job["meta"] is None


def test_get_analysis_job_result_never_surfaces_placeholder_as_real_result(jobs_db):
    """The placeholder analysis_results.result_json='{}' written at
    job creation must never be returned as a real result, even if a
    caller somehow asks while status is still 'queued' — this is the
    exact failure mode docs/40_async_analysis_jobs_design.md "13.2"
    warns about."""
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    assert jobs_db.results[created.analysis_run_id]["result_json"] == {}

    job = repo.get_analysis_job_result(created.analysis_run_id)

    assert job["result"] is None


def test_get_analysis_job_result_returns_result_for_completed_job(jobs_db):
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["status"] = "completed"
    jobs_db.results[created.analysis_run_id]["result_json"] = {"brandName": "Acme"}
    jobs_db.results[created.analysis_run_id]["meta_json"] = {"sections": {}}

    job = repo.get_analysis_job_result(created.analysis_run_id)

    assert job["status"] == "completed"
    assert job["result"] == {"brandName": "Acme"}
    assert job["meta"] == {"sections": {}}


def test_get_analysis_job_result_returns_no_result_for_failed_job(jobs_db):
    created = repo.create_queued_analysis_run(**BASE_KWARGS)
    jobs_db.runs[created.analysis_run_id]["status"] = "failed"
    jobs_db.runs[created.analysis_run_id]["error_message"] = "worker lease expired"

    job = repo.get_analysis_job_result(created.analysis_run_id)

    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["meta"] is None
    assert job["errorMessage"] == "worker lease expired"


def test_get_analysis_job_result_returns_none_when_not_found(jobs_db):
    assert repo.get_analysis_job_result(str(uuid.uuid4())) is None
