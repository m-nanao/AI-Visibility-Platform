"""DB integration tests for create_queued_analysis_run() against a
REAL PostgreSQL instance — the only kind of test that can actually
prove the advisory-lock + unique-index design
(services.analysis_history_repository.create_queued_analysis_run(),
see docs/40_async_analysis_jobs_design.md "10"/"11") is safe under
genuine concurrency. Every other test in this backend (including
tests/test_analysis_jobs_repository.py) mocks psycopg and therefore
runs everything sequentially in one Python thread — a fake cursor has
no real locking/isolation semantics to get wrong, so it cannot be used
to claim concurrency safety. This file exists so that claim is backed
by something real whenever a PostgreSQL instance is actually
available, and is explicit about not making that claim otherwise.

Requires a `TEST_DATABASE_URL` environment variable pointing at a
disposable PostgreSQL database (e.g.
`postgresql://localhost:5544/analysis_jobs_test`) — never
`DATABASE_URL` itself, so this file can never accidentally run against
whatever database `DATABASE_URL` happens to point at in a given
environment. The whole module is skipped with an explicit reason when
`TEST_DATABASE_URL` is unset.

**This module HAS been executed, against a real local PostgreSQL, as
part of implementing the fix in this task** (the original Phase 1 task
had no PostgreSQL/docker available and shipped this file unexecuted —
see git history). Reproduction, from `backend/`:

```
# one-time setup (macOS + Homebrew; adjust for your platform)
brew install postgresql@16
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@16/bin/pg_ctl \
    -D /opt/homebrew/var/postgresql@16 -l /tmp/pg_test.log -o "-p 5544" start
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@16/bin/createdb -p 5544 analysis_jobs_test

# run the tests
export TEST_DATABASE_URL="postgresql://localhost:5544/analysis_jobs_test"
pytest tests/test_analysis_jobs_repository_integration.py -v

# teardown
LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@16/bin/pg_ctl \
    -D /opt/homebrew/var/postgresql@16 stop
```

All 7 tests in this module passed against that real instance,
including — critically — the two tests that exercise the fix this
task made (`test_concurrent_create_same_user_different_projects_respects_user_limit`
/ `test_concurrent_create_same_project_different_users_respects_project_limit`):
the former was confirmed to actually *fail* (10/10 concurrent requests
succeeded instead of the intended 3) when the user-scoped advisory
lock was temporarily removed from create_queued_analysis_run(), and
pass again once it was restored — this is not a vacuous assertion.
`analysis_jobs_test` only ever existed on `localhost:5544` for the
duration of this task; it has been dropped and the local PostgreSQL
service stopped. No Supabase connection of any kind was made.

This migration (005_async_analysis_jobs_phase1.sql) was deliberately
written with no foreign key to `auth.users` (see that file's header),
specifically so it — unlike 002_add_organizations_projects.sql — can
be applied to a plain local/CI PostgreSQL instance with no
Supabase-managed auth schema. This test module creates its own
minimal `brands`/`analysis_runs`/`analysis_results` schema (the
columns Phase 1 actually touches, matching
001_initial_analysis_history.sql + 002's `project_id` +
005's two new columns) in a dedicated schema that is dropped after
each test, rather than depending on organizations/projects/
organization_members — this file is about Phase 1's job-table logic,
not the separate (and already-tested — see tests/test_project_access.py)
project-membership machinery.
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
        "TEST_DATABASE_URL is not set — no local PostgreSQL/docker is "
        "configured in this environment (confirmed during Phase 1 "
        "implementation: no psql/pg_ctl/docker binary, no psycopg "
        "driver installed). These tests were written but never "
        "executed; run them against a disposable PostgreSQL instance "
        "before relying on this module's concurrency-safety claims."
    ),
)


@pytest.fixture
def db_connection():
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"analysis_jobs_test_{uuid.uuid4().hex[:8]}"
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
    try:
        yield conn, schema
    finally:
        with conn.cursor() as cur:
            cur.execute(f"drop schema {schema} cascade")
        conn.close()


def _database_url_with_search_path(schema: str) -> str:
    separator = "&" if "?" in TEST_DATABASE_URL else "?"
    return f"{TEST_DATABASE_URL}{separator}options=-csearch_path%3D{schema}"


def _create(database_url, **overrides):
    from services.analysis_history_repository import create_queued_analysis_run, load_db_settings
    import services.analysis_history_repository as repo

    base = dict(
        project_id="11111111-1111-1111-1111-111111111111",
        created_by_user_id="22222222-2222-2222-2222-222222222222",
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
        max_queued_per_project=100,
        max_queued_per_user=100,
    )
    base.update(overrides)

    original_load = repo.load_db_settings
    repo.load_db_settings = lambda: type(
        "S", (), {"database_url": database_url, "save_enabled": True}
    )()
    try:
        return create_queued_analysis_run(**base)
    finally:
        repo.load_db_settings = original_load


def test_concurrent_create_with_same_idempotency_key_creates_exactly_one_job(
    db_connection,
):
    """The real test this module exists for: fire N genuinely
    concurrent create_queued_analysis_run() calls (real threads, real
    separate PostgreSQL connections) with the *same* idempotency key,
    and assert exactly one `analysis_runs` row exists afterwards — the
    advisory lock (pg_advisory_xact_lock keyed on project_id) must
    serialize them, and the unique index is the final backstop even if
    it didn't."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    results: list = []
    errors: list = []

    def worker():
        try:
            results.append(_create(database_url))
        except Exception as exc:  # noqa: BLE001 - recording for assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"unexpected errors: {errors}"
    assert len(results) == 8

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 1

    analysis_run_ids = {r.analysis_run_id for r in results}
    assert len(analysis_run_ids) == 1
    assert sum(1 for r in results if r.created) == 1


