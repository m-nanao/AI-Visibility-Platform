-- Task 6-D-4C-2 (feature/gemini-external-document-supplement): widens
-- migration 010's analysis_run_websearch_reservations_metric_check
-- CHECK constraint to additionally allow the new 'gemini_external_document'
-- metric. Additive-only in intent (no table/column is dropped), but
-- technically requires dropping and recreating the CHECK constraint
-- itself, since PostgreSQL has no "ALTER CHECK to add a value" syntax.
-- migrations/010_add_analysis_run_websearch_reservations.sql itself is
-- NOT edited — this is a separate, later migration, per this task's
-- own instruction not to rewrite an already-applied migration file.
--
-- Why a new metric, not a reuse of 'google_websearch': Task 6-D-4C-2's
-- own feature (Gemini answering from externally-fetched Web documents,
-- via services/gemini_external_document_provider.py) is a categorically
-- different cost/operation than 'google_websearch' (Google Search
-- grounding via the google_search tool, services/gemini_websearch_provider.py,
-- still disabled pending Task 6-D-4B-3A's ToS review). Both happen to
-- call a Gemini model, but conflating their quota counters would make
-- it impossible to budget/observe them independently — the same
-- reasoning migration 010's own header gives for why
-- analysis_usage_counters' per-metric design exists at all.
--
-- `analysis_usage_counters.metric` (migration 009) has no CHECK
-- constraint, so the new metric string already works there without
-- any migration — only this table's narrower, Task 6-D-2A-scoped
-- allowlist needs widening.
--
-- This migration is a design artifact only — like every other
-- numbered migration in this repository, it has NOT been applied to
-- any real/production (Supabase) database as part of this task. It
-- HAS been applied to, and verified against, a disposable local
-- PostgreSQL instance (created and torn down for this task only — see
-- tests/test_websearch_quota_reservation_integration.py, extended by
-- this task to also apply this migration) to confirm the widened
-- constraint is valid and that reserve_websearch_quota_for_analysis_run()
-- accepts the new metric without any other code change.
--
-- Rollback:
--   alter table analysis_run_websearch_reservations
--       drop constraint analysis_run_websearch_reservations_metric_check;
--   alter table analysis_run_websearch_reservations
--       add constraint analysis_run_websearch_reservations_metric_check
--           check (metric in ('openai_websearch', 'anthropic_websearch', 'google_websearch'));

alter table analysis_run_websearch_reservations
    drop constraint analysis_run_websearch_reservations_metric_check;

alter table analysis_run_websearch_reservations
    add constraint analysis_run_websearch_reservations_metric_check
        check (metric in (
            'openai_websearch',
            'anthropic_websearch',
            'google_websearch',
            'gemini_external_document'
        ));
