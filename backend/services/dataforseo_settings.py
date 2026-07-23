"""Reads DataForSEO-related environment variables into a small,
safe-to-pass-around settings object.

This module does not call DataForSEO — it exists purely to centralize
how credentials/mode env vars are read (see services/ai_overview_provider.py,
the only caller that actually decides whether to connect). Two
properties matter for safety:

1. The actual password value is never stored anywhere, not even in
   this settings object — only whether one was set
   (`password_configured`). There is therefore nothing to leak via a
   log line, an API response, or a stray `repr()`/`str()` call, since
   the value simply isn't held in memory beyond the one line that
   checks for its presence.
2. `is_live_allowed_for_manual_check` requires *five* independent
   things to all be true at once — credentials configured,
   `DATAFORSEO_API_ENV=live`, `DATAFORSEO_LIVE_API_ENABLED=true`, an
   exact-match manual confirmation string
   (`DATAFORSEO_LIVE_CONFIRM_TEXT=ALLOW_DATAFORSEO_LIVE_ONCE`), and
   `DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE=1` — so no single
   misconfigured environment variable, and no accidental "leave live
   mode on" after a manual check, can enable a real (billable) Live
   API call. There is deliberately no way to make Live the *persistent*
   default from this module alone: reaching `dataforseo` mode at all
   still requires `AI_OVERVIEW_PROVIDER_MODE`/`ALLOW_AI_OVERVIEW_MODE_OVERRIDE`
   to agree first (see services/ai_overview_provider.py).
"""

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

DataForSEOApiEnv = Literal["sandbox", "live"]

# Which DataForSEO SERP endpoint to request. "google_ai_mode_live_advanced"
# is the recommended default — manual verification against DataForSEO
# Sandbox (see docs/07_decisions.md) confirmed that the Google Organic
# endpoint does *not* reliably surface an "ai_overview" item for the
# queries tried, while the AI Mode endpoint does. "google_organic_live_advanced"
# is kept only for backwards compatibility with the previous
# implementation. Note that "live" in both endpoint names is DataForSEO's
# own naming for their instant-response request method — orthogonal to
# the Sandbox/Live *environment* distinction (DATAFORSEO_API_ENV) this
# codebase cares about; the actual HTTP host requested is always decided
# by DATAFORSEO_API_ENV, never by this setting.
DataForSEOSerpEndpoint = Literal["google_ai_mode_live_advanced", "google_organic_live_advanced"]
DEFAULT_SERP_ENDPOINT: DataForSEOSerpEndpoint = "google_ai_mode_live_advanced"
_VALID_SERP_ENDPOINTS: tuple[DataForSEOSerpEndpoint, ...] = (
    "google_ai_mode_live_advanced",
    "google_organic_live_advanced",
)

# Request parameters for the SERP call, all overridable via env vars.
# Defaults match the exact combination manually verified to return an
# "ai_overview" item for a "Vercel" query against DataForSEO Sandbox
# (see docs/07_decisions.md): Japan/Japanese, desktop, Windows.
DEFAULT_LOCATION_CODE = 2392  # DataForSEO location_code for "Japan"
DEFAULT_LANGUAGE_CODE = "ja"
DEFAULT_DEVICE = "desktop"
_VALID_DEVICES: tuple[str, ...] = ("desktop", "mobile")
DEFAULT_OS = "windows"
# Not exhaustive of everything DataForSEO accepts, but covers the OS
# values it documents for desktop (windows/macos/linux) and mobile
# (android/ios); anything else falls back to the safe default.
_VALID_OS_VALUES: tuple[str, ...] = ("windows", "macos", "linux", "android", "ios")

# Base URLs for the two DataForSEO API environments. Only
# SANDBOX_BASE_URL is ever actually requested by this codebase (see
# services/dataforseo_client.py) — LIVE_BASE_URL is defined here for
# completeness/documentation only, so a future task that does
# implement Live has a single place to read it from, but no code path
# in this task constructs a request against it.
SANDBOX_BASE_URL = "https://sandbox.dataforseo.com"
LIVE_BASE_URL = "https://api.dataforseo.com"

