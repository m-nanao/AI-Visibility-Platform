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

**JSON parsing is deliberately lenient (fix/ai-gap-comparison-json-parse).**
In production, Claude's raw text output didn't always come back as a
pure JSON object — markdown code fences, a leading sentence like
「以下が比較結果です。」, or a trailing sentence after the JSON were
observed, all of which made the original strict `json.loads()` call
fail every time even though the Anthropic call itself succeeded. See
parse_ai_gap_comparison_json() below for the extraction strategy (pure
JSON -> fenced JSON -> brace-to-brace extraction) and
_coerce_str_list() for turning a single string into a one-item list
when the model returns a bare string instead of an array. Only a text
with no JSON object extractable at all still fails — every other field
is defaulted rather than causing the whole comparison to be discarded.
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

# Shown when parse_ai_gap_comparison_json() can't extract a JSON
# object at all even after stripping a code fence and trying
# brace-to-brace extraction — a genuine parse failure, distinct from
# the (now defaulted, not failed) case of individual missing fields.
# Reworded from the original "AI比較の出力を解釈できませんでした。" to
# read more like an actionable, temporary failure rather than a
# permanent incompatibility — the internal log line below still says
# "parse_failed" for operators grepping logs.
_PARSE_FAILED_REASON = (
    "AI比較の生成結果を読み取れませんでした。時間をおいて再度お試しください。"
)

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
    "- 出力はJSONオブジェクトそのものだけにすること。\n"
    "- JSONのみを返してください。Markdownコードフェンス(```等)、説明文、前置き、"
    "後置きは一切出力しないでください。「以下が比較結果です」のような文も不要です。\n"
    "- 出力の最初の文字は必ず { 、最後の文字は必ず } にすること。\n"
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
    "各リストが空になる場合は空配列 [] を返すこと。\n\n"
    "出力例(このJSON以外は一切出力しないこと):\n"
    "{\n"
    '  "matchedPoints": ["Web上・AI回答の両方でSEO支援会社として言及されている"],\n'
    '  "webStrongAiWeak": ["Web上ではAI検索対策が強く出ているが、AI回答では弱い"],\n'
    '  "aiStrongWebWeak": ["AI回答では一般的なブランディング会社として説明されやすい"],\n'
    '  "gapSummary": "Web上とAI回答で説明の強調点が異なる傾向があります。",\n'
    '  "recommendations": ["社名の近くに主要サービス名を一貫して記載する"]\n'
    "}"
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


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Removes a leading/trailing ```json ... ``` or ``` ... ``` fence
    if present — defensive only; the system prompt explicitly forbids
    this, but models don't always comply (observed in production, see
    module docstring: パターンB/C)."""
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _extract_braces(text: str) -> str | None:
    """Extracts the substring from the first `{` to the last `}`
    (inclusive) — a last-resort fallback for output with a leading
    and/or trailing sentence around an otherwise well-formed JSON
    object (observed in production, see module docstring: パターン
    D/E, e.g. 「以下が比較結果です。」before the JSON, or a trailing
    disclaimer sentence after it). Returns None when no `{`/`}` pair is
    present at all."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def parse_ai_gap_comparison_json(raw_text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from Claude's raw text
    output. Tries, in order: (1) the stripped text as-is (pure JSON,
    パターンA), (2) with a markdown code fence removed (パターンB/C),
    (3) brace-to-brace extraction from the fence-stripped text, and
    (4) brace-to-brace extraction from the original text — covering a
    leading/trailing sentence that sits outside a code fence, inside
    one, or with no fence at all (パターンD/E). Returns the parsed
    dict from the first candidate that is valid JSON *and* a JSON
    object (not a list/string/number), or None when none of the
    candidates parse — the only case the caller treats as a genuine
    failure.

    Never logs or returns `raw_text` itself — only this function's own
    boolean outcome is observable to callers, so a caller that wants to
    log a failure must not pass the raw text through (see module
    docstring's "token/API key/raw secretをlog/responseに出さない"
    policy, which extends to the raw model output here since it may
    echo back brand/Web content that shouldn't be logged verbatim).
    """
    fence_stripped = _strip_code_fence(raw_text)
    candidates = [raw_text.strip(), fence_stripped]

    braces_from_fence_stripped = _extract_braces(fence_stripped)
    if braces_from_fence_stripped is not None:
        candidates.append(braces_from_fence_stripped)

    braces_from_raw = _extract_braces(raw_text)
    if braces_from_raw is not None:
        candidates.append(braces_from_raw)

    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _coerce_str_list(value: Any) -> list[str]:
    """Normalizes a list-shaped field from the model's output into
    `list[str]`, trimmed to MAX_ITEMS_PER_LIST. A bare string is
    wrapped into a single-item list (observed in production: the model
    sometimes returns e.g. `"recommendations": "a single sentence"`
    instead of `["a single sentence"]`) rather than being discarded as
    the wrong type. Missing/null/any other type defaults to `[]`."""
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][
        :MAX_ITEMS_PER_LIST
    ]


def _parse_comparison(text: str) -> WebAiGapAiComparison | None:
    """Parses Claude's raw text output into a WebAiGapAiComparison, or
    None only when parse_ai_gap_comparison_json() can't extract a JSON
    object at all. Every field is defaulted rather than raising when
    missing/malformed (gapSummary -> None, every list field -> `[]`
    via _coerce_str_list) — a comparison with some fields missing is
    still more useful than discarding it entirely. `caution` is always
    overwritten with the fixed CAUTION_TEXT regardless of what the
    model produced (see module docstring); `status`/`method` keep their
    WebAiGapAiComparison defaults ("real"/"ai_comparison") regardless
    of what's in `parsed` — this endpoint only ever persists a
    successful comparison, so there is no other value either field
    could usefully hold here.
    """
    parsed = parse_ai_gap_comparison_json(text)
    if parsed is None:
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
        # Never logs `text` itself — only its length, which is safe
        # (never a secret, and not useful enough on its own to be
        # worth withholding) and lets an operator distinguish "empty
        # response" from "long response that still didn't parse".
        logger.warning(
            "Failed to parse AI gap comparison output as JSON (parse_failed, length=%d)",
            len(text),
        )
        return AiGapComparisonOutcome(success=False, reason=_PARSE_FAILED_REASON)

    return AiGapComparisonOutcome(
        success=True, reason="AI comparison succeeded.", comparison=comparison
    )
