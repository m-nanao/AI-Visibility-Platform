"""OpenAI API HTTP client — asks a ChatGPT-equivalent model (via
OpenAI's Responses API) one question about a brand, as a lightweight
"how does an AI model talk about this brand" observation to sit
alongside the DataForSEO-backed Google AI Mode/AI Overview observation
in `aiOverviewComparison`.

**This is not a re-creation of what the ChatGPT app itself "knows" or
does.** It is a single, non-browsing text-generation request to an
OpenAI API model — see `services/ai_observation_prompts.py`'s
`SYSTEM_PROMPT` (shared with services/claude_client.py/
services/gemini_client.py as of Task 6-C Review Prep 1, so all three
ask the exact same question), which explicitly instructs the model
not to browse the web. No references/citations are requested or
parsed; this module never touches OpenAI's web-search tool.

**This module never decides *whether* to call OpenAI — only *how*.**
All gating (default mode, per-request override, credentials, request
limit) lives in services/chatgpt_provider.py's `build_chatgpt_observation()`,
which only ever calls `fetch_chatgpt_observation()` after confirming
every gate holds. This mirrors services/dataforseo_client.py's split
of responsibilities (see that module's docstring) for the same
reason: a single, thoroughly-tested gate in one place is safer than
duplicating gate logic across modules that could drift out of sync.

Uses the existing `httpx` dependency directly against OpenAI's REST
API (`POST https://api.openai.com/v1/responses`) rather than the
`openai` SDK, since that package isn't already a project dependency and
this feature doesn't justify adding one.

This client never raises out of `fetch_chatgpt_observation()` — network
errors, timeouts, non-2xx responses, and unexpected response shapes are
all caught and converted into a `ChatGptObservationResult` with
`success=False` and a safe (credential-free) `reason`, so an OpenAI
outage or response-shape quirk can never take down `/analyze`.

**Incomplete-response detection (Task 6-D-3B, added after a production
report of a ChatGPT answer visibly cut off mid-sentence at the same
point on repeated runs).** The Responses API's `max_output_tokens`
caps *reasoning tokens plus visible output tokens combined* for a
reasoning model like gpt-5-mini — see
https://developers.openai.com/api/docs/guides/reasoning — so a call
can run out of budget before finishing its visible answer even when
HTTP 200 and some readable text come back. When that happens, OpenAI's
own response carries `"status": "incomplete"` and
`"incomplete_details": {"reason": "max_output_tokens"}` (or another
reason). This module reads that signal directly (see
`_extract_completion_state()`) rather than only inferring truncation
heuristically, and surfaces it via the same `finishReason`/
`isTruncated`/`note` fields services/gemini_client.py already defined
for its own truncation signal — *never* as a hard failure: a truncated
answer still has `success=True` (there is real, if incomplete, text to
show), exactly mirroring Gemini's own "soft signal, not an error"
philosophy. `classify_recognition_level()` itself is unchanged — a
truncated answer missing its trailing recognition-level label line
still safely falls back to `"indeterminate"` via that function's own
existing logic, never guessed at here.
"""

import logging
from dataclasses import dataclass

import httpx

from models import RecognitionLevel
from services.ai_observation_prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_prompt,
    classify_recognition_level,
    strip_recognition_label_line,
)
from services.chatgpt_settings import ChatGptCredentials

logger = logging.getLogger(__name__)

RESPONSES_API_URL = "https://api.openai.com/v1/responses"

# Generous enough for a single text-generation call at up to
# MAX_MAX_OUTPUT_TOKENS (see chatgpt_settings.py), short enough that an
# OpenAI-side hang can't stall /analyze for long.
REQUEST_TIMEOUT_SECONDS = 20.0

_SUMMARY_MAX_CHARS = 200
# fullSummary is a detail view, not an excerpt — allowed much more room
# than _SUMMARY_MAX_CHARS, matching services/dataforseo_client.py's
# fullSummary sizing (see that module's _FULL_SUMMARY_MAX_CHARS).
_FULL_SUMMARY_MAX_CHARS = 2500

