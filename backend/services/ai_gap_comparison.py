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

**JSON parsing is deliberately lenient (fix/ai-gap-comparison-json-parse,
fix/ai-gap-comparison-diagnostics).** In production, Claude's raw text
output didn't always come back as a pure JSON object — markdown code
fences, a leading sentence like「以下が比較結果です。」, or a trailing
sentence after the JSON were observed, all of which made the original
strict `json.loads()` call fail every time even though the Anthropic
call itself succeeded. See parse_ai_gap_comparison_json() below for
the extraction strategy (pure JSON -> fenced JSON -> brace-to-brace
extraction -> light syntax repair on each candidate) and
_coerce_str_list() for turning a single string into a one-item list
when the model returns a bare string instead of an array.

Even after that fix, production still failed every time — which
means the failure was happening *before* JSON parsing even got a
chance to run (e.g. Claude's response not containing a usable text
block at all, or an empty one) rather than in parsing itself. This
module now tracks exactly *which* stage failed via a short, safe
internal reason code (see the `_REASON_*` constants and
`AiGapComparisonOutcome.internal_reason`) — logged with only safe,
non-secret diagnostics (content-block type names, text length, block
counts; never the API key, any token, or the raw Claude output/Web
content itself) and exposed to the API caller as a `reason` field
alongside the existing user-facing `error` message, so an operator can
tell "no text block was present at all" apart from "found a text block
but it was blank" apart from "found text but it had no JSON-looking
substring" apart from "found something JSON-shaped but it didn't
parse" without ever seeing a secret or the raw output.

**Text fallback for REASON_NO_JSON_OBJECT_FOUND
(fix/ai-gap-comparison-text-fallback).** Production logs confirmed a
case where the Anthropic call succeeded, a text block was present and
non-empty (e.g. raw_length=947), and yet no `{`...`}`-shaped substring
existed anywhere in it — i.e. Claude answered in natural language
instead of attempting JSON at all. No amount of additional JSON
parsing leniency can recover a comparison from that, so for this
*specific* reason only (never REASON_JSON_DECODE_FAILED, which still
means a genuine, reportable failure), this module now accepts the raw
text itself as a safe, best-effort fallback result rather than
discarding it — see _try_build_text_fallback() below. This still
reuses the single Anthropic response already received; it never makes
a second Claude call to "fix" the output into JSON. The resulting
WebAiGapAiComparison has `method="ai_comparison_text_fallback"` and
`textSummary` set instead of the structured list fields, so the
frontend can render it distinctly from a normal structured comparison.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
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
# docs/39_ai_gap_comparison_design.md's "最大5件程度" instruction to
# the model, enforced here again defensively in case the model returns
# more.
MAX_ITEMS_PER_LIST = 5

CAUTION_TEXT = (
    "AIによる比較であり、AIの内部認識を直接示すものではありません。"
)

# --- Text fallback (fix/ai-gap-comparison-text-fallback) ---
#
# Only used when parse_ai_gap_comparison_json() reports
# REASON_NO_JSON_OBJECT_FOUND (no `{`...`}`-shaped substring anywhere —
# see module docstring). REASON_JSON_DECODE_FAILED (something
# JSON-shaped was found but didn't parse) is never eligible — that
# still means a genuine parse failure worth reporting as such.
METHOD_TEXT_FALLBACK = "ai_comparison_text_fallback"

# Below this length, a "no JSON found" response is too short to be a
# useful comparison on its own (e.g. a one-line acknowledgement) — not
# worth presenting as a result, so it's still treated as a failure.
MIN_TEXT_FALLBACK_LENGTH = 80

# Above this length, the fallback text is truncated (with a trailing
# "…") before being persisted/displayed — keeps a pathologically long
# natural-language response bounded without needing a second Claude
# call to shorten it.
MAX_TEXT_FALLBACK_LENGTH = 4000

_TEXT_FALLBACK_GAP_SUMMARY = (
    "Claudeが構造化JSONではなく文章形式で比較結果を返しました。"
    "以下の文章形式の比較結果をご確認ください。"
)
_TEXT_FALLBACK_RECOMMENDATION = "上記の文章形式の比較結果を確認してください。"

