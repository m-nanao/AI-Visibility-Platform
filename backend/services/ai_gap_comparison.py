"""AI-powered (not rule-based) comparison of the saved Web excerpt and
AI observation summaries — POST /analysis-runs/{id}/web-ai-gap/
ai-comparison (main.py). Design: docs/39_ai_gap_comparison_design.md.

**Manual, on-demand only.** Unlike the existing rule-based
`webAiGap` (services/web_ai_gap.py, computed during every `/analyze`
request), this module is never called from `/analyze` — only from the
history detail screen's "AIで差分を生成" button, via
backend/main.py's generate_web_ai_gap_ai_comparison() endpoint. This
keeps the existing `/analyze` timeout budget untouched (see
docs/39_ai_gap_comparison_design.md "6. 実行タイミング比較"'s 案B).

**No new data gathering of any kind.** The only inputs are the
already-saved `result_json["webAiGap"]`'s `webContext.summary` and
`aiContexts[].summary` — both already-truncated excerpts computed
earlier by services/web_ai_gap.py from data that request's `/analyze`
already had. This module never re-fetches a URL, never re-calls
Common Crawl/DataForSEO, and never re-calls ChatGPT/Claude/Gemini
observation providers — the **one and only** external call here is a
single Anthropic Messages API request asking Claude to compare the two
already-collected excerpts semantically.

**Provider**: fixed to Claude (Anthropic API) for this first
implementation — see docs/39_ai_gap_comparison_design.md "7. provider
方針". Reuses services/claude_settings.py's existing
CLAUDE_API_KEY/CLAUDE_MODEL/CLAUDE_MAX_OUTPUT_TOKENS configuration (no
new environment variable), but is otherwise entirely independent of
services/claude_provider.py's CLAUDE_PROVIDER_MODE/
ALLOW_CLAUDE_MODE_OVERRIDE gates — those gate the unrelated "Claude as
an AI-observation card" feature, not this one. The only gate here is
"is CLAUDE_API_KEY configured" (see generate_ai_gap_comparison()).

Never raises: a missing/unconfigured key, a missing/insufficient
webAiGap, a network error, a non-2xx response, or an unparseable
output are all caught and turned into an AiGapComparisonOutcome with
success=False and a short, safe-to-display `reason` (never the API key
itself) — mirrors services/gemini_rerun.py's GeminiRerunOutcome
pattern. The caller (main.py) must not write anything to the database
when success is False, leaving both the existing `webAiGap` and any
previously generated `webAiGapAiComparison` untouched.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from models import WebAiGapAiComparison
from services.claude_settings import get_claude_credentials, get_claude_settings

logger = logging.getLogger(__name__)

MESSAGES_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Generous enough for a single structured-comparison call; short enough
# that an Anthropic-side hang can't stall the manual-generation request
# for long (this is a synchronous HTTP request initiated by a button
# click, not a background job).
REQUEST_TIMEOUT_SECONDS = 30.0

# Caps how many items each list field can hold — matches
# docs/39_ai_gap_comparison_design.md's "最大3〜5項目程度" instruction
# to the model, enforced here again defensively in case the model
# returns more.
MAX_ITEMS_PER_LIST = 5

CAUTION_TEXT = (
    "AIによる比較であり、AIの内部認識を直接示すものではありません。"
)

# Reasons shown to the caller when nothing was even attempted (no
# Anthropic call made) — kept distinct from a call that was attempted
# and failed (see generate_ai_gap_comparison()'s `unavailable` flag),
# so main.py can return 503 ("not available right now") instead of 502
# ("the call itself failed") for these cases.
_WEB_AI_GAP_NOT_READY_REASON = (
    "Web上の説明とAI回答のズレの簡易判定がまだ利用できないため、AI比較を生成できません。"
)
_INSUFFICIENT_INPUT_REASON = (
    "Web上の説明またはAI観測の抜粋が不足しているため、AI比較を生成できません。"
)
_CREDENTIALS_MISSING_REASON = "Anthropic API key is not configured."

_PLATFORM_LABELS: dict[str, str] = {
    "chatgpt": "ChatGPT",
    "claude": "Claude",
    "gemini": "Gemini",
    "ai_overview": "AI Overview / Google AI Mode",
}

SYSTEM_PROMPT = (
    "あなたはWebサイトの記載内容と、生成AIがそのブランドについて答えた内容を比較する"
    "アナリストです。入力として、Web上で確認できるブランドの説明(抜粋)と、"
    "複数の生成AIがそのブランドについて答えた内容(抜粋)が渡されます。\n\n"
    "あなたの仕事は、Web上の説明とAI回答の間にある意味的なズレ(語句が一致しなくても"
    "伝えている内容・強調点が違う場合を含む)を比較することです。\n\n"
    "厳守事項:\n"
    "- 出力は有効なJSONオブジェクトのみとし、JSON以外の文章・説明・コードフェンス"
    "(```等)を一切含めないこと。\n"
    "- AIの内部認識・学習内容を断定しないこと(「AIは必ず...と学習している」"
    "「AIの内部では...と認識している」のような表現は禁止)。\n"
    "- 「必ず改善する」「必ず変わる」のような保証表現を使わないこと。\n"
    "- あくまで「Web上の説明」と「AIの回答(単発観測)」という2つのテキストの比較で"
    "あることを前提とした、控えめで仮定的な表現にすること。\n"
    "- 各リスト項目は最大5件程度までとし、簡潔な日本語の文にすること。\n\n"
    "出力するJSONのキー:\n"
    '- "matchedPoints": Web上の説明とAI回答の両方で一致している点のリスト\n'
    '- "webStrongAiWeak": Web上では強く出ているがAI回答では弱い、または出ていない点のリスト\n'
    '- "aiStrongWebWeak": AI回答では強く出ているがWeb上では弱い、または出ていない点のリスト\n'
    '- "gapSummary": 上記を踏まえた1〜2文のズレの要約(文字列)\n'
    '- "recommendations": 改善ヒントのリスト(最大5件程度)\n\n'
    "各リストが空になる場合は空配列 [] を返すこと。"
)


@dataclass(frozen=True)
class AiGapComparisonOutcome:
    """Outcome of one attempt to generate an AI-based Web/AI gap
    comparison. `success=False` means nothing should be persisted —
    `comparison` is None in that case. `unavailable=True` distinguishes
    "nothing was even attempted" (missing/insufficient input, or
    CLAUDE_API_KEY not configured) from "an Anthropic call was made and
    failed" (`unavailable=False`) — main.py maps the former to 503 and
    the latter to 502, mirroring how the rest of this history API
    already distinguishes "not configured" (503) from "the external
    call itself failed" (502, see POST /analysis-runs/{id}/rerun/gemini).
    """

    success: bool
    reason: str
    comparison: WebAiGapAiComparison | None = None
    unavailable: bool = False


def _strip_code_fence(text: str) -> str:
    """Removes a leading/trailing ```json ... ``` or ``` ... ``` fence
    if present — defensive only; the system prompt explicitly forbids
    this, but models don't always comply."""
    stripped = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][
        :MAX_ITEMS_PER_LIST
    ]