# Task 6-D-3B: shown alongside a card whose answer may have been cut
# short — mirrors services/gemini_client.py's own TRUNCATION_NOTE
# wording/intent.
TRUNCATION_NOTE = (
    "OpenAI APIの出力が途中で終了した可能性があります。"
    "必要に応じて再実行するか、出力上限を増やして検証してください。"
)


@dataclass(frozen=True)
class ChatGptObservationResult:
    """Outcome of one OpenAI Responses API call, already reduced to
    what chatgpt_provider.py needs — never holds the raw JSON response
    or the API key. `reason` is always a complete, safe-to-surface
    sentence; `success` is True only when readable text was actually
    extracted from the response.

    `finish_reason`/`is_truncated`/`note` (Task 6-D-3B) mirror
    services/gemini_client.py's own fields of the same name/intent —
    see this module's docstring. All three are only ever set on a
    successful (`success=True`) result; `is_truncated=True` is a soft
    signal, never a reason to treat this result as a failure.
    """

    success: bool
    reason: str
    mentioned: bool = False
    summary: str | None = None
    full_summary: str | None = None
    # Task 6-D-1 (feature/recognition-level-classification) — both
    # None unless `success` is True (nothing to classify/version
    # otherwise). See models.RecognitionLevel's docstring: a
    # self-report, never a verified fact.
    recognition_level: RecognitionLevel | None = None
    prompt_version: str | None = None
    # Task 6-D-3B (feature/chatgpt-truncation-detection) — see module
    # docstring's "Incomplete-response detection" section.
    finish_reason: str | None = None
    is_truncated: bool = False
    note: str | None = None


# Model name prefixes that reject a "temperature" field on OpenAI's
# Responses API (observed: gpt-5-mini + temperature=0.2 returns HTTP
# 400; gpt-4.1-mini and gpt-4o-mini accept it). Kept as an explicit,
# extensible tuple rather than a single string check in case a future
# model family has the same restriction.
_NO_TEMPERATURE_MODEL_PREFIXES: tuple[str, ...] = ("gpt-5",)


def should_send_temperature(model: str) -> bool:
    """Whether `temperature` is safe to include in the OpenAI Responses
    API request body for `model`. False for gpt-5* models (see
    _NO_TEMPERATURE_MODEL_PREFIXES above) — CHATGPT_TEMPERATURE is
    still read from settings either way, it's simply omitted from the
    request body for these models so the call doesn't fail with HTTP
    400. Case-insensitive so "GPT-5-MINI" is treated the same as
    "gpt-5-mini".
    """
    normalized = model.strip().lower()
    return not normalized.startswith(_NO_TEMPERATURE_MODEL_PREFIXES)


# Model name prefixes that are OpenAI *reasoning* models, for which
# `reasoning.effort` is a meaningful, accepted Responses API field —
# see https://developers.openai.com/api/docs/guides/reasoning (accepted
# values observed/documented: "minimal"/"low"/"medium"/"high",
# model-dependent). Deliberately the same prefix set as
# _NO_TEMPERATURE_MODEL_PREFIXES today (gpt-5* models are both
# reasoning models and temperature-rejecting), kept as its own tuple
# since the two restrictions are independent and could diverge for a
# future model family.
_REASONING_MODEL_PREFIXES: tuple[str, ...] = ("gpt-5",)

# Task 6-D-3B: lowers (from whatever the model's own unspecified
# default is) how many of max_output_tokens a reasoning model spends on
# invisible reasoning before producing visible output — see module
# docstring's "Incomplete-response detection" section for why that
# matters here. Deliberately "low", not "minimal": this observation
# asks the model to identify a specific, possibly obscure company by
# name, which benefits from at least some reasoning; "minimal" is also
# documented as incompatible with the web_search tool for gpt-5 models
# elsewhere in this codebase (services/chatgpt_websearch_client.py),
# though that restriction doesn't apply here, since this module never
# offers that tool.
DEFAULT_REASONING_EFFORT = "low"