# Simple substring check against the *start* of the response only
# (see _looks_like_refusal()) — catches an outright refusal/apology
# without trying to be a thorough classifier (the task explicitly
# calls for a simple check, not an elaborate one). Mixed case/width
# variants are intentionally limited to what's plausible from a model
# response, not an exhaustive list.
_REFUSAL_HEAD_PHRASES = (
    "i can't",
    "i cannot",
    "i'm unable",
    "i am unable",
    "i'm sorry",
    "i am sorry",
    "申し訳ありません",
    "申し訳ございません",
    "すみません",
    "ごめんなさい",
    "お答えできません",
    "回答できません",
    "対応できません",
    "できません",
)
_REFUSAL_HEAD_WINDOW = 80

# --- Safe, short internal reason codes (fix/ai-gap-comparison-diagnostics) -
#
# Never secrets, never the raw Claude output/Web content — just a
# stage name identifying *where* generation stopped. Logged alongside
# safe diagnostics (see _log_parse_diagnostics()) and exposed to the
# API caller as a `reason` field (backend/main.py) distinct from the
# existing user-facing `error` message, so an operator can distinguish
# failure stages without ever seeing a secret or the raw output.
REASON_WEB_AI_GAP_NOT_READY = "web_ai_gap_not_ready"
REASON_INSUFFICIENT_INPUT = "insufficient_input"
REASON_CREDENTIALS_MISSING = "credentials_missing"
REASON_NETWORK_ERROR = "network_error"
REASON_NON_200_STATUS = "non_200_status"
REASON_NON_JSON_RESPONSE = "non_json_response"
REASON_NO_TEXT_CONTENT = "no_text_content"
REASON_EMPTY_MODEL_OUTPUT = "empty_model_output"
REASON_NO_JSON_OBJECT_FOUND = "no_json_object_found"
REASON_JSON_DECODE_FAILED = "json_decode_failed"
REASON_VALIDATION_FAILED = "validation_failed"

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

