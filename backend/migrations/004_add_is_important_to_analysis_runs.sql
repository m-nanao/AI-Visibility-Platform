-- Important flag for analysis_runs (feature/history-important-flag).
--
-- Scope: adds a non-null `is_important boolean default false` column
-- to `analysis_runs` so a saved analysis history entry can be marked
-- as important — a lighter-weight alternative to tags/notes for
-- finding review-worthy/comparison-worthy/report-candidate history
-- later as the history list grows. This is DB design 案A from
-- docs/38_history_marking_design.md ("5. DB設計案"): a single shared
-- flag directly on `analysis_runs`, not a per-user mark. See that
-- document's "6. 推奨案" for why 案A was chosen to start with, and its
-- "移行コストの整理" section for what moving to 案B
-- (`analysis_run_marks`) would involve later if per-user flags or
-- tags/notes become necessary.
--
-- `not null default false` (rather than a nullable column, unlike
-- 003's `deleted_at`) is intentional: every existing row becomes
-- `is_important = false` on migration, which is exactly the "not
-- marked important yet" state a pre-existing row should have — there
-- is no third "unknown" state to represent, unlike a timestamp column.
--
-- Deliberately NOT included here (see
-- docs/28_supabase_auth_rls_migration_design.md's staged-migration
-- convention, followed by 002/003 above):
--   - any RLS policy change — RLS stays exactly as it is today.
--   - an `analysis_run_marks` table (案B) — not needed for this stage.
--   - a per-user important flag — 案A is a single shared flag; see
--     docs/38_history_marking_design.md for the per-user alternative.
--   - an "important only" filter, notes, or tags — out of scope for
--     this stage (see docs/38_history_marking_design.md "9. 実装段階").
--
-- This file is a design artifact only, like 001/002/003 before it — it
-- has not been applied to any real database as part of this task
-- (対象外: 本番Supabaseへのmigration適用, Supabase設定変更). Applying it
-- to the production Supabase database, if/when that is wanted, is a
-- manual step the user runs in the Supabase SQL Editor — see
-- docs/38_history_marking_design.md's production-application notes
-- added alongside this migration. Idempotent: `if not exists` on both
-- the column and the index, so re-running this file against a
-- database that already has them is a no-op. Existing rows are left
-- with `is_important = false` (the default) — no existing data is
-- removed or altered, and the existing `deleted_at` soft-delete
-- column/behavior (003_add_deleted_at_to_analysis_runs.sql) is
-- untouched by this migration.

alter table analysis_runs
  add column if not exists is_important boolean not null default false;

-- Supports a future "important only" list filter (not implemented in
-- this stage — see docs/38_history_marking_design.md "9. 実装段階"'s
-- 第2段階) alongside the existing `project_id`-scoped, newest-first
-- listing query in
-- backend/services/analysis_history_repository.py's
-- list_analysis_runs().
create index if not exists idx_analysis_runs_project_important_created_at
  on analysis_runs (project_id, is_important, created_at desc);