def _parse_comparison(text: str) -> WebAiGapAiComparison | None:
    """Parses Claude's raw text output into a WebAiGapAiComparison, or
    None if the text isn't valid JSON / isn't a JSON object. Every
    field is coerced defensively (wrong type -> empty/None) rather than
    raising, since a malformed field in an otherwise-usable response
    shouldn't throw the whole comparison away. `caution` is always
    overwritten with the fixed CAUTION_TEXT regardless of what the
    model produced (see module docstring)."""
    try:
        parsed = json.loads(_strip_code_fence(text))
    except ValueError:
        return None

    if not isinstance(parsed, dict):
        return None

    gap_summary = parsed.get("gapSummary")
    if not isinstance(gap_summary, str) or not gap_summary.strip():
        gap_summary = None
    else:
        gap_summary = gap_summary.strip()

    return WebAiGapAiComparison(
        matchedPoints=_coerce_str_list(parsed.get("matchedPoints")),
        webStrongAiWeak=_coerce_str_list(parsed.get("webStrongAiWeak")),
        aiStrongWebWeak=_coerce_str_list(parsed.get("aiStrongWebWeak")),
        gapSummary=gap_summary,
        recommendations=_coerce_str_list(parsed.get("recommendations")),
        caution=CAUTION_TEXT,
    )


def _extract_output_text(payload: object) -> str | None:
    """Same extraction logic as services/claude_client.py's
    _extract_output_text() — duplicated locally (rather than imported)
    since that function is private to that module and this module's
    use case (structured JSON output, not a brand-observation summary)
    is different enough to warrant its own small, independent copy."""
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


