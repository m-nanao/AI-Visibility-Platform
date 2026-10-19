-- Favorite flag for analysis_runs (feature/history-favorite-flag).
--
-- Scope: adds a non-null `is_favorite boolean default false` column
-- to `analysis_runs`, independent of the existing `is_important`
-- column (004_add_is_important_to_analysis_runs.sql) — "重要" and
-- "お気に入り" are two separate, independently-toggleable marks on the
-- same row, not one flag reused for two purposes.
--
-- Shared-within-project, not per-user: mirrors 004's own "案A" design
-- exactly (a single shared flag directly on `analysis_runs`), for the
-- same underlying reason — this project's analysis_runs/brands are
-- scoped to a `project_id`, and a project's members (see
-- `organization_members` in 002_add_organizations_projects.sql, a
-- (organization_id, user_id) many-to-many) already all see the same
-- history list for that project. A per-user favorite would need a
-- separate `analysis_run_favorites (analysis_run_id, user_id)` table
-- instead of this column — not needed for this task's requirement
-- ("project内で共有されるお気に入りを基本案とする"), and not something
-- this migration forecloses: a later per-user stage could still add
-- that table alongside this column without touching it.
--
-- `not null default false` (rather than nullable): every existing row
-- becomes `is_favorite = false` on migration — exactly the "not
-- favorited yet" state a pre-existing row should have, same reasoning
-- as 004's `is_important` column.
--
-- Deliberately NOT included here (same staged-migration convention as
-- 002/003/004 before it):
--   - any RLS policy change — RLS stays exactly as it is today.
--   - a per-user `analysis_run_favorites` table — see above; not
--     needed for this stage's shared-favorite requirement.
--   - any change to `is_important` or its existing index/behavior —
--     the two flags are independent and this migration touches
--     nothing about the existing one.
--
-- This file is a design artifact only, like 001-006 before it — it
-- has not been applied to any real database as part of this task
-- (対象外: 本番Supabaseへのmigration適用). Applying it to the production
-- Supabase database is a manual step the user runs in the Supabase
-- SQL Editor after review/approval — see this task's完了報告「6. 本番
-- 適用時の注意点」. Idempotent: `if not exists` on both the column and
-- the index, so re-running this file against a database that already
-- has them is a no-op. Existing rows are left with `is_favorite =
-- false` (the default) — no existing data is removed or altered, and
-- the existing `is_important`/`deleted_at` columns and behavior are
-- untouched by this migration.

alter table analysis_runs
  add column if not exists is_favorite boolean not null default false;

-- Supports a server-side "favorite only" list filter (this task's
-- `favorite=true` query param on GET /analysis-runs) alongside the
-- existing `project_id`-scoped, newest-first listing query in
-- backend/services/analysis_history_repository.py's
-- list_analysis_runs() — mirrors 004's own
-- idx_analysis_runs_project_important_created_at index exactly, one
-- column swapped.
create index if not exists idx_analysis_runs_project_favorite_created_at
  on analysis_runs (project_id, is_favorite, created_at desc);
