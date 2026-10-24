"""DB integration tests for
services/websearch_quota_reservation.py's
reserve_websearch_quota_for_analysis_run() against a REAL PostgreSQL
instance (Task 6-D-2B, feature/websearch-quota-reservation) — the
only kind of test that can actually prove the daily/monthly
atomic-cap-and-increment claim is safe under genuine concurrency.
Every mocked test (tests/test_websearch_quota_reservation.py) runs
sequentially in one Python thread and cannot make that claim on its
own, mirroring tests/test_sync_analysis_idempotency_integration.py's
own rationale exactly.

This module deliberately does NOT create organizations/projects/
organization_members (which would need a Supabase-only `auth.users`
table to match production — see migrations/002's own header) —
project-membership authorization is already covered, with mocks, by
tests/test_project_access.py and
tests/test_websearch_quota_reservation.py, and
services/project_access.can_user_access_analysis_run() is monkeypatched
to always allow access here. This mirrors
tests/test_analysis_jobs_repository_integration.py's own documented
reasoning ("this file is about Phase 1's job-table logic, not the
separate (and already-tested) project-membership machinery").

Requires a `TEST_DATABASE_URL` environment variable pointing at a
disposable PostgreSQL database — never `DATABASE_URL` itself. The
whole module is skipped with an explicit reason when it's unset.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL is not set — these tests require a disposable "
        "local PostgreSQL instance to prove genuine concurrency safety."
    ),
)


def _migration_010_sql() -> str:
    """Reads the real migration file rather than duplicating its SQL
    inline — so this fixture proves migrations/010_add_analysis_run_websearch_reservations.sql
    itself applies cleanly against a real PostgreSQL instance (this
    task's test item "新テーブルへのmigration適用成功"), not just a
    hand-copied approximation of it."""
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    path = os.path.join(migrations_dir, "010_add_analysis_run_websearch_reservations.sql")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _migration_011_sql() -> str:
    """Task 6-D-4C-2 (feature/gemini-external-document-supplement):
    reads migrations/011_add_gemini_external_document_metric.sql the
    same way _migration_010_sql() does — applied on top of migration
    010 in the `db_connection` fixture below, so every test in this
    module runs against the real, widened CHECK constraint (allowing
    'gemini_external_document' alongside the original three metrics),
    not a hand-copied approximation."""
    migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
    path = os.path.join(migrations_dir, "011_add_gemini_external_document_metric.sql")
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def db_connection():
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"websearch_quota_test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"create schema {schema}")
        cur.execute(f"set search_path to {schema}")
        cur.execute("create extension if not exists pgcrypto")
        cur.execute(
            """
            create table analysis_runs (
                id uuid primary key default gen_random_uuid(),
                project_id uuid,
                status text not null,
                deleted_at timestamptz,
                locked_by text,
                lease_expires_at timestamptz
            )
            """
        )
        # Exact schema from migrations/009_add_analysis_usage_counters.sql
        # (Task 6-B4) — no change needed for Task 6-D-2A/6-D-2B, since
        # `metric` has no CHECK constraint restricting its values (see
        # this task's completion report).
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
        # The real migration 010 SQL — applied as-is (not a hand-copied
        # approximation) to prove it actually runs cleanly against a
        # real PostgreSQL instance.
        cur.execute(_migration_010_sql())
        # Task 6-D-4C-2: the real migration 011 SQL, applied
        # immediately on top of 010 — proves the widened CHECK
        # constraint itself applies cleanly (DROP + ADD CONSTRAINT
        # against a table that migration 010 just created in this
        # same transaction) and that every test below runs against the
        # real, final constraint shape.
        cur.execute(_migration_011_sql())
    try:
        yield conn, schema
    finally:
        with conn.cursor() as cur:
            cur.execute(f"drop schema {schema} cascade")
        conn.close()


def _database_url_with_search_path(schema: str) -> str:
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    return f"{TEST_DATABASE_URL}{separator}options=-csearch_path%3D{schema}"


def _insert_running_run(conn, schema: str, project_id: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_runs (project_id, status) "
            "values (%s, 'running') returning id",
            (project_id,),
        )
        (run_id,) = cur.fetchone()
    return str(run_id)


def _insert_leased_run(
    conn, schema: str, project_id: str, *, locked_by: str | None, lease_seconds: float | None
) -> str:
    """Task 6-D-5C-4G: like _insert_running_run() but also sets
    `locked_by`/`lease_expires_at` — `lease_seconds` may be negative
    (an already-expired lease) or `None` (a null lease, as a
    synchronous-only row created before migration 006 or a queued row
    a worker never claimed would have)."""
    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_runs "
            "(project_id, status, locked_by, lease_expires_at) "
            "values (%s, 'running', %s, "
            "case when %s is null then null else now() + make_interval(secs => %s) end) "
            "returning id",
            (project_id, locked_by, lease_seconds, lease_seconds),
        )
        (run_id,) = cur.fetchone()
    return str(run_id)


def _patch_db_and_access(monkeypatch, database_url: str) -> None:
    """Patches load_db_settings()/can_user_access_analysis_run() ONCE,
    via pytest's own monkeypatch fixture (restored automatically at
    test teardown) — deliberately NOT done per-call inside _reserve()
    below. A per-call set/restore cycle raced across threads in a
    genuinely concurrent test (confirmed directly: the real
    can_user_access_analysis_run(), which needs a `projects` table
    this module's minimal schema doesn't create, was observed running
    when one thread's `finally` restored the original mid-flight while
    another thread's call was still in progress). Setting it once,
    before any thread starts, and leaving it in place for the whole
    concurrent run removes that race entirely."""
    import services.analysis_history_repository as repo
    import services.websearch_quota_reservation as wq

    monkeypatch.setattr(
        repo,
        "load_db_settings",
        lambda: type("S", (), {"database_url": database_url, "save_enabled": True})(),
    )
    monkeypatch.setattr(
        wq, "can_user_access_analysis_run", lambda conn, user_id, analysis_run_id: True
    )


def _reserve(
    *,
    analysis_run_id,
    project_id,
    user_id="user-1",
    metric="openai_websearch",
    async_worker_id=None,
):
    import services.websearch_quota_reservation as wq

    return wq.reserve_websearch_quota_for_analysis_run(
        analysis_run_id=analysis_run_id,
        project_id=project_id,
        user_id=user_id,
        metric=metric,
        async_worker_id=async_worker_id,
    )


def _set_quota_env(monkeypatch, *, daily: int, monthly: int, metric_suffix: str = "OPENAI_WEBSEARCH"):
    monkeypatch.setenv(f"ANALYZE_QUOTA_MAX_PROJECT_DAILY_{metric_suffix}", str(daily))
    monkeypatch.setenv(f"ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_{metric_suffix}", str(monthly))


def test_reservation_succeeds_when_both_daily_and_monthly_have_room(monkeypatch, db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    result = _reserve(analysis_run_id=run_id, project_id=project_id)

    assert result.metric == "openai_websearch"
    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    assert rows == {"daily": 1, "monthly": 1}


def test_default_zero_limit_rejects_the_reservation(monkeypatch, db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    for name in (
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI_WEBSEARCH",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_OPENAI_WEBSEARCH",
    ):
        monkeypatch.delenv(name, raising=False)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.AnalysisQuotaExceededError):
        _reserve(analysis_run_id=run_id, project_id=project_id)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_usage_counters")
        (row_count,) = cur.fetchone()
    assert row_count == 0


def test_daily_limit_exceeded_leaves_no_partial_counter_rows(monkeypatch, db_connection):
    """The core "no partial state" claim: daily is already exhausted
    (limit 1, already at 1), monthly still has room — the whole
    reservation must be rejected, and the monthly counter must NOT
    have been incremented either."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=1, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    # Pre-exhaust the daily counter directly.
    import services.analysis_history_repository as repo

    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_usage_counters "
            "(scope_type, scope_id, metric, period_type, period_start, count) "
            "values ('project', %s, 'openai_websearch', 'daily', %s, 1)",
            (project_id, repo.daily_period_start()),
        )

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.AnalysisQuotaExceededError) as excinfo:
        _reserve(analysis_run_id=run_id, project_id=project_id)
    assert excinfo.value.period_type == "daily"

    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    # Daily stays at its pre-exhausted 1 (never incremented past the
    # limit); monthly was never created at all — proving the rejection
    # happened strictly before any monthly increment, not after one
    # that then got rolled back.
    assert rows == {"daily": 1}

    # The reservation-marker insert (migration 010) that happened
    # earlier in the same transaction must have rolled back too — no
    # stray row for this run/metric.
    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s and metric = 'openai_websearch'",
            (run_id,),
        )
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 0