# Shown for every failure stage *after* the Anthropic call itself
# succeeds (no readable text, no JSON object, decode failure,
# validation failure) — reworded from the original "AI比較の出力を解釈
# できませんでした。" to read like an actionable, temporary failure
# rather than a permanent incompatibility. The underlying stage is
# still distinguishable via `internal_reason`/the log line, which a
# caller/operator can inspect without this user-facing text needing to
# change.
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
    "厳守事項(最重要):\n"
    "- 出力はJSONオブジェクト1つのみにすること。他には何も出力しないこと。\n"
    "- 出力の最初の文字は必ず { 、最後の文字は必ず } にすること。\n"
    "- Markdown記法(コードフェンス```、見出し#、箇条書き-/*等)を一切使わないこと。\n"
    "- JSON以外の説明文・前置き・後置き・箇条書き本文を一切出力しないこと。"
    "「以下が比較結果です」のような文も不要です。\n"
    "- JSON以外の文章形式では絶対に返さないこと。"
    "どうしても判断が難しい場合でも、必ず上記のJSON形式に収めて回答すること。\n"
    "- 各キーの値は日本語の文字列、または日本語文字列の配列にすること。\n"
    "- \"recommendations\"は必ず要素数1件以上の配列にすること(空配列にしないこと)。\n"
    "- \"gapSummary\"は必ず文字列にすること(nullや省略は不可)。\n"
    "- 入力だけでは判断が難しい場合でも、空のJSONではなく、"
    "「入力が限られているため確定的な判断は難しいが...」のような、"
    "控えめで補助的な見立てとして内容のあるJSONを返すこと。\n"
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
    '- "gapSummary": 上記を踏まえた1〜2文のズレの要約(文字列、必須)\n'
    '- "recommendations": 改善ヒントのリスト(1件以上、最大5件程度、必須)\n\n'
    "matchedPoints/webStrongAiWeak/aiStrongWebWeakが空になる場合は空配列 [] を返すこと"
    "(ただしgapSummary/recommendationsは空にしないこと)。\n\n"
    "出力例(このJSON以外は一切出力しないこと。説明・コードフェンスは不要):\n"
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

    `reason` is always a short, user-safe-to-display sentence (never a
    secret or raw model output). `internal_reason`, when set, is one of
    the `REASON_*` constants above — a stable, safe machine-readable
    code identifying exactly which stage failed, for backend/main.py to
    optionally surface as a separate `reason` field in the API response
    body (distinct from `error`) and for operators to grep logs by.
    `internal_reason` is None only on success.
    """

    success: bool
    reason: str
    comparison: WebAiGapAiComparison | None = None
    unavailable: bool = False
    internal_reason: str | None = None


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

# Trailing comma immediately before a closing `}`/`]` — a common minor
# JSON syntax slip (e.g. `{"a": 1,}`) that json.loads() rejects outright
# but is unambiguous to repair.
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

# Fullwidth/typographic quote characters a model sometimes substitutes
# for ASCII `"`/`'` — invalid inside JSON string delimiters.
_QUOTE_TRANSLATION = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})

# Leading/trailing invisible characters (BOM, zero-width space) that
# can sneak in around an otherwise well-formed JSON object.
_INVISIBLE_CHARS = "﻿​"


def _strip_code_fence(text: str) -> str:
    """Removes a leading/trailing ```json ... ``` or ``` ... ``` fence
    if present — defensive only; the system prompt explicitly forbids
    this, but models don't always comply (observed in production, see
    module docstring)."""
    stripped = text.strip()
    match = _CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _extract_braces(text: str) -> str | None:
    """Extracts the substring from the first `{` to the last `}`
    (inclusive) — a last-resort fallback for output with a leading
    and/or trailing sentence around an otherwise well-formed JSON
    object (observed in production, e.g.「以下が比較結果です。」before
    the JSON, or a trailing disclaimer sentence after it). Returns None
    when no `{`/`}` pair is present at all."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _repair_json_candidate(text: str) -> str:
    """Applies a small set of unambiguous, non-speculative syntax
    repairs to a JSON-shaped candidate string that failed to parse as-
    is — never invents or guesses structure, only normalizes
    characters that are never valid in strict JSON regardless of
    intent: fullwidth quotes -> ASCII quotes, a trailing comma right
    before a closing `}`/`]`, and leading/trailing invisible
    characters (BOM/zero-width space). If the input still doesn't
    parse after this, parse_ai_gap_comparison_json() reports a genuine
    decode failure rather than attempting anything more aggressive."""
    repaired = text.strip(_INVISIBLE_CHARS + " \t\r\n")
    repaired = repaired.translate(_QUOTE_TRANSLATION)
    repaired = _TRAILING_COMMA_RE.sub(r"\1", repaired)
    return repaired


