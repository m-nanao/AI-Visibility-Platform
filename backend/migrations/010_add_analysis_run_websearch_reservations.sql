-- Task 6-D-2B additional work (feature/websearch-quota-reservation):
-- a durable, uniquely-keyed marker preventing the *same*
-- (analysis_run_id, metric) pair from reserving Task 6-D-2A's
-- websearch quota (openai_websearch/anthropic_websearch/
-- google_websearch — migration 009's analysis_usage_counters.metric)
-- more than once. Additive only — no existing table, column, or
-- constraint is altered.
--
-- Why this table exists (see services/websearch_quota_reservation.py's
-- module docstring and this task's own completion report for the full
-- investigation): the daily/monthly *aggregate* cap in
-- analysis_usage_counters is already fully concurrency-safe on its
-- own, but nothing about that table's (scope_type, scope_id, metric,
-- period_type, period_start) primary key prevents the *same run*
-- reserving the *same provider's* websearch quota twice (e.g. a
-- retried request). Two options were considered and rejected before
-- landing on this table:
--   - loosening analysis_usage_counters_scope_type_check/
--     analysis_usage_counters_period_type_check (migration 009) to
--     add an "analysis_run"/"once" value — rejected: that table's
--     whole key shape (period_start-bucketed) has nothing to do with
--     "has this one run already reserved", and repurposing it that
--     way would make its own daily/monthly semantics harder to reason
--     about for every future reader.
--   - reusing analysis_results.meta_json as a transient scratch flag
--     — rejected: GET /analysis-runs/{id} returns meta_json as a
--     loose, unvalidated dict (models.AnalysisRunDetailResponse.meta),
--     so a marker written there before the run completes could be
--     observed by a client calling that endpoint while the run is
--     still 'running' — an observable change to existing API behavior
--     this task must not make.
--
-- A dedicated table with its own `primary key (analysis_run_id,
-- metric)` is the narrowest fix: it says exactly one thing ("this run
-- has reserved this provider's websearch quota"), is never returned
-- by any existing read endpoint (no code reads from this table except
-- services/websearch_quota_reservation.py), and reuses the exact same
-- "insert ... on conflict do nothing" atomicity pattern every other
-- quota primitive in this codebase already relies on.
--
-- `metric` is restricted by CHECK to the same three Task 6-D-2A
-- values analyze_quota_settings.py defines — deliberately narrower
-- than analysis_usage_counters.metric (which has no such CHECK, since
-- it's shared by every current and future paid-provider metric); this
-- table only ever exists for the websearch-follow-up feature, so
-- there is no reason to allow anything else here.
--
-- `analysis_run_id` references analysis_runs(id) on delete cascade —
-- mirrors analysis_results'/analysis_run_tags' own existing FK
-- convention (migrations 001/008): a reservation marker has no
-- meaning once the run it was reserved for no longer exists.
--
-- This migration is a design artifact only — like every other
-- numbered migration in this repository, it has NOT been applied to
-- any real/production (Supabase) database as part of this task. It
-- HAS been applied to, and verified against, a disposable local
-- PostgreSQL 17 instance (created and torn down for this task only —
-- see tests/test_websearch_quota_reservation_integration.py's module
-- docstring) to confirm the schema below is valid and the atomicity
-- claims in services/websearch_quota_reservation.py hold against it.
--
-- Rollback: drop table if exists analysis_run_websearch_reservations;

create table if not exists analysis_run_websearch_reservations (
    analysis_run_id uuid not null references analysis_runs(id) on delete cascade,
    metric          text not null,
    reserved_at     timestamptz not null default now(),
    constraint analysis_run_websearch_reservations_pkey
        primary key (analysis_run_id, metric),
    constraint analysis_run_websearch_reservations_metric_check
        check (metric in ('openai_websearch', 'anthropic_websearch', 'google_websearch'))
);