def test_concurrent_create_with_different_keys_creates_separate_jobs(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    results: list = []

    def worker(key):
        results.append(_create(database_url, idempotency_key=key))

    threads = [
        threading.Thread(target=worker, args=(f"key-{i}",)) for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 5
    assert all(r.created for r in results)


def test_create_then_replay_with_different_input_conflicts(db_connection):
    from services.analysis_history_repository import AnalysisJobCreateConflictError

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    _create(database_url)

    with pytest.raises(AnalysisJobCreateConflictError):
        _create(database_url, urls=["https://different.example.com"])


def test_concurrent_create_same_user_different_projects_respects_user_limit(
    db_connection,
):
    """The scenario the two-advisory-lock fix (project lock + user
    lock, see create_queued_analysis_run()'s docstring) exists for:
    one user firing genuinely concurrent requests across *different*
    projects must still never exceed their own queued-job limit. A
    project-only lock cannot protect this check, since each request
    takes a different project-scoped lock and none of them would ever
    block each other — the user-scoped lock is what serializes the
    count-then-insert across projects."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    user_id = "33333333-3333-3333-3333-333333333333"
    results: list = []
    errors: list = []

    def worker(i):
        try:
            results.append(
                _create(
                    database_url,
                    project_id=f"44444444-4444-4444-4444-44444444440{i}",
                    created_by_user_id=user_id,
                    idempotency_key=f"key-{i}",
                    max_queued_per_project=100,
                    max_queued_per_user=3,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    from services.analysis_history_repository import AnalysisJobLimitExceededError

    assert len(results) == 3, f"expected exactly 3 successes, got {len(results)}"
    assert len(errors) == 7
    assert all(isinstance(e, AnalysisJobLimitExceededError) for e in errors)
    assert all(e.scope == "user" for e in errors)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 3


def test_concurrent_create_same_project_different_users_respects_project_limit(
    db_connection,
):
    """Mirror of the above for the project-scoped limit: several
    different users hitting the *same* project concurrently must
    never collectively exceed that project's queued-job limit."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    project_id = "55555555-5555-5555-5555-555555555555"
    results: list = []
    errors: list = []

    def worker(i):
        try:
            results.append(
                _create(
                    database_url,
                    project_id=project_id,
                    created_by_user_id=f"66666666-6666-6666-6666-66666666660{i}",
                    idempotency_key=f"key-{i}",
                    max_queued_per_project=2,
                    max_queued_per_user=100,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    from services.analysis_history_repository import AnalysisJobLimitExceededError

    assert len(results) == 2, f"expected exactly 2 successes, got {len(results)}"
    assert len(errors) == 8
    assert all(isinstance(e, AnalysisJobLimitExceededError) for e in errors)
    assert all(e.scope == "project" for e in errors)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 2


def test_limit_exceeded_rolls_back_cleanly_and_does_not_block_later_retry(
    db_connection,
):
    """Verifies the failed attempt's transaction actually rolled back
    (not just that this process didn't crash): after a
    AnalysisJobLimitExceededError, the exact same request (same key)
    must still succeed once the limit is no longer in the way — a
    leftover partial write from the failed attempt would either make
    this retry see a pre-existing (wrong) row or fail a constraint it
    shouldn't."""
    from services.analysis_history_repository import AnalysisJobLimitExceededError

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create(database_url, idempotency_key="key-1", max_queued_per_project=1)
    assert first.created is True

    with pytest.raises(AnalysisJobLimitExceededError):
        _create(database_url, idempotency_key="key-2", max_queued_per_project=1)

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 1, "the failed attempt must not have left a partial row behind"

    second = _create(database_url, idempotency_key="key-2", max_queued_per_project=100)
    assert second.created is True
    assert second.analysis_run_id != first.analysis_run_id

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 2


def test_migration_005_preserves_existing_history_and_enforces_idempotency():
    """Applies the *actual* migration file
    (backend/migrations/005_async_analysis_jobs_phase1.sql) verbatim
    against a schema shaped like the pre-005 production schema (001's
    analysis_runs + 002's project_id, no auth.users dependency so this
    can run on plain local PostgreSQL — see module docstring), with a
    pre-existing "legacy" row already in it (simulating real history
    saved by today's synchronous POST /analyze, which never sets
    created_by_user_id/idempotency_key). Confirms:
    - the legacy row's columns are completely unchanged (migration is
      additive only).
    - the two new columns exist and are NULL on the legacy row.
    - two more NULL-idempotency_key rows can coexist (the partial
      unique index must not apply to NULL, matching the file's `where
      idempotency_key is not null` header comment).
    - a genuine duplicate (project_id, created_by_user_id,
      idempotency_key) *does* violate the new index.
    """
    import psycopg
    from psycopg.errors import UniqueViolation

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"analysis_jobs_migration_test_{uuid.uuid4().hex[:8]}"
    try:
        with conn.cursor() as cur:
            cur.execute(f"create schema {schema}")
            cur.execute(f"set search_path to {schema}")
            cur.execute("create extension if not exists pgcrypto")
            # Pre-005 shape: 001's analysis_runs + 002's project_id,
            # minus everything that depends on a Supabase-managed
            # auth schema (organizations/projects/organization_members
            # themselves aren't needed for this migration's own
            # columns/index to be meaningfully tested).
            cur.execute(
                """
                create table brands (
                    id uuid primary key default gen_random_uuid(),
                    name text not null,
                    canonical_domain text,
                    project_id uuid,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now()
                )
                """
            )
            cur.execute(
                """
                create table analysis_runs (
                    id uuid primary key default gen_random_uuid(),
                    brand_id uuid not null references brands(id) on delete cascade,
                    project_id uuid,
                    status text not null,
                    input_snapshot jsonb not null,
                    source_summary jsonb,
                    started_at timestamptz not null default now(),
                    completed_at timestamptz,
                    error_message text,
                    deleted_at timestamptz,
                    is_important boolean not null default false,
                    created_at timestamptz not null default now(),
                    updated_at timestamptz not null default now(),
                    constraint analysis_runs_status_check check (
                        status in ('queued', 'running', 'completed', 'partial', 'failed')
                    )
                )
                """
            )
            cur.execute(
                """
                create table analysis_results (
                    id uuid primary key default gen_random_uuid(),
                    analysis_run_id uuid not null references analysis_runs(id) on delete cascade,
                    visibility_score integer,
                    result_json jsonb not null,
                    meta_json jsonb,
                    created_at timestamptz not null default now()
                )
                """
            )

            # A pre-existing "legacy" row — exactly what today's
            # synchronous save_analysis_history() writes (no
            # created_by_user_id/idempotency_key concept at all).
            cur.execute(
                """
                insert into brands (name, project_id) values ('Legacy Brand', %s)
                returning id
                """,
                ("77777777-7777-7777-7777-777777777777",),
            )
            (legacy_brand_id,) = cur.fetchone()
            cur.execute(
                """
                insert into analysis_runs (brand_id, project_id, status, input_snapshot)
                values (%s, %s, 'completed', '{"brandName": "Legacy Brand"}')
                returning id, status, project_id
                """,
                (legacy_brand_id, "77777777-7777-7777-7777-777777777777"),
            )
            legacy_row_before = cur.fetchone()

            # Apply the real migration file, verbatim, exactly as a
            # reviewer would against a real database.
            migration_path = os.path.join(
                os.path.dirname(__file__), "..", "migrations",
                "005_async_analysis_jobs_phase1.sql",
            )
            with open(migration_path, encoding="utf-8") as f:
                migration_sql = f.read()
            cur.execute(migration_sql)

            # The legacy row is completely unaffected.
            cur.execute(
                "select id, status, project_id, created_by_user_id, idempotency_key "
                "from analysis_runs where id = %s",
                (legacy_row_before[0],),
            )
            legacy_row_after = cur.fetchone()
            assert legacy_row_after[0] == legacy_row_before[0]
            assert legacy_row_after[1] == legacy_row_before[1] == "completed"
            assert legacy_row_after[2] == legacy_row_before[2]
            assert legacy_row_after[3] is None
            assert legacy_row_after[4] is None

            # Two more NULL-idempotency_key rows for the same project
            # coexist fine — the partial index doesn't apply to them.
            cur.execute(
                """
                insert into analysis_runs (brand_id, project_id, status, input_snapshot)
                values (%s, %s, 'completed', '{}'), (%s, %s, 'completed', '{}')
                """,
                (
                    legacy_brand_id,
                    "77777777-7777-7777-7777-777777777777",
                    legacy_brand_id,
                    "77777777-7777-7777-7777-777777777777",
                ),
            )

            # A genuine duplicate (project_id, created_by_user_id,
            # idempotency_key) *does* violate the new index.
            cur.execute(
                """
                insert into analysis_runs
                    (brand_id, project_id, status, input_snapshot,
                     created_by_user_id, idempotency_key)
                values (%s, %s, 'queued', '{}', %s, %s)
                """,
                (
                    legacy_brand_id,
                    "77777777-7777-7777-7777-777777777777",
                    "88888888-8888-8888-8888-888888888888",
                    "dup-key",
                ),
            )
            with pytest.raises(UniqueViolation):
                cur.execute(
                    """
                    insert into analysis_runs
                        (brand_id, project_id, status, input_snapshot,
                         created_by_user_id, idempotency_key)
                    values (%s, %s, 'queued', '{}', %s, %s)
                    """,
                    (
                        legacy_brand_id,
                        "77777777-7777-7777-7777-777777777777",
                        "88888888-8888-8888-8888-888888888888",
                        "dup-key",
                    ),
                )
            conn.rollback()
    finally:
        with conn.cursor() as cur:
            cur.execute(f"drop schema if exists {schema} cascade")
        conn.close()


# --- Phase 2 worker functions (claim/complete/fail_expired) ----------------
# — migration 006's locked_by/locked_at/lease_expires_at/attempt_count
# columns are included in the db_connection fixture's schema above (see
# its create table analysis_runs statement) — this section proves the
# real safety properties a mocked test cannot:
# claim_next_queued_analysis_run()'s `for update skip locked` under
# genuine concurrency, and complete_analysis_job()'s stale-worker
# rejection under a genuine race between two real connections.


class _PatchedDbSettings:
    def __init__(self, database_url):
        self.database_url = database_url
        self.save_enabled = True


def _patched_load_db_settings(database_url):
    import services.analysis_history_repository as repo

    original = repo.load_db_settings
    repo.load_db_settings = lambda: _PatchedDbSettings(database_url)
    return original


def _restore_load_db_settings(original):
    import services.analysis_history_repository as repo

    repo.load_db_settings = original


def _claim(database_url, *, worker_id, lease_seconds=180):
    from services.analysis_history_repository import claim_next_queued_analysis_run

    original = _patched_load_db_settings(database_url)
    try:
        return claim_next_queued_analysis_run(worker_id=worker_id, lease_seconds=lease_seconds)
    finally:
        _restore_load_db_settings(original)


def _complete(database_url, analysis_run_id, **kwargs):
    from services.analysis_history_repository import complete_analysis_job

    original = _patched_load_db_settings(database_url)
    try:
        return complete_analysis_job(analysis_run_id, **kwargs)
    finally:
        _restore_load_db_settings(original)


def _fail_expired(database_url):
    from services.analysis_history_repository import fail_expired_running_analysis_runs

    original = _patched_load_db_settings(database_url)
    try:
        return fail_expired_running_analysis_runs()
    finally:
        _restore_load_db_settings(original)


def test_concurrent_claim_by_many_workers_each_gets_a_distinct_job(db_connection):
    """The scenario claim_next_queued_analysis_run()'s `for update
    skip locked` exists for: with several queued jobs and several
    workers polling concurrently (real threads, real separate
    PostgreSQL connections), every job must be claimed by exactly one
    worker — no job claimed twice, no worker left idle while a job
    sits unclaimed."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    for i in range(6):
        _create(database_url, idempotency_key=f"key-{i}")

    claims: list = []
    lock = threading.Lock()

    def worker(worker_id):
        result = _claim(database_url, worker_id=worker_id)
        if result is not None:
            with lock:
                claims.append((worker_id, result.analysis_run_id))

    threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claims) == 6
    claimed_run_ids = [run_id for _worker_id, run_id in claims]
    assert len(set(claimed_run_ids)) == 6  # every job claimed exactly once

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs where status = 'running'")
        (running_count,) = cur.fetchone()
    assert running_count == 6


def test_claim_with_more_workers_than_jobs_leaves_extras_empty_handed(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    _create(database_url, idempotency_key="only-job")

    results: list = []
    lock = threading.Lock()

    def worker(worker_id):
        result = _claim(database_url, worker_id=worker_id)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    non_none = [r for r in results if r is not None]
    assert len(non_none) == 1


def test_complete_job_atomically_saves_result_and_updates_status(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="w1")
    assert claimed.analysis_run_id == created.analysis_run_id

    ok = _complete(
        database_url,
        created.analysis_run_id,
        worker_id="w1",
        status="completed",
        result_json={"brandName": "Acme"},
        meta_json={"sections": {}},
        error_message=None,
    )
    assert ok is True

    with conn.cursor() as cur:
        cur.execute(
            f"select ar.status, res.result_json, res.meta_json "
            f"from {schema}.analysis_runs ar "
            f"join {schema}.analysis_results res on res.analysis_run_id = ar.id "
            f"where ar.id = %s",
            (created.analysis_run_id,),
        )
        status, result_json, meta_json = cur.fetchone()

    assert status == "completed"
    assert result_json == {"brandName": "Acme"}
    assert meta_json == {"sections": {}}

    # No new analysis_runs row was created by completing this job.
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (row_count,) = cur.fetchone()
    assert row_count == 1


def test_stale_worker_cannot_overwrite_a_job_reclaimed_after_lease_expiry(db_connection):
    """The real race complete_analysis_job()'s `locked_by = worker_id
    and status = 'running'` condition exists to prevent: worker A
    claims a job, its lease expires, fail_expired_running_analysis_runs()
    reaps it to 'failed' — and *then* worker A (unaware its lease is
    gone) tries to save a result. That late write must be discarded,
    never overwriting the 'failed' state with stale data."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    time.sleep(1.2)  # let the 1-second lease actually expire

    expired_ids = _fail_expired(database_url)
    assert expired_ids == [created.analysis_run_id]

    with conn.cursor() as cur:
        cur.execute(
            f"select status from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (status,) = cur.fetchone()
    assert status == "failed"

    # worker-a, unaware its lease already expired, now tries to save
    # its (late) result.
    ok = _complete(
        database_url,
        claimed.analysis_run_id,
        worker_id="worker-a",
        status="completed",
        result_json={"brandName": "too late, should never be saved"},
        meta_json=None,
        error_message=None,
    )

    assert ok is False
    with conn.cursor() as cur:
        cur.execute(
            f"select ar.status, res.result_json "
            f"from {schema}.analysis_runs ar "
            f"join {schema}.analysis_results res on res.analysis_run_id = ar.id "
            f"where ar.id = %s",
            (created.analysis_run_id,),
        )
        status, result_json = cur.fetchone()
    assert status == "failed"  # still failed, not resurrected to 'completed'
    assert result_json == {}  # the stale result was never written


def test_fail_expired_never_requeues_an_abandoned_job(db_connection):
    """Explicit real-DB regression guard for docs/40 "11.4": an
    abandoned job (expired lease) must become 'failed', never
    'queued' again — the whole point is that this backend cannot
    safely assume a full automatic re-run is free of duplicate paid
    API calls."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    time.sleep(1.2)

    _fail_expired(database_url)

    with conn.cursor() as cur:
        cur.execute(
            f"select status from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (status,) = cur.fetchone()
    assert status == "failed"
    assert status != "queued"


def test_migration_006_preserves_phase1_jobs_and_adds_lease_columns():
    """Applies the *actual* migration file
    (backend/migrations/006_async_analysis_jobs_phase2.sql) verbatim
    against a schema shaped like the post-005 database: a legacy
    synchronous-/analyze row, AND an already-existing Phase 1 'queued'
    job (created_by_user_id/idempotency_key set, no lease columns yet)
    — proving 006 is additive-only on top of 005, not just on top of
    001."""
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"analysis_jobs_migration006_test_{uuid.uuid4().hex[:8]}"
    try:
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
            # Post-005 shape: 001's analysis_runs + 002's project_id +
            # 005's created_by_user_id/idempotency_key — no lease
            # columns yet, exactly what a real database would look
            # like right before 006 is applied.
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
                    created_at timestamptz not null default now(),
                    constraint analysis_runs_status_check check (
                        status in ('queued', 'running', 'completed', 'partial', 'failed')
                    )
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

            cur.execute("insert into brands (name) values ('Legacy Brand') returning id")
            (brand_id,) = cur.fetchone()
            cur.execute(
                """
                insert into analysis_runs (brand_id, status, input_snapshot)
                values (%s, 'completed', '{"brandName": "Legacy Brand"}')
                returning id
                """,
                (brand_id,),
            )
            (legacy_run_id,) = cur.fetchone()

            cur.execute(
                """
                insert into analysis_runs
                    (brand_id, status, input_snapshot, created_by_user_id, idempotency_key)
                values (%s, 'queued', '{"brandName": "Phase1 Job"}',
                        '99999999-9999-9999-9999-999999999999', 'phase1-key')
                returning id
                """,
                (brand_id,),
            )
            (phase1_job_id,) = cur.fetchone()

            migration_path = os.path.join(
                os.path.dirname(__file__), "..", "migrations",
                "006_async_analysis_jobs_phase2.sql",
            )
            with open(migration_path, encoding="utf-8") as f:
                migration_sql = f.read()
            cur.execute(migration_sql)

            # The legacy row and the Phase 1 job are both unaffected,
            # and both get the new lease columns as null/0 defaults.
            cur.execute(
                "select status, locked_by, locked_at, lease_expires_at, attempt_count "
                "from analysis_runs where id = %s",
                (legacy_run_id,),
            )
            status, locked_by, locked_at, lease_expires_at, attempt_count = cur.fetchone()
            assert status == "completed"
            assert locked_by is None
            assert locked_at is None
            assert lease_expires_at is None
            assert attempt_count == 0

            cur.execute(
                "select status, created_by_user_id, idempotency_key, locked_by, attempt_count "
                "from analysis_runs where id = %s",
                (phase1_job_id,),
            )
            (
                status,
                created_by_user_id,
                idempotency_key,
                locked_by,
                attempt_count,
            ) = cur.fetchone()
            assert status == "queued"
            assert str(created_by_user_id) == "99999999-9999-9999-9999-999999999999"
            assert idempotency_key == "phase1-key"
            assert locked_by is None
            assert attempt_count == 0

            # The two new partial indexes exist.
            cur.execute(
                f"select indexname from pg_indexes where schemaname = %s "
                f"and tablename = 'analysis_runs'",
                (schema,),
            )
            index_names = {row[0] for row in cur.fetchall()}
            assert "idx_analysis_runs_status_created_at" in index_names
            assert "idx_analysis_runs_status_lease_expires_at" in index_names

            # Re-applying the migration is a no-op (idempotent).
            cur.execute(migration_sql)
    finally:
        with conn.cursor() as cur:
            cur.execute(f"drop schema if exists {schema} cascade")
        conn.close()
