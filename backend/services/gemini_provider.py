"""Gemini observation provider — a single, optional Google Gemini API
call asked one question about the brand, whose result (if any) is
appended to `aiOverviewComparison` as an extra card alongside the
DataForSEO-backed Google AI Mode/AI Overview card, the ChatGPT card
(services/chatgpt_provider.py), and the Claude card
(services/claude_provider.py). All three observation providers are
independent of one another (their own gates, their own mode) and are
combined only in main.py.

**Not a re-creation of the Gemini app/service's own knowledge/behavior.**
This asks a Gemini API model one non-browsing text-generation question
about the brand — see services/gemini_client.py and the shared prompt
in services/ai_observation_prompts.py. No web search, no
references/citations.

This exists specifically to prevent an accidental real (billable)
Gemini API call during development or testing. Two independent gates
have to agree before anything other than "no Gemini card" can happen —
mirrors services/claude_provider.py's own two-gate design:

1. `GEMINI_PROVIDER_MODE` (env var, default "off") — the
   operator-controlled default for the whole service.
2. `ALLOW_GEMINI_MODE_OVERRIDE` (env var, default false) — whether a
   per-request `geminiMode` field is honored at all. When this is
   false (the default), a caller can put any value it likes in the
   request body and it changes nothing; only the environment default
   applies.

Two modes:

- "off": no Gemini call, no card.
- "google": calls services/gemini_client.py's connector, but only once
  every one of these also holds: `GEMINI_API_KEY` configured, and
  `GEMINI_REQUEST_LIMIT_PER_ANALYZE` (services/gemini_settings.py) is
  exactly 1. Any single condition missing means no external call is
  made at all — a safe (credential-free) `reason` explains why instead.

**Deliberately not gated by `aiOverviewMode == "mock"`**, unlike
ChatGPT's provider — see services/claude_provider.py's module
docstring for the full rationale (no "Gemini" card exists in the mock
fixture, so there is no duplicate-card risk to avoid). Gemini
observation mode is controlled solely by
GEMINI_PROVIDER_MODE/ALLOW_GEMINI_MODE_OVERRIDE/`geminiMode`, entirely
independent of `AIOverviewProviderInfo`/`ChatGptProviderInfo`/
`ClaudeProviderInfo` above.

Either way, any failure (missing key, network error, unexpected
response shape, request limit misconfigured) falls back to no card
with a `GeminiEnvironment` of "unavailable". `/analyze` itself never
fails because of this — a Gemini problem only ever affects whether this
one extra card is present.
"""

import logging
import os

from models import AIOverviewComparisonItem, GeminiEnvironment, GeminiProviderMode, GeminiStatus
from services.gemini_client import fetch_gemini_observation
from services.gemini_settings import GeminiSettings, get_gemini_credentials, get_gemini_settings

logger = logging.getLogger(__name__)

_VALID_MODES: tuple[GeminiProviderMode, ...] = ("off", "google")

GEMINI_PLATFORM_LABEL = "Gemini (Google API)"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_mode_from_env() -> GeminiProviderMode:
    raw = os.environ.get("GEMINI_PROVIDER_MODE", "off").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "GEMINI_PROVIDER_MODE=%r is not one of %s; falling back to \"off\"",
            raw,
            _VALID_MODES,
        )
        return "off"
    return raw  # type: ignore[return-value]


def resolve_gemini_mode(request_override: GeminiProviderMode | None) -> GeminiProviderMode:
    """Decides which mode to run for this request — mirrors
    services/claude_provider.py's resolve_claude_mode().

    `request_override` (AnalyzeRequest.geminiMode) is only honored when
    ALLOW_GEMINI_MODE_OVERRIDE=true — otherwise the environment default
    (GEMINI_PROVIDER_MODE) is used regardless of what the caller sent,
    so a request body alone can never turn on a billable Gemini call in
    an environment that isn't configured to allow it.
    """
    default_mode = _default_mode_from_env()
    if request_override is None:
        return default_mode
    if not _env_flag("ALLOW_GEMINI_MODE_OVERRIDE"):
        return default_mode
    return request_override


def _gate_rejection_reason(settings: GeminiSettings, credentials_configured: bool) -> str:
    """Produces the most specific reason why a "google"-mode call
    didn't happen. Checked in order from "most fundamental" to "most
    specific", mirroring services/claude_provider.py's
    _gate_rejection_reason().
    """
    if not credentials_configured:
        return "Gemini API key is not configured."
    # credentials_configured holds — the only other gate is the request limit.
    return "Gemini request limit must be 1."


def build_gemini_observation(
    brand_name: str, mode: GeminiProviderMode
) -> tuple[AIOverviewComparisonItem | None, GeminiStatus, str, GeminiEnvironment]:
    """Returns (item, status, human-readable reason, environment) for
    the given mode. "off" never calls Gemini. "google" calls
    services/gemini_client.py's connector only once GEMINI_API_KEY is
    configured and GEMINI_REQUEST_LIMIT_PER_ANALYZE is exactly 1 — any
    single gate missing means no external call is made at all (see
    module docstring). Never includes the API key itself in any reason
    string (it isn't even held anywhere except the one short-lived
    GeminiCredentials object — see services/gemini_settings.py).

    `item` is None whenever no card should be added to
    aiOverviewComparison (mode "off", or a "google" attempt that didn't
    succeed) — the caller (main.py) simply skips appending in that
    case.
    """
    if mode == "off":
        return None, "off", "Gemini observation is disabled.", "off"

    # mode == "google"
    settings = get_gemini_settings()
    credentials = get_gemini_credentials()
    if credentials is None or settings.request_limit_per_analyze != 1:
        return (
            None,
            "unavailable",
            _gate_rejection_reason(settings, credentials is not None),
            "unavailable",
        )

    result = fetch_gemini_observation(
        credentials,
        brand_name,
        model=settings.model,
        max_output_tokens=settings.max_output_tokens,
    )
    if not result.success:
        return None, "unavailable", result.reason, "unavailable"

    item = AIOverviewComparisonItem(
        platform=GEMINI_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=None,
        referenceSummary=None,
        ownDomainReferenced=None,
    )
    return item, "real", result.reason, "api"
