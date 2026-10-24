-- Task 6-D-5C-2 (feature/claude-fact-extraction-mvp): widens migration
-- 010's analysis_run_websearch_reservations_metric_check CHECK
-- constraint (already widened once by migration 011) to additionally
-- allow the new 'fact_extraction' metric. Additive-only in intent (no
-- table/column is dropped), but technically requires dropping and
-- recreating the CHECK constraint itself, since PostgreSQL has no
-- "ALTER CHECK to add a value" syntax. Neither
-- migrations/010_add_analysis_run_websearch_reservations.sql nor
-- migrations/011_add_gemini_external_document_metric.sql is edited —
-- this is a separate, later migration, per this task's own
-- instruction not to rewrite an already-applied migration file.
--
-- Why a new metric, not a reuse of 'anthropic'/'anthropic_websearch':
-- Task 6-D-5C-2's own feature (Claude-based structured fact extraction
-- from one already-produced ChatGPT no-search card's answer, via
-- services/fact_extraction_provider.py) is a categorically different
-- cost/operation from both: 'anthropic' meters the no-search Claude
-- observation itself, and 'anthropic_websearch' meters Claude's own
-- conditional Web-search supplement (services/claude_websearch_provider.py).
-- All three happen to call a Claude model, but conflating their quota
-- counters would make it impossible to budget/observe them
-- independently — the same reasoning migration 010's own header gives
-- for why analysis_usage_counters' per-metric design exists at all.
--
-- `analysis_usage_counters.metric` (migration 009) has no CHECK
-- constraint, so the new metric string already works there without
-- any migration — only this table's narrower, Task 6-D-2A-scoped
-- allowlist needs widening.
--
-- This migration is a design artifact only — like every other
-- numbered migration in this repository, it has NOT been applied to
-- any real/production (Supabase) database as part of this task.
--
-- Rollback:
--   alter table analysis_run_websearch_reservations
--       drop constraint analysis_run_websearch_reservations_metric_check;
--   alter table analysis_run_websearch_reservations
--       add constraint analysis_run_websearch_reservations_metric_check
--           check (metric in (
--               'openai_websearch',
--               'anthropic_websearch',
--               'google_websearch',
--               'gemini_external_document'
--           ));

alter table analysis_run_websearch_reservations
    drop constraint analysis_run_websearch_reservations_metric_check;

alter table analysis_run_websearch_reservations
    add constraint analysis_run_websearch_reservations_metric_check
        check (metric in (
            'openai_websearch',
            'anthropic_websearch',
            'google_websearch',
            'gemini_external_document',
            'fact_extraction'
        ));
