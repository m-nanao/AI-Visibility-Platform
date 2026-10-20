-- Tags and categories for analysis_runs (feature/history-tags-categories).
-- See this task's design review (Task 5-A, corrected in its
-- follow-up review) for the full investigation behind this file,
-- including a real-PostgreSQL-17 reproduction of two hazards this
-- migration's design deliberately avoids:
--
-- 1. A naive design with BOTH a single-column `category_id uuid
--    references categories(id) on delete set null` AND a separate
--    composite FK `(category_id, project_id) references
--    categories(id, project_id)` creates two independent FK
--    constraints on the same column with potentially conflicting
--    delete actions. This migration defines exactly ONE FK on
--    `category_id` — the composite one below — never a plain
--    single-column one.
--
-- 2. If `categories.project_id`/`tags.project_id` used `on delete
--    cascade` (the naive choice, mirroring brands/analysis_runs'
--    existing `on delete set null` pattern loosely), deleting a
--    `projects` row that still has categories would, in the same
--    statement, both CASCADE-delete the category row AND (via
--    analysis_runs.project_id's own pre-existing `on delete set
--    null` to projects) null out `analysis_runs.project_id` on any
--    run in that project. These two cascade actions on the same
--    `analysis_runs` row race: by the time the composite FK's `on
--    delete set null (category_id)` action looks for rows matching
--    the deleted category's (id, project_id), the row's project_id
--    has already been nulled by the sibling action and is no longer
--    found — leaving `category_id` dangling, pointing at a category
--    row that no longer exists. Reproduced directly against a real
--    PostgreSQL 17 instance before writing this migration. Fixed
--    here by making `categories.project_id`/`tags.project_id` `on
--    delete restrict` instead: deleting a project that still has any
--    category or tag is rejected outright, so the dangerous
--    simultaneous-cascade scenario can never occur. (This app has no
--    code path that ever deletes a `projects` row today — this is a
--    forward-looking safeguard, not a fix for an observed bug.)
--
-- Scope — new tables/columns only, nothing destructive:
--   - `categories`, `tags`: project-shared, one row per name per
--     project. Name uniqueness is case-insensitive and
--     whitespace-trimmed (`lower(btrim(name))`), enforced by a
--     UNIQUE INDEX on the expression, not a plain UNIQUE(project_id,
--     name) — the latter would allow "Foo" and "foo" (or " Foo ") to
--     coexist as if distinct. A CHECK constraint separately rejects
--     an empty (whitespace-only) or over-100-character name — DB
--     constraints only operate on the raw `name` text, not on this
--     migration's validation story around what the API sends; both
--     the CHECK and the index use the same `btrim`/`lower`
--     normalization so they agree on what counts as "the same name".
--   - `analysis_run_tags`: many-to-many join table between
--     `analysis_runs` and `tags`. Deliberately denormalizes
--     `project_id` onto this table (not derivable from a plain join
--     alone at the FK-definition level) specifically so its two
--     composite FKs can force `analysis_run_id` and `tag_id` to
--     belong to the exact same project as each other and as this
--     row — this is the DB-level "no cross-project mixing"
--     guarantee this task asked for, beyond what API-level checks
--     alone provide.
--   - `analysis_runs.category_id`: nullable (0-or-1 category per
--     run, "未分類" = null), guarded by the same cross-project
--     containment via its own composite FK.
--   - `analysis_runs.project_id` stays nullable (existing,
--     pre-002_add_organizations_projects.sql compatibility is
--     unchanged by this migration) — but assigning a category to
--     such a row would make `category_id` non-null while
--     `project_id` is null, which the composite FK alone does NOT
--     catch (PostgreSQL's default `MATCH SIMPLE` skips a composite FK
--     check entirely when *any* of its own referencing columns is
--     null — here, `project_id`). The extra CHECK constraint
--     `chk_analysis_runs_category_requires_project` closes exactly
--     this gap: a category can only ever be set on a run that
--     already has a project. Verified directly against a real
--     PostgreSQL 17 instance as part of this migration's review.
--
-- This file is a design artifact only, like 001-007 before it — it
-- has NOT been applied to any real database as part of this task
-- (対象外: 本番Supabaseへのmigration適用, Supabase設定変更). Idempotent:
-- every CREATE/ALTER uses `if not exists` (or, where PostgreSQL has
-- no `if not exists` form for a given constraint type, is written to
-- be safe to re-run manually with that in mind — see the inline notes
-- below). Existing rows are untouched: every existing `analysis_runs`
-- row gets `category_id = null` (already "未分類", not a new state),
-- no row's `project_id`/`is_important`/`is_favorite`/`deleted_at` is
-- touched, and no row is deleted.

create table if not exists categories (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete restrict,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_categories_name_length check (char_length(btrim(name)) between 1 and 100),
  -- Required as the target of analysis_runs' composite FK below —
  -- redundant with the existing `id` PK for uniqueness purposes (id
  -- alone is already globally unique), but PostgreSQL requires the
  -- exact referenced column tuple to have its own unique constraint.
  unique (id, project_id)
);

-- Case-insensitive, whitespace-trimmed duplicate prevention — see
-- this file's header. A plain `unique (project_id, name)` is
-- deliberately NOT also added; it would be redundant with (and looser
-- than) this expression index.
create unique index if not exists uq_categories_project_name_ci
  on categories (project_id, lower(btrim(name)));

create index if not exists idx_categories_project_id on categories(project_id);

create table if not exists tags (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete restrict,
  name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint chk_tags_name_length check (char_length(btrim(name)) between 1 and 100),
  unique (id, project_id)
);

create unique index if not exists uq_tags_project_name_ci
  on tags (project_id, lower(btrim(name)));

create index if not exists idx_tags_project_id on tags(project_id);

-- `unique (id, project_id)` on analysis_runs is new here — required
-- as the target of the two composite FKs below (analysis_run_tags',
-- and this migration's own category_id one). `add constraint` has no
-- `if not exists` form in PostgreSQL, so this migration guards it
-- with a catalog check instead, making it safe to re-run.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'uq_analysis_runs_id_project'
      and conrelid = 'public.analysis_runs'::regclass
  ) then
    alter table analysis_runs
      add constraint uq_analysis_runs_id_project unique (id, project_id);
  end if;
end $$;

alter table analysis_runs
  add column if not exists category_id uuid;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'fk_analysis_runs_category_project'
      and conrelid = 'public.analysis_runs'::regclass
  ) then
    alter table analysis_runs
      add constraint fk_analysis_runs_category_project
      foreign key (category_id, project_id)
      references categories(id, project_id)
      on delete set null (category_id);
  end if;
end $$;

-- Closes the `project_id is null` gap the composite FK's `MATCH
-- SIMPLE` semantics leave open (see this file's header) — a run with
-- no project can never be given a category, regardless of which one.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'chk_analysis_runs_category_requires_project'
      and conrelid = 'public.analysis_runs'::regclass
  ) then
    alter table analysis_runs
      add constraint chk_analysis_runs_category_requires_project
      check (category_id is null or project_id is not null);
  end if;
end $$;

create index if not exists idx_analysis_runs_category_id on analysis_runs(category_id);
create index if not exists idx_analysis_runs_project_category_created_at
  on analysis_runs (project_id, category_id, created_at desc);

create table if not exists analysis_run_tags (
  analysis_run_id uuid not null,
  tag_id uuid not null,
  -- Denormalized from analysis_runs.project_id/tags.project_id —
  -- required so the two composite FKs below can force both sides to
  -- agree on the same project. Set from analysis_runs.project_id at
  -- insert time by the application (see
  -- services/analysis_history_repository.py's
  -- attach_tag_to_analysis_run()); never user-supplied directly.
  project_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (analysis_run_id, tag_id),
  foreign key (analysis_run_id, project_id)
    references analysis_runs(id, project_id) on delete cascade,
  foreign key (tag_id, project_id)
    references tags(id, project_id) on delete cascade
);

-- Supports the reverse lookup (which runs have tag X — used by the
-- OR-search filter's EXISTS subquery, correlated on analysis_run_id,
-- and by FK-cascade efficiency when a tag is deleted) in addition to
-- the primary key's own (analysis_run_id, tag_id) ordering.
create index if not exists idx_analysis_run_tags_tag_id on analysis_run_tags(tag_id);
