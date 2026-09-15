"""Anthropic API HTTP client — asks a Claude model (via Anthropic's
Messages API) one question about a brand, as a lightweight "how does an
AI model talk about this brand" observation to sit alongside the
existing ChatGPT observation (services/chatgpt_client.py) and Google AI
Mode/AI Overview observation in `aiOverviewComparison`.

**This is not a re-creation of what the Claude app/service itself
"knows" or does.** It is a single, non-browsing text-generation request
to an Anthropic API model — see the system prompt in
services/ai_observation_prompts.py, which explicitly instructs the
model not to browse the web. This module shares that prompt with
services/gemini_client.py (not with services/chatgpt_client.py, whose
existing prompt predates this feature and is already in production —
see ai_observation_prompts.py's module docstring) so Claude's and
Gemini's answers are directly comparable.

**This module never decides *whether* to call Anthropic — only *how*.**
All gating (default mode, per-request override, credentials, request
limit) lives in services/claude_provider.py's
`build_claude_observation()`, which only ever calls
`fetch_claude_observation()` after confirming every gate holds. This
mirrors services/chatgpt_client.py's split of responsibilities (see
that module's docstring) for the same reason.

Uses the existing `httpx` dependency directly against Anthropic's REST
API (`POST https://api.anthropic.com/v1/messages`) rather than the
`anthropic` SDK, since that package isn't already a project dependency
and this feature doesn't justify adding one.

This client never raises out of `fetch_claude_observation()` — network
errors, timeouts, non-2xx responses, and unexpected response shapes are
all caught and converted into a `ClaudeObservationResult` with
`success=False` and a safe (credential-free) `reason`, so an Anthropic
outage or response-shape quirk can never take down `/analyze`.
"""

import logging
from dataclasses import dataclass

import httpx

from services.ai_observation_prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    summarize_observation_text,
)
from services.claude_settings import ClaudeCredentials

logger = logging.getLogger(__name__)

MESSAGES_API_URL = "https://api.anthropic.com/v1/messages"

# Required by Anthropic's Messages API; pinned to a fixed dated value
# rather than sourced from env, since it selects a wire-format
# revision, not a model — a config surface that would only ever change
# alongside a code change to this client.
ANTHROPIC_API_VERSION = "2023-06-01"

# Generous enough for a single text-generation call at up to
# MAX_MAX_OUTPUT_TOKENS (see claude_settings.py), short enough that an
# Anthropic-side hang can't stall /analyze for long.
REQUEST_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class ClaudeObservationResult:
    """Outcome of one Anthropic Messages API call, already reduced to
    what claude_provider.py needs — never holds the raw JSON response
    or the API key. `reason` is always a complete, safe-to-surface
    sentence; `success` is True only when readable text was actually
    extracted from the response.
    """

    success: bool
    reason: str
    mentioned: bool = False
    summary: str | None = None
    full_summary: str | None = None


def _build_request_body(brand_name: str, model: str, max_output_tokens: int) -> dict:
    return {
        "model": model,
        "max_tokens": max_output_tokens,
        # Anthropic's Messages API takes the system prompt as a
        # top-level field, not as a "system"-role message inside
        # `messages` (unlike OpenAI's Responses API in
        # chatgpt_client.py).
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": build_user_prompt(brand_name)},
        ],
    }


def _extract_output_text(payload: object) -> str | None:
    """Best-effort extraction of the model's answer text from
    Anthropic's Messages API envelope: `content` is a list of blocks,
    each with a `type`; only `type == "text"` blocks carry a `text`
    field. Returns None if no readable text block is found.
    """
    if not isinstance(payload, dict):
        return None

    content = payload.get("content")
    if not isinstance(content, list):
        return None

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    if not parts:
        return None
    return "\n\n".join(parts)


def fetch_claude_observation(
    credentials: ClaudeCredentials,
    brand_name: str,
    *,
    model: str,
    max_output_tokens: int,
) -> ClaudeObservationResult:
    """Asks the given Claude model one non-browsing question about
    `brand_name` via the Messages API. Issues exactly one HTTP request
    (multi-question/follow-up is out of scope, so
    `CLAUDE_REQUEST_LIMIT_PER_ANALYZE` isn't consulted here).

    This function itself does not decide whether calling Anthropic is
    *allowed* — see the module docstring: that gating lives entirely in
    services/claude_provider.py.
    """
    body = _build_request_body(brand_name, model, max_output_tokens)

    try:
        response = httpx.post(
            MESSAGES_API_URL,
            json=body,
            headers={
                "x-api-key": credentials.api_key,
                "anthropic-version": ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("Anthropic API request failed (network/timeout error)")
        return ClaudeObservationResult(
            success=False,
            reason="Anthropic API request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("Anthropic API returned HTTP %d", response.status_code)
        return ClaudeObservationResult(
            success=False,
            reason=f"Anthropic API request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Anthropic API returned a non-JSON response")
        return ClaudeObservationResult(
            success=False,
            reason="Anthropic API request failed: response was not valid JSON.",
        )

    text = _extract_output_text(payload)
    if text is None:
        return ClaudeObservationResult(
            success=False,
            reason="Anthropic API returned no readable text.",
        )

    mentioned, summary, full_summary = summarize_observation_text(text, brand_name)
    return ClaudeObservationResult(
        success=True,
        reason="Claude Anthropic API request succeeded.",
        mentioned=mentioned,
        summary=summary,
        full_summary=full_summary,
    )
