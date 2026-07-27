"""OpenAI API HTTP client — asks a ChatGPT-equivalent model (via
OpenAI's Responses API) one question about a brand, as a lightweight
"how does an AI model talk about this brand" observation to sit
alongside the DataForSEO-backed Google AI Mode/AI Overview observation
in `aiOverviewComparison`.

**This is not a re-creation of what the ChatGPT app itself "knows" or
does.** It is a single, non-browsing text-generation request to an
OpenAI API model — see the system prompt in `_build_request_body()`,
which explicitly instructs the model not to browse the web. No
references/citations are requested or parsed; this module never
touches OpenAI's web-search tool.

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
"""

import logging
from dataclasses import dataclass

import httpx

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

_SYSTEM_PROMPT = (
    "あなたは、AIがブランドをどのように説明するかを観測するための評価用アシスタントです。"
    "Web検索は行わず、一般的な知識に基づいて日本語で回答してください。"
    "不確かな点は断定しすぎず、簡潔に述べてください。"
)


@dataclass(frozen=True)
class ChatGptObservationResult:
    """Outcome of one OpenAI Responses API call, already reduced to
    what chatgpt_provider.py needs — never holds the raw JSON response
    or the API key. `reason` is always a complete, safe-to-surface
    sentence; `success` is True only when readable text was actually
    extracted from the response.
    """

    success: bool
    reason: str
    mentioned: bool = False
    summary: str | None = None
    full_summary: str | None = None


_USER_PROMPT_TEMPLATE = (
    "次のブランドについて、一般的にどのような企業・サービスとして認識されるかを"
    "日本語で説明してください。\n"
    "\n"
    "ブランド名: {brand_name}\n"
    "\n"
    "回答は以下の観点を含め、全体で3〜5文程度にしてください。\n"
    "- 何を提供しているか\n"
    "- 主な利用者または用途\n"
    "- 代表的な特徴や強み\n"
    "\n"
    "注意:\n"
    "- 箇条書きではなく自然文で回答してください\n"
    "- 参照元やURLは挙げないでください\n"
    "- 分からない場合は「一般的には十分な情報を確認できません」と述べてください"
)


def _build_request_body(
    brand_name: str, model: str, max_output_tokens: int, temperature: float
) -> dict:
    user_prompt = _USER_PROMPT_TEMPLATE.format(brand_name=brand_name)
    return {
        "model": model,
        "input": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": max_output_tokens,
        # Low by design — see chatgpt_settings.py's DEFAULT_TEMPERATURE —
        # so the same brand name produces a similarly-shaped answer
        # across /analyze calls, for demo/verification stability.
        "temperature": temperature,
        # Never persist this one-off observation request on OpenAI's
        # side — this project doesn't do its own DB storage either
        # (see docs/07_decisions.md).
        "store": False,
    }


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


def _summarize(text: str, brand_name: str) -> tuple[bool, str, str]:
    """Reduces the model's raw answer text to (mentioned, summary,
    full_summary). `summary` is a short excerpt (<= _SUMMARY_MAX_CHARS);
    `full_summary` is the fuller text (<= _FULL_SUMMARY_MAX_CHARS).
    """
    mentioned = brand_name.lower() in text.lower()

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

    text = _extract_output_text(payload)
    if text is None:
        return ChatGptObservationResult(
            success=False,
            reason="OpenAI API returned no readable text.",
        )

    mentioned, summary, full_summary = _summarize(text, brand_name)
    return ChatGptObservationResult(
        success=True,
        reason="ChatGPT OpenAI API request succeeded.",
        mentioned=mentioned,
        summary=summary,
        full_summary=full_summary,
    )
