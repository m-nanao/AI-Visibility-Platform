"""DB integration tests for tags/categories (feature/history-tags-
categories) against a REAL PostgreSQL instance — see
backend/migrations/008_add_tags_and_categories.sql for the schema
under test. Mirrors tests/test_analysis_history_list_integration.py's
conventions exactly (self-contained, dropped-after-each-test schema;
skipped without TEST_DATABASE_URL), extended with `projects`/
`categories`/`tags`/`analysis_run_tags` and `analysis_runs.category_id`
so this file can exercise the composite FKs / CHECK constraint /
RESTRICT behavior that migration 008 actually adds — not just the
Python-level translation of a mocked exception (see
tests/test_tags_categories_repository.py for that).
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
        "instance before relying on this module's claims."
    ),
)


@pytest.fixture
def db_connection():
    import psycopg

    conn = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
    schema = f"tags_categories_test_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(f"create schema {schema}")
        cur.execute(f"set search_path to {schema}")
        cur.execute("create extension if not exists pgcrypto")
        cur.execute(
            """
            create table projects (
                id uuid primary key default gen_random_uuid(),
                name text not null
            )
            """
        )
        cur.execute(
            """
            create table brands (
                id uuid primary key default gen_random_uuid(),
                name text not null,
                canonical_domain text,
                project_id uuid references projects(id) on delete set null,
                created_at timestamptz not null default now()
            )
            """
        )
        cur.execute(
            """
            create table analysis_runs (
                id uuid primary key default gen_random_uuid(),
                brand_id uuid not null references brands(id),
                project_id uuid references projects(id) on delete set null,
                status text not null,
                input_snapshot jsonb not null,
                source_summary jsonb,
                started_at timestamptz,
                completed_at timestamptz,
                deleted_at timestamptz,
                is_important boolean not null default false,
                is_favorite boolean not null default false,
                created_at timestamptz not null default now(),
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
                analysis_run_id uuid not null references analysis_runs(id),
                visibility_score integer,
                result_json jsonb not null,
                meta_json jsonb,
                created_at timestamptz not null default now()
            )
            """
        )
        # --- migration 008's own schema, applied inline here ---------
        cur.execute(
            """
            create table categories (
                id uuid primary key default gen_random_uuid(),
                project_id uuid not null references projects(id) on delete restrict,
                name text not null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now(),
                constraint chk_categories_name_length check (char_length(btrim(name)) between 1 and 100),
                unique (id, project_id)
            )
            """
        )
        cur.execute(
            "create unique index uq_categories_project_name_ci "
            "on categories (project_id, lower(btrim(name)))"
        )
        cur.execute(
            """
            create table tags (
                id uuid primary key default gen_random_uuid(),
                project_id uuid not null references projects(id) on delete restrict,
                name text not null,
                created_at timestamptz not null default now(),
                updated_at timestamptz not null default now(),
                constraint chk_tags_name_length check (char_length(btrim(name)) between 1 and 100),
                unique (id, project_id)
            )
            """
        )
        cur.execute(
            "create unique index uq_tags_project_name_ci "
            "on tags (project_id, lower(btrim(name)))"
        )
        cur.execute(
            "alter table analysis_runs add constraint uq_analysis_runs_id_project unique (id, project_id)"
        )
        cur.execute("alter table analysis_runs add column category_id uuid")
        cur.execute(
            """
            alter table analysis_runs
              add constraint fk_analysis_runs_category_project
              foreign key (category_id, project_id)
              references categories(id, project_id)
              on delete set null (category_id)
            """
        )
        cur.execute(
            """
            alter table analysis_runs
              add constraint chk_analysis_runs_category_requires_project
              check (category_id is null or project_id is not null)
            """
        )
        cur.execute(
            """
            create table analysis_run_tags (
                analysis_run_id uuid not null,
                tag_id uuid not null,
                project_id uuid not null,
                created_at timestamptz not null default now(),
                primary key (analysis_run_id, tag_id),
                foreign key (analysis_run_id, project_id) references analysis_runs(id, project_id) on delete cascade,
                foreign key (tag_id, project_id) references tags(id, project_id) on delete cascade
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


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)


def _insert_project(conn, schema, *, name="Project"):
    with conn.cursor() as cur:
        cur.execute(f"set search_path to {schema}")
        cur.execute("insert into projects (name) values (%s) returning id", (name,))
        return str(cur.fetchone()[0])