# Default number of DataForSEO requests a single /analyze call is
# allowed to make, once a real connector exists. Kept deliberately low
# — DataForSEO is billed per request. MAX_REQUEST_LIMIT_PER_ANALYZE is
# a hard ceiling so a bad env var value (e.g. a typo like "100000")
# can't remove the cap entirely.
DEFAULT_REQUEST_LIMIT_PER_ANALYZE = 1
MAX_REQUEST_LIMIT_PER_ANALYZE = 10

_VALID_API_ENVS: tuple[DataForSEOApiEnv, ...] = ("sandbox", "live")

# Exact string an operator must set DATAFORSEO_LIVE_CONFIRM_TEXT to in
# order to satisfy the manual Live confirmation gate (see
# is_live_allowed_for_manual_check below). Deliberately not a simple
# "true"/"1" boolean flag — a distinctive, unlikely-to-be-set-by-accident
# string makes it much harder to enable a billable Live request through
# a copy-pasted `.env` template or a stray "true" left over from testing
# a different flag.
DATAFORSEO_LIVE_CONFIRM_TEXT_REQUIRED = "ALLOW_DATAFORSEO_LIVE_ONCE"


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
    live_confirm_text_matches: bool
    request_limit_per_analyze: int
    is_configured: bool
    can_use_live_api: bool
    is_sandbox_env: bool
    is_live_env: bool
    is_live_allowed_for_manual_check: bool
    serp_endpoint: DataForSEOSerpEndpoint
    location_code: int
    language_code: str
    device: str
    os: str

    def __repr__(self) -> str:
        # Overridden so accidentally logging/printing this object (or
        # a dataclass default repr scan of it) can never show the
        # login value either, even though it's technically not the
        # secret half of the credential pair. Everything else here
        # (env/flags/gates/SERP request parameters) isn't a secret, so
        # it's shown as-is — including live_confirm_text_matches, which
        # is only a bool (whether the configured text matched the
        # required constant), never the configured text itself.
        login_display = "<set>" if self.login else None
        return (
            "DataForSEOSettings("
            f"login={login_display!r}, "
            f"password_configured={self.password_configured}, "
            f"api_env={self.api_env!r}, "
            f"live_api_enabled={self.live_api_enabled}, "
            f"live_confirm_text_matches={self.live_confirm_text_matches}, "
            f"request_limit_per_analyze={self.request_limit_per_analyze}, "
            f"is_configured={self.is_configured}, "
            f"can_use_live_api={self.can_use_live_api}, "
            f"is_sandbox_env={self.is_sandbox_env}, "
            f"is_live_env={self.is_live_env}, "
            f"is_live_allowed_for_manual_check={self.is_live_allowed_for_manual_check}, "
            f"serp_endpoint={self.serp_endpoint!r}, "
            f"location_code={self.location_code}, "
            f"language_code={self.language_code!r}, "
            f"device={self.device!r}, "
            f"os={self.os!r})"
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


def _resolve_live_confirm_text_matches() -> bool:
    # Intentionally an exact, case-sensitive match — no trimming beyond
    # surrounding whitespace, no case-insensitivity, no truthy-string
    # coercion like the other boolean flags in this module use. This is
    # a one-time manual confirmation phrase, not a persistent settings
    # flag, so it should not be easy to satisfy by accident.
    raw = os.environ.get("DATAFORSEO_LIVE_CONFIRM_TEXT", "").strip()
    return raw == DATAFORSEO_LIVE_CONFIRM_TEXT_REQUIRED


def _resolve_serp_endpoint() -> DataForSEOSerpEndpoint:
    raw = os.environ.get("DATAFORSEO_SERP_ENDPOINT", DEFAULT_SERP_ENDPOINT).strip().lower()
    if raw not in _VALID_SERP_ENDPOINTS:
        logger.warning(
            "DATAFORSEO_SERP_ENDPOINT=%r is not one of %s; falling back to %r",
            raw,
            _VALID_SERP_ENDPOINTS,
            DEFAULT_SERP_ENDPOINT,
        )
        return DEFAULT_SERP_ENDPOINT
    return raw  # type: ignore[return-value]


def _resolve_location_code() -> int:
    raw = os.environ.get("DATAFORSEO_LOCATION_CODE", str(DEFAULT_LOCATION_CODE)).strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "DATAFORSEO_LOCATION_CODE=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_LOCATION_CODE,
        )
        return DEFAULT_LOCATION_CODE


