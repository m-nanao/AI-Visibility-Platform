-- Phase 1 of async analysis job support (feature/async-analysis-jobs-phase1).
-- See docs/40_async_analysis_jobs_design.md ("5. ジョブ実行に必要な
-- データの確定", "6. DB設計案") for the investigation behind this file.
--
-- Scope: this migration adds exactly the two columns Phase 1's job
-- accept/read API needs that the existing analysis_runs schema cannot
-- already provide — "who started this job" and "which client-side
-- start-operation does this job correspond to" — plus the unique index
-- that makes the second one actually enforce idempotency. Everything
-- else Phase 1 needs (brand name, urls/documents, provider modes,
-- project_id) is already representable with existing columns
-- (analysis_runs.project_id from 002_add_organizations_projects.sql,
-- analysis_runs.input_snapshot jsonb from 001_initial_analysis_history.sql).
--
-- Deliberately NOT included here (see docs/40_async_analysis_jobs_design.md
-- "6.2", which splits the job-related columns across two migrations by
-- phase rather than adding them all at once):
--   - locked_by / locked_at / lease_expires_at / attempt_count — these
--     are worker-lease columns that only matter once a worker exists
--     (Phase 2). Adding them now, unused, would be speculative.
--   - any RLS policy change — RLS stays exactly as it is today.
--   - a foreign key from created_by_user_id to auth.users(id). Unlike
--     organization_members.user_id (002_add_organizations_projects.sql),
--     this column is deliberately left as a plain uuid with no FK:
--     the authoritative check for "is this really a valid, currently
--     accessible user" is the JWT verification + project-membership
--     check the API performs at request time (services/jwt_auth.py +
--     services/project_access.py), not a DB constraint. Keeping this
--     column FK-free also means this migration (unlike 002) can be
--     applied to a plain local/CI PostgreSQL instance with no
--     Supabase-managed auth schema, which is what lets
--     tests/test_analysis_jobs_repository_integration.py exercise the
--     unique index below against a real database.
--
-- This file is a design artifact only, like 001/002/003/004 before it
-- — it has not been applied to any real database as part of this task
-- (対象外: 本番Supabaseへのmigration適用, Supabase設定変更, RLS変更).
-- Idempotent: `if not exists` on both new columns and the new index,
-- so re-running this file against a database that already has them is
-- a no-op. Existing rows (every row saved by today's synchronous
-- POST /analyze) are left with created_by_user_id/idempotency_key both
-- null — exactly their "no job concept existed yet" state, no
-- existing data is removed or altered, and the existing
-- deleted_at/is_important columns (003/004) are untouched.

alter table analysis_runs
  -- Who started this job (the JWT's `sub` claim, i.e. a Supabase Auth
  -- user id) — see docs/40_async_analysis_jobs_design.md "5". Null for
  -- every row saved by the existing synchronous POST /analyze (which
  -- has no caller identity at all) and for any row that predates this
  -- migration.
  add column if not exists created_by_user_id uuid,
  -- The client-generated idempotency key for one "start analysis"
  -- operation — see docs/40_async_analysis_jobs_design.md "10". Null
  -- for every row saved by the existing synchronous POST /analyze.
  add column if not exists idempotency_key text;

-- Enforces idempotency at the database level (not just a SELECT-then-
-- INSERT in application code, which would race under concurrent
-- requests) — see docs/40_async_analysis_jobs_design.md "10.1" for why
-- the uniqueness scope is (project_id, created_by_user_id,
-- idempotency_key) rather than idempotency_key alone: a key is only
-- ever compared within the same project and the same caller, so two
-- unrelated users/projects can never collide on the same key string.
--
-- The `where idempotency_key is not null` partial condition means this
-- constraint simply does not apply to any row with a null
-- idempotency_key (every existing analysis_runs row today, and any
-- future row written by a path that still doesn't set one) — Postgres
-- treats NULL as never equal to NULL for uniqueness purposes, but the
-- explicit partial condition keeps that intent legible and keeps the
-- index itself smaller (it only indexes rows that actually use this
-- feature).
create unique index if not exists idx_analysis_runs_idempotency
  on analysis_runs (project_id, created_by_user_id, idempotency_key)
  where idempotency_key is not null;
