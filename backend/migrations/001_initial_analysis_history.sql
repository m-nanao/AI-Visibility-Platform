-- Initial analysis history schema for PostgreSQL / Supabase.
--
-- Scope: the minimum 3-table slice described in
-- docs/19_minimum_db_migration_design.md ("Phase 1: AnalysisRun保存" in
-- docs/18_db_persistence_design.md "11. MVPからDB対応へ移行する段階的手順").
-- Individual observation tables (input_urls / documents /
-- cooccurrence_terms / context_analyses / ai_overview_observations /
-- chatgpt_observations / common_crawl_fetches / analysis_sources /
-- analysis_result_sources / embeddings) are intentionally NOT created
-- here — see docs/19_minimum_db_migration_design.md "4. 初期実装で
-- 作らないテーブル". The whole /analyze response is stored as one
-- result_json blob per AnalysisRun instead.
--
-- This file is a design artifact only — it has not been applied to any
-- real database as part of this task (see docs/19_minimum_db_migration_design.md,
-- 対象外: 実DBへのmigration適用).
--
-- updated_at auto-update triggers are deliberately NOT included in this
-- initial migration (docs/19_minimum_db_migration_design.md "11.
-- Supabase / PostgreSQL migration方針" leaves this an open choice and
-- says to omit it when in doubt).

create extension if not exists pgcrypto;

create table if not exists brands (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  canonical_domain text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists analysis_runs (
  id uuid primary key default gen_random_uuid(),
  brand_id uuid not null references brands(id) on delete cascade,
  status text not null,
  input_snapshot jsonb not null,
  source_summary jsonb,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint analysis_runs_status_check check (
    status in ('queued', 'running', 'completed', 'partial', 'failed')
  )
);

create table if not exists analysis_results (
  id uuid primary key default gen_random_uuid(),
  analysis_run_id uuid not null references analysis_runs(id) on delete cascade,
  visibility_score integer,
  result_json jsonb not null,
  meta_json jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_brands_name on brands(name);
create index if not exists idx_analysis_runs_brand_id_created_at on analysis_runs(brand_id, created_at desc);
create index if not exists idx_analysis_results_analysis_run_id on analysis_results(analysis_run_id);
