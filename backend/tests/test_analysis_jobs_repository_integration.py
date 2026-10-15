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
`postgresql://postgres:postgres@localhost:5432/postgres`) — never
`DATABASE_URL` itself, so this file can never accidentally run against
whatever database `DATABASE_URL` happens to point at in a given
environment. The whole module is skipped with an explicit reason when
`TEST_DATABASE_URL` is unset, which is the case in the sandbox this
Phase 1 task was implemented in (confirmed: no `psql`/`pg_ctl`/`docker`
binary and no `psycopg` driver install available there at all) — this
module has NOT been executed as part of this task; it is provided so a
reviewer with local PostgreSQL/docker (or CI with a postgres service
container added) can run it before Phase 1 goes anywhere near a real
deployment.

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