def _insert_run(
    conn,
    schema,
    *,
    brand_name,
    project_id=None,
    status="completed",
    deleted_at=None,
    category_id=None,
):
    with conn.cursor() as cur:
        cur.execute(f"set search_path to {schema}")
        cur.execute(
            "insert into brands (name, project_id) values (%s, %s) returning id",
            (brand_name, project_id),
        )
        (brand_id,) = cur.fetchone()

        input_snapshot = {"brandName": brand_name, "urls": []}
        cur.execute(
            """
            insert into analysis_runs
                (brand_id, project_id, status, input_snapshot, deleted_at, category_id)
            values (%s, %s, %s, %s, %s, %s)
            returning id
            """,
            (brand_id, project_id, status, _jsonb(input_snapshot), deleted_at, category_id),
        )
        (run_id,) = cur.fetchone()

        cur.execute(
            "insert into analysis_results (analysis_run_id, result_json) values (%s, %s)",
            (run_id, _jsonb({})),
        )
    return str(run_id)


# --- Tag CRUD -------------------------------------------------------------


def test_create_and_list_tags(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)

        created = repo.create_tag(project_id=project_id, name="新規顧客")
        tags = repo.list_tags(project_id=project_id)

        assert created["name"] == "新規顧客"
        assert [t["id"] for t in tags] == [created["id"]]
    finally:
        repo.load_db_settings = original


