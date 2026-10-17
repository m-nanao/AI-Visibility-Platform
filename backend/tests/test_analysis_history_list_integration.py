"""DB integration tests for list_analysis_runs()/count_analysis_runs()'s
server-side search/important-filter/date-range/sort/pagination
(feature/history-server-side-search-pagination) against a REAL
PostgreSQL instance — the previous implementation only ever filtered/
sorted the single already-fetched page client-side, so a match past
that page could never be found; this file exists to prove the new
server-side behavior actually works against a real database, not just
a mocked cursor (see tests/test_analysis_history_repository.py for the
mocked, sequential-only unit tests of the same functions).

Requires a `TEST_DATABASE_URL` environment variable pointing at a
disposable PostgreSQL database (e.g.
`postgresql://localhost:5544/analysis_jobs_test`) — never
`DATABASE_URL` itself, so this file can never accidentally run against
whatever database `DATABASE_URL` happens to point at in a given
environment. The whole module is skipped with an explicit reason when
`TEST_DATABASE_URL` is unset.

Creates its own minimal `brands`/`analysis_runs`/`analysis_results`
schema (001_initial_analysis_history.sql + 002's `project_id` + 003's
`deleted_at` + 004's `is_important` — the columns these two functions
actually touch) in a dedicated schema that is dropped after each test,
rather than depending on a shared fixture database. No Supabase
connection of any kind is made by this file.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason=(
        "TEST_DATABASE_URL is not set — no local PostgreSQL/docker is "
        "configured in this environment. These tests were written but "
        "never executed; run them against a disposable PostgreSQL "
        "instance before relying on this module's search/pagination "
        "correctness claims."
    ),
)


@pytest.fixture
def db_connection():
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"history_list_test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"create schema {schema}")
        cur.execute(f"set search_path to {schema}")
        cur.execute("create extension if not exists pgcrypto")
        cur.execute(
            """
            create table brands (
                id uuid primary key default gen_random_uuid(),
                name text not null,
                canonical_domain text,
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
                source_summary jsonb,
                started_at timestamptz,
                completed_at timestamptz,
                error_message text,
                deleted_at timestamptz,
                is_important boolean not null default false,
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table analysis_results (
                id uuid primary key default gen_random_uuid(),
                analysis_run_id uuid not null references analysis_runs(id),
                visibility_score integer,
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


def _patched_repo(database_url):
    import services.analysis_history_repository as repo

    original = repo.load_db_settings
    repo.load_db_settings = lambda: type(
        "S", (), {"database_url": database_url, "save_enabled": True}
    )()
    return repo, original


def _insert_run(
    conn,
    schema,
    *,
    brand_name,
    project_id=None,
    status="completed",
    urls=None,
    started_at=None,
    created_at=None,
    is_important=False,
    deleted_at=None,
):
    with conn.cursor() as cur:
        cur.execute(f"set search_path to {schema}")
        cur.execute(
            "insert into brands (name, project_id) values (%s, %s) returning id",
            (brand_name, project_id),
        )
        (brand_id,) = cur.fetchone()

        input_snapshot = {"brandName": brand_name, "urls": urls or []}
        columns = [
            "brand_id",
            "project_id",
            "status",
            "input_snapshot",
            "is_important",
            "deleted_at",
        ]
        values = [brand_id, project_id, status, _jsonb(input_snapshot), is_important, deleted_at]
        if started_at is not None:
            columns.append("started_at")
            values.append(started_at)
        if created_at is not None:
            columns.append("created_at")
            values.append(created_at)

        placeholders = ", ".join(["%s"] * len(values))
        cur.execute(
            f"insert into analysis_runs ({', '.join(columns)}) values ({placeholders}) returning id",
            values,
        )
        (run_id,) = cur.fetchone()

        cur.execute(
            "insert into analysis_results (analysis_run_id, result_json) values (%s, %s)",
            (run_id, _jsonb({})),
        )
    return str(run_id)


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def test_search_finds_a_match_past_the_first_page(db_connection):
    """The exact bug this task fixes: with more than one page's worth
    of history, a brand name that only appears on (what used to be)
    page 2 must still be found."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        for i in range(25):
            _insert_run(conn, schema, brand_name=f"ブランド{i:02d}")
        _insert_run(conn, schema, brand_name="サイボウズ")  # the 26th row

        total = repo.count_analysis_runs(search="サイボウズ")
        items = repo.list_analysis_runs(search="サイボウズ", limit=20, offset=0)

        assert total == 1
        assert len(items) == 1
        assert items[0]["brandName"] == "サイボウズ"
    finally:
        repo.load_db_settings = original


def test_search_is_case_insensitive_and_partial(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(conn, schema, brand_name="Cybozu Inc.")
        _insert_run(conn, schema, brand_name="Other Co.")

        items = repo.list_analysis_runs(search="CYBOZU")

        assert [item["brandName"] for item in items] == ["Cybozu Inc."]
    finally:
        repo.load_db_settings = original


def test_search_matches_domain_in_urls(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(
            conn, schema, brand_name="A社", urls=["https://www.cybozu.co.jp/"]
        )
        _insert_run(conn, schema, brand_name="B社", urls=["https://example.com/"])

        items = repo.list_analysis_runs(search="cybozu.co.jp")

        assert [item["brandName"] for item in items] == ["A社"]
    finally:
        repo.load_db_settings = original


def test_important_filter_matches_only_important_rows(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(conn, schema, brand_name="重要", is_important=True)
        _insert_run(conn, schema, brand_name="通常", is_important=False)

        important_only = repo.list_analysis_runs(important=True)
        everything = repo.list_analysis_runs(important=None)

        assert [item["brandName"] for item in important_only] == ["重要"]
        assert len(everything) == 2
    finally:
        repo.load_db_settings = original


def test_date_range_filters_inclusive_from_exclusive_to(db_connection):
    """JST calendar-date semantics land here as already-resolved,
    timezone-aware instants (see main.py's _parse_history_list_boundary()
    and app/lib/analysis-history.ts's jstDateStringToRangeBoundary() on
    the frontend side) — this only proves the >=/< comparison itself is
    correct once given those instants."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(
            conn,
            schema,
            brand_name="Before",
            started_at=datetime(2026, 9, 30, 23, 59, 59, tzinfo=timezone.utc),
        )
        _insert_run(
            conn,
            schema,
            brand_name="InRange",
            started_at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        _insert_run(
            conn,
            schema,
            brand_name="OnExclusiveBoundary",
            started_at=datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc),
        )

        items = repo.list_analysis_runs(
            started_from=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            started_to=datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc),
        )

        assert [item["brandName"] for item in items] == ["InRange"]
    finally:
        repo.load_db_settings = original