def test_monthly_limit_exceeded_leaves_no_partial_counter_rows(monkeypatch, db_connection):
    """Mirror of the above with the limits swapped: daily has room,
    monthly is already exhausted — daily must not end up incremented
    either, since the whole reservation is one transaction."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=1)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    import services.analysis_history_repository as repo

    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_usage_counters "
            "(scope_type, scope_id, metric, period_type, period_start, count) "
            "values ('project', %s, 'openai_websearch', 'monthly', %s, 1)",
            (project_id, repo.monthly_period_start()),
        )

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.AnalysisQuotaExceededError) as excinfo:
        _reserve(analysis_run_id=run_id, project_id=project_id)
    assert excinfo.value.period_type == "monthly"

    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    # Sorted key order (scope_type, scope_id, metric, period_type) in
    # _reserve_usage_counters() means "daily" is attempted before
    # "monthly" alphabetically — proving daily's own successful
    # INSERT gets rolled back too once monthly then fails.
    assert rows == {"monthly": 1}

    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s and metric = 'openai_websearch'",
            (run_id,),
        )
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 0


def test_concurrent_reservations_never_exceed_the_daily_limit(db_connection, monkeypatch):
    """The real test this module exists for: fire genuinely concurrent
    reservation attempts (real threads, real separate PostgreSQL
    connections) against the same project+metric with a daily limit of
    3, and assert exactly 3 succeed while the rest are rejected — the
    aggregate cap is never exceeded even under real concurrency."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=3, monthly=100)
    project_id = str(uuid.uuid4())
    run_ids = [_insert_running_run(conn, schema, project_id) for _ in range(10)]

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def worker(run_id):
        import services.websearch_quota_reservation as wq

        try:
            result = _reserve(analysis_run_id=run_id, project_id=project_id)
            with lock:
                results.append(result)
        except wq.AnalysisQuotaExceededError as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(run_id,)) for run_id in run_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 3, f"expected exactly 3 successful reservations, got {len(results)}"
    assert len(errors) == 7

    with conn.cursor() as cur:
        cur.execute(
            f"select count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' and period_type = 'daily'"
        )
        (final_count,) = cur.fetchone()
    assert final_count == 3


