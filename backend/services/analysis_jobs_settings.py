"""Reads async-analysis-job-related environment variables into a
small settings object.

Placed under services/ to match the existing convention of every other
settings module living here (see services/db_settings.py,
services/auth_settings.py, services/common_crawl_settings.py).

Phase 1 of docs/40_async_analysis_jobs_design.md's staged plan
("15. 段階的実装計画") added `ANALYSIS_JOBS_ENABLED`, which gates the
entire POST/GET /analysis-jobs* endpoint group off by default — since
Phase 1 alone has no worker, a job created while only that flag is on
would sit in `queued` forever.

Phase 2 adds `ANALYSIS_JOBS_WORKER_ENABLED` — a second, independent
flag gating whether this process's FastAPI `lifespan` starts the
background worker task at all (see services/analysis_job_worker.py).
Independent on purpose: `ANALYSIS_JOBS_ENABLED=true` with
`ANALYSIS_JOBS_WORKER_ENABLED=false` is a valid, intentional
configuration (jobs can be created/inspected via the API but nothing
ever executes them — e.g. for safely testing Phase 1's API surface in
an environment that must never run analysis automatically), and so is
the reverse during development. Both default to False, so a
production deployment that doesn't set either env var behaves exactly
as it did before Phase 1/2 existed. No value here is a secret.
"""

import os
from dataclasses import dataclass

DEFAULT_ANALYSIS_JOBS_ENABLED = False
DEFAULT_ANALYSIS_JOBS_WORKER_ENABLED = False
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
# Worker tuning defaults (docs/40 "11.3"/"12.6"/"21") — also not a
# final product decision, just a reasonable MVP starting point. The
# lease must comfortably exceed the pipeline's worst-case wall-clock
# time (docs/40 "1.3": ~100s with every provider ON) with margin for a
# slow Render Free cold instance; the poll interval trades
# responsiveness against DB load. The heartbeat interval must be
# comfortably shorter than the lease — a worker genuinely still
# running a job extends the lease well before it would otherwise
# expire — see services/analysis_job_worker.py's heartbeat loop.
DEFAULT_LEASE_SECONDS = 180
DEFAULT_POLL_INTERVAL_SECONDS = 5
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class AnalysisJobsSettings:
    """Snapshot of async-analysis-job configuration for the current
    process."""

    enabled: bool
    worker_enabled: bool
    max_queued_per_project: int
    max_queued_per_user: int
    lease_seconds: int
    poll_interval_seconds: int
    heartbeat_interval_seconds: int


def _resolve_bool_env(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
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
    """Reads ANALYSIS_JOBS_ENABLED/ANALYSIS_JOBS_WORKER_ENABLED/
    ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT/ANALYSIS_JOBS_MAX_QUEUED_PER_USER/
    ANALYSIS_JOBS_LEASE_SECONDS/ANALYSIS_JOBS_POLL_INTERVAL_SECONDS/
    ANALYSIS_JOBS_HEARTBEAT_INTERVAL_SECONDS env vars fresh on every
    call (mirrors load_db_settings() and friends elsewhere in this
    codebase). Both `enabled` and `worker_enabled` default to False —
    neither the job endpoints nor the worker are ever reachable/started
    unless explicitly turned on.
    """
    return AnalysisJobsSettings(
        enabled=_resolve_bool_env("ANALYSIS_JOBS_ENABLED"),
        worker_enabled=_resolve_bool_env("ANALYSIS_JOBS_WORKER_ENABLED"),
        max_queued_per_project=_resolve_positive_int_env(
            "ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT", DEFAULT_MAX_QUEUED_PER_PROJECT
        ),
        max_queued_per_user=_resolve_positive_int_env(
            "ANALYSIS_JOBS_MAX_QUEUED_PER_USER", DEFAULT_MAX_QUEUED_PER_USER
        ),
        lease_seconds=_resolve_positive_int_env(
            "ANALYSIS_JOBS_LEASE_SECONDS", DEFAULT_LEASE_SECONDS
        ),
        poll_interval_seconds=_resolve_positive_int_env(
            "ANALYSIS_JOBS_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS
        ),
        heartbeat_interval_seconds=_resolve_positive_int_env(
            "ANALYSIS_JOBS_HEARTBEAT_INTERVAL_SECONDS", DEFAULT_HEARTBEAT_INTERVAL_SECONDS
        ),
    )
