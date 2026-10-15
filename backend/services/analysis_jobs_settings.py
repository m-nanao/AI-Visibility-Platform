"""Reads async-analysis-job-related environment variables into a
small settings object.

Placed under services/ to match the existing convention of every other
settings module living here (see services/db_settings.py,
services/auth_settings.py, services/common_crawl_settings.py).

This is Phase 1 of docs/40_async_analysis_jobs_design.md's staged plan
("15. 段階的実装計画") — `ANALYSIS_JOBS_ENABLED` gates the entire
POST/GET /analysis-jobs* endpoint group off by default, since Phase 1
has no worker yet (a job created in this phase sits in `queued`
forever) and this feature must stay invisible to production users
until Phase 2/3 ship (see docs/40 "15. Phase 1" / "17. 運用・コスト").
No value here is a secret.
"""

import os
from dataclasses import dataclass

DEFAULT_ANALYSIS_JOBS_ENABLED = False
# MVP placeholders, not a product/business decision made for real — see
# docs/40_async_analysis_jobs_design.md "8.3" and "18" (未解決事項 2),
# which explicitly defer the actual limit values to product/ops
# judgment. These defaults exist only so Phase 1's queued-job-limit
# check (services/analysis_history_repository.create_queued_analysis_run())
# has *some* finite bound rather than none, and are deliberately small
# given Phase 1 jobs never leave "queued" (nothing ever frees up a
# slot) — operators can override via env without a code change once a
# real limit is decided.
DEFAULT_MAX_QUEUED_PER_PROJECT = 5
DEFAULT_MAX_QUEUED_PER_USER = 3


@dataclass(frozen=True)
class AnalysisJobsSettings:
    """Snapshot of async-analysis-job configuration for the current
    process."""

    enabled: bool
    max_queued_per_project: int
    max_queued_per_user: int


def _resolve_enabled() -> bool:
    raw = os.environ.get("ANALYSIS_JOBS_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def load_analysis_jobs_settings() -> AnalysisJobsSettings:
    """Reads ANALYSIS_JOBS_ENABLED/ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT/
    ANALYSIS_JOBS_MAX_QUEUED_PER_USER env vars fresh on every call
    (mirrors load_db_settings() and friends elsewhere in this
    codebase). Defaults to enabled=False — the new job endpoints are
    never reachable unless explicitly turned on.
    """
    return AnalysisJobsSettings(
        enabled=_resolve_enabled(),
        max_queued_per_project=_resolve_positive_int_env(
            "ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT", DEFAULT_MAX_QUEUED_PER_PROJECT
        ),
        max_queued_per_user=_resolve_positive_int_env(
            "ANALYSIS_JOBS_MAX_QUEUED_PER_USER", DEFAULT_MAX_QUEUED_PER_USER
        ),
    )