def parse_ai_gap_comparison_json(raw_text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Best-effort extraction of a JSON object from Claude's raw text
    output. Returns `(parsed_dict, None)` on success, or
    `(None, reason)` on failure where `reason` is one of:

    - REASON_NO_JSON_OBJECT_FOUND: no `{`...`}`-shaped substring exists
      anywhere in the text at all (e.g. Claude returned pure natural
      language with no JSON attempt) — nothing to even try repairing.
    - REASON_JSON_DECODE_FAILED: a `{`...`}`-shaped substring (or the
      text/fence-stripped text itself) exists, but neither it nor its
      lightly-repaired form (see _repair_json_candidate()) parses as
      valid JSON, or parses to something other than a JSON object
      (e.g. a bare array/string/number).

    Tries, in order, each of: the stripped text as-is (pure JSON), with
    a markdown code fence removed, brace-to-brace extraction from the
    fence-stripped text, and brace-to-brace extraction from the
    original text — and for each candidate, both the candidate itself
    and a lightly-repaired version of it (fullwidth quotes, trailing
    commas, invisible characters). Returns the parsed dict from the
    first candidate (repaired or not) that is valid JSON *and* a JSON
    object.

    Never logs or returns `raw_text` itself — only this function's own
    boolean outcome and reason code are observable to callers, so a
    caller that wants to log a failure must not pass the raw text
    through (see module docstring's secrets/raw-output policy, which
    extends to the raw model output here since it may echo back
    brand/Web content that shouldn't be logged verbatim).
    """
    fence_stripped = _strip_code_fence(raw_text)
    braces_from_fence_stripped = _extract_braces(fence_stripped)
    braces_from_raw = _extract_braces(raw_text)

    candidates = [raw_text.strip(), fence_stripped]
    if braces_from_fence_stripped is not None:
        candidates.append(braces_from_fence_stripped)
    if braces_from_raw is not None:
        candidates.append(braces_from_raw)

    has_json_shaped_candidate = (
        braces_from_fence_stripped is not None or braces_from_raw is not None
    )

    for candidate in candidates:
        if not candidate:
            continue
        for attempt in (candidate, _repair_json_candidate(candidate)):
            try:
                parsed = json.loads(attempt)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed, None
            # Decoded, but to something other than a JSON object (e.g.
            # a bare array/string) — still counts as "found something
            # JSON-shaped", just not a usable one.
            has_json_shaped_candidate = True

    if has_json_shaped_candidate:
        return None, REASON_JSON_DECODE_FAILED
    return None, REASON_NO_JSON_OBJECT_FOUND


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


def _looks_like_refusal(text: str) -> bool:
    """Simple, intentionally non-exhaustive check for an outright
    refusal/apology at the *start* of Claude's response (e.g. "申し訳
    ありませんが..." or "I can't help with that.") — only the first
    `_REFUSAL_HEAD_WINDOW` characters are checked, so a hedge sentence
    like "〜できませんが、以下のように見立てられます" later in a
    substantive response doesn't falsely disqualify it. Per the task's
    own guidance, this is deliberately simple rather than a thorough
    classifier."""
    head = text[:_REFUSAL_HEAD_WINDOW].lower()
    return any(phrase in head for phrase in _REFUSAL_HEAD_PHRASES)


def _build_text_fallback_comparison(text: str) -> WebAiGapAiComparison:
    """Builds a WebAiGapAiComparison from Claude's raw natural-language
    text when no JSON object could be found in it at all — see module
    docstring's "Text fallback" section. Truncates to
    MAX_TEXT_FALLBACK_LENGTH (with a trailing "…") rather than storing
    an unbounded amount of text."""
    truncated = text[:MAX_TEXT_FALLBACK_LENGTH]
    if len(text) > MAX_TEXT_FALLBACK_LENGTH:
        truncated = truncated.rstrip() + "…"
    return WebAiGapAiComparison(
        method=METHOD_TEXT_FALLBACK,
        matchedPoints=[],
        webStrongAiWeak=[],
        aiStrongWebWeak=[],
        gapSummary=_TEXT_FALLBACK_GAP_SUMMARY,
        recommendations=[_TEXT_FALLBACK_RECOMMENDATION],
        textSummary=truncated,
        caution=CAUTION_TEXT,
    )


def _try_build_text_fallback(text: str) -> WebAiGapAiComparison | None:
    """Returns a text-fallback WebAiGapAiComparison when `text` (already
    stripped by the caller) is eligible, or None when it isn't — too
    short (< MIN_TEXT_FALLBACK_LENGTH) or looks like an outright
    refusal/apology (see _looks_like_refusal()). Only called for
    REASON_NO_JSON_OBJECT_FOUND; a genuine decode failure
    (REASON_JSON_DECODE_FAILED) is never eligible for this fallback."""
    if len(text) < MIN_TEXT_FALLBACK_LENGTH:
        return None
    if _looks_like_refusal(text):
        return None
    return _build_text_fallback_comparison(text)


def _parse_comparison(text: str) -> tuple[WebAiGapAiComparison | None, str | None]:
    """Parses Claude's raw text output into a WebAiGapAiComparison.
    Returns `(comparison, None)` on success, or `(None, reason)` where
    `reason` is whatever parse_ai_gap_comparison_json() reported
    (REASON_NO_JSON_OBJECT_FOUND / REASON_JSON_DECODE_FAILED), or
    REASON_VALIDATION_FAILED if a JSON object was found but
    constructing the model from it still failed unexpectedly (should be
    unreachable in practice since every field is coerced defensively
    below, but guarded against rather than letting a stray
    pydantic.ValidationError escape this module).

    Every field is defaulted rather than raising when missing/malformed
    (gapSummary -> None, every list field -> `[]` via
    _coerce_str_list) — a comparison with some fields missing is still
    more useful than discarding it entirely. `caution` is always
    overwritten with the fixed CAUTION_TEXT regardless of what the
    model produced (see module docstring); `status`/`method` keep their
    WebAiGapAiComparison defaults ("real"/"ai_comparison") regardless
    of what's in `parsed`.

    When no JSON object is found at all (REASON_NO_JSON_OBJECT_FOUND),
    tries the text fallback (see _try_build_text_fallback()) before
    giving up — this still counts as success (`reason` is None) with
    `comparison.method == METHOD_TEXT_FALLBACK`, letting the caller
    distinguish a text-fallback success from a normal structured one
    purely by inspecting `comparison.method`.
    """
    parsed, reason = parse_ai_gap_comparison_json(text)
    if parsed is None:
        if reason == REASON_NO_JSON_OBJECT_FOUND:
            fallback = _try_build_text_fallback(text.strip())
            if fallback is not None:
                return fallback, None
        return None, reason

    gap_summary = parsed.get("gapSummary")
    if not isinstance(gap_summary, str) or not gap_summary.strip():
        gap_summary = None
    else:
        gap_summary = gap_summary.strip()

    try:
        comparison = WebAiGapAiComparison(
            matchedPoints=_coerce_str_list(parsed.get("matchedPoints")),
            webStrongAiWeak=_coerce_str_list(parsed.get("webStrongAiWeak")),
            aiStrongWebWeak=_coerce_str_list(parsed.get("aiStrongWebWeak")),
            gapSummary=gap_summary,
            recommendations=_coerce_str_list(parsed.get("recommendations")),
            caution=CAUTION_TEXT,
        )
    except Exception:
        logger.exception("Failed to construct WebAiGapAiComparison from a parsed JSON object")
        return None, REASON_VALIDATION_FAILED

    return comparison, None


@dataclass(frozen=True)
class _ContentExtraction:
    """Result of pulling readable text out of one Anthropic Messages
    API response payload — see _extract_output_text(). Carries only
    safe-to-log diagnostics (content-block type names, counts) never
    the content itself, so a caller can log this directly without any
    redaction step of its own."""

    text: str | None
    content_types: list[str] = field(default_factory=list)
    text_block_count: int = 0
    reason: str | None = None  # REASON_NO_TEXT_CONTENT / REASON_EMPTY_MODEL_OUTPUT, or None


def _extract_output_text(payload: object) -> _ContentExtraction:
    """Extracts readable text from Anthropic's Messages API response
    envelope (`content` is a list of blocks, each with a `type`; only
    `type == "text"` blocks carry a `text` field), while recording
    enough shape information to diagnose a failure safely:
    `content_types` (the `type` of every block, in order — e.g.
    `["text"]`, `["tool_use"]`, `[]`) and `text_block_count` (how many
    of those blocks were actually `type == "text"`, regardless of
    whether their text was blank).

    `reason` distinguishes two failure stages that were previously
    indistinguishable (fix/ai-gap-comparison-diagnostics): payload
    isn't a dict / `content` isn't a list / no block has
    `type == "text"` at all -> REASON_NO_TEXT_CONTENT; at least one
    text block exists but every one of them was blank/whitespace-only
    -> REASON_EMPTY_MODEL_OUTPUT. `text` is None whenever `reason` is
    set, and set (never blank) otherwise.
    """
    if not isinstance(payload, dict):
        return _ContentExtraction(text=None, reason=REASON_NO_TEXT_CONTENT)

    content = payload.get("content")
    if not isinstance(content, list):
        return _ContentExtraction(text=None, reason=REASON_NO_TEXT_CONTENT)

    content_types: list[str] = []
    parts: list[str] = []
    text_block_count = 0
    for block in content:
        if not isinstance(block, dict):
            content_types.append("<non-dict>")
            continue
        block_type = block.get("type")
        content_types.append(block_type if isinstance(block_type, str) else "<unknown>")
        if block_type != "text":
            continue
        text_block_count += 1
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    if text_block_count == 0:
        return _ContentExtraction(
            text=None, content_types=content_types, text_block_count=0, reason=REASON_NO_TEXT_CONTENT
        )

    combined = "\n\n".join(parts)
    if not combined.strip():
        return _ContentExtraction(
            text=None,
            content_types=content_types,
            text_block_count=text_block_count,
            reason=REASON_EMPTY_MODEL_OUTPUT,
        )

    return _ContentExtraction(
        text=combined, content_types=content_types, text_block_count=text_block_count, reason=None
    )


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
    *, brand_name: str, result_json: dict[str, Any], analysis_run_id: str | None = None
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

    `analysis_run_id` is optional and used only for log correlation
    (never returned to the caller, never logged alongside anything
    secret) — passing it lets an operator grep Render logs for exactly
    which saved run a given failure/diagnostic line belongs to.
    """
    web_ai_gap = result_json.get("webAiGap")
    if not isinstance(web_ai_gap, dict) or web_ai_gap.get("status") != "real":
        return AiGapComparisonOutcome(
            success=False,
            reason=_WEB_AI_GAP_NOT_READY_REASON,
            unavailable=True,
            internal_reason=REASON_WEB_AI_GAP_NOT_READY,
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
            success=False,
            reason=_INSUFFICIENT_INPUT_REASON,
            unavailable=True,
            internal_reason=REASON_INSUFFICIENT_INPUT,
        )

    credentials = get_claude_credentials()
    if credentials is None:
        return AiGapComparisonOutcome(
            success=False,
            reason=_CREDENTIALS_MISSING_REASON,
            unavailable=True,
            internal_reason=REASON_CREDENTIALS_MISSING,
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
        logger.warning(
            "AI gap comparison failed: reason=%s analysis_run_id=%s model=%s",
            REASON_NETWORK_ERROR,
            analysis_run_id,
            settings.model,
        )
        return AiGapComparisonOutcome(
            success=False,
            reason="Anthropic API request failed due to a network or timeout error.",
            internal_reason=REASON_NETWORK_ERROR,
        )

    if response.status_code != 200:
        logger.warning(
            "AI gap comparison failed: reason=%s analysis_run_id=%s model=%s http_status=%d",
            REASON_NON_200_STATUS,
            analysis_run_id,
            settings.model,
            response.status_code,
        )
        return AiGapComparisonOutcome(
            success=False,
            reason=f"Anthropic API request failed with HTTP {response.status_code}.",
            internal_reason=REASON_NON_200_STATUS,
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning(
            "AI gap comparison failed: reason=%s analysis_run_id=%s model=%s",
            REASON_NON_JSON_RESPONSE,
            analysis_run_id,
            settings.model,
        )
        return AiGapComparisonOutcome(
            success=False,
            reason="Anthropic API request failed: response was not valid JSON.",
            internal_reason=REASON_NON_JSON_RESPONSE,
        )

    extraction = _extract_output_text(payload)
    if extraction.text is None:
        # Safe diagnostics only: content-block type names and counts,
        # never the block content itself — see _ContentExtraction's
        # docstring and the module docstring's logging policy.
        logger.warning(
            "AI gap comparison failed: reason=%s analysis_run_id=%s model=%s "
            "content_types=%s text_block_count=%d",
            extraction.reason,
            analysis_run_id,
            settings.model,
            extraction.content_types,
            extraction.text_block_count,
        )
        return AiGapComparisonOutcome(
            success=False, reason=_PARSE_FAILED_REASON, internal_reason=extraction.reason
        )

    comparison, parse_reason = _parse_comparison(extraction.text)
    if comparison is None:
        # Never logs the text itself — only its length, which is safe
        # (never a secret, and not useful enough on its own to be
        # worth withholding) and lets an operator distinguish "short
        # response" from "long response that still didn't parse".
        logger.warning(
            "AI gap comparison failed: reason=%s analysis_run_id=%s model=%s "
            "raw_length=%d content_types=%s text_block_count=%d",
            parse_reason,
            analysis_run_id,
            settings.model,
            len(extraction.text),
            extraction.content_types,
            extraction.text_block_count,
        )
        return AiGapComparisonOutcome(
            success=False, reason=_PARSE_FAILED_REASON, internal_reason=parse_reason
        )

    if comparison.method == METHOD_TEXT_FALLBACK:
        # Not a failure — logged at info level (never a warning) since
        # this is an accepted, safe fallback outcome, not a problem.
        # Only the length is logged, never the text itself.
        logger.info(
            "AI gap comparison used text fallback: analysis_run_id=%s model=%s raw_length=%d",
            analysis_run_id,
            settings.model,
            len(extraction.text),
        )

    return AiGapComparisonOutcome(
        success=True, reason="AI comparison succeeded.", comparison=comparison
    )
