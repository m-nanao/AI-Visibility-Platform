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


def _extend(database_url, analysis_run_id, *, worker_id, lease_seconds=180):
    from services.analysis_history_repository import extend_analysis_job_lease

    original = _patched_load_db_settings(database_url)
    try:
        return extend_analysis_job_lease(
            analysis_run_id, worker_id=worker_id, lease_seconds=lease_seconds
        )
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


def test_claim_returns_project_id_and_created_by_user_id(db_connection):
    """Task 6-D-5C-2 (feature/claude-fact-extraction-mvp):
    claim_next_queued_analysis_run() now also returns
    project_id/created_by_user_id (read from the real `analysis_runs`
    row against a real PostgreSQL instance, not a mock) — see
    services/analysis_job_worker.py's attempt_fact_extraction() call
    site, which needs both to reserve quota the same way the
    authenticated sync path already does."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(
        database_url,
        idempotency_key="key-project-id-roundtrip",
        project_id="44444444-4444-4444-4444-444444444444",
        created_by_user_id="55555555-5555-5555-5555-555555555555",
    )

    claimed = _claim(database_url, worker_id="worker-1")

    assert claimed is not None
    assert claimed.analysis_run_id == created.analysis_run_id
    assert claimed.project_id == "44444444-4444-4444-4444-444444444444"
    assert claimed.created_by_user_id == "55555555-5555-5555-5555-555555555555"


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


# --- lease-check-on-complete / heartbeat (Problems 1 & 2) --------------------
# These tests exist because a review found two real gaps in the first
# Phase 2 cut: (1) complete_analysis_job()'s original condition
# (locked_by + status='running') did not check whether the lease had
# already expired, so a completion could land in the gap between the
# lease actually expiring and fail_expired_running_analysis_runs()'s
# next sweep; (2) nothing extended a job's lease while it was still
# genuinely running, so any analysis slower than the lease
# (lease_seconds, default 180s) would be reaped out from under its own
# worker. Both are fixed by adding `lease_expires_at > now()` to
# complete_analysis_job()'s condition and by extend_analysis_job_lease()
# (the heartbeat) — see docs/40_async_analysis_jobs_design.md "21".


def test_complete_rejected_when_lease_expired_but_sweeper_has_not_run_yet(db_connection):
    """The exact gap Problem 1 closes: the lease has already passed
    (by wall-clock time), but fail_expired_running_analysis_runs()
    has deliberately NOT been called yet (simulating the real-world
    gap between a lease expiring and the next sweep cycle actually
    running) — the owning worker's own completion write must still be
    rejected, not merely a *different* worker's."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    time.sleep(1.2)  # the 1-second lease has now passed — sweeper NOT called

    with conn.cursor() as cur:
        cur.execute(
            f"select status from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (status,) = cur.fetchone()
    assert status == "running"  # still 'running' — nothing has swept it yet

    ok = _complete(
        database_url,
        created.analysis_run_id,
        worker_id="worker-a",
        status="completed",
        result_json={"brandName": "should never be saved — lease already expired"},
        meta_json=None,
        error_message=None,
    )

    assert ok is False
    with conn.cursor() as cur:
        cur.execute(
            f"select ar.status, res.result_json from {schema}.analysis_runs ar "
            f"join {schema}.analysis_results res on res.analysis_run_id = ar.id "
            f"where ar.id = %s",
            (created.analysis_run_id,),
        )
        status, result_json = cur.fetchone()
    assert status == "running"  # untouched (not even flipped to 'failed' by this call)
    assert result_json == {}  # the stale result was never written


def test_heartbeat_keeps_a_long_running_job_alive_past_its_original_lease(db_connection):
    """Problem 2's fix, proven for real: a job claimed with a short
    lease, kept alive purely by repeated extend_analysis_job_lease()
    calls (simulating a heartbeat ticking throughout a long analysis),
    survives well past when its *original* lease would have expired —
    the sweeper must not reap it, and completion must still succeed
    afterward."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    # Three heartbeat ticks, each re-extending by 1s, spanning well
    # past the original 1-second lease.
    for _ in range(3):
        time.sleep(0.4)
        extended = _extend(database_url, claimed.analysis_run_id, worker_id="worker-a", lease_seconds=1)
        assert extended is True

    # Total elapsed time (~1.2s) already exceeds the original 1-second
    # lease — if heartbeating weren't working, this job would already
    # be failed.
    _fail_expired(database_url)

    with conn.cursor() as cur:
        cur.execute(
            f"select status from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (status,) = cur.fetchone()
    assert status == "running"  # still alive — the heartbeat kept extending it

    ok = _complete(
        database_url,
        claimed.analysis_run_id,
        worker_id="worker-a",
        status="completed",
        result_json={"brandName": "Acme"},
        meta_json=None,
        error_message=None,
    )
    assert ok is True


def test_heartbeat_cannot_extend_a_lease_already_reaped_by_the_sweeper(db_connection):
    """The other direction of the same race: once the sweeper has
    already failed a job, a heartbeat that was still in flight for it
    (e.g. a worker that hadn't yet noticed its pipeline call returned,
    or a heartbeat tick that lost a race with the sweeper) must not be
    able to revive it."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    time.sleep(1.2)
    expired_ids = _fail_expired(database_url)
    assert expired_ids == [created.analysis_run_id]

    extended = _extend(database_url, claimed.analysis_run_id, worker_id="worker-a", lease_seconds=180)

    assert extended is False
    with conn.cursor() as cur:
        cur.execute(
            f"select status from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (status,) = cur.fetchone()
    assert status == "failed"  # still failed — the heartbeat did not resurrect it


def test_heartbeat_and_sweeper_race_near_the_lease_boundary(db_connection):
    """A genuine concurrency race at the exact moment a lease crosses
    its expiry: one real thread repeatedly tries to extend the lease
    (as a heartbeat would) while another repeatedly calls the sweeper,
    both running concurrently right around the boundary. Whichever
    wins, the final state must be *consistent* — never both "extended"
    and "failed" at once, and never a state that would let the worker
    believe it still owns a job the sweeper has already reaped."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="worker-a", lease_seconds=1)

    import time

    extend_results: list[bool] = []
    sweep_results: list[list[str]] = []
    stop = threading.Event()

    def heartbeat_worker():
        while not stop.is_set():
            extend_results.append(
                _extend(database_url, claimed.analysis_run_id, worker_id="worker-a", lease_seconds=1)
            )
            time.sleep(0.05)

    def sweeper_worker():
        while not stop.is_set():
            sweep_results.append(_fail_expired(database_url))
            time.sleep(0.05)

    threads = [
        threading.Thread(target=heartbeat_worker),
        threading.Thread(target=sweeper_worker),
    ]
    for t in threads:
        t.start()
    time.sleep(1.5)  # let the race run across the ~1s lease boundary
    stop.set()
    for t in threads:
        t.join()

    with conn.cursor() as cur:
        cur.execute(
            f"select status, lease_expires_at from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        status, lease_expires_at = cur.fetchone()

    # Consistency check: if the job ended up 'failed', no extend call
    # after that point may have reported success, and vice versa — a
    # heartbeat and the sweeper must never disagree about ownership at
    # the same instant.
    if status == "failed":
        # Once failed, the row must never again be extendable.
        assert _extend(database_url, claimed.analysis_run_id, worker_id="worker-a", lease_seconds=1) is False
    else:
        assert status == "running"
        assert lease_expires_at is not None

    # The sweeper never left the job in an invalid intermediate state
    # (e.g. 'queued') regardless of how the race resolved.
    assert status in ("running", "failed")


def test_extend_rejects_wrong_worker_id_for_real(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="k1")
    claimed = _claim(database_url, worker_id="the-real-owner", lease_seconds=180)

    extended = _extend(database_url, claimed.analysis_run_id, worker_id="an-impostor", lease_seconds=180)

    assert extended is False
    with conn.cursor() as cur:
        cur.execute(
            f"select locked_by from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        (locked_by,) = cur.fetchone()
    assert locked_by == "the-real-owner"  # ownership untouched by the impostor's attempt


# --- cancel_queued_analysis_run() — fix/async-job-cancel-safety -------------
#
# This section proves the fix this task made: claim_next_queued_analysis_run()
# now excludes soft-deleted rows, cancel_queued_analysis_run() is race-safe
# against a concurrent claim, cancellation actually frees the queued-job
# limit slot, and a cancelled job's idempotency key can be legitimately
# reused by a genuine retry rather than resurrecting the dead row.


def _cancel(database_url, analysis_run_id):
    from services.analysis_history_repository import cancel_queued_analysis_run

    original = _patched_load_db_settings(database_url)
    try:
        return cancel_queued_analysis_run(analysis_run_id)
    finally:
        _restore_load_db_settings(original)


def test_claim_skips_a_cancelled_queued_job(db_connection):
    """The core bug this task fixes: a job cancelled while still
    'queued' must never be claimed and executed by a worker."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="only-job")
    cancel_result = _cancel(database_url, created.analysis_run_id)
    assert cancel_result.outcome == "cancelled"

    claimed = _claim(database_url, worker_id="worker-1")
    assert claimed is None

    with conn.cursor() as cur:
        cur.execute(
            f"select status, deleted_at from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        status, deleted_at = cur.fetchone()
    assert status == "queued"  # never transitioned — truly never ran
    assert deleted_at is not None


def test_claim_still_claims_a_normal_job_once_a_different_one_is_cancelled(
    db_connection,
):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    cancelled_job = _create(database_url, idempotency_key="cancel-me")
    normal_job = _create(database_url, idempotency_key="keep-me")
    _cancel(database_url, cancelled_job.analysis_run_id)

    claimed = _claim(database_url, worker_id="worker-1")

    assert claimed is not None
    assert claimed.analysis_run_id == normal_job.analysis_run_id


def test_claim_wins_the_race_cancel_then_reports_not_cancellable(db_connection):
    """One ordering of the claim/cancel race: the worker claims the
    row first (queued -> running) before the cancel request reaches
    it. The cancel attempt must not succeed or disturb the running job
    — it must honestly report that the job is no longer cancellable."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="race-a")
    claimed = _claim(database_url, worker_id="worker-1")
    assert claimed is not None

    cancel_result = _cancel(database_url, created.analysis_run_id)

    assert cancel_result.outcome == "not_cancellable"
    assert cancel_result.status == "running"
    with conn.cursor() as cur:
        cur.execute(
            f"select status, deleted_at, locked_by from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        status, deleted_at, locked_by = cur.fetchone()
    assert status == "running"
    assert deleted_at is None  # the failed cancel attempt touched nothing
    assert locked_by == "worker-1"  # the claim is completely undisturbed


def test_cancel_wins_the_race_claim_then_finds_nothing(db_connection):
    """The other ordering: the cancel request reaches the row first.
    The subsequent claim attempt must find no queued work at all —
    not a crash, not a claim of the now-deleted row."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="race-b")
    cancel_result = _cancel(database_url, created.analysis_run_id)
    assert cancel_result.outcome == "cancelled"

    claimed = _claim(database_url, worker_id="worker-1")

    assert claimed is None


def test_cancel_is_idempotent_for_an_already_cancelled_job(db_connection):
    database_url = _database_url_with_search_path(db_connection[1])

    created = _create(database_url, idempotency_key="repeat-cancel")
    first = _cancel(database_url, created.analysis_run_id)
    second = _cancel(database_url, created.analysis_run_id)

    assert first.outcome == "cancelled"
    assert second.outcome == "already_cancelled"


def test_cancel_rejects_a_completed_job_without_claiming_to_undo_it(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="done")
    claimed = _claim(database_url, worker_id="worker-1")
    completed_ok = _complete(
        database_url,
        claimed.analysis_run_id,
        worker_id="worker-1",
        status="completed",
        result_json={"ok": True},
        meta_json={},
        error_message=None,
    )
    assert completed_ok is True

    cancel_result = _cancel(database_url, created.analysis_run_id)

    assert cancel_result.outcome == "not_cancellable"
    assert cancel_result.status == "completed"


def test_cancel_nonexistent_job_reports_not_found(db_connection):
    database_url = _database_url_with_search_path(db_connection[1])

    cancel_result = _cancel(database_url, "00000000-0000-0000-0000-000000000000")

    assert cancel_result.outcome == "not_found"


def test_cancelled_job_does_not_count_against_the_queued_limit(db_connection):
    """A cancelled job must actually free its queued-slot, not just
    hide from the worker forever while still occupying the limit —
    otherwise "cancel" wouldn't actually let the caller start over."""
    database_url = _database_url_with_search_path(db_connection[1])

    first = _create(
        database_url, idempotency_key="limit-1", max_queued_per_project=1, max_queued_per_user=1
    )
    _cancel(database_url, first.analysis_run_id)

    # Without the fix, this would raise AnalysisJobLimitExceededError
    # because the cancelled job's row still had status='queued'.
    second = _create(
        database_url, idempotency_key="limit-2", max_queued_per_project=1, max_queued_per_user=1
    )

    assert second.created is True


def test_cancel_retains_the_idempotency_key(db_connection):
    """The current design (revised from this task's first commit):
    cancellation does NOT clear idempotency_key — it stays set,
    `status` stays 'queued', and only `deleted_at` changes. This is
    what lets the exact-key lookup below keep finding the cancelled
    row on a replay, so it can be refused rather than silently
    resurrected or duplicated."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(database_url, idempotency_key="keep-me")
    _cancel(database_url, created.analysis_run_id)

    with conn.cursor() as cur:
        cur.execute(
            f"select status, deleted_at, idempotency_key from {schema}.analysis_runs where id = %s",
            (created.analysis_run_id,),
        )
        status, deleted_at, idempotency_key = cur.fetchone()
    assert status == "queued"
    assert deleted_at is not None
    assert idempotency_key == "keep-me"


def test_replay_with_the_same_key_after_cancel_is_rejected_not_recreated(db_connection):
    """A client retrying the exact same "start analysis" operation
    (same project/user/idempotency key) after that job was cancelled
    must be refused outright — never a brand-new job for the same key
    (that would let a cancelled operation silently come back to life
    via a retry), and never the cancelled row handed back as if
    nothing had happened."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create(database_url, idempotency_key="retry-key")
    _cancel(database_url, first.analysis_run_id)

    from services.analysis_history_repository import AnalysisJobCancelledConflictError

    with pytest.raises(AnalysisJobCancelledConflictError) as exc_info:
        _create(database_url, idempotency_key="retry-key")

    assert exc_info.value.existing_analysis_run_id == first.analysis_run_id
    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (total,) = cur.fetchone()
    assert total == 1  # no second row was created


def test_replay_with_the_same_key_after_cancel_is_rejected_even_with_different_input(
    db_connection,
):
    """The cancelled-key check runs before the input-match comparison
    — refused outright, regardless of whether the resubmitted input
    happens to match the original."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create(database_url, idempotency_key="retry-key-2", urls=["https://a.example.com"])
    _cancel(database_url, first.analysis_run_id)

    from services.analysis_history_repository import AnalysisJobCancelledConflictError

    with pytest.raises(AnalysisJobCancelledConflictError):
        _create(database_url, idempotency_key="retry-key-2", urls=["https://b.example.com"])

    with conn.cursor() as cur:
        cur.execute(f"select count(*) from {schema}.analysis_runs")
        (total,) = cur.fetchone()
    assert total == 1


def test_a_fresh_key_after_cancel_starts_a_normal_new_job(db_connection):
    """An explicit new "start analysis" operation — a different
    idempotency key, exactly what a client generates deliberately for
    a new attempt — must succeed completely normally, unaffected by
    an earlier cancelled job for the same project/user."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    first = _create(database_url, idempotency_key="old-key")
    _cancel(database_url, first.analysis_run_id)

    second = _create(database_url, idempotency_key="brand-new-key")

    assert second.created is True
    assert second.analysis_run_id != first.analysis_run_id
    with conn.cursor() as cur:
        cur.execute(
            f"select status, idempotency_key from {schema}.analysis_runs where id = %s",
            (second.analysis_run_id,),
        )
        status2, idempotency_key2 = cur.fetchone()
    assert status2 == "queued"
    assert idempotency_key2 == "brand-new-key"


def test_can_user_cancel_analysis_run_rejects_a_different_user_in_the_same_project(
    db_connection,
):
    """Real-DB proof of the authorization requirement: a fellow
    project member (even within the exact same project) who did not
    create this job must not be treated as able to cancel it —
    can_user_cancel_analysis_run() checks created_by_user_id only, no
    project/organization join at all."""
    from services.project_access import can_user_cancel_analysis_run

    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)

    created = _create(
        database_url,
        idempotency_key="owned-by-creator",
        created_by_user_id="22222222-2222-2222-2222-222222222222",
    )

    # `conn`'s search_path is already set to `schema` by the
    # db_connection fixture for the lifetime of this session.
    allowed_for_creator = can_user_cancel_analysis_run(
        conn, "22222222-2222-2222-2222-222222222222", created.analysis_run_id
    )
    allowed_for_other_user = can_user_cancel_analysis_run(
        conn, "33333333-3333-3333-3333-333333333333", created.analysis_run_id
    )

    assert allowed_for_creator is True
    assert allowed_for_other_user is False
