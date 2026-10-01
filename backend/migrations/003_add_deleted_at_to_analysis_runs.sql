-- Soft delete for analysis_runs (feature/history-delete-and-mode-badges).
--
-- Scope: adds a nullable `deleted_at` column to `analysis_runs` so a
-- saved analysis history entry can be hidden from the history
-- list/detail APIs without destroying the row — the依頼者 asked for a
-- way to clean up similar-looking test runs (full-ON/single-ON/failed
-- verification attempts) from the history list without losing them
-- permanently in case they're needed later. `analysis_results`/`brands`
-- are untouched: deleting an `analysis_runs` row never deletes its
-- joined result or brand.
--
-- This migration does not turn a "soft delete" into a behavior by
-- itself — backend/services/analysis_history_repository.py's
-- list_analysis_runs()/get_analysis_run()/get_previous_analysis_run_for_brand()
-- filter on `deleted_at is null` in application code, and the new
-- soft_delete_analysis_run() sets this column via `UPDATE ... SET
-- deleted_at = now()`, never `DELETE FROM analysis_runs`.
--
-- Deliberately NOT included here (see
-- docs/28_supabase_auth_rls_migration_design.md's staged-migration
-- convention, followed by 002_add_organizations_projects.sql above):
--   - any RLS policy change — RLS stays exactly as it is today.
--   - hard-deleting or archiving any existing row.
--   - a restore/undelete API — not needed yet; `deleted_at` can be
--     cleared manually (`update analysis_runs set deleted_at = null
--     where id = ...`) if a mistaken delete needs undoing later.
--
-- This file is a design artifact only, like 001/002 before it — it has
-- not been applied to any real database as part of this task (対象外:
-- 本番Supabaseへのmigration適用, Supabase設定変更). Idempotent: `if not
-- exists` on both the column and the index, so re-running this file
-- against a database that already has them is a no-op. Existing rows
-- are left with `deleted_at` null (not already deleted), exactly as
-- before this migration — no existing data is removed or altered.

alter table analysis_runs
  add column if not exists deleted_at timestamptz;

-- Supports the `and deleted_at is null` filter added to every read
-- path (list/detail/previous-run-for-comparison).
create index if not exists idx_analysis_runs_deleted_at
  on analysis_runs (deleted_at);

-- Supports list_analysis_runs()'s combination of a JWT-mode
-- `project_id in (...)` filter, the new `deleted_at is null` filter,
-- and its `order by created_at desc` — the common case once this
-- feature ships (see backend/services/analysis_history_repository.py).
create index if not exists idx_analysis_runs_project_deleted_created_at
  on analysis_runs (project_id, deleted_at, created_at desc);
