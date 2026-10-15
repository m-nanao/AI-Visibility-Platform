-- Phase 2 of async analysis job support (feature/async-analysis-jobs-phase2).
-- See docs/40_async_analysis_jobs_design.md ("11. ワーカーの排他制御と
-- 中断処理", "12. Workerの実装方法とRender上のライフサイクル") for the
-- design behind this file.
--
-- Scope: adds the four "worker lease" columns Phase 1's migration
-- (005_async_analysis_jobs_phase1.sql) deliberately deferred — they
-- only matter once a worker actually exists to claim/complete a job,
-- which is exactly what this phase adds. No new status values are
-- needed: analysis_runs.status's existing CHECK constraint
-- ('queued'/'running'/'completed'/'partial'/'failed', from
-- 001_initial_analysis_history.sql) already covers every state Phase
-- 2's worker transitions a job through.
--
-- Apply after 001-005 (depends only on analysis_runs already existing
-- with the created_by_user_id/idempotency_key columns from 005 — this
-- migration does not touch either of those, it only adds new columns
-- alongside them). Like 002-005 before it, this is a design artifact
-- only — it has NOT been applied to any real database as part of this
-- task (対象外: 本番Supabaseへのmigration適用, Supabase設定変更, RLS変更).
--
-- Rollback: `alter table analysis_runs drop column if exists locked_by,
-- drop column if exists locked_at, drop column if exists
-- lease_expires_at, drop column if exists attempt_count;` — safe at
-- any time (these columns are only ever read/written by Phase 2's
-- worker code; nothing else depends on them), and drops no data that
-- existed before this migration.
--
-- Idempotent: `if not exists` on every column and index, so re-running
-- this file against a database that already has them is a no-op.
-- Existing rows (every row from before this migration — both
-- synchronous /analyze saves with created_by_user_id/idempotency_key
-- both null, and Phase 1 queued jobs with those two columns already
-- set) get locked_by/locked_at/lease_expires_at = null and
-- attempt_count = 0, which is exactly their "never claimed by a
-- worker yet" state — no existing data is removed or altered.

alter table analysis_runs
  -- Which worker instance currently owns this job (an opaque string
  -- identifier the worker process generates for itself, e.g.
  -- hostname+pid — see docs/40 "11.3"). Null until a worker first
  -- claims the row; cleared back to null is NOT done on completion
  -- (the final locked_by value is kept as a diagnostic trail of who
  -- last touched the row — see services/analysis_job_worker.py).
  add column if not exists locked_by text,
  -- When the current owner claimed this job — this is "execution
  -- actually started", distinct from the existing `started_at`
  -- (unchanged by this migration), which has meant "became queued"
  -- since 001_initial_analysis_history.sql and keeps that meaning —
  -- see docs/40 "13.5" for why these two timestamps are deliberately
  -- different columns rather than redefining `started_at`.
  add column if not exists locked_at timestamptz,
  -- The lease deadline: if `status = 'running'` and
  -- `lease_expires_at < now()`, the owning worker is presumed dead
  -- (crashed, Render restarted/slept mid-job, etc.) and the next
  -- worker's poll cycle transitions the row directly to 'failed' —
  -- never back to 'queued' (see docs/40 "11.4": no automatic full
  -- re-run after a lease expires, since this backend cannot know
  -- whether an external paid API call already happened).
  add column if not exists lease_expires_at timestamptz,
  -- How many times a worker has claimed this row (incremented on
  -- every successful claim, including a claim of a previously
  -- lease-expired-then-failed... no — a failed row is never
  -- re-claimed automatically, see above; this column exists purely
  -- as a diagnostic/debugging aid for Phase 2, not as an input to any
  -- retry-limit decision Phase 2 itself makes).
  add column if not exists attempt_count integer not null default 0;

-- Supports the worker's polling query (claim_next_queued_analysis_run()
-- in services/analysis_history_repository.py): find the oldest
-- 'queued' row to claim next.
create index if not exists idx_analysis_runs_status_created_at
  on analysis_runs (status, created_at)
  where status = 'queued';

-- Supports the lease-expiry sweep
-- (fail_expired_running_analysis_runs()): find every 'running' row
-- whose lease has expired.
create index if not exists idx_analysis_runs_status_lease_expires_at
  on analysis_runs (status, lease_expires_at)
  where status = 'running';
