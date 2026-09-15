"""Google Gemini API HTTP client — asks a Gemini model (via Google's
`generateContent` API) one question about a brand, as a lightweight
"how does an AI model talk about this brand" observation to sit
alongside the existing ChatGPT observation (services/chatgpt_client.py),
the new Claude observation (services/claude_client.py), and the Google
AI Mode/AI Overview observation in `aiOverviewComparison`.

**This is not a re-creation of what the Gemini app/service itself
"knows" or does.** It is a single, non-browsing text-generation request
to a Gemini API model — see the shared system prompt in
services/ai_observation_prompts.py, which explicitly instructs the
model not to browse the web. This module shares that prompt with
services/claude_client.py (not with services/chatgpt_client.py — see
ai_observation_prompts.py's module docstring) so Claude's and Gemini's
answers are directly comparable.

**This module never decides *whether* to call Gemini — only *how*.**
All gating (default mode, per-request override, credentials, request
limit) lives in services/gemini_provider.py's
`build_gemini_observation()`, which only ever calls
`fetch_gemini_observation()` after confirming every gate holds. This
mirrors services/claude_client.py's split of responsibilities (see
that module's docstring) for the same reason.

Uses the existing `httpx` dependency directly against Google's REST API
(`POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`)
rather than the `google-generativeai`/`google-genai` SDK, since neither
package is already a project dependency and this feature doesn't
justify adding one. The API key is passed via the `x-goog-api-key`
header rather than the `?key=` query-string parameter Google's own
docs often show, specifically so it never ends up in a URL that could
be logged by an HTTP client, proxy, or access log.

This client never raises out of `fetch_gemini_observation()` — network
errors, timeouts, non-2xx responses, and unexpected response shapes are
all caught and converted into a `GeminiObservationResult` with
`success=False` and a safe (credential-free) `reason`, so a Gemini
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
from services.gemini_settings import GeminiCredentials

logger = logging.getLogger(__name__)

GENERATE_CONTENT_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

# Generous enough for a single text-generation call at up to
# MAX_MAX_OUTPUT_TOKENS (see gemini_settings.py), short enough that a
# Gemini-side hang can't stall /analyze for long.
REQUEST_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class GeminiObservationResult:
    """Outcome of one Gemini generateContent API call, already reduced
    to what gemini_provider.py needs — never holds the raw JSON
    response or the API key. `reason` is always a complete,
    safe-to-surface sentence; `success` is True only when readable text
    was actually extracted from the response.
    """

    success: bool
    reason: str
    mentioned: bool = False
    summary: str | None = None
    full_summary: str | None = None


def _build_request_body(brand_name: str, max_output_tokens: int) -> dict:
    return {
        "contents": [
            {"role": "user", "parts": [{"text": build_user_prompt(brand_name)}]},
        ],
        # Gemini's generateContent API takes the system prompt as a
        # dedicated top-level field, not as a "system"-role entry in
        # `contents`.
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"maxOutputTokens": max_output_tokens},
    }


def _extract_output_text(payload: object) -> str | None:
    """Best-effort extraction of the model's answer text from Gemini's
    generateContent envelope: `candidates[].content.parts[].text`.
    Deliberately defensive/type-checked at every level, since Gemini's
    response shape has varied across API versions/models (e.g. a
    candidate can be present with no `content` at all when the response
    was blocked by a safety filter). Returns None if no readable text
    is found anywhere.
    """
    if not isinstance(payload, dict):
        return None

    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return None

    parts_out: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                parts_out.append(text.strip())

    if not parts_out:
        return None
    return "\n\n".join(parts_out)


def fetch_gemini_observation(
    credentials: GeminiCredentials,
    brand_name: str,
    *,
    model: str,
    max_output_tokens: int,
) -> GeminiObservationResult:
    """Asks the given Gemini model one non-browsing question about
    `brand_name` via the generateContent API. Issues exactly one HTTP
    request (multi-question/follow-up is out of scope, so
    `GEMINI_REQUEST_LIMIT_PER_ANALYZE` isn't consulted here).

    This function itself does not decide whether calling Gemini is
    *allowed* — see the module docstring: that gating lives entirely in
    services/gemini_provider.py.
    """
    body = _build_request_body(brand_name, max_output_tokens)
    url = GENERATE_CONTENT_URL_TEMPLATE.format(model=model)

    try:
        response = httpx.post(
            url,
            json=body,
            headers={
                "x-goog-api-key": credentials.api_key,
                "content-type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("Gemini API request failed (network/timeout error)")
        return GeminiObservationResult(
            success=False,
            reason="Gemini API request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("Gemini API returned HTTP %d", response.status_code)
        return GeminiObservationResult(
            success=False,
            reason=f"Gemini API request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Gemini API returned a non-JSON response")
        return GeminiObservationResult(
            success=False,
            reason="Gemini API request failed: response was not valid JSON.",
        )

    text = _extract_output_text(payload)
    if text is None:
        return GeminiObservationResult(
            success=False,
            reason="Gemini API returned no readable text.",
        )

    mentioned, summary, full_summary = summarize_observation_text(text, brand_name)
    return GeminiObservationResult(
        success=True,
        reason="Gemini Google API request succeeded.",
        mentioned=mentioned,
        summary=summary,
        full_summary=full_summary,
    )