def should_send_reasoning_effort(model: str) -> bool:
    """Whether `reasoning.effort` is meaningful to include for `model`
    — true for gpt-5* models (see _REASONING_MODEL_PREFIXES above).
    Omitted entirely for non-reasoning models, which don't accept a
    `reasoning` field the same way (and have no corresponding
    truncation-via-reasoning-tokens risk to mitigate). Case-insensitive,
    mirrors should_send_temperature()'s own style.
    """
    normalized = model.strip().lower()
    return normalized.startswith(_REASONING_MODEL_PREFIXES)


def _build_request_body(
    brand_name: str, model: str, max_output_tokens: int, temperature: float
) -> dict:
    user_prompt = build_user_prompt(brand_name)
    body: dict = {
        "model": model,
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": max_output_tokens,
        # Never persist this one-off observation request on OpenAI's
        # side — this project doesn't do its own DB storage either
        # (see docs/07_decisions.md).
        "store": False,
    }

    # Low by design — see chatgpt_settings.py's DEFAULT_TEMPERATURE — so
    # the same brand name produces a similarly-shaped answer across
    # /analyze calls, for demo/verification stability. Omitted entirely
    # for gpt-5* models, which reject this field with HTTP 400 (see
    # should_send_temperature above) — logged, not surfaced in `reason`.
    if should_send_temperature(model):
        body["temperature"] = temperature
    else:
        logger.info("temperature was omitted for gpt-5 model compatibility (model=%s)", model)

    # Task 6-D-3B — see DEFAULT_REASONING_EFFORT's own comment above.
    if should_send_reasoning_effort(model):
        body["reasoning"] = {"effort": DEFAULT_REASONING_EFFORT}

    return body


def _extract_output_text(payload: object) -> str | None:
    """Best-effort extraction of the model's answer text from OpenAI's
    Responses API envelope. Prefers the top-level `output_text`
    convenience field when present; otherwise walks `output[].content[]`
    looking for `text` fields and joins whatever is found. Returns None
    if neither shape yields any readable text.
    """
    if not isinstance(payload, dict):
        return None

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = payload.get("output")
    if not isinstance(output, list):
        return None

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())

    if not parts:
        return None
    return "\n\n".join(parts)


def _extract_completion_state(payload: object) -> tuple[str | None, str | None]:
    """Returns (status, incomplete_reason) from a Responses API
    envelope — Task 6-D-3B. `status` is OpenAI's own top-level field
    (e.g. "completed", "incomplete", "failed"); `incomplete_reason` is
    `incomplete_details.reason` (e.g. "max_output_tokens") when present.
    Both None when `payload` isn't shaped as expected, or when the
    response is a normal "completed" one with no `incomplete_details`
    at all — this function never guesses a reason that wasn't actually
    returned.

    This is the authoritative truncation signal this module relies on
    (unlike services/gemini_client.py, this module does not also add a
    heuristic markdown/short-text fallback — a community report notes
    OpenAI has, at least once, returned `status: "completed"` with
    `incomplete_details: null` for an answer that still looked cut off,
    so this signal is not claimed to catch every possible truncation,
    only the ones OpenAI itself reports).
    """
    if not isinstance(payload, dict):
        return None, None

    status = payload.get("status")
    status = status if isinstance(status, str) and status.strip() else None

    incomplete_reason = None
    incomplete_details = payload.get("incomplete_details")
    if isinstance(incomplete_details, dict):
        raw_reason = incomplete_details.get("reason")
        if isinstance(raw_reason, str) and raw_reason.strip():
            incomplete_reason = raw_reason.strip()

    return status, incomplete_reason