def test_run_belonging_to_a_different_project_is_rejected_and_reserves_nothing(
    monkeypatch, db_connection
):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    real_project_id = str(uuid.uuid4())
    other_project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, real_project_id)

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaRunNotFoundError):
        _reserve(analysis_run_id=run_id, project_id=other_project_id)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_usage_counters")
        (row_count,) = cur.fetchone()
    assert row_count == 0


def test_a_non_running_run_is_rejected_and_reserves_nothing(monkeypatch, db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_runs (project_id, status) "
            "values (%s, 'completed') returning id",
            (project_id,),
        )
        (run_id,) = cur.fetchone()

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaRunNotRunningError):
        _reserve(analysis_run_id=str(run_id), project_id=project_id)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_usage_counters")
        (row_count,) = cur.fetchone()
    assert row_count == 0


def test_the_existing_project_and_provider_counters_are_unaffected(monkeypatch, db_connection):
    """Task 6-D-2B item 5 / this task's "既存機能の保護": reserving a
    websearch metric must never touch the pre-existing
    "all_analyses"/"openai"/"anthropic"/"google" counter rows for the
    same project."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    import services.analysis_history_repository as repo

    with conn.cursor() as cur:
        cur.execute(
            f"insert into {schema}.analysis_usage_counters "
            "(scope_type, scope_id, metric, period_type, period_start, count) "
            "values ('project', %s, 'openai', 'daily', %s, 7)",
            (project_id, repo.daily_period_start()),
        )

    _reserve(analysis_run_id=run_id, project_id=project_id)

    with conn.cursor() as cur:
        cur.execute(
            f"select count from {schema}.analysis_usage_counters "
            "where metric = 'openai' and period_type = 'daily'"
        )
        (openai_count,) = cur.fetchone()
    assert openai_count == 7


# --- duplicate-reservation prevention (migration 010) -----------------


def test_a_second_reservation_for_the_same_run_and_metric_is_rejected(monkeypatch, db_connection):
    """Task 6-D-2B follow-up item 6: once (analysis_run_id, metric) has
    been reserved, a second attempt must be rejected and must not
    increment the counters again."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    first = _reserve(analysis_run_id=run_id, project_id=project_id)
    assert first.metric == "openai_websearch"

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaAlreadyReservedError):
        _reserve(analysis_run_id=run_id, project_id=project_id)

    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    # Still exactly 1 each — the second (rejected) attempt never
    # incremented either counter a second time.
    assert rows == {"daily": 1, "monthly": 1}

    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s and metric = 'openai_websearch'",
            (run_id,),
        )
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 1


