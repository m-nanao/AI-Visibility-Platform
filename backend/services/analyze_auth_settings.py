"""Reads the ANALYZE_AUTH_REQUIRED environment variable into a small
settings object.

Placed under services/ to match the existing convention of every other
settings module living here (see services/db_settings.py,
services/auth_settings.py, services/analysis_jobs_settings.py).

Task 6-B2 (feature/sync-analyze-jwt-project-auth): adds a JWT+project
authorization gate to POST /analyze, but keeps the existing anonymous/
default-project behavior fully intact as long as this flag is false —
which it is by default, so an existing deployment that doesn't set this
var is completely unaffected. Only once this flag is explicitly set to
true does POST /analyze require a verified Supabase JWT and an
accessible projectId; see main.py's analyze() for the actual gate.
"""

import os
from dataclasses import dataclass

DEFAULT_ANALYZE_AUTH_REQUIRED = False


@dataclass(frozen=True)
class AnalyzeAuthSettings:
    """Snapshot of POST /analyze's auth-requirement configuration for
    the current process."""

    auth_required: bool


def _resolve_auth_required() -> bool:
    raw = os.environ.get("ANALYZE_AUTH_REQUIRED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def load_analyze_auth_settings() -> AnalyzeAuthSettings:
    """Reads ANALYZE_AUTH_REQUIRED fresh on every call (mirrors
    load_auth_settings() and friends elsewhere in this codebase).
    Defaults to auth_required=False — POST /analyze remains anonymous
    and unchanged unless this is explicitly turned on.
    """
    return AnalyzeAuthSettings(auth_required=_resolve_auth_required())
