"""Sanity-checks backend/migrations/001_initial_analysis_history.sql as
a plain text file — this migration is a design artifact only and is
never executed against a database as part of this test suite (see
docs/19_minimum_db_migration_design.md, 対象外: 実DBへのmigration適用).
"""

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "migrations" / "001_initial_analysis_history.sql"
)


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
