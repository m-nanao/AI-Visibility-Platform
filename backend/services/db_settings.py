"""Reads DB persistence-related environment variables into a small
settings object.

Placed under services/ (rather than the backend/settings_db.py
candidate name from the task) to match the existing convention of
every other provider settings module living here (see
services/common_crawl_settings.py, services/chatgpt_settings.py,
services/dataforseo_settings.py).

Unlike services/common_crawl_settings.py, DATABASE_URL is a credential
(a Postgres connection string commonly embeds a password) — never log
or repr() it. Only save_enabled is safe to log.

See docs/19_minimum_db_migration_design.md for the migration/table
design this feeds into (services/analysis_history_repository.py).
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_SAVE_ENABLED = False


@dataclass(frozen=True)
class DbSettings:
    """Snapshot of DB persistence configuration for the current
    process. `database_url` may be `None` and, when set, must not be
    logged or included in any response.
    """

    save_enabled: bool
    database_url: str | None


def _resolve_save_enabled() -> bool:
    raw = os.environ.get("DB_SAVE_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_database_url() -> str | None:
    raw = os.environ.get("DATABASE_URL", "").strip()
    return raw or None


def load_db_settings() -> DbSettings:
    """Reads DB_SAVE_ENABLED/DATABASE_URL env vars fresh on every call
    (mirrors load_common_crawl_settings() and friends elsewhere in this
    codebase), so a test or an operator changing the environment takes
    effect on the next request without a restart. Defaults to
    save_enabled=False — DB persistence never activates unless
    explicitly turned on.
    """
    return DbSettings(
        save_enabled=_resolve_save_enabled(),
        database_url=_resolve_database_url(),
    )


def is_db_save_configured(settings: DbSettings | None = None) -> bool:
    """True only when DB persistence should be attempted at all —
    DB_SAVE_ENABLED=true AND DATABASE_URL is set. Used by
    services/analysis_history_repository.py to skip DB work entirely
    (no connection attempt) whenever either is missing.
    """
    settings = settings or load_db_settings()
    return settings.save_enabled and settings.database_url is not None
