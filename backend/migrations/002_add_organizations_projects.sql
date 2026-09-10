-- Organization/project scaffolding for Supabase Auth/RLS, per
-- docs/27_supabase_auth_rls_design.md and
-- docs/28_supabase_auth_rls_migration_design.md.
--
-- Scope: this is migration "002" in
-- docs/28_supabase_auth_rls_migration_design.md's staged plan
-- ("10. 段階的migration案") — it only adds the organizations/projects/
-- organization_members tables, a nullable project_id column on
-- brands/analysis_runs, a default organization/project, and a backfill
-- of existing rows onto that default project.
--
-- Deliberately NOT included in this migration (see docs/28
-- "9. RLS policy追加方針" / "15. 初期実装でやること・やらないこと"):
--   - turning row level security ON for any table — RLS stays off for now.
--   - any row-level access policy — those land in a later migration
--     (docs/28's migration 006), once frontend/backend Auth support exists.
--   - `not null` on brands.project_id / analysis_runs.project_id — stays
--     nullable until the app can reliably populate it (docs/28's
--     migration 007).
--   - Dropping or deleting any existing table, column, or row.
--
-- This file is a design artifact only — like 001_initial_analysis_history.sql,
-- it has not been applied to any real database as part of this task
-- (対象外: 本番Supabaseへのmigration適用, Supabase設定変更, RLS有効化).
-- `organization_members.user_id` references `auth.users(id)`, which only
-- exists on an actual Supabase project — this migration is written for a
-- Supabase target, not a plain local/CI PostgreSQL instance.

create table if not exists organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name text not null,
  slug text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (organization_id, slug)
);

-- auth.users is a Supabase-managed table; this table only makes sense
-- against an actual Supabase project (see file header note above).
create table if not exists organization_members (
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null,
  created_at timestamptz not null default now(),
  primary key (organization_id, user_id),
  constraint organization_members_role_check check (role in ('owner', 'member'))
);

-- Nullable for now — existing rows have no project yet, and the app
-- does not write this column until a later task adds Auth support
-- (docs/28_supabase_auth_rls_migration_design.md "6. 既存テーブルへの
-- 追加カラム案"). `on delete set null` rather than cascade: a deleted
-- project should not take existing brands/analysis_runs down with it.
alter table brands
  add column if not exists project_id uuid references projects(id) on delete set null;

alter table analysis_runs
  add column if not exists project_id uuid references projects(id) on delete set null;

-- Default organization/project so existing data has somewhere to live
-- immediately after this migration (docs/28 "7. default organization /
-- default project の扱い"). Keyed by slug (unique) rather than name, so
-- re-running this migration does not create duplicates.
insert into organizations (name, slug)
values ('Default Organization', 'default')
on conflict (slug) do nothing;

insert into projects (organization_id, name, slug)
select o.id, 'Default Project', 'default'
from organizations o
where o.slug = 'default'
on conflict (organization_id, slug) do nothing;

-- Backfill: every existing brand/analysis_run that has no project yet
-- (i.e. everything, on a first run of this migration) is attached to
-- the default project above. Re-running this migration is a no-op here
-- too, since the `where project_id is null` guard only touches rows
-- that still need it.
update brands
set project_id = (
  select p.id
  from projects p
  join organizations o on o.id = p.organization_id
  where o.slug = 'default' and p.slug = 'default'
)
where project_id is null;

update analysis_runs
set project_id = (
  select p.id
  from projects p
  join organizations o on o.id = p.organization_id
  where o.slug = 'default' and p.slug = 'default'
)
where project_id is null;

create index if not exists idx_projects_organization_id on projects(organization_id);
create index if not exists idx_organization_members_user_id on organization_members(user_id);
create index if not exists idx_brands_project_id on brands(project_id);
create index if not exists idx_analysis_runs_project_id on analysis_runs(project_id);
create index if not exists idx_analysis_runs_project_created_at on analysis_runs(project_id, created_at desc);