def test_concurrent_reservations_for_the_same_run_and_metric_only_one_succeeds(
    monkeypatch, db_connection
):
    """The other real test this module exists for: fire 10 genuinely
    concurrent reservation attempts (real threads, real separate
    PostgreSQL connections) for the exact same (analysis_run_id,
    metric), and assert exactly 1 succeeds while the other 9 are
    rejected as WebsearchQuotaAlreadyReservedError — never two
    "first" reservations, and the counters end up incremented exactly
    once, not 10 times."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    results: list = []
    errors: list = []
    lock = threading.Lock()

    def worker():
        import services.websearch_quota_reservation as wq

        try:
            result = _reserve(analysis_run_id=run_id, project_id=project_id)
            with lock:
                results.append(result)
        except wq.WebsearchQuotaAlreadyReservedError as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 1, f"expected exactly 1 successful reservation, got {len(results)}"
    assert len(errors) == 9

    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    assert rows == {"daily": 1, "monthly": 1}

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_run_websearch_reservations")
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 1


def test_a_different_run_can_independently_reserve_the_same_metric(monkeypatch, db_connection):
    """Task 6-D-2B follow-up item 10: reservations are scoped per-run,
    not globally per-metric — a second, different run must be able to
    reserve the same metric independently of the first."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    run_id_1 = _insert_running_run(conn, schema, project_id)
    run_id_2 = _insert_running_run(conn, schema, project_id)

    first = _reserve(analysis_run_id=run_id_1, project_id=project_id)
    second = _reserve(analysis_run_id=run_id_2, project_id=project_id)

    assert first.analysis_run_id != second.analysis_run_id

    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'openai_websearch' order by period_type"
        )
        rows = dict(cur.fetchall())
    # Both runs' reservations share the same project-scoped daily/
    # monthly counters (by design — the cap is per project+metric, not
    # per run) — two independent successful reservations means count=2.
    assert rows == {"daily": 2, "monthly": 2}

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_run_websearch_reservations")
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 2


def test_the_same_run_can_independently_reserve_a_different_provider(monkeypatch, db_connection):
    """Task 6-D-2B follow-up item 10: the dedup marker is keyed by
    (analysis_run_id, metric) together — the same run reserving a
    *different* provider's websearch metric must succeed
    independently of its first reservation."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50, metric_suffix="OPENAI_WEBSEARCH")
    _set_quota_env(monkeypatch, daily=50, monthly=50, metric_suffix="ANTHROPIC_WEBSEARCH")
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    first = _reserve(analysis_run_id=run_id, project_id=project_id, metric="openai_websearch")
    second = _reserve(analysis_run_id=run_id, project_id=project_id, metric="anthropic_websearch")

    assert first.metric == "openai_websearch"
    assert second.metric == "anthropic_websearch"

    with conn.cursor() as cur:
        cur.execute(
            f"select metric, count(*) from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s group by metric",
            (run_id,),
        )
        rows = dict(cur.fetchall())
    assert rows == {"openai_websearch": 1, "anthropic_websearch": 1}


def test_a_db_error_during_the_reservation_rolls_back_cleanly(monkeypatch, db_connection):
    """Task 6-D-2B follow-up item 9: a genuine DB-level failure partway
    through must leave neither the reservation marker nor either
    counter behind. Simulated here by dropping
    analysis_usage_counters *after* the reservation-marker insert
    would otherwise succeed, forcing _reserve_usage_counters() itself
    to fail with a real PostgreSQL error."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=50, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    with conn.cursor() as cur:
        cur.execute(f"drop table {schema}.analysis_usage_counters")

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaReservationError):
        _reserve(analysis_run_id=run_id, project_id=project_id)

    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s",
            (run_id,),
        )
        (reservation_count,) = cur.fetchone()
    assert reservation_count == 0


