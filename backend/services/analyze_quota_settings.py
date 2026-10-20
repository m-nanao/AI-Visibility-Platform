"""Reads Task 6-B4 (feature/sync-analyze-jwt-project-auth) usage-quota
environment variables into a small settings object.

Placed under services/ to match the existing convention of every
other settings module living here (see services/db_settings.py,
services/analysis_jobs_settings.py, services/dataforseo_settings.py).

Two independent flags, mirroring the ANALYZE_AUTH_REQUIRED /
NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED split from Task 6-B2:

- `ANALYZE_QUOTA_ENFORCEMENT_ENABLED` (default False) — whether the
  authenticated synchronous /analyze path
  (main._analyze_authenticated_idempotent(), ANALYZE_AUTH_REQUIRED=true)
  actually reserves/checks usage counters at all. False means the
  limits below are never consulted — the exact pre-Task-6-B4 behavior.
- `ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA` (default False) — a narrow,
  explicit *development/testing-only* escape hatch. With
  ANALYZE_AUTH_REQUIRED=true, running with quota enforcement disabled
  means every cost-protection guarantee this feature exists for is
  gone (an authenticated caller could submit unlimited distinct
  requestIds, each a fresh, unmetered, potentially paid execution) —
  see Task 6-B4's design report "6". The basic/default policy is
  therefore to *refuse* to run the authenticated path at all in that
  combination (main.py returns 503/quota_enforcement_required) rather
  than silently running unmetered. Setting this flag to true is the
  only way to deliberately accept that combination anyway — it must
  never be left set in a production deployment; see the warning log
  main.py emits every time this path is taken.

Every per-scope/per-metric limit below accepts 0 as a fully valid,
meaningful value ("this is disabled — never allow a single call"), so
the integer parser here (_resolve_non_negative_int_env) is
deliberately different from analysis_jobs_settings.py's
_resolve_positive_int_env(), which treats 0 as invalid. An unset,
blank, negative, or non-integer env value always falls back to this
module's own DEFAULT_* constant for that specific setting — never to
0-as-a-stand-in-for-"any failure", and never silently promoted to a
larger number — so a misconfigured/missing env var can only ever make
a paid provider's limit *more* conservative (its safe default is
already 0; see below), never accidentally permissive. Setting a
provider's limit above 0 only ever raises the *cap* on how many calls
may happen — it has no effect whatsoever on whether that provider is
enabled in the first place (that is decided entirely by
AI_OVERVIEW_PROVIDER_MODE/CHATGPT_PROVIDER_MODE/CLAUDE_PROVIDER_MODE/
GEMINI_PROVIDER_MODE and their own ALLOW_*_MODE_OVERRIDE flags,
unrelated to this module) — there is no way to "turn on" a paid
provider via any variable defined here.
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_ANALYZE_QUOTA_ENFORCEMENT_ENABLED = False
DEFAULT_ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA = False

# MVP placeholders, not a final product/business decision — see Task
# 6-B4's design report "2" for the reasoning behind each number. Every
# paid-provider default is deliberately 0 ("disabled") until a real
# budget decision is made; only the "all analyses" counters (which
# also cover free mock/off runs) and the never-billed DataForSEO
# Sandbox path start with a non-zero default.
DEFAULT_MAX_USER_DAILY = 20
DEFAULT_MAX_PROJECT_DAILY = 50
DEFAULT_MAX_PROJECT_MONTHLY = 500

# One (daily, monthly) default pair per paid-provider metric this
# feature meters. Keys match the exact `metric` strings
# create_running_analysis_run()'s required_counters use (see
# services/analysis_history_repository.py) and
# resolve_dataforseo_environment()'s return values
# ("sandbox"/"live" -> "dataforseo_sandbox"/"dataforseo_live").
_DEFAULT_DAILY_BY_METRIC: dict[str, int] = {
    "dataforseo_sandbox": 50,
    "dataforseo_live": 0,
    "openai": 0,
    "anthropic": 0,
    "google": 0,
}
_DEFAULT_MONTHLY_BY_METRIC: dict[str, int] = {
    "dataforseo_sandbox": 500,
    "dataforseo_live": 0,
    "openai": 0,
    "anthropic": 0,
    "google": 0,
}

# Maps each metric to the env-var name suffix used below —
# ANALYZE_QUOTA_MAX_PROJECT_DAILY_<suffix> /
# ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_<suffix>.
_METRIC_ENV_SUFFIXES: dict[str, str] = {
    "dataforseo_sandbox": "DATAFORSEO_SANDBOX",
    "dataforseo_live": "DATAFORSEO_LIVE",
    "openai": "OPENAI",
    "anthropic": "ANTHROPIC",
    "google": "GOOGLE",
}


def _resolve_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "%s=%r is not a recognized boolean; falling back to %s", name, raw, default
    )
    return default


def _resolve_non_negative_int_env(name: str, default: int) -> int:
    """Like analysis_jobs_settings.py's _resolve_positive_int_env(),
    but 0 is a valid result (meaning "disabled") rather than treated
    as invalid — see this module's docstring for why that distinction
    matters here. Logs a warning (not a silent fallback) on an
    invalid/negative value, mirroring dataforseo_settings.py's
    _resolve_request_limit() style, since a quota-limit misconfiguration
    is exactly the kind of thing an operator needs to notice.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "%s=%r is not an integer; falling back to %s", name, raw, default
        )
        return default
    if value < 0:
        logger.warning(
            "%s=%r must be 0 or greater; falling back to %s", name, raw, default
        )
        return default
    return value


