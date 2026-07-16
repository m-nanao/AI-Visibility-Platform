"""Reads DataForSEO-related environment variables into a small,
safe-to-pass-around settings object.

This module does not call DataForSEO — it exists purely to centralize
how credentials/mode env vars are read, ahead of the actual connector
being implemented (see services/ai_overview_provider.py, which is the
only current caller). Two properties matter for safety:

1. The actual password value is never stored anywhere, not even in
   this settings object — only whether one was set
   (`password_configured`). There is therefore nothing to leak via a
   log line, an API response, or a stray `repr()`/`str()` call, since
   the value simply isn't held in memory beyond the one line that
   checks for its presence.
2. `can_use_live_api` requires three things to *all* be true —
   credentials configured, `DATAFORSEO_API_ENV=live`, and
   `DATAFORSEO_LIVE_API_ENABLED=true` — so a single misconfigured
   environment variable can't accidentally enable a real (billable)
   API call once a real connector exists.
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

DataForSEOApiEnv = Literal["sandbox", "live"]

# Default number of DataForSEO requests a single /analyze call is
# allowed to make, once a real connector exists. Kept deliberately low
# — DataForSEO is billed per request. MAX_REQUEST_LIMIT_PER_ANALYZE is
# a hard ceiling so a bad env var value (e.g. a typo like "100000")
# can't remove the cap entirely.
DEFAULT_REQUEST_LIMIT_PER_ANALYZE = 1
MAX_REQUEST_LIMIT_PER_ANALYZE = 10

_VALID_API_ENVS: tuple[DataForSEOApiEnv, ...] = ("sandbox", "live")


@dataclass(frozen=True)
class DataForSEOSettings:
    """Snapshot of DataForSEO configuration for the current process.

    `login` is kept as its actual value (a DataForSEO account
    identifier, not a secret on its own) so a future connector can use
    it directly; `password_configured` deliberately holds only a bool,
    never the password itself. See module docstring for why.
    """

    login: str | None
    password_configured: bool
    api_env: DataForSEOApiEnv
    live_api_enabled: bool
    request_limit_per_analyze: int
    is_configured: bool
    can_use_live_api: bool

    def __repr__(self) -> str:
        # Overridden so accidentally logging/printing this object (or
        # a dataclass default repr scan of it) can never show the
        # login value either, even though it's technically not the
        # secret half of the credential pair.
        login_display = "<set>" if self.login else None
        return (
            "DataForSEOSettings("
            f"login={login_display!r}, "
            f"password_configured={self.password_configured}, "
            f"api_env={self.api_env!r}, "
            f"live_api_enabled={self.live_api_enabled}, "
            f"request_limit_per_analyze={self.request_limit_per_analyze}, "
            f"is_configured={self.is_configured}, "
            f"can_use_live_api={self.can_use_live_api})"
        )


def _resolve_api_env() -> DataForSEOApiEnv:
    raw = os.environ.get("DATAFORSEO_API_ENV", "sandbox").strip().lower()
    if raw not in _VALID_API_ENVS:
        logger.warning(
            "DATAFORSEO_API_ENV=%r is not one of %s; falling back to \"sandbox\"",
            raw,
            _VALID_API_ENVS,
        )
        return "sandbox"
    return raw  # type: ignore[return-value]


def _resolve_request_limit() -> int:
    raw = os.environ.get(
        "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", str(DEFAULT_REQUEST_LIMIT_PER_ANALYZE)
    ).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
        )
        return DEFAULT_REQUEST_LIMIT_PER_ANALYZE

    if value < 0:
        logger.warning(
            "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=%d is negative; falling back to %d",
            value,
            DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
        )
        return DEFAULT_REQUEST_LIMIT_PER_ANALYZE

    if value > MAX_REQUEST_LIMIT_PER_ANALYZE:
        logger.warning(
            "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=%d exceeds the safety ceiling of %d; capping",
            value,
            MAX_REQUEST_LIMIT_PER_ANALYZE,
        )
        return MAX_REQUEST_LIMIT_PER_ANALYZE

    return value


def get_dataforseo_settings() -> DataForSEOSettings:
    """Reads DATAFORSEO_* env vars fresh on every call (mirrors the
    TOKENIZER_MODE/AI_OVERVIEW_PROVIDER_MODE pattern elsewhere in this
    codebase), so a test or an operator changing the environment takes
    effect on the next request without a restart being required by
    this function itself.
    """
    login = os.environ.get("DATAFORSEO_LOGIN", "").strip() or None
    password_configured = bool(os.environ.get("DATAFORSEO_PASSWORD", "").strip())

    api_env = _resolve_api_env()
    live_api_enabled = os.environ.get("DATAFORSEO_LIVE_API_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    request_limit_per_analyze = _resolve_request_limit()

    is_configured = login is not None and password_configured
    can_use_live_api = is_configured and api_env == "live" and live_api_enabled

    return DataForSEOSettings(
        login=login,
        password_configured=password_configured,
        api_env=api_env,
        live_api_enabled=live_api_enabled,
        request_limit_per_analyze=request_limit_per_analyze,
        is_configured=is_configured,
        can_use_live_api=can_use_live_api,
    )
