-- Task 6-B4 (feature/sync-analyze-jwt-project-auth): atomic
-- usage-quota counters for the authenticated synchronous POST
-- /analyze path, used alongside create_running_analysis_run()'s
-- existing idempotency mechanism (migration 005/006). Additive
-- only — no existing table, column, or constraint is altered.
--
-- Safe to apply with ANALYZE_AUTH_REQUIRED=false and/or
-- ANALYZE_QUOTA_ENFORCEMENT_ENABLED=false (the production default as
-- of this task): this migration alone changes no runtime behavior —
-- nothing reads or writes this table unless both of those are true.
--
-- Design notes (see Task 6-B4's design report for the full
-- investigation this migration implements):
--
-- - `scope_type` is part of the key (not inferred from scope_id's
--   uuid alone) so a `user` row and a `project` row can never be
--   confused even though both scope_id columns share the same uuid
--   type and (astronomically unlikely but never relied upon) could
--   otherwise collide.
-- - `metric` distinguishes "all_analyses" (every analysis, mock/off
--   included) from a specific paid provider's actual call count
--   ("dataforseo_sandbox" / "dataforseo_live" / "openai" /
--   "anthropic" / "google") — see
--   services/ai_overview_provider.py's resolve_dataforseo_environment()
--   and backend/main.py's _analyze_authenticated_idempotent() for
--   exactly which resolved provider mode maps to which metric value.
-- - `period_start` is always computed in application code (UTC
--   day/month truncation — see
--   services/analysis_history_repository.py's daily_period_start()/
--   monthly_period_start()), never in SQL via now()/AT TIME ZONE —
--   this avoids any dependency on a connection's session TimeZone
--   GUC, which could otherwise let two connections disagree on where
--   a day/month boundary falls.
-- - No FK on scope_id: it polymorphically refers to either
--   projects.id or auth.users.id depending on scope_type, so a single
--   FK isn't expressible. An orphaned counter row (after a
--   project/user is ever deleted — no code path does that today) is
--   harmless dead data, not a correctness risk; a future cleanup job
--   is out of this task's scope.
-- - This table is never written to by the async job system
--   (services/analysis_job_worker.py) — out of this task's scope by
--   design (see design report "10. 追加でユーザー判断が必要な事項").
--
-- Rollback: drop table if exists analysis_usage_counters;

create table if not exists analysis_usage_counters (
    scope_type   text not null,
    scope_id     uuid not null,
    metric       text not null,
    period_type  text not null,
    period_start timestamptz not null,
    count        integer not null default 0,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    constraint analysis_usage_counters_pkey
        primary key (scope_type, scope_id, metric, period_type, period_start),
    constraint analysis_usage_counters_scope_type_check
        check (scope_type in ('user', 'project')),
    constraint analysis_usage_counters_period_type_check
        check (period_type in ('daily', 'monthly')),
    constraint analysis_usage_counters_count_check
        check (count >= 0)
);

-- Supports "show this project's/user's current usage" admin/debug
-- queries without a full table scan; the primary key above already
-- covers the exact-match atomic upsert this feature's hot path needs
-- (insert ... on conflict (scope_type, scope_id, metric, period_type,
-- period_start) do update ... where count < limit returning count).
create index if not exists idx_analysis_usage_counters_scope
    on analysis_usage_counters (scope_type, scope_id, period_type, period_start);
