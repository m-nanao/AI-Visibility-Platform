"""Claude observation provider — a single, optional Anthropic API call
asked one question about the brand, whose result (if any) is appended
to `aiOverviewComparison` as an extra card alongside the DataForSEO-
backed Google AI Mode/AI Overview card and the ChatGPT card
(services/chatgpt_provider.py). See services/gemini_provider.py for the
equivalent Gemini provider; all three are independent of one another
(their own gates, their own mode) and are combined only in main.py.

**Not a re-creation of the Claude app/service's own knowledge/behavior.**
This asks an Anthropic API model one non-browsing text-generation
question about the brand — see services/claude_client.py and the
shared prompt in services/ai_observation_prompts.py. No web search, no
references/citations.

This exists specifically to prevent an accidental real (billable)
Anthropic API call during development or testing. Two independent
gates have to agree before anything other than "no Claude card" can
happen — mirrors services/chatgpt_provider.py's own two-gate design:

1. `CLAUDE_PROVIDER_MODE` (env var, default "off") — the
   operator-controlled default for the whole service.
2. `ALLOW_CLAUDE_MODE_OVERRIDE` (env var, default false) — whether a
   per-request `claudeMode` field is honored at all. When this is
   false (the default), a caller can put any value it likes in the
   request body and it changes nothing; only the environment default
   applies.

Two modes:

- "off": no Anthropic call, no card.
- "anthropic": calls services/claude_client.py's connector, but only
  once every one of these also holds: `CLAUDE_API_KEY` configured, and
  `CLAUDE_REQUEST_LIMIT_PER_ANALYZE` (services/claude_settings.py) is
  exactly 1. Any single condition missing means no external call is
  made at all — a safe (credential-free) `reason` explains why instead.

**Deliberately not gated by `aiOverviewMode == "mock"`**, unlike
ChatGPT's provider. ChatGPT is skipped in mock mode only because
services/ai_overview_provider.py's mock fixture already has a fixed
"ChatGPT" card, so a second real one would be a confusing duplicate —
that mock fixture has no "Claude" card, so there is no such collision
here. Claude observation mode is controlled solely by
CLAUDE_PROVIDER_MODE/ALLOW_CLAUDE_MODE_OVERRIDE/`claudeMode`, entirely
independent of `AIOverviewProviderInfo`/`ChatGptProviderInfo` above.

Either way, any failure (missing key, network error, unexpected
response shape, request limit misconfigured) falls back to no card
with a `ClaudeEnvironment` of "unavailable". `/analyze` itself never
fails because of this — an Anthropic problem only ever affects whether
this one extra card is present.
"""

import logging
import os

from models import AIOverviewComparisonItem, ClaudeEnvironment, ClaudeProviderMode, ClaudeStatus
from services.claude_client import fetch_claude_observation
from services.claude_settings import ClaudeSettings, get_claude_credentials, get_claude_settings

logger = logging.getLogger(__name__)

_VALID_MODES: tuple[ClaudeProviderMode, ...] = ("off", "anthropic")

CLAUDE_PLATFORM_LABEL = "Claude (Anthropic API)"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _default_mode_from_env() -> ClaudeProviderMode:
    raw = os.environ.get("CLAUDE_PROVIDER_MODE", "off").strip().lower()
    if raw not in _VALID_MODES:
        logger.warning(
            "CLAUDE_PROVIDER_MODE=%r is not one of %s; falling back to \"off\"",
            raw,
            _VALID_MODES,
        )
        return "off"
    return raw  # type: ignore[return-value]


def resolve_claude_mode(request_override: ClaudeProviderMode | None) -> ClaudeProviderMode:
    """Decides which mode to run for this request — mirrors
    services/chatgpt_provider.py's resolve_chatgpt_mode().

    `request_override` (AnalyzeRequest.claudeMode) is only honored when
    ALLOW_CLAUDE_MODE_OVERRIDE=true — otherwise the environment default
    (CLAUDE_PROVIDER_MODE) is used regardless of what the caller sent,
    so a request body alone can never turn on a billable Anthropic call
    in an environment that isn't configured to allow it.
    """
    default_mode = _default_mode_from_env()
    if request_override is None:
        return default_mode
    if not _env_flag("ALLOW_CLAUDE_MODE_OVERRIDE"):
        return default_mode
    return request_override


def _gate_rejection_reason(settings: ClaudeSettings, credentials_configured: bool) -> str:
    """Produces the most specific reason why an "anthropic"-mode call
    didn't happen. Checked in order from "most fundamental" to "most
    specific", mirroring services/chatgpt_provider.py's
    _gate_rejection_reason().
    """
    if not credentials_configured:
        return "Anthropic API key is not configured."
    # credentials_configured holds — the only other gate is the request limit.
    return "Claude request limit must be 1."


def build_claude_observation(
    brand_name: str, mode: ClaudeProviderMode
) -> tuple[AIOverviewComparisonItem | None, ClaudeStatus, str, ClaudeEnvironment]:
    """Returns (item, status, human-readable reason, environment) for
    the given mode. "off" never calls Anthropic. "anthropic" calls
    services/claude_client.py's connector only once CLAUDE_API_KEY is
    configured and CLAUDE_REQUEST_LIMIT_PER_ANALYZE is exactly 1 — any
    single gate missing means no external call is made at all (see
    module docstring). Never includes the API key itself in any reason
    string (it isn't even held anywhere except the one short-lived
    ClaudeCredentials object — see services/claude_settings.py).

    `item` is None whenever no card should be added to
    aiOverviewComparison (mode "off", or an "anthropic" attempt that
    didn't succeed) — the caller (main.py) simply skips appending in
    that case.
    """
    if mode == "off":
        return None, "off", "Claude observation is disabled.", "off"

    # mode == "anthropic"
    settings = get_claude_settings()
    credentials = get_claude_credentials()
    if credentials is None or settings.request_limit_per_analyze != 1:
        return (
            None,
            "unavailable",
            _gate_rejection_reason(settings, credentials is not None),
            "unavailable",
        )

    result = fetch_claude_observation(
        credentials,
        brand_name,
        model=settings.model,
        max_output_tokens=settings.max_output_tokens,
    )
    if not result.success:
        return None, "unavailable", result.reason, "unavailable"

    item = AIOverviewComparisonItem(
        platform=CLAUDE_PLATFORM_LABEL,
        mentioned=result.mentioned,
        rank=None,
        summary=result.summary or "",
        fullSummary=result.full_summary,
        references=None,
        referenceSummary=None,
        ownDomainReferenced=None,
    )
    return item, "real", result.reason, "api"
