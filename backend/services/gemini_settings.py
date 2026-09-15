"""Reads Gemini-observation-related (Google Gemini API) environment
variables into a small, safe-to-pass-around settings object.

Mirrors services/claude_settings.py (itself mirroring
services/chatgpt_settings.py) exactly: this module does not call
Gemini itself (see services/gemini_client.py for the one place that
does) and does not decide *whether* "google" mode is even reachable
(see services/gemini_provider.py, which reads
GEMINI_PROVIDER_MODE/ALLOW_GEMINI_MODE_OVERRIDE directly).

The actual API key value is never stored anywhere except the one
short-lived GeminiCredentials object built immediately before a
request — see get_gemini_credentials().

**Default is always off, and this module never enables anything by
itself.** GEMINI_PROVIDER_MODE defaults to "off"
(services/gemini_provider.py), and this feature is not enabled in any
Render/Vercel environment as part of this change — see
docs/36_multi_ai_comparison_design.md.
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

DEFAULT_MAX_OUTPUT_TOKENS = 700
MIN_MAX_OUTPUT_TOKENS = 100
MAX_MAX_OUTPUT_TOKENS = 1500

# Default and only value that lets services/gemini_provider.py actually
# call Gemini — a single Gemini observation per /analyze request is the
# whole scope of this feature, mirroring
# services/claude_settings.py's DEFAULT_REQUEST_LIMIT_PER_ANALYZE. A
# different value doesn't get clamped back to 1: it's treated as an
# explicit gate failure instead.
DEFAULT_REQUEST_LIMIT_PER_ANALYZE = 1


@dataclass(frozen=True)
class GeminiCredentials:
    """The actual Gemini API key, for the one place that legitimately
    needs it: building the `x-goog-api-key` header for a
    generateContent request (see services/gemini_client.py). Never
    logged, never put in a response, held only for the duration of
    building one request — same pattern as
    services/claude_settings.py's ClaudeCredentials.
    """

    api_key: str

    def __repr__(self) -> str:
        return "GeminiCredentials(api_key=<redacted>)"


def get_gemini_credentials() -> GeminiCredentials | None:
    """Returns the actual API key, or None if unset. Callers should use
    this only to build an HTTP `x-goog-api-key` header immediately
    before a request — never store, log, or forward the result
    elsewhere.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None
    return GeminiCredentials(api_key=api_key)


@dataclass(frozen=True)
class GeminiSettings:
    """Snapshot of Gemini API request configuration for the current
    process — everything here is safe to log (no secret), unlike
    GeminiCredentials above.
    """

    is_configured: bool
    model: str
    max_output_tokens: int
    request_limit_per_analyze: int

    def __repr__(self) -> str:
        return (
            "GeminiSettings("
            f"is_configured={self.is_configured}, "
            f"model={self.model!r}, "
            f"max_output_tokens={self.max_output_tokens}, "
            f"request_limit_per_analyze={self.request_limit_per_analyze})"
        )


def _resolve_model() -> str:
    raw = os.environ.get("GEMINI_MODEL", "").strip()
    return raw or DEFAULT_MODEL


def _resolve_max_output_tokens() -> int:
    raw = os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "GEMINI_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS

    if value < MIN_MAX_OUTPUT_TOKENS or value > MAX_MAX_OUTPUT_TOKENS:
        logger.warning(
            "GEMINI_MAX_OUTPUT_TOKENS=%d is outside the allowed range [%d, %d]; falling back to %d",
            value,
            MIN_MAX_OUTPUT_TOKENS,
            MAX_MAX_OUTPUT_TOKENS,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS

    return value


def _resolve_request_limit() -> int:
    raw = os.environ.get(
        "GEMINI_REQUEST_LIMIT_PER_ANALYZE", str(DEFAULT_REQUEST_LIMIT_PER_ANALYZE)
    ).strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "GEMINI_REQUEST_LIMIT_PER_ANALYZE=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
        )
        return DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def get_gemini_settings() -> GeminiSettings:
    """Reads GEMINI_*/GEMINI_API_KEY env vars fresh on every call
    (mirrors services/claude_settings.py's get_claude_settings()), so a
    test or an operator changing the environment takes effect on the
    next request without a restart.
    """
    return GeminiSettings(
        is_configured=get_gemini_credentials() is not None,
        model=_resolve_model(),
        max_output_tokens=_resolve_max_output_tokens(),
        request_limit_per_analyze=_resolve_request_limit(),
    )