def test_gemini_external_document_metric_is_accepted_after_migration_011(monkeypatch, db_connection):
    """Task 6-D-4C-2: proves migrations/011_add_gemini_external_document_metric.sql's
    widened CHECK constraint actually accepts the new
    'gemini_external_document' metric against a real PostgreSQL
    instance — reserve_websearch_quota_for_analysis_run() needed no
    other code change to support it (only WEBSEARCH_METRICS in
    services/websearch_quota_reservation.py and this migration)."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50, metric_suffix="GEMINI_EXTERNAL_DOCUMENT")
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    result = _reserve(
        analysis_run_id=run_id, project_id=project_id, metric="gemini_external_document"
    )

    assert result.metric == "gemini_external_document"
    with conn.cursor() as cur:
        cur.execute(
            f"select period_type, count from {schema}.analysis_usage_counters "
            "where metric = 'gemini_external_document' order by period_type"
        )
        rows = dict(cur.fetchall())
    assert rows == {"daily": 1, "monthly": 1}
    with conn.cursor() as cur:
        cur.execute(
            f"select metric from {schema}.analysis_run_websearch_reservations "
            "where analysis_run_id = %s",
            (run_id,),
        )
        (metric,) = cur.fetchone()
    assert metric == "gemini_external_document"


def test_gemini_external_document_metric_rejects_a_second_reservation_for_the_same_run(
    monkeypatch, db_connection
):
    """Same double-reservation protection the original three metrics
    already get (migration 010's own primary-key guarantee) — this
    confirms the new metric is not somehow exempt from it."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50, metric_suffix="GEMINI_EXTERNAL_DOCUMENT")
    project_id = str(uuid.uuid4())
    run_id = _insert_running_run(conn, schema, project_id)

    _reserve(analysis_run_id=run_id, project_id=project_id, metric="gemini_external_document")

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaAlreadyReservedError):
        _reserve(analysis_run_id=run_id, project_id=project_id, metric="gemini_external_document")

    with conn.cursor() as cur:
        cur.execute(
            f"select count from {schema}.analysis_usage_counters "
            "where metric = 'gemini_external_document' and period_type = 'daily'"
        )
        (count,) = cur.fetchone()
    assert count == 1


# --- Task 6-D-5C-4G (feature/async-analysis-supplements): async lease
# validation, added inside this same transaction --------------------------
#
# These are the tests that can only be trusted against a real
# PostgreSQL instance (per this task's own "Python側で事前SELECTした
# だけで『原子的に安全』と判断しない" instruction) — a mocked test can
# confirm the Python-level branching but cannot prove the `for update`
# row lock actually serializes against a genuinely concurrent writer;
# see test_for_update_serializes_against_a_concurrent_lease_change
# below for the one test that does.


def test_async_reservation_succeeds_with_a_valid_matching_lease(monkeypatch, db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=180
    )

    result = _reserve(analysis_run_id=run_id, project_id=project_id, async_worker_id="worker-A")

    assert result.metric == "openai_websearch"


def test_async_reservation_rejected_when_lease_already_expired(monkeypatch, db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    # Negative lease_seconds -> lease_expires_at already in the past —
    # `status` is still 'running' (nothing has swept it yet), which is
    # exactly the pre-existing gap this task closes: the old code
    # would have accepted this.
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=-60
    )

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        _reserve(analysis_run_id=run_id, project_id=project_id, async_worker_id="worker-A")

    with conn.cursor() as cur:
        cur.execute(
            f"select count(*) from {schema}.analysis_usage_counters where metric = 'openai_websearch'"
        )
        (count,) = cur.fetchone()
    assert count == 0


