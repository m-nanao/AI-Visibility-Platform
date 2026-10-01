"""Builds the short "which observations were ON for this run" summary
shown on each GET /analysis-runs list item (`AnalysisRunListItem.
modeSummary`, see backend/models.py's AnalysisRunModeSummary).

Added after a依頼者 ran several full-ON/single-ON verification passes
(ChatGPT/Claude/Gemini/DataForSEO all enabled, then individually) and
found the resulting history list entries impossible to tell apart —
this lets them scan the list and see at a glance which provider(s)
were actually live for each saved run.

Computed entirely from `analysis_results.meta_json` (the saved
AnalysisMeta.model_dump(), already stored alongside result_json — see
services/analysis_history_repository.py's save_analysis_history()) —
no new external API call, no new table, no new column beyond
deleted_at (see backend/migrations/003_add_deleted_at_to_analysis_runs.sql,
an unrelated change landing in the same task). `input_snapshot` is
deliberately NOT used here: it only records whether a request
*attempted* to override a mode, not whether the provider actually ran
(the effective mode can come from the server's own env default even
when input_snapshot has no override field at all) — meta_json already
reflects the real outcome, so it is the more reliable single source of
truth for this summary.

Every value falls back to "unknown" when the corresponding provider
info is missing from meta_json — covers both a genuinely old saved run
(from before a given provider existed) and the defensive case of
meta_json itself being None (a row saved before the meta_json column
was populated). "unknown" is deliberately distinct from "off": the
former means "we can't tell", the latter means "we can tell, and it
was off".
"""

from __future__ import annotations

from typing import Any

# Mirrors app/lib/meta-label.ts's resolveAiOverviewEnvironment() exactly
# (same fallback rule, kept in sync deliberately) — `environment` is
# optional on AIOverviewProviderInfo for backward compatibility with a
# saved run from before that field existed, so a meta_json blob that
# only has `mode`/`status` still needs to resolve to a definite value
# rather than falling through to "unknown" (which would otherwise make
# every pre-`environment` saved run unnecessarily non-informative).
def _resolve_ai_overview_value(provider: dict[str, Any] | None) -> str:
    if not provider:
        return "unknown"

    environment = provider.get("environment")
    if environment:
        return str(environment)

    mode = provider.get("mode")
    if mode == "off":
        return "off"
    if mode == "mock":
        return "mock"
    # mode == "dataforseo"/"dataforseo_sandbox"/"dataforseo_live" with no
    # recorded environment (pre-environment-field save) — status "real"
    # can only have come from the Sandbox host at that point in this
    # project's history (Live required extra gates added later), so
    # "sandbox" is the safe reading; anything else is "unavailable".
    return "sandbox" if provider.get("status") == "real" else "unavailable"


def _resolve_status_value(provider: dict[str, Any] | None) -> str:
    """Shared by chatgpt/claude/gemini/commonCrawl — all four provider
    info shapes already carry a `status` of exactly "real"/"off"/
    "unavailable" (see ChatGptStatus/ClaudeStatus/GeminiStatus/
    CommonCrawlProviderStatus in backend/models.py), so there is no
    environment-style fallback to resolve here."""
    if not provider:
        return "unknown"
    status = provider.get("status")
    return str(status) if status else "unknown"


def build_mode_summary(meta: dict[str, Any] | None) -> dict[str, str]:
    """Returns the 5-key dict backing AnalysisRunModeSummary, from one
    saved run's `analysis_results.meta_json`. Never raises — a
    malformed/partial meta dict only ever degrades individual keys to
    "unknown", it never prevents the rest of the list item from being
    built."""
    meta = meta or {}

    return {
        "aiOverview": _resolve_ai_overview_value(meta.get("aiOverviewProvider")),
        "chatgpt": _resolve_status_value(meta.get("chatgptProvider")),
        "claude": _resolve_status_value(meta.get("claudeProvider")),
        "gemini": _resolve_status_value(meta.get("geminiProvider")),
        "commonCrawl": _resolve_status_value(meta.get("commonCrawlProvider")),
    }