def test_create_tag_rejects_case_and_whitespace_insensitive_duplicate(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        repo.create_tag(project_id=project_id, name="新規顧客")

        with pytest.raises(repo.TagNameConflictError):
            repo.create_tag(project_id=project_id, name="  新規顧客  ")
    finally:
        repo.load_db_settings = original


def test_create_tag_rejects_empty_and_overlong_name(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)

        with pytest.raises(repo.TagNameInvalidError):
            repo.create_tag(project_id=project_id, name="   ")
        with pytest.raises(repo.TagNameInvalidError):
            repo.create_tag(project_id=project_id, name="x" * 101)
    finally:
        repo.load_db_settings = original


def test_tags_are_isolated_between_projects(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_a = _insert_project(conn, schema, name="A")
        project_b = _insert_project(conn, schema, name="B")
        # Same name allowed in two different projects.
        repo.create_tag(project_id=project_a, name="共通タグ")
        repo.create_tag(project_id=project_b, name="共通タグ")

        tags_a = repo.list_tags(project_id=project_a)
        tags_b = repo.list_tags(project_id=project_b)

        assert len(tags_a) == 1
        assert len(tags_b) == 1
        assert tags_a[0]["projectId"] == project_a
        assert tags_b[0]["projectId"] == project_b
    finally:
        repo.load_db_settings = original


def test_rename_tag_preserves_run_association(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="旧名")
        run_id = _insert_run(conn, schema, brand_name="Brand", project_id=project_id)
        repo.attach_tag_to_analysis_run(run_id, tag["id"])

        repo.rename_tag(tag["id"], name="新名")
        items = repo.list_analysis_runs(tag_ids=[tag["id"]])

        assert len(items) == 1
        assert items[0]["tags"][0]["name"] == "新名"
    finally:
        repo.load_db_settings = original


def test_delete_tag_removes_association_but_not_the_run(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        run_id = _insert_run(conn, schema, brand_name="Brand", project_id=project_id)
        repo.attach_tag_to_analysis_run(run_id, tag["id"])

        deleted = repo.delete_tag(tag["id"])
        items = repo.list_analysis_runs()

        assert deleted is True
        matching = [item for item in items if item["id"] == run_id]
        assert len(matching) == 1
        assert matching[0]["tags"] == []
    finally:
        repo.load_db_settings = original


# --- Category CRUD ---------------------------------------------------------


def test_create_category_rejects_duplicate_and_invalid_names(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        repo.create_category(project_id=project_id, name="製品A")

        with pytest.raises(repo.CategoryNameConflictError):
            repo.create_category(project_id=project_id, name=" 製品a ".upper().strip())
        with pytest.raises(repo.CategoryNameInvalidError):
            repo.create_category(project_id=project_id, name="")
    finally:
        repo.load_db_settings = original


def test_delete_category_sets_runs_uncategorized_without_deleting_them(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        category = repo.create_category(project_id=project_id, name="製品A")
        run_id = _insert_run(
            conn, schema, brand_name="Brand", project_id=project_id, category_id=category["id"]
        )

        deleted = repo.delete_category(category["id"])
        items = repo.list_analysis_runs()
        matching = [item for item in items if item["id"] == run_id]

        assert deleted is True
        assert len(matching) == 1
        assert matching[0]["category"] is None
    finally:
        repo.load_db_settings = original


def test_category_cannot_be_set_from_a_different_project(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_a = _insert_project(conn, schema, name="A")
        project_b = _insert_project(conn, schema, name="B")
        category_b = repo.create_category(project_id=project_b, name="製品B")
        run_in_a = _insert_run(conn, schema, brand_name="Brand", project_id=project_a)

        with pytest.raises(repo.CategoryNotAssignableError):
            repo.set_analysis_run_category(run_in_a, category_b["id"])
    finally:
        repo.load_db_settings = original


def test_category_requires_project_check_constraint(db_connection):
    """The CHECK constraint this task added specifically for the
    nullable-project_id gap: a run with no project can never be given
    a category, regardless of which one."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        category = repo.create_category(project_id=project_id, name="製品A")
        run_without_project = _insert_run(conn, schema, brand_name="Brand", project_id=None)

        with pytest.raises(repo.CategoryRequiresProjectError):
            repo.set_analysis_run_category(run_without_project, category["id"])
    finally:
        repo.load_db_settings = original


def test_tag_cannot_be_attached_from_a_different_project(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_a = _insert_project(conn, schema, name="A")
        project_b = _insert_project(conn, schema, name="B")
        tag_b = repo.create_tag(project_id=project_b, name="タグB")
        run_in_a = _insert_run(conn, schema, brand_name="Brand", project_id=project_a)

        with pytest.raises(repo.TagNotAssignableError):
            repo.attach_tag_to_analysis_run(run_in_a, tag_b["id"])
    finally:
        repo.load_db_settings = original


def test_project_deletion_is_restricted_while_categories_or_tags_exist(db_connection):
    """Verifies migration 008's fix for the real PG17-reproduced
    dangling-reference hazard: categories.project_id/tags.project_id
    are ON DELETE RESTRICT, not CASCADE, so deleting a project that
    still has a category or tag is rejected outright rather than
    silently leaving a dangling analysis_runs.category_id behind."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        repo.create_category(project_id=project_id, name="製品A")

        with conn.cursor() as cur, pytest.raises(Exception):
            cur.execute(f"set search_path to {schema}")
            cur.execute("delete from projects where id = %s", (project_id,))
    finally:
        repo.load_db_settings = original


# --- Filtering: tags OR, category exact-match, uncategorized-only --------


def test_tag_ids_filter_is_or_match(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag_1 = repo.create_tag(project_id=project_id, name="タグ1")
        tag_2 = repo.create_tag(project_id=project_id, name="タグ2")
        tag_3 = repo.create_tag(project_id=project_id, name="タグ3")
        run_1 = _insert_run(conn, schema, brand_name="Run1", project_id=project_id)
        run_2 = _insert_run(conn, schema, brand_name="Run2", project_id=project_id)
        run_3 = _insert_run(conn, schema, brand_name="Run3", project_id=project_id)
        repo.attach_tag_to_analysis_run(run_1, tag_1["id"])
        repo.attach_tag_to_analysis_run(run_2, tag_2["id"])
        repo.attach_tag_to_analysis_run(run_3, tag_3["id"])

        items = repo.list_analysis_runs(tag_ids=[tag_1["id"], tag_2["id"]])
        total = repo.count_analysis_runs(tag_ids=[tag_1["id"], tag_2["id"]])

        assert {item["id"] for item in items} == {run_1, run_2}
        assert total == 2
    finally:
        repo.load_db_settings = original


def test_category_id_filter_exact_match(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        category = repo.create_category(project_id=project_id, name="製品A")
        other_category = repo.create_category(project_id=project_id, name="製品B")
        run_in_category = _insert_run(
            conn, schema, brand_name="InCat", project_id=project_id, category_id=category["id"]
        )
        _insert_run(
            conn, schema, brand_name="InOtherCat", project_id=project_id, category_id=other_category["id"]
        )

        items = repo.list_analysis_runs(category_id=category["id"])

        assert [item["id"] for item in items] == [run_in_category]
    finally:
        repo.load_db_settings = original


def test_uncategorized_only_filter(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        category = repo.create_category(project_id=project_id, name="製品A")
        uncategorized_run = _insert_run(conn, schema, brand_name="Uncat", project_id=project_id)
        _insert_run(
            conn, schema, brand_name="Cat", project_id=project_id, category_id=category["id"]
        )

        items = repo.list_analysis_runs(uncategorized_only=True)

        assert [item["id"] for item in items] == [uncategorized_run]
    finally:
        repo.load_db_settings = original


def test_tags_and_category_combine_with_important_as_and(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        category = repo.create_category(project_id=project_id, name="製品A")

        with conn.cursor() as cur:
            cur.execute(f"set search_path to {schema}")
            cur.execute(
                "insert into brands (name, project_id) values (%s, %s) returning id",
                ("Brand", project_id),
            )
            (brand_id,) = cur.fetchone()
            cur.execute(
                """
                insert into analysis_runs
                    (brand_id, project_id, status, input_snapshot, is_important, category_id)
                values (%s, %s, 'completed', %s, true, %s)
                returning id
                """,
                (brand_id, project_id, _jsonb({}), category["id"]),
            )
            (matching_run_id,) = cur.fetchone()
            cur.execute(
                "insert into analysis_results (analysis_run_id, result_json) values (%s, %s)",
                (matching_run_id, _jsonb({})),
            )
        repo.attach_tag_to_analysis_run(str(matching_run_id), tag["id"])

        # A second run with the tag but NOT important — must be excluded.
        other_run = _insert_run(conn, schema, brand_name="Other", project_id=project_id)
        repo.attach_tag_to_analysis_run(other_run, tag["id"])

        items = repo.list_analysis_runs(
            tag_ids=[tag["id"]], category_id=category["id"], important=True
        )
        total = repo.count_analysis_runs(
            tag_ids=[tag["id"]], category_id=category["id"], important=True
        )

        assert [item["id"] for item in items] == [str(matching_run_id)]
        assert total == 1
    finally:
        repo.load_db_settings = original


def test_pagination_and_count_integrity_with_tag_filter_past_first_page(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        for i in range(25):
            _insert_run(conn, schema, brand_name=f"ブランド{i:02d}", project_id=project_id)
        tagged_run = _insert_run(conn, schema, brand_name="Tagged", project_id=project_id)
        repo.attach_tag_to_analysis_run(tagged_run, tag["id"])

        items = repo.list_analysis_runs(tag_ids=[tag["id"]], limit=20, offset=0)
        total = repo.count_analysis_runs(tag_ids=[tag["id"]])

        assert total == 1
        assert [item["id"] for item in items] == [tagged_run]
    finally:
        repo.load_db_settings = original


def test_soft_deleted_run_cannot_be_tagged_or_categorized(db_connection):
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        category = repo.create_category(project_id=project_id, name="製品A")
        deleted_run = _insert_run(
            conn,
            schema,
            brand_name="Deleted",
            project_id=project_id,
            deleted_at=datetime.now(timezone.utc),
        )

        attach_result = repo.attach_tag_to_analysis_run(deleted_run, tag["id"])
        category_result = repo.set_analysis_run_category(deleted_run, category["id"])

        assert attach_result is False
        assert category_result is False
    finally:
        repo.load_db_settings = original


def test_queued_run_cannot_be_tagged_or_categorized(db_connection):
    """This task's explicit backend-level block on editing a
    queued/running run's tags/category."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        queued_run = _insert_run(
            conn, schema, brand_name="Queued", project_id=project_id, status="queued"
        )

        with pytest.raises(repo.AnalysisRunStatusConflictError):
            repo.attach_tag_to_analysis_run(queued_run, tag["id"])
    finally:
        repo.load_db_settings = original


def test_failed_run_can_still_be_tagged(db_connection):
    """'failed' is terminal but not in the blocking set — matches the
    existing important/favorite precedent for failed jobs."""
    conn, schema = db_connection
    database_url = _database_url_with_search_path(schema)
    repo, original = _patched_repo(database_url)
    try:
        project_id = _insert_project(conn, schema)
        tag = repo.create_tag(project_id=project_id, name="タグ")
        failed_run = _insert_run(
            conn, schema, brand_name="Failed", project_id=project_id, status="failed"
        )

        assert repo.attach_tag_to_analysis_run(failed_run, tag["id"]) is True
    finally:
        repo.load_db_settings = original
