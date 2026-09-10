"""Sanity-checks backend/migrations/001_initial_analysis_history.sql and
002_add_organizations_projects.sql as plain text files — these
migrations are design artifacts only and are never executed against a
database as part of this test suite (see
docs/19_minimum_db_migration_design.md /
docs/28_supabase_auth_rls_migration_design.md, 対象外: 実DBへのmigration適用).
"""

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "001_initial_analysis_history.sql"
ORGANIZATIONS_MIGRATION_PATH = MIGRATIONS_DIR / "002_add_organizations_projects.sql"


def test_migration_file_exists():
    assert MIGRATION_PATH.exists()


def test_migration_contains_the_three_initial_tables():
    sql = MIGRATION_PATH.read_text().lower()
    for table in ("brands", "analysis_runs", "analysis_results"):
        assert f"create table if not exists {table}" in sql


def test_migration_does_not_contain_out_of_scope_tables():
    sql = MIGRATION_PATH.read_text().lower()
    for table in (
        "input_urls",
        "documents",
        "cooccurrence_terms",
        "context_analyses",
        "ai_overview_observations",
        "chatgpt_observations",
        "common_crawl_fetches",
    ):
        assert f"create table if not exists {table}" not in sql


def test_migration_references_brand_id_foreign_key():
    sql = MIGRATION_PATH.read_text().lower()
    assert "references brands(id)" in sql


def test_migration_has_analysis_runs_status_check():
    sql = MIGRATION_PATH.read_text().lower()
    assert "analysis_runs_status_check" in sql
    for status in ("queued", "running", "completed", "partial", "failed"):
        assert status in sql


# --- 002_add_organizations_projects.sql
# (docs/28_supabase_auth_rls_migration_design.md) ---


def test_organizations_migration_file_exists():
    assert ORGANIZATIONS_MIGRATION_PATH.exists()


def test_organizations_migration_creates_the_three_new_tables():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    for table in ("organizations", "projects", "organization_members"):
        assert f"create table if not exists {table}" in sql


def test_organizations_migration_adds_project_id_to_existing_tables():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "alter table brands" in sql
    assert "alter table analysis_runs" in sql
    assert sql.count("add column if not exists project_id") == 2


def test_organizations_migration_creates_default_organization_and_project():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "insert into organizations" in sql
    assert "insert into projects" in sql
    assert "default organization" in sql
    assert "default project" in sql


def test_organizations_migration_backfills_existing_rows():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "update brands" in sql
    assert "update analysis_runs" in sql
    assert "where project_id is null" in sql


def test_organizations_migration_adds_expected_indexes():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    for index in (
        "idx_projects_organization_id",
        "idx_organization_members_user_id",
        "idx_brands_project_id",
        "idx_analysis_runs_project_id",
    ):
        assert f"create index if not exists {index}" in sql


def test_organizations_migration_does_not_enable_rls_or_add_policies():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "enable row level security" not in sql
    assert "create policy" not in sql


def test_organizations_migration_does_not_force_not_null_project_id():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "alter column project_id set not null" not in sql
    assert "project_id uuid not null" not in sql


def test_organizations_migration_does_not_drop_or_delete_anything():
    sql = ORGANIZATIONS_MIGRATION_PATH.read_text().lower()
    assert "drop table" not in sql
    assert "drop column" not in sql
    assert "delete from" not in sql