@dataclass(frozen=True)
class AnalyzeQuotaSettings:
    """Snapshot of Task 6-B4 usage-quota configuration for the current
    process. `max_project_daily_by_metric`/`max_project_monthly_by_metric`
    are keyed by the exact paid-provider `metric` strings this feature
    uses (see module docstring)."""

    enforcement_enabled: bool
    allow_auth_without_quota: bool
    max_user_daily: int
    max_project_daily: int
    max_project_monthly: int
    max_project_daily_by_metric: dict[str, int] = field(default_factory=dict)
    max_project_monthly_by_metric: dict[str, int] = field(default_factory=dict)


def load_analyze_quota_settings() -> AnalyzeQuotaSettings:
    """Reads every ANALYZE_QUOTA_*/ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA env
    var fresh on every call (mirrors load_analysis_jobs_settings() and
    every other load_*_settings() in this codebase — no caching, so a
    test can monkeypatch os.environ and simply call this again)."""
    daily_by_metric = {
        metric: _resolve_non_negative_int_env(
            f"ANALYZE_QUOTA_MAX_PROJECT_DAILY_{suffix}", _DEFAULT_DAILY_BY_METRIC[metric]
        )
        for metric, suffix in _METRIC_ENV_SUFFIXES.items()
    }
    monthly_by_metric = {
        metric: _resolve_non_negative_int_env(
            f"ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_{suffix}", _DEFAULT_MONTHLY_BY_METRIC[metric]
        )
        for metric, suffix in _METRIC_ENV_SUFFIXES.items()
    }
    return AnalyzeQuotaSettings(
        enforcement_enabled=_resolve_bool_env(
            "ANALYZE_QUOTA_ENFORCEMENT_ENABLED", DEFAULT_ANALYZE_QUOTA_ENFORCEMENT_ENABLED
        ),
        allow_auth_without_quota=_resolve_bool_env(
            "ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA", DEFAULT_ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA
        ),
        max_user_daily=_resolve_non_negative_int_env(
            "ANALYZE_QUOTA_MAX_USER_DAILY", DEFAULT_MAX_USER_DAILY
        ),
        max_project_daily=_resolve_non_negative_int_env(
            "ANALYZE_QUOTA_MAX_PROJECT_DAILY", DEFAULT_MAX_PROJECT_DAILY
        ),
        max_project_monthly=_resolve_non_negative_int_env(
            "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY", DEFAULT_MAX_PROJECT_MONTHLY
        ),
        max_project_daily_by_metric=daily_by_metric,
        max_project_monthly_by_metric=monthly_by_metric,
    )