def _resolve_language_code() -> str:
    raw = os.environ.get("DATAFORSEO_LANGUAGE_CODE", "").strip()
    return raw or DEFAULT_LANGUAGE_CODE


def _resolve_device() -> str:
    raw = os.environ.get("DATAFORSEO_DEVICE", DEFAULT_DEVICE).strip().lower()
    if raw not in _VALID_DEVICES:
        logger.warning(
            "DATAFORSEO_DEVICE=%r is not one of %s; falling back to %r",
            raw,
            _VALID_DEVICES,
            DEFAULT_DEVICE,
        )
        return DEFAULT_DEVICE
    return raw


def _resolve_os() -> str:
    raw = os.environ.get("DATAFORSEO_OS", DEFAULT_OS).strip().lower()
    if raw not in _VALID_OS_VALUES:
        logger.warning(
            "DATAFORSEO_OS=%r is not one of %s; falling back to %r",
            raw,
            _VALID_OS_VALUES,
            DEFAULT_OS,
        )
        return DEFAULT_OS
    return raw


@dataclass(frozen=True)
class DataForSEOCredentials:
    """The actual login/password pair, for the one place that legitimately
    needs it: building the Basic Auth header for a Sandbox request (see
    services/dataforseo_client.py). Deliberately a *separate* type from
    DataForSEOSettings above — that object is designed to be safe to log
    or hand to callers freely, and must never be extended to also carry
    the real password. This type is the opposite: never logged, never
    put in a response, and held only for the duration of building one
    HTTP request.
    """

    login: str
    password: str

    def __repr__(self) -> str:
        return "DataForSEOCredentials(login=<redacted>, password=<redacted>)"


def get_dataforseo_credentials() -> DataForSEOCredentials | None:
    """Returns the actual credential pair, or None if either half is
    unset. Callers should use this only to build an HTTP Basic Auth
    tuple immediately before a request — never store, log, or forward
    the result elsewhere.
    """
    login = os.environ.get("DATAFORSEO_LOGIN", "").strip()
    password = os.environ.get("DATAFORSEO_PASSWORD", "").strip()
    if not login or not password:
        return None
    return DataForSEOCredentials(login=login, password=password)


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
    live_confirm_text_matches = _resolve_live_confirm_text_matches()
    request_limit_per_analyze = _resolve_request_limit()

    is_configured = login is not None and password_configured
    can_use_live_api = is_configured and api_env == "live" and live_api_enabled
    is_sandbox_env = api_env == "sandbox"
    is_live_env = api_env == "live"
    # All five gates below must hold at once — see module docstring and
    # docs/07_decisions.md for why each one exists. Unlike
    # `can_use_live_api` above (kept for backwards compatibility, not
    # currently consulted for the actual Live-vs-Sandbox host decision),
    # this is the one property services/ai_overview_provider.py actually
    # checks before ever building a request against the Live host.
    is_live_allowed_for_manual_check = (
        is_live_env
        and live_api_enabled
        and live_confirm_text_matches
        and request_limit_per_analyze == 1
        and is_configured
    )

    return DataForSEOSettings(
        login=login,
        password_configured=password_configured,
        api_env=api_env,
        live_api_enabled=live_api_enabled,
        live_confirm_text_matches=live_confirm_text_matches,
        request_limit_per_analyze=request_limit_per_analyze,
        is_configured=is_configured,
        can_use_live_api=can_use_live_api,
        is_sandbox_env=is_sandbox_env,
        is_live_env=is_live_env,
        is_live_allowed_for_manual_check=is_live_allowed_for_manual_check,
        serp_endpoint=_resolve_serp_endpoint(),
        location_code=_resolve_location_code(),
        language_code=_resolve_language_code(),
        device=_resolve_device(),
        os=_resolve_os(),
    )