def test_started_at_null_falls_back_to_created_at_for_date_filtering(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(
            conn,
            schema,
            brand_name="NoStartedAt",
            created_at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
        )

        items = repo.list_analysis_runs(
            started_from=datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc),
            started_to=datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc),
        )

        assert [item["brandName"] for item in items] == ["NoStartedAt"]
    finally:
        repo.load_db_settings = original


def test_sort_newest_and_oldest(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(
            conn, schema, brand_name="Oldest",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        _insert_run(
            conn, schema, brand_name="Newest",
            started_at=datetime(2026, 12, 1, tzinfo=timezone.utc),
        )

        newest_first = repo.list_analysis_runs(sort="newest")
        oldest_first = repo.list_analysis_runs(sort="oldest")

        assert [item["brandName"] for item in newest_first] == ["Newest", "Oldest"]
        assert [item["brandName"] for item in oldest_first] == ["Oldest", "Newest"]
    finally:
        repo.load_db_settings = original


def test_sort_is_stable_across_pages_for_identical_timestamps(db_connection):
    """Rows sharing the exact same `started_at` must still paginate
    deterministically (no row ever duplicated on two pages or skipped
    entirely) — the `ar.id` tie-breaker is what guarantees this."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        same_timestamp = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            _insert_run(conn, schema, brand_name=f"Tied{i:02d}", started_at=same_timestamp)

        page1 = repo.list_analysis_runs(limit=5, offset=0, sort="newest")
        page2 = repo.list_analysis_runs(limit=5, offset=5, sort="newest")

        page1_ids = {item["id"] for item in page1}
        page2_ids = {item["id"] for item in page2}
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1_ids.isdisjoint(page2_ids)  # no row appears on both pages
    finally:
        repo.load_db_settings = original


def test_multiple_conditions_combine_as_and(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(
            conn, schema, brand_name="サイボウズA", is_important=True,
            started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        # Matches search, but not important -> excluded.
        _insert_run(
            conn, schema, brand_name="サイボウズB", is_important=False,
            started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        # Important and in range, but doesn't match search -> excluded.
        _insert_run(
            conn, schema, brand_name="他社", is_important=True,
            started_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

        items = repo.list_analysis_runs(
            search="サイボウズ",
            important=True,
            started_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
            started_to=datetime(2026, 11, 1, tzinfo=timezone.utc),
        )

        assert [item["brandName"] for item in items] == ["サイボウズA"]
    finally:
        repo.load_db_settings = original


def test_pagination_total_matches_count_across_full_page_set(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        for i in range(25):
            _insert_run(conn, schema, brand_name=f"ブランド{i:02d}")

        total = repo.count_analysis_runs()
        page1 = repo.list_analysis_runs(limit=20, offset=0)
        page2 = repo.list_analysis_runs(limit=20, offset=20)

        assert total == 25
        assert len(page1) == 20
        assert len(page2) == 5
        all_ids = {item["id"] for item in page1} | {item["id"] for item in page2}
        assert len(all_ids) == 25  # every row seen exactly once across both pages
    finally:
        repo.load_db_settings = original


def test_soft_deleted_rows_are_excluded_from_both_list_and_count(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(conn, schema, brand_name="Visible")
        _insert_run(
            conn, schema, brand_name="Deleted", deleted_at=datetime.now(timezone.utc)
        )

        items = repo.list_analysis_runs()
        total = repo.count_analysis_runs()

        assert [item["brandName"] for item in items] == ["Visible"]
        assert total == 1
    finally:
        repo.load_db_settings = original


def test_project_scoping_excludes_other_projects_from_both_list_and_count(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        _insert_run(conn, schema, brand_name="MyProject", project_id="11111111-1111-1111-1111-111111111111")
        _insert_run(conn, schema, brand_name="OtherProject", project_id="22222222-2222-2222-2222-222222222222")

        items = repo.list_analysis_runs(project_ids=["11111111-1111-1111-1111-111111111111"])
        total = repo.count_analysis_runs(project_ids=["11111111-1111-1111-1111-111111111111"])

        assert [item["brandName"] for item in items] == ["MyProject"]
        assert total == 1
    finally:
        repo.load_db_settings = original