def _build_user_prompt(
    brand_name: str,
    web_summary: str,
    web_source_url: str | None,
    ai_contexts: list[dict[str, Any]],
) -> str:
    lines = [f"ブランド名: {brand_name}", "", "【Web上の説明(抜粋)】", web_summary]
    if web_source_url:
        lines.append(f"(取得元URL: {web_source_url})")

    lines.append("")
    lines.append("【AIの回答(抜粋、観測ごと)】")
    for context in ai_contexts:
        platform_key = context.get("platform")
        summary = context.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            continue
        label = _PLATFORM_LABELS.get(platform_key, platform_key or "不明")
        lines.append(f"- {label}: {summary.strip()}")

    return "\n".join(lines)


def _build_request_body(brand_name: str, result_json: dict[str, Any], model: str, max_output_tokens: int):
    web_ai_gap = result_json.get("webAiGap") or {}
    web_context = web_ai_gap.get("webContext") or {}
    user_prompt = _build_user_prompt(
        brand_name,
        web_context.get("summary", ""),
        web_context.get("sourceUrl"),
        web_ai_gap.get("aiContexts") or [],
    )
    return {
        "model": model,
        "max_tokens": max_output_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
    }


def generate_ai_gap_comparison(
    *, brand_name: str, result_json: dict[str, Any]
) -> AiGapComparisonOutcome:
    """Generates one AI-based Web/AI gap comparison from the already-
    saved `result_json["webAiGap"]` — see module docstring for exactly
    what is (and isn't) called. Returns success=False without ever
    calling Anthropic when the existing rule-based webAiGap isn't
    usable as input (missing, `status != "real"`, or either side's
    excerpt is empty) or when CLAUDE_API_KEY isn't configured — in all
    of these cases `unavailable=True` (main.py returns 503). A call
    that is actually attempted and then fails (network error, non-2xx,
    invalid JSON, or an unparseable comparison) returns
    `unavailable=False` (main.py returns 502).
    """
    web_ai_gap = result_json.get("webAiGap")
    if not isinstance(web_ai_gap, dict) or web_ai_gap.get("status") != "real":
        return AiGapComparisonOutcome(
            success=False, reason=_WEB_AI_GAP_NOT_READY_REASON, unavailable=True
        )

    web_context = web_ai_gap.get("webContext") or {}
    web_summary = web_context.get("summary")
    ai_contexts = web_ai_gap.get("aiContexts") or []
    has_ai_summary = any(
        isinstance(context, dict) and isinstance(context.get("summary"), str) and context["summary"].strip()
        for context in ai_contexts
    )
    if not isinstance(web_summary, str) or not web_summary.strip() or not has_ai_summary:
        return AiGapComparisonOutcome(
            success=False, reason=_INSUFFICIENT_INPUT_REASON, unavailable=True
        )

    credentials = get_claude_credentials()
    if credentials is None:
        return AiGapComparisonOutcome(
            success=False, reason=_CREDENTIALS_MISSING_REASON, unavailable=True
        )

    settings = get_claude_settings()
    body = _build_request_body(brand_name, result_json, settings.model, settings.max_output_tokens)

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
        return AiGapComparisonOutcome(
            success=False,
            reason="Anthropic API request failed due to a network or timeout error.",
        )

    if response.status_code != 200:
        logger.warning("Anthropic API returned HTTP %d", response.status_code)
        return AiGapComparisonOutcome(
            success=False,
            reason=f"Anthropic API request failed with HTTP {response.status_code}.",
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning("Anthropic API returned a non-JSON response")
        return AiGapComparisonOutcome(
            success=False,
            reason="Anthropic API request failed: response was not valid JSON.",
        )

    text = _extract_output_text(payload)
    if text is None:
        return AiGapComparisonOutcome(
            success=False, reason="Anthropic API returned no readable text."
        )

    comparison = _parse_comparison(text)
    if comparison is None:
        logger.warning("Failed to parse AI gap comparison output as JSON")
        return AiGapComparisonOutcome(
            success=False, reason="AI比較の出力を解釈できませんでした。"
        )

    return AiGapComparisonOutcome(
        success=True, reason="AI comparison succeeded.", comparison=comparison
    )
