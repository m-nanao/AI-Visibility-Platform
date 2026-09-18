"""Web上の情報環境とAI回答観測の差分を見せる補助セクション
("Web上の説明とAI回答のズレ", `AnalysisResult.webAiGap`).

Added per a依頼者 review request: they want to compare what a Common
Crawl/web-fetched Document says about the brand against what
ChatGPT/Claude/Gemini/AI Overview say about it, to get a sense of
where the two diverge and what to reinforce on the Web side.

Deliberately minimal / no new external calls:

- Reuses the Document[] already fetched for cooccurrenceRanking/
  context analysis — no new web fetch, no new Common Crawl call.
- Reuses the AIOverviewComparisonItem[] already produced by the
  existing ChatGPT/Claude/Gemini/AI Overview providers — no new call
  to any of them.
- Reuses services/cooccurrence.py's compute_cooccurrence_ranking() to
  rank keywords on the AI side with the exact same tokenizer/window
  logic already used for the Web-side cooccurrenceRanking, instead of
  inventing a second tokenizer.
- No semantic diff/embeddings/LLM summarization call — "the gap" is
  just "keywords that show up a lot on one side and barely on the
  other", a rough MVP heuristic (see _build_gap_summary below).

Never asserts what an AI has "learned" or "understood", and never
claims Common Crawl represents an AI's actual training data — every
user-facing string here only ever compares "Web上で確認できる文脈" and
"AI観測上の回答傾向" (see WEB_AI_GAP_NOTE / WEB_AI_GAP_UNAVAILABLE_NOTE).
"""

from models import (
    AIOverviewComparisonItem,
    CooccurrenceKeyword,
    Document,
    WebAiGapAiContext,
    WebAiGapPlatform,
    WebAiGapResult,
    WebAiGapWebContext,
)
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.claude_provider import CLAUDE_PLATFORM_LABEL
from services.cooccurrence import compute_cooccurrence_ranking
from services.gemini_provider import GEMINI_PLATFORM_LABEL

# Real AI Overview cards only ever use one of these two platform labels
# (see services/ai_overview_provider.py's _ENVIRONMENT_PLATFORM_LABELS)
# — the mock fixture's "Google AI Overview" placeholder never matches
# this prefix, so mock data is correctly excluded from the diff (per
# the task's "off/unavailable/mockは...使いすぎない" policy).
_AI_OVERVIEW_PLATFORM_PREFIX = "Google AI Mode ("

# Priority order for both picking which AIOverviewComparisonItem to use
# per platform key and for ordering WebAiGapResult.aiContexts.
_PLATFORM_ORDER: tuple[WebAiGapPlatform, ...] = ("chatgpt", "claude", "gemini", "ai_overview")

# Representative-excerpt length caps — short enough to keep the
# response small and the on-screen comparison readable side-by-side,
# consistent with services/context_analysis.py's MAX_EXCERPT_CHARS
# (160) and AIOverviewComparisonItem.summary's own ~200 char length.
MAX_WEB_CONTEXT_CHARS = 200
MAX_AI_CONTEXT_CHARS = 200

# How many top keywords each side's ranking considers when looking for
# "distinctive" (mostly one-sided) terms — kept small since this is a
# short summary sentence, not an exhaustive report.
GAP_KEYWORD_TOP_N = 5
MAX_GAP_KEYWORDS_IN_SUMMARY = 3

WEB_AI_GAP_NOTE = (
    "Web上の情報環境とAI回答の単発観測を比較した補助的な見立てです。"
    "AIの内部認識を直接示すものではありません。"
)

WEB_AI_GAP_UNAVAILABLE_NOTE = (
    "Web情報またはAI観測が不足しているため、差分比較は表示できません。"
)

# Always included as the first suggestion when status="real" — a
# generic, safe-to-show direction that doesn't depend on which
# keywords happened to differ (matches the task's own example wording
# verbatim). A second, more specific suggestion is appended only when
# the keyword comparison actually found something distinctive on the
# Web side (see _build_suggestions).
_GENERIC_SUGGESTION = (
    "社名の近くに、AI回答上でも出したい主要サービス名・対象顧客・強みを明示すると、"
    "Web上の説明とAI回答上の説明のズレを減らせる可能性があります。"
)


def _truncate(text: str, limit: int) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


def _classify_ai_platform(platform: str) -> WebAiGapPlatform | None:
    """Maps one AIOverviewComparisonItem.platform display string to a
    short WebAiGapPlatform key, or None when it isn't a real
    single-shot AI observation this module knows how to use (the mock
    fixture's "Google AI Overview"/"ChatGPT"/"Perplexity"/"Copilot"
    placeholders all return None here).
    """
    if platform == CHATGPT_PLATFORM_LABEL:
        return "chatgpt"
    if platform == CLAUDE_PLATFORM_LABEL:
        return "claude"
    if platform == GEMINI_PLATFORM_LABEL:
        return "gemini"
    if platform.startswith(_AI_OVERVIEW_PLATFORM_PREFIX):
        return "ai_overview"
    return None


def _pick_web_context_document(documents: list[Document]) -> Document | None:
    """Common Crawl由来文書があればそれを優先、なければ入力URL
    (web_fetch)由来文書 — see module docstring / the task's指定した
    優先順位. Returns None when neither is present (e.g. only
    development_sample/user_provided documents this request)."""
    for source_type in ("common_crawl", "web_fetch"):
        for document in documents:
            if document.sourceType == source_type and document.text.strip():
                return document
    return None


