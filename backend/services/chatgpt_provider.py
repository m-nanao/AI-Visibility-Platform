"""ChatGPT-equivalent observation provider — a single, optional
OpenAI API call asked one question about the brand, whose result (if
any) is appended to `aiOverviewComparison` as an extra card alongside
the DataForSEO-backed Google AI Mode/AI Overview card. See
services/ai_overview_provider.py for that other provider; this module
is deliberately independent of it (its own gates, its own mode) and is
combined with it only in main.py.

**Not a re-creation of the ChatGPT app's own knowledge/behavior.** This
asks an OpenAI API model one non-browsing text-generation question
about the brand — see services/chatgpt_client.py's system prompt. No
web search, no references/citations.

This exists specifically to prevent an accidental real (billable)
OpenAI API call during development or testing. Two independent gates
have to agree before anything other than "no ChatGPT card" can happen —
mirrors services/ai_overview_provider.py's own two-gate design for
DataForSEO:

1. `CHATGPT_PROVIDER_MODE` (env var, default "off") — the
   operator-controlled default for the whole service.
2. `ALLOW_CHATGPT_MODE_OVERRIDE` (env var, default false) — whether a
   per-request `chatgptMode` field is honored at all. When this is
   false (the default), a caller can put any value it likes in the
   request body and it changes nothing; only the environment default
   applies.

Two modes:

- "off": no OpenAI call, no card. This is also always the effective
  mode when the AI Overview section itself is "mock" — see main.py:
  the mock aiOverviewComparison fixture already has its own fixed
  "ChatGPT" card, so adding a second, real one would be a confusing
  duplicate rather than an enrichment.
- "openai": calls services/chatgpt_client.py's connector, but only
  once every one of these also holds: `OPENAI_API_KEY` configured, and
  `CHATGPT_REQUEST_LIMIT_PER_ANALYZE` (services/chatgpt_settings.py) is
  exactly 1. Any single condition missing means no external call is
  made at all — a safe (credential-free) `reason` explains why instead.

Either way, any failure (missing key, network error, unexpected
response shape, request limit misconfigured) falls back to no card
with a `ChatGptEnvironment` of "unavailable". `/analyze` itself never
fails because of this — an OpenAI problem only ever affects whether
this one extra card is present.
"""

import logging
import os

from models import AIOverviewComparisonItem, ChatGptEnvironment, ChatGptProviderMode, ChatGptStatus
from services.chatgpt_client import fetch_chatgpt_observation
from services.chatgpt_settings import ChatGptSettings, get_chatgpt_credentials, get_chatgpt_settings

logger = logging.getLogger(__name__)

_VALID_MODES: tuple[ChatGptProviderMode, ...] = ("off", "openai")

CHATGPT_PLATFORM_LABEL = "ChatGPT (OpenAI API)"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_mode_from_env() -> ChatGptProviderMode:
    raw = os.environ.get("CHATGPT_PROVIDER_MODE", "off").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "CHATGPT_PROVIDER_MODE=%r is not one of %s; falling back to \"off\"",
            raw,
            _VALID_MODES,
        )
        return "off"
    return raw  # type: ignore[return-value]


def resolve_chatgpt_mode(request_override: ChatGptProviderMode | None) -> ChatGptProviderMode:
    """Decides which mode to run for this request — mirrors
    services/ai_overview_provider.py's resolve_ai_overview_mode().

    `request_override` (AnalyzeRequest.chatgptMode) is only honored when
    ALLOW_CHATGPT_MODE_OVERRIDE=true — otherwise the environment
    default (CHATGPT_PROVIDER_MODE) is used regardless of what the
    caller sent, so a request body alone can never turn on a billable
    OpenAI call in an environment that isn't configured to allow it.
    """
    default_mode = _default_mode_from_env()
    if request_override is None:
        return default_mode
    if not _env_flag("ALLOW_CHATGPT_MODE_OVERRIDE"):
        return default_mode
    return request_override


def _gate_rejection_reason(settings: ChatGptSettings, credentials_configured: bool) -> str:
    """Produces the most specific reason why an "openai"-mode call
    didn't happen. Checked in order from "most fundamental" to "most
    specific", mirroring services/ai_overview_provider.py's
    _live_gate_rejection_reason().
    """
    if not credentials_configured:
        return "OpenAI API key is not configured."
    # credentials_configured holds — the only other gate is the request limit.
    return "ChatGPT request limit must be 1."


def build_chatgpt_observation(
    brand_name: str, mode: ChatGptProviderMode
) -> tuple[AIOverviewComparisonItem | None, ChatGptStatus, str, ChatGptEnvironment]:
    """Returns (item, status, human-readable reason, environment) for
    the given mode. "off" never calls OpenAI. "openai" calls
    services/chatgpt_client.py's connector only once
    OPENAI_API_KEY is configured and
    CHATGPT_REQUEST_LIMIT_PER_ANALYZE is exactly 1 — any single gate
    missing means no external call is made at all (see module
    docstring). Never includes the API key itself in any reason string
    (it isn't even held anywhere except the one short-lived
    ChatGptCredentials object — see services/chatgpt_settings.py).

    `item` is None whenever no card should be added to
    aiOverviewComparison (mode "off", or an "openai" attempt that
    didn't succeed) — the caller (main.py) simply skips appending in
    that case.
    """
    if mode == "off":
        return None, "off", "ChatGPT observation is disabled.", "off"

    # mode == "openai"
    settings = get_chatgpt_settings()
    credentials = get_chatgpt_credentials()
    if credentials is None or settings.request_limit_per_analyze != 1:
        return (
            None,
            "unavailable",
            _gate_rejection_reason(settings, credentials is not None),
            "unavailable",
        )

    result = fetch_chatgpt_observation(
        credentials,
        brand_name,
        model=settings.model,
        max_output_tokens=settings.max_output_tokens,
    )
    if not result.success:
        return None, "unavailable", result.reason, "unavailable"

    item = AIOverviewComparisonItem(
        platform=CHATGPT_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=None,
        referenceSummary=None,
        ownDomainReferenced=None,
    )
    return item, "real", result.reason, "api"