def _summarize(text: str, brand_name: str) -> tuple[bool, str, str]:
    """Reduces the model's raw answer text to (mentioned, summary,
    full_summary). `summary` is a short excerpt (<= _SUMMARY_MAX_CHARS);
    `full_summary` is the fuller text (<= _FULL_SUMMARY_MAX_CHARS).
    `summary`/`full_summary` have the trailing recognition-label line
    (Task 6-D-1) stripped out via
    services/ai_observation_prompts.py's strip_recognition_label_line()
    — `mentioned` is computed from the original, unstripped `text`.
    """
    mentioned = brand_name.lower() in text.lower()
    text = strip_recognition_label_line(text)

    cleaned = " ".join(text.split())
    if len(cleaned) > _SUMMARY_MAX_CHARS:
        summary = cleaned[:_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        summary = cleaned

    if len(text) > _FULL_SUMMARY_MAX_CHARS:
        full_summary = text[:_FULL_SUMMARY_MAX_CHARS].rstrip() + "…"
    else:
        full_summary = text

    return mentioned, summary, full_summary


def fetch_chatgpt_observation(
    credentials: ChatGptCredentials,
    brand_name: str,
    *,
    model: str,
    max_output_tokens: int,
    temperature: float,
) -> ChatGptObservationResult:
    """Asks the given OpenAI model one non-browsing question about
    `brand_name` via the Responses API. Issues exactly one HTTP request
    (multi-question/follow-up is out of scope, so
    `CHATGPT_REQUEST_LIMIT_PER_ANALYZE` isn't consulted here).

    This function itself does not decide whether calling OpenAI is
    *allowed* — see the module docstring: that gating lives entirely in
    services/chatgpt_provider.py.
    """
    body = _build_request_body(brand_name, model, max_output_tokens, temperature)

    try:
        response = httpx.post(
            RESPONSES_API_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {credentials.api_key}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        logger.warning("OpenAI API request failed (network/timeout error)")
        return ChatGptObservationResult(
            success=False,
            reason="OpenAI API request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("OpenAI API returned HTTP %d", response.status_code)
        return ChatGptObservationResult(
            success=False,
            reason=f"OpenAI API request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("OpenAI API returned a non-JSON response")
        return ChatGptObservationResult(
            success=False,
            reason="OpenAI API request failed: response was not valid JSON.",
        )

    status, incomplete_reason = _extract_completion_state(payload)
    text = _extract_output_text(payload)
    if text is None:
        reason = "OpenAI API returned no readable text."
        if status == "incomplete":
            # Task 6-D-3B item 1: distinguish "nothing came back at
            # all" (e.g. a response-shape surprise) from "the response
            # was explicitly incomplete before any readable text was
            # produced" (e.g. all of max_output_tokens spent on
            # invisible reasoning — see module docstring).
            reason = (
                f"{reason} (OpenAI response was incomplete"
                + (f", reason={incomplete_reason}" if incomplete_reason else "")
                + ")"
            )
        return ChatGptObservationResult(
            success=False,
            reason=reason,
        )

    is_truncated = status == "incomplete"
    mentioned, summary, full_summary = _summarize(text, brand_name)
    return ChatGptObservationResult(
        success=True,
        reason="ChatGPT OpenAI API request succeeded.",
        mentioned=mentioned,
        summary=summary,
        full_summary=full_summary,
        # Classified from the raw, untruncated `text` (not `summary`/
        # `full_summary`, which may be cut short) so the self-report
        # label line is never lost to truncation. Never re-derived or
        # second-guessed based on `is_truncated` below — a truncated
        # answer missing its label line still safely falls back to
        # "indeterminate" via classify_recognition_level()'s own
        # existing logic (Task 6-D-3B explicitly keeps this unchanged).
        recognition_level=classify_recognition_level(text),
        prompt_version=PROMPT_VERSION,
        finish_reason=incomplete_reason if is_truncated else None,
        is_truncated=is_truncated,
        note=TRUNCATION_NOTE if is_truncated else None,
    )