def _build_web_context(brand_name: str, documents: list[Document]) -> WebAiGapWebContext | None:
    document = _pick_web_context_document(documents)
    if document is None:
        return None

    text = document.text
    brand_index = text.lower().find(brand_name.lower())
    # A small lead-in before the brand mention (mirrors
    # services/cooccurrence.py's brand-window approach) so the excerpt
    # doesn't always start mid-sentence right at the brand name.
    window_start = max(0, brand_index - 20) if brand_index != -1 else 0
    excerpt = _truncate(text[window_start:], MAX_WEB_CONTEXT_CHARS)
    if not excerpt:
        return None

    return WebAiGapWebContext(
        summary=excerpt,
        sourceType=document.sourceType,  # "common_crawl" | "web_fetch" only, see _pick_web_context_document
        sourceUrl=document.sourceUrl,
    )


def _build_ai_contexts(items: list[AIOverviewComparisonItem]) -> list[WebAiGapAiContext]:
    """Picks at most one real observation per platform key (first
    match wins) and orders the result by _PLATFORM_ORDER — "利用できる
    ものだけ表示する" per the task."""
    by_platform: dict[WebAiGapPlatform, AIOverviewComparisonItem] = {}
    for item in items:
        key = _classify_ai_platform(item.platform)
        if key is None or key in by_platform or not item.summary.strip():
            continue
        by_platform[key] = item

    return [
        WebAiGapAiContext(
            platform=key,
            summary=_truncate(by_platform[key].summary, MAX_AI_CONTEXT_CHARS),
        )
        for key in _PLATFORM_ORDER
        if key in by_platform
    ]


def _distinctive_keywords(
    ranking: list[CooccurrenceKeyword], other_text: str, limit: int
) -> list[str]:
    """Keywords ranked highly in `ranking` that barely show up in
    `other_text` (a simple case-insensitive substring check) — used for
    both "Web側に多いがAI側に弱い語" and its mirror image. Not a claim
    that the term is entirely absent from the other side, only that it
    doesn't appear verbatim in the short excerpt being compared."""
    other_lower = other_text.lower()
    return [kw.keyword for kw in ranking if kw.keyword.lower() not in other_lower][:limit]


def _build_gap_summary(
    brand_name: str,
    web_ranking: list[CooccurrenceKeyword],
    web_text: str,
    ai_contexts: list[WebAiGapAiContext],
) -> str | None:
    if not ai_contexts:
        return None

    ai_text = " ".join(context.summary for context in ai_contexts)
    ai_ranking = compute_cooccurrence_ranking(brand_name, [ai_text], top_n=GAP_KEYWORD_TOP_N)

    web_only = _distinctive_keywords(web_ranking, ai_text, MAX_GAP_KEYWORDS_IN_SUMMARY)
    ai_only = _distinctive_keywords(ai_ranking, web_text, MAX_GAP_KEYWORDS_IN_SUMMARY)

    if web_only and ai_only:
        return (
            f"Web上では「{'・'.join(web_only)}」が目立つ一方、"
            f"AI回答では「{'・'.join(ai_only)}」が中心に説明されています。"
        )
    if ai_only:
        return (
            f"AI回答では「{'・'.join(ai_only)}」が中心に説明されており、"
            "Web上で確認できる文脈との重なりは限定的です。"
        )
    if web_only:
        return (
            f"Web上では「{'・'.join(web_only)}」が目立ちますが、"
            "AI観測上の回答ではあまり触れられていません。"
        )
    return "Web上の文脈とAI観測上の回答傾向に、大きな差は確認できませんでした。"


def _build_suggestions(
    web_ranking: list[CooccurrenceKeyword], ai_text: str
) -> list[str]:
    suggestions = [_GENERIC_SUGGESTION]
    web_only = _distinctive_keywords(web_ranking, ai_text, 2)
    if web_only:
        suggestions.append(
            f"「{'・'.join(web_only)}」など、Web上で強調されている内容を、"
            "社名の近くやFAQ・会社概要ページでも一貫して記載することを検討してください。"
        )
    return suggestions


def build_web_ai_gap(
    brand_name: str,
    documents: list[Document],
    cooccurrence_ranking: list[CooccurrenceKeyword],
    ai_overview_comparison: list[AIOverviewComparisonItem],
) -> WebAiGapResult:
    """Builds AnalysisResult.webAiGap from data already computed
    elsewhere in this /analyze request (see module docstring — no new
    external call of any kind). `status` is "unavailable" whenever
    either side has nothing usable (missing Web-side Document, or zero
    real AI observations this request) — see WEB_AI_GAP_UNAVAILABLE_NOTE.
    """
    web_context = _build_web_context(brand_name, documents)
    ai_contexts = _build_ai_contexts(ai_overview_comparison)

    if web_context is None or not ai_contexts:
        return WebAiGapResult(status="unavailable", note=WEB_AI_GAP_UNAVAILABLE_NOTE)

    top_web_ranking = cooccurrence_ranking[:GAP_KEYWORD_TOP_N]
    ai_text = " ".join(context.summary for context in ai_contexts)
    gap_summary = _build_gap_summary(brand_name, top_web_ranking, web_context.summary, ai_contexts)
    suggestions = _build_suggestions(top_web_ranking, ai_text)

    return WebAiGapResult(
        status="real",
        webContext=web_context,
        aiContexts=ai_contexts,
        gapSummary=gap_summary,
        suggestions=suggestions,
        note=WEB_AI_GAP_NOTE,
    )