def test_async_reservation_rejected_on_worker_id_mismatch(monkeypatch, db_connection):
    """Whether this means "a different worker now legitimately owns
    it" or "this worker's own stale belief about a lease it no longer
    holds" is indistinguishable from here — both correctly reject (see
    WebsearchQuotaLeaseInvalidError's own docstring)."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=180
    )

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        _reserve(analysis_run_id=run_id, project_id=project_id, async_worker_id="worker-B")


def test_async_reservation_rejected_when_lease_is_null(monkeypatch, db_connection):
    """A 'running' row with a null lease (e.g. a pre-migration-006 row,
    or a locked_by set by something other than the worker's own claim
    path) must never be treated as "owned" by any async_worker_id."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=None
    )

    import services.websearch_quota_reservation as wq

    with pytest.raises(wq.WebsearchQuotaLeaseInvalidError):
        _reserve(analysis_run_id=run_id, project_id=project_id, async_worker_id="worker-A")


def test_sync_call_with_no_async_worker_id_ignores_lease_entirely(monkeypatch, db_connection):
    """The exact same leased-but-expired row that
    test_async_reservation_rejected_when_lease_already_expired rejects
    must still succeed for a synchronous caller (async_worker_id
    omitted) — this is the explicit regression guard for "既存の同期
    処理は、現在の契約を維持する"."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=-60
    )

    result = _reserve(analysis_run_id=run_id, project_id=project_id)  # async_worker_id omitted

    assert result.metric == "openai_websearch"


def test_for_update_serializes_against_a_concurrent_lease_change(monkeypatch, db_connection):
    """Proves the row-level lock this task's `for update` added is
    what actually makes the lease check race-safe — not merely "a
    Python SELECT followed by a Python if-check" (explicitly not
    trusted as atomic on its own per this task's own instructions). A
    second, fully independent connection's plain UPDATE on the exact
    same row (the same shape extend_analysis_job_lease() or
    fail_expired_running_analysis_runs() would issue, with no advisory
    lock of its own) must block until the reservation's own
    transaction commits, never interleave with it."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    _patch_db_and_access(monkeypatch, database_url)
    _set_quota_env(monkeypatch, daily=5, monthly=50)
    project_id = str(uuid.uuid4())
    run_id = _insert_leased_run(
        conn, schema, project_id, locked_by="worker-A", lease_seconds=180
    )

    import services.analysis_history_repository as repo

    original_reserve_counters = repo._reserve_usage_counters
    proceed_with_reservation = threading.Event()

    def delayed_reserve_counters(cur, requirements):
        # By the time this runs, the `for update` SELECT inside
        # reserve_websearch_quota_for_analysis_run() has already taken
        # the row lock — giving the concurrent UPDATE below a chance
        # to attempt (and block on) it before this transaction
        # commits.
        proceed_with_reservation.wait(timeout=5)
        return original_reserve_counters(cur, requirements)

    monkeypatch.setattr(repo, "_reserve_usage_counters", delayed_reserve_counters)

    events: list[str] = []

    def concurrent_lease_clearing_update():
        import psycopg

        with psycopg.connect(database_url, autocommit=True) as conn2:
            with conn2.cursor() as cur2:
                events.append("update_attempt_started")
                cur2.execute(
                    f"update {schema}.analysis_runs set locked_by = 'worker-B' "
                    "where id = %s",
                    (run_id,),
                )
        events.append("update_completed")

    updater = threading.Thread(target=concurrent_lease_clearing_update)
    updater.start()
    updater.join(timeout=0.3)  # the UPDATE should still be blocked on the row lock
    assert "update_completed" not in events
    assert "update_attempt_started" in events

    proceed_with_reservation.set()
    result = _reserve(analysis_run_id=run_id, project_id=project_id, async_worker_id="worker-A")
    updater.join(timeout=5)

    assert result.metric == "openai_websearch"
    assert events == ["update_attempt_started", "update_completed"]
