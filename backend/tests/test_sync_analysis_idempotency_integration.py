"""DB integration tests for create_running_analysis_run() against a
REAL PostgreSQL instance (Task 6-B3, feature/sync-analyze-jwt-project-auth)
— the only kind of test that can actually prove the advisory-lock +
unique-index design is safe under genuine concurrency, mirroring
tests/test_analysis_jobs_repository_integration.py's own rationale and
conventions exactly (same schema, same db_connection fixture shape,
same disposable-schema-per-test approach). Every mocked test in this
backend (including tests/test_sync_analysis_idempotency_repository.py)
runs everything sequentially in one Python thread and cannot make this
claim on its own.

Requires a `TEST_DATABASE_URL` environment variable pointing at a
disposable PostgreSQL database — never `DATABASE_URL` itself. The
whole module is skipped with an explicit reason when it's unset.

**This module HAS been executed, against real local disposable
PostgreSQL 16 and 17 instances (macOS/Homebrew), as part of
implementing and later auditing/fixing Task 6-B3.** Each instance was
created, used only for this verification, and torn down (dropdb +
pg_ctl stop) within the same session — no Supabase connection of any
kind was made. All tests in this module passed.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL is not set — these tests require a disposable "
        "local PostgreSQL instance to prove genuine concurrency safety."
    ),
)


@pytest.fixture
def db_connection():
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"sync_analyze_test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"create schema {schema}")
        cur.execute(f"set search_path to {schema}")
        cur.execute("create extension if not exists pgcrypto")
        cur.execute(
            """
            create table brands (
                id uuid primary key default gen_random_uuid(),
                name text not null,
                project_id uuid,
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table analysis_runs (
                id uuid primary key default gen_random_uuid(),
                brand_id uuid not null references brands(id),
                project_id uuid,
                status text not null,
                input_snapshot jsonb not null,
                started_at timestamptz not null default now(),
                completed_at timestamptz,
                error_message text,
                deleted_at timestamptz,
                created_by_user_id uuid,
                idempotency_key text,
                locked_by text,
                locked_at timestamptz,
                lease_expires_at timestamptz,
                attempt_count integer not null default 0,
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create unique index idx_analysis_runs_idempotency
            on analysis_runs (project_id, created_by_user_id, idempotency_key)
            where idempotency_key is not null
            """
        )
        # Mirrors migration 006's partial index — not load-bearing for
        # these tests' assertions, but included so the schema matches
        # production and so a future test could exercise
        # claim_next_queued_analysis_run() against the same schema if
        # needed.
        cur.execute(
            """
            create index idx_analysis_runs_status_created_at
            on analysis_runs (status, created_at)
            where status = 'queued'
            """
        )
        cur.execute(
            """
            create table analysis_results (
                id uuid primary key default gen_random_uuid(),
                analysis_run_id uuid not null references analysis_runs(id),
                result_json jsonb not null,
                meta_json jsonb,
                created_at timestamptz not null default now()
            )
            """
        )
        # Exact schema from migrations/009_add_analysis_usage_counters.sql
        # (Task 6-B4).
        cur.execute(
            """
            create table analysis_usage_counters (
                scope_type   text not null,
                scope_id     uuid not null,
                metric       text not null,
                period_type  text not null,
                period_start timestamptz not null,
                count        integer not null default 0,
                created_at   timestamptz not null default now(),
                updated_at   timestamptz not null default now(),
                constraint analysis_usage_counters_pkey
                    primary key (scope_type, scope_id, metric, period_type, period_start),
                constraint analysis_usage_counters_scope_type_check
                    check (scope_type in ('user', 'project')),
                constraint analysis_usage_counters_period_type_check
                    check (period_type in ('daily', 'monthly')),
                constraint analysis_usage_counters_count_check
                    check (count >= 0)
            )
            """
        )
        cur.execute(
            """
            create index idx_analysis_usage_counters_scope
                on analysis_usage_counters (scope_type, scope_id, period_type, period_start)
            """
        )
    try:
        yield conn, schema
    finally:
        with conn.cursor() as cur:
            cur.execute(f"drop schema {schema} cascade")
        conn.close()


def _database_url_with_search_path(schema: str) -> str:
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    return f"{TEST_DATABASE_URL}{separator}options=-csearch_path%3D{schema}"


def _create_running(database_url, **overrides):
    import services.analysis_history_repository as repo
    from services.analysis_history_repository import create_running_analysis_run

    base = dict(
        project_id="11111111-1111-1111-1111-111111111111",
        created_by_user_id="22222222-2222-2222-2222-222222222222",
        idempotency_key="req-1",
        brand_name="Acme",
        documents=None,
        urls=["https://example.com"],
        common_crawl_mode=None,
        common_crawl_domain=None,
        ai_overview_mode=None,
        chatgpt_mode=None,
        claude_mode=None,
        gemini_mode=None,
        lease_seconds=180,
    )
    base.update(overrides)

    original_load = repo.load_db_settings
    repo.load_db_settings = lambda: type(
        "S", (), {"database_url": database_url, "save_enabled": True}
    )()
    try:
        return create_running_analysis_run(**base)
    finally:
        repo.load_db_settings = original_load


def test_concurrent_requests_with_same_request_id_create_exactly_one_running_row(
    db_connection,
):
    """The real test this module exists for: fire 10 genuinely
    concurrent create_running_analysis_run() calls (real threads, real
    separate PostgreSQL connections) with the *same* idempotency key,
    and assert exactly one succeeds with created=True while every
    other one is rejected as "still running" — never silently starting
    a second execution for the same key."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def worker():
        import services.analysis_history_repository as repo

        try:
            result = _create_running(database_url)
            with lock:
                results.append(result)
        except repo.SyncAnalysisStillRunningError as exc:
            with lock:
                errors.append(exc)
        except Exception as exc:  # noqa: BLE001 - recorded for the assertion below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    import services.analysis_history_repository as repo

    still_running_errors = [e for e in errors if isinstance(e, repo.SyncAnalysisStillRunningError)]
    other_errors = [e for e in errors if not isinstance(e, repo.SyncAnalysisStillRunningError)]

    assert not other_errors, f"unexpected non-still-running errors: {other_errors}"
    assert len(results) == 1, f"expected exactly 1 new execution, got {len(results)}"
    assert results[0].created is True
    assert len(still_running_errors) == 9

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 1

    with conn.cursor() as cur:
        cur.execute(f"select status from {schema}.analysis_runs")
        (status,) = cur.fetchone()
    assert status == "running"


def test_concurrent_requests_with_different_request_ids_create_separate_rows(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    results: list = []
    lock = threading.Lock()

    def worker(key):
        result = _create_running(database_url, idempotency_key=key)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(f"req-{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    assert all(r.created for r in results)
    assert len({r.analysis_run_id for r in results}) == 5

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 5


def test_a_created_row_is_never_visible_as_queued_to_the_async_worker(db_connection):
    """Proves the structural claim underpinning this whole feature's
    safety: a synchronous run's status is *never*, even momentarily,
    'queued' — the exact WHERE clause
    claim_next_queued_analysis_run() uses never matches it."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    result = _create_running(database_url)
    assert result.created is True

    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_runs "
            "where status = 'queued' and deleted_at is null"
        )
        (queued_count,) = cur.fetchone()
    assert queued_count == 0


def test_second_request_sees_still_running_then_lease_expiry_makes_it_failed_not_retried(
    db_connection,
):
    """Render停止/中断を想定したケース、実DBで確認: first reserves the
    row; a second call while the lease is still valid is rejected as
    still-running; once the lease is manually expired (simulating a
    killed process that never got to complete it), the very next call
    — with no background sweep process involved at all — discovers
    this inline and refuses to create a new row, instead reporting the
    (now lazily-failed) row as permanently unusable for this key."""
    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create_running(database_url, lease_seconds=5)
    assert first.created is True

    with pytest.raises(repo.SyncAnalysisStillRunningError):
        _create_running(database_url)

    # Simulate the lease having already expired (e.g. Render killed
    # the process mid-request) by moving it into the past directly.
    with conn.cursor() as cur:
        cur.execute(
            f"update {schema}.analysis_runs set lease_expires_at = now() - interval '1 second'"
        )

    with pytest.raises(repo.SyncAnalysisPreviouslyFailedError):
        _create_running(database_url)

    with conn.cursor() as cur:
        cur.execute(f"select status from {schema}.analysis_runs")
        (status,) = cur.fetchone()
    assert status == "failed"

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 1


def test_late_completion_after_lazy_expiry_never_overwrites_the_failed_row(db_connection):
    """Task 6-B3 audit (不具合B's root cause, verified on real
    PostgreSQL): the ORIGINAL process is still genuinely executing
    (not stopped — see the module-level reasoning above) when its
    lease expires and a *different* request's lazy-expiry check
    transitions the row to 'failed'. When the original process finally
    finishes and calls complete_analysis_job() with its own
    `locked_by` token to save a REAL completed result, that call must
    be refused (status='running' no longer matches) — the row must
    stay 'failed', and the real result must never reach
    `analysis_results`. This is the DB-level half of 不具合B; the other
    half (main.py must not report this run's id as if it held a saved
    result) is covered by
    tests/test_main_analyze_idempotency.py's
    test_lease_expired_completion_omits_analysis_run_id_from_response.
    """
    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create_running(database_url, lease_seconds=1)
    assert first.created is True
    original_locked_by = first.locked_by
    run_id = first.analysis_run_id

    # Simulate the lease having expired while the original process is
    # still genuinely running (never assume expiry means "stopped" —
    # same reasoning as the test above).
    with conn.cursor() as cur:
        cur.execute(
            f"update {schema}.analysis_runs set lease_expires_at = now() - interval '1 second'"
        )

    # A different request (same key) discovers the expiry and sweeps
    # the row to 'failed'.
    with pytest.raises(repo.SyncAnalysisPreviouslyFailedError):
        _create_running(database_url)

    # Meanwhile, a THIRD request with a genuinely different key (e.g.
    # the Frontend bug this audit found: a resubmission that was given
    # a fresh requestId instead of reusing the original) is free to
    # start its own, fully independent execution — proving the
    # backend has no secondary defense once a different key is used.
    second = _create_running(database_url, idempotency_key="req-unrelated")
    assert second.created is True
    assert second.analysis_run_id != run_id

    # The ORIGINAL process now finally finishes and tries to save its
    # real result — this must be refused, not overwrite the 'failed'
    # row.
    original_load_db_settings = repo.load_db_settings
    repo.load_db_settings = lambda: type(
        "S", (), {"database_url": database_url, "save_enabled": True}
    )()
    try:
        completed = repo.complete_analysis_job(
            run_id,
            worker_id=original_locked_by,
            status="completed",
            result_json={"brandName": "Acme", "lateRealResult": True},
            meta_json={},
            error_message=None,
        )
    finally:
        repo.load_db_settings = original_load_db_settings

    assert completed is False

    with conn.cursor() as cur:
        cur.execute(f"select status from {schema}.analysis_runs where id = %s", (run_id,))
        (status,) = cur.fetchone()
        cur.execute(
            f"select result_json from {schema}.analysis_results where analysis_run_id = %s",
            (run_id,),
        )
        (result_json,) = cur.fetchone()
    assert status == "failed"
    assert result_json == {}
    assert "lateRealResult" not in result_json


# --- Task 6-B4 usage-quota counters (real PostgreSQL) -------------------


def _requirement(scope_type, scope_id, metric, period_type, limit):
    import services.analysis_history_repository as repo

    return repo.UsageCounterRequirement(
        scope_type=scope_type,
        scope_id=scope_id,
        metric=metric,
        period_type=period_type,
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        limit=limit,
    )


def test_quota_exceeded_rolls_back_the_run_row_and_every_counter_increment(db_connection):
    """The core atomicity requirement, proven on a real transaction
    (not the mocked fake, which has no real rollback semantics): when
    one of several counters is already at its limit, NOTHING from
    this attempt persists — not the analysis_runs/analysis_results
    row, and not even the OTHER counters this same call already
    incremented earlier in its own counter-reservation loop."""
    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    counters = [
        _requirement("user", "22222222-2222-2222-2222-222222222222", "all_analyses", "daily", limit=20),
        _requirement("project", "11111111-1111-1111-1111-111111111111", "openai", "daily", limit=0),
    ]

    with pytest.raises(repo.AnalysisQuotaExceededError) as exc_info:
        _create_running(database_url, required_counters=counters)

    assert exc_info.value.metric == "openai"

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (run_count,) = cur.fetchone()
        cur.execute(f"select count(*) from {schema}.analysis_results")
        (result_count,) = cur.fetchone()
        cur.execute(f"select count(*) from {schema}.analysis_usage_counters")
        (counter_rows,) = cur.fetchone()
    # Not even the "user/all_analyses/daily" counter (reserved BEFORE
    # the openai one that actually failed, in the same loop) survived.
    assert run_count == 0
    assert result_count == 0
    assert counter_rows == 0


def test_quota_success_persists_the_run_and_every_counter(db_connection):
    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    counters = [
        _requirement("user", "22222222-2222-2222-2222-222222222222", "all_analyses", "daily", limit=20),
        _requirement("project", "11111111-1111-1111-1111-111111111111", "all_analyses", "daily", limit=50),
    ]

    result = _create_running(database_url, required_counters=counters)
    assert result.created is True

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (run_count,) = cur.fetchone()
        cur.execute(f"select count, scope_type from {schema}.analysis_usage_counters order by scope_type")
        rows = cur.fetchall()
    assert run_count == 1
    assert rows == [(1, "project"), (1, "user")]


def test_concurrent_different_request_ids_never_exceed_the_project_daily_limit(db_connection):
    """異なるrequestIdの同時10件で上限を超えない — the real concurrency
    proof this feature's safety rests on: 10 genuinely concurrent
    create_running_analysis_run() calls (real threads, real separate
    connections), each a distinct idempotency_key for the SAME
    project, with a project-daily limit of 8. Exactly 8 must succeed
    and exactly 2 must be rejected — never more than 8, and never
    fewer (no false rejection either)."""
    import threading

    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def worker(i):
        counters = [
            _requirement(
                "project", "11111111-1111-1111-1111-111111111111", "all_analyses", "daily", limit=8
            )
        ]
        try:
            result = _create_running(
                database_url, idempotency_key=f"req-{i}", required_counters=counters
            )
            with lock:
                results.append(result)
        except repo.AnalysisQuotaExceededError as exc:
            with lock:
                errors.append(exc)
        except Exception as exc:  # noqa: BLE001 - recorded for the assertion below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    quota_errors = [e for e in errors if isinstance(e, repo.AnalysisQuotaExceededError)]
    other_errors = [e for e in errors if not isinstance(e, repo.AnalysisQuotaExceededError)]

    assert not other_errors, f"unexpected non-quota errors: {other_errors}"
    assert len(results) == 8
    assert len(quota_errors) == 2

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (run_count,) = cur.fetchone()
        cur.execute(f"select count from {schema}.analysis_usage_counters")
        (counter_value,) = cur.fetchone()
    assert run_count == 8
    assert counter_value == 8


def test_resubmission_of_existing_key_never_increments_counters_real_db(db_connection):
    """同じrequestIdの再送で二重消費なし, proven on real PostgreSQL."""
    import services.analysis_history_repository as repo

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    counters = [
        _requirement("user", "22222222-2222-2222-2222-222222222222", "all_analyses", "daily", limit=20)
    ]

    first = _create_running(database_url, lease_seconds=180, required_counters=counters)
    assert first.created is True

    with pytest.raises(repo.SyncAnalysisStillRunningError):
        _create_running(database_url, required_counters=counters)

    with conn.cursor() as cur:
        cur.execute(f"select count from {schema}.analysis_usage_counters")
        (counter_value,) = cur.fetchone()
    assert counter_value == 1
