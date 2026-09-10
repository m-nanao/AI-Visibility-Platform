"""Reads DB persistence-related environment variables into a small
settings object.

Placed under services/ (rather than the backend/settings_db.py
candidate name from the task) to match the existing convention of
every other provider settings module living here (see
services/common_crawl_settings.py, services/chatgpt_settings.py,
services/dataforseo_settings.py).

Unlike services/common_crawl_settings.py, DATABASE_URL is a credential
(a Postgres connection string commonly embeds a password) — never log
or repr() it. Only save_enabled is safe to log. The same applies to
HISTORY_READ_TOKEN below.

See docs/19_minimum_db_migration_design.md for the migration/table
design this feeds into (services/analysis_history_repository.py), and
docs/24_auth_rls_history_access_design.md for why the read API also
needs a shared-secret gate (HISTORY_READ_TOKEN) on top of
READ_HISTORY_ENABLED — READ_HISTORY_ENABLED alone doesn't stop anyone
who can reach this service from reading saved history.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_SAVE_ENABLED = False
DEFAULT_READ_HISTORY_ENABLED = False


@dataclass(frozen=True)
class DbSettings:
    """Snapshot of DB persistence configuration for the current
    process. `database_url` may be `None` and, when set, must not be
    logged or included in any response.
    """

    save_enabled: bool
    database_url: str | None
    # Deliberately a separate flag from save_enabled — see
    # is_history_read_enabled()'s docstring for why DB_SAVE_ENABLED
    # alone must never turn on the read API.
    read_history_enabled: bool
    # Shared secret the read API requires in the X-History-Read-Token
    # header — see is_history_read_token_configured() and main.py's
    # _check_history_read_access(). Never log or include in a response.
    history_read_token: str | None


def _resolve_save_enabled() -> bool:
    raw = os.environ.get("DB_SAVE_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_read_history_enabled() -> bool:
    raw = os.environ.get("READ_HISTORY_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_database_url() -> str | None:
    raw = os.environ.get("DATABASE_URL", "").strip()
    return raw or None


def _resolve_history_read_token() -> str | None:
    raw = os.environ.get("HISTORY_READ_TOKEN", "").strip()
    return raw or None


def load_db_settings() -> DbSettings:
    """Reads DB_SAVE_ENABLED/READ_HISTORY_ENABLED/DATABASE_URL/
    HISTORY_READ_TOKEN env vars fresh on every call (mirrors
    load_common_crawl_settings() and friends elsewhere in this
    codebase), so a test or an operator changing the environment takes
    effect on the next request without a restart. Defaults to
    save_enabled=False/read_history_enabled=False/history_read_token=None
    — neither DB persistence nor the read API activates unless
    explicitly turned on.
    """
    return DbSettings(
        save_enabled=_resolve_save_enabled(),
        database_url=_resolve_database_url(),
        read_history_enabled=_resolve_read_history_enabled(),
        history_read_token=_resolve_history_read_token(),
    )


def is_db_save_configured(settings: DbSettings | None = None) -> bool:
    """True only when DB persistence should be attempted at all —
    DB_SAVE_ENABLED=true AND DATABASE_URL is set. Used by
    services/analysis_history_repository.py to skip DB work entirely
    (no connection attempt) whenever either is missing.
    """
    settings = settings or load_db_settings()
    return settings.save_enabled and settings.database_url is not None


def is_history_read_enabled(settings: DbSettings | None = None) -> bool:
    """True only when the read API (GET /analysis-runs, GET
    /analysis-runs/{id}) should be allowed to attempt a DB connection —
    READ_HISTORY_ENABLED=true AND DATABASE_URL is set.

    Deliberately independent of save_enabled: DB_SAVE_ENABLED=true alone
    must never turn on the read API, because saving is an internal
    backend-to-DB write with no external caller, while the read API is
    reachable by anyone who can call this service — a different safety
    profile that needs its own explicit opt-in (see
    docs/20_analysis_history_read_api_design.md "9. 認証未実装期間の
    公開範囲").
    """
    settings = settings or load_db_settings()
    return settings.read_history_enabled and settings.database_url is not None


def is_history_read_token_configured(settings: DbSettings | None = None) -> bool:
    """True only when HISTORY_READ_TOKEN is set to a non-blank value.

    Checked by main.py's read API endpoints *in addition to*
    is_history_read_enabled() — READ_HISTORY_ENABLED=true alone is not
    enough to serve requests; an operator must also configure a token,
    so the read API can never be reachable by anyone who can simply
    guess an analysis_run_id (see
    docs/24_auth_rls_history_access_design.md "7. backend APIでの
    アクセス制御案"). Independent of is_db_save_configured()/
    is_history_read_enabled() the same way those two are independent of
    each other.
    """
    settings = settings or load_db_settings()
    return settings.history_read_token is not None
