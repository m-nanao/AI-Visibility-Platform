"""Reads ChatGPT-observation-related (OpenAI API) environment
variables into a small, safe-to-pass-around settings object.

Mirrors services/dataforseo_settings.py's split of responsibilities:
this module does not call OpenAI itself (see services/chatgpt_client.py
for the one place that does) and does not decide *whether* "openai"
mode is even reachable (see services/chatgpt_provider.py, which reads
CHATGPT_PROVIDER_MODE/ALLOW_CHATGPT_MODE_OVERRIDE directly — those two
env vars gate the whole ChatGPT-observation feature, not just OpenAI
API configuration, so they live in the provider module rather than
here, exactly like AI_OVERVIEW_PROVIDER_MODE/ALLOW_AI_OVERVIEW_MODE_OVERRIDE
live in services/ai_overview_provider.py rather than
services/dataforseo_settings.py).

The actual API key value is never stored anywhere except the one
short-lived ChatGptCredentials object built immediately before a
request — see get_chatgpt_credentials().
"""

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5-mini"

DEFAULT_MAX_OUTPUT_TOKENS = 700
MIN_MAX_OUTPUT_TOKENS = 100
MAX_MAX_OUTPUT_TOKENS = 1500

# Low by design: this observation is meant to be a stable, repeatable
# demo/verification data point, not a creative or varied answer. A
# lower temperature keeps the same brand name producing a similarly-
# shaped answer across /analyze calls (see docs/07_decisions.md).
DEFAULT_TEMPERATURE = 0.2
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 1.0

# Default and only value that lets services/chatgpt_provider.py actually
# call OpenAI — a single ChatGPT observation per /analyze request is
# the whole scope of this feature (see docs/07_decisions.md). A
# different value doesn't get clamped back to 1: it's treated as an
# explicit gate failure instead (mirrors DataForSEO's
# DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE + is_live_allowed_for_manual_check).
DEFAULT_REQUEST_LIMIT_PER_ANALYZE = 1


@dataclass(frozen=True)
class ChatGptCredentials:
    """The actual OpenAI API key, for the one place that legitimately
    needs it: building the Authorization header for a Responses API
    request (see services/chatgpt_client.py). Never logged, never put
    in a response, held only for the duration of building one request —
    same pattern as services/dataforseo_settings.py's
    DataForSEOCredentials.
    """

    api_key: str

    def __repr__(self) -> str:
        return "ChatGptCredentials(api_key=<redacted>)"


def get_chatgpt_credentials() -> ChatGptCredentials | None:
    """Returns the actual API key, or None if unset. Callers should use
    this only to build an HTTP Authorization header immediately before
    a request — never store, log, or forward the result elsewhere.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    return ChatGptCredentials(api_key=api_key)


@dataclass(frozen=True)
class ChatGptSettings:
    """Snapshot of OpenAI API request configuration for the current
    process — everything here is safe to log (no secret), unlike
    ChatGptCredentials above.
    """

    is_configured: bool
    model: str
    max_output_tokens: int
    request_limit_per_analyze: int
    temperature: float

    def __repr__(self) -> str:
        return (
            "ChatGptSettings("
            f"is_configured={self.is_configured}, "
            f"model={self.model!r}, "
            f"max_output_tokens={self.max_output_tokens}, "
            f"request_limit_per_analyze={self.request_limit_per_analyze}, "
            f"temperature={self.temperature})"
        )


def _resolve_model() -> str:
    raw = os.environ.get("CHATGPT_MODEL", "").strip()
    return raw or DEFAULT_MODEL


def _resolve_max_output_tokens() -> int:
    raw = os.environ.get("CHATGPT_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "CHATGPT_MAX_OUTPUT_TOKENS=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS

    if value < MIN_MAX_OUTPUT_TOKENS or value > MAX_MAX_OUTPUT_TOKENS:
        logger.warning(
            "CHATGPT_MAX_OUTPUT_TOKENS=%d is outside the allowed range [%d, %d]; falling back to %d",
            value,
            MIN_MAX_OUTPUT_TOKENS,
            MAX_MAX_OUTPUT_TOKENS,
            DEFAULT_MAX_OUTPUT_TOKENS,
        )
        return DEFAULT_MAX_OUTPUT_TOKENS

    return value


def _resolve_request_limit() -> int:
    raw = os.environ.get(
        "CHATGPT_REQUEST_LIMIT_PER_ANALYZE", str(DEFAULT_REQUEST_LIMIT_PER_ANALYZE)
    ).strip()
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "CHATGPT_REQUEST_LIMIT_PER_ANALYZE=%r is not an integer; falling back to %d",
            raw,
            DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
        )
        return DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def _resolve_temperature() -> float:
    raw = os.environ.get("CHATGPT_TEMPERATURE", str(DEFAULT_TEMPERATURE)).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "CHATGPT_TEMPERATURE=%r is not a number; falling back to %s",
            raw,
            DEFAULT_TEMPERATURE,
        )
        return DEFAULT_TEMPERATURE

    if value < MIN_TEMPERATURE or value > MAX_TEMPERATURE:
        logger.warning(
            "CHATGPT_TEMPERATURE=%s is outside the allowed range [%s, %s]; falling back to %s",
            value,
            MIN_TEMPERATURE,
            MAX_TEMPERATURE,
            DEFAULT_TEMPERATURE,
        )
        return DEFAULT_TEMPERATURE

    return value


def get_chatgpt_settings() -> ChatGptSettings:
    """Reads CHATGPT_*/OPENAI_API_KEY env vars fresh on every call
    (mirrors services/dataforseo_settings.py's get_dataforseo_settings()),
    so a test or an operator changing the environment takes effect on
    the next request without a restart.
    """
    return ChatGptSettings(
        is_configured=get_chatgpt_credentials() is not None,
        model=_resolve_model(),
        max_output_tokens=_resolve_max_output_tokens(),
        request_limit_per_analyze=_resolve_request_limit(),
        temperature=_resolve_temperature(),
    )
