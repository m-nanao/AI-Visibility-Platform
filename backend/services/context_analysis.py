"""Lightweight, rule-based context analysis over DocumentChunk[].

This is an early Analyzer stage that turns DocumentChunk[] (see
services/document_chunker.py, the Pipeline's "Chunker" stage) into
ContextAnalysisItem[] — the shape the frontend's contextAnalysis
section already expects (backend/models.py's ContextAnalysisItem;
unchanged by this module). Deliberately simple:

- No AI/LLM calls. Category and sentiment are decided by small
  keyword lists, not by understanding the text.
- No new dependencies — stdlib only, cheap enough for Render's free
  tier (a handful of substring checks per chunk).
- Not real NLP: a category is "whichever keyword list scored the most
  hits", and sentiment is "positive keyword count vs negative keyword
  count". This is intentionally a rough categorization, not accurate
  text understanding.

Chunks are first filtered to those mentioning `brand_name`
(case-insensitive — Document/DocumentChunk text has already been
through the Normalizer, so full-width/half-width variants are already
folded to one form by the time this runs). If none mention the brand
at all, a small fallback pool (the first chunks overall) is used
instead of returning nothing, since development_sample/short inputs
can otherwise produce an empty section for no good reason.
"""

from collections import defaultdict

from models import ContextAnalysisItem, DocumentChunk, Sentiment

# Bounds how many chunks get scanned per call, regardless of how many
# a caller passes in. Each check is a handful of cheap substring
# scans, but this keeps a single /analyze request bounded even for an
# unusually large Document[] on Render's free tier.
MAX_CANDIDATE_CHUNKS = 500

# How many chunks to fall back to (in original order) when none
# mention brand_name at all.
FALLBACK_CHUNK_COUNT = 20

MAX_EXCERPT_CHARS = 160

# Checked in this priority order — a chunk is assigned to whichever
# category has the most keyword hits; ties go to the earlier category
# in this list. "general" is the default when nothing matches.
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "pricing": [
        "料金", "価格", "プラン", "月額", "無料", "有料",
        "price", "pricing", "plan", "cost", "free", "paid",
    ],
    "feature": [
        "機能", "できる", "対応", "api", "自動", "連携",
        "feature", "function", "integration", "automate",
    ],
    "use_case": [
        "導入事例", "事例", "活用", "使い方", "ケース",
        "use case", "case study", "example",
    ],
    "support": [
        "サポート", "ヘルプ", "問い合わせ",
        "support", "help", "contact",
    ],
    "reliability": [
        "安定", "セキュリティ", "信頼", "sla",
        "secure", "security", "reliable", "uptime",
    ],
    "comparison": [
        "比較", "競合", "代替",
        "versus", "vs", "compare", "alternative",
    ],
    "risk_or_issue": [
        "課題", "問題", "失敗", "エラー", "リスク",
        "issue", "problem", "error", "risk", "limitation",
    ],
}

# Japanese labels for display in ContextAnalysisItem.context — kept in
# the same style as the existing mock data (mock_analysis.py), so the
# section reads consistently whether a category came from real
# analysis or the still-mocked sections around it.
CATEGORY_LABELS: dict[str, str] = {
    "pricing": "料金・価格",
    "feature": "機能",
    "use_case": "導入事例・活用",
    "support": "サポート",
    "reliability": "信頼性・セキュリティ",
    "comparison": "比較検討",
    "risk_or_issue": "課題・懸念点",
    "general": "その他の文脈",
}

POSITIVE_KEYWORDS = [
    "良い", "おすすめ", "満足", "便利", "高評価", "好評", "使いやすい",
    "スムーズ", "迅速", "充実", "分かりやすい", "評判",
    "good", "great", "easy", "love", "excellent", "recommend",
    "useful", "helpful", "satisfied", "smooth",
]
NEGATIVE_KEYWORDS = [
    "不満", "遅い", "難しい", "問題", "エラー", "失敗", "悪い", "懸念",
    "issue", "problem", "bad", "difficult", "slow", "expensive",
    "fail", "error", "complaint", "risk", "concern",
]


def classify_context(text: str) -> str:
    """Returns the category (a key of CATEGORY_KEYWORDS, or "general")
    with the most keyword hits in `text`. Case-insensitive.
    """
    haystack = text.lower()
    best_category = "general"
    best_score = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(haystack.count(keyword) for keyword in keywords)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


def _score_sentiment(texts: list[str]) -> Sentiment:
    haystack = " ".join(texts).lower()
    positive = sum(haystack.count(keyword) for keyword in POSITIVE_KEYWORDS)
    negative = sum(haystack.count(keyword) for keyword in NEGATIVE_KEYWORDS)
    if positive > negative:
        return "positive"
    if negative > positive:
        return "negative"
    return "neutral"


def _make_excerpt(text: str) -> str:
    """A short excerpt for ContextAnalysisItem.exampleQuote — never a
    full chunk, so the frontend/API response stays small regardless of
    chunk size.
    """
    stripped = text.strip()
    if len(stripped) <= MAX_EXCERPT_CHARS:
        return stripped
    return stripped[: MAX_EXCERPT_CHARS - 1].rstrip() + "…"


def _select_candidate_chunks(
    brand_name: str, chunks: list[DocumentChunk]
) -> tuple[list[DocumentChunk], bool]:
    """Returns (candidate chunks, used_fallback). Prefers chunks that
    mention `brand_name` (case-insensitive); falls back to the first
    few chunks overall when none do, so a short/sparse corpus
    (e.g. development_sample) doesn't produce an empty section.
    """
    brand_lower = brand_name.lower()
    matching = [chunk for chunk in chunks if brand_lower in chunk.text.lower()]
    if matching:
        return matching[:MAX_CANDIDATE_CHUNKS], False
    return chunks[:FALLBACK_CHUNK_COUNT], True


def analyze_contexts(
    brand_name: str,
    chunks: list[DocumentChunk],
    max_contexts: int = 8,
) -> list[ContextAnalysisItem]:
    """Builds ContextAnalysisItem[] from DocumentChunk[] using simple,
    keyword-based category/sentiment rules (see module docstring).

    Returns [] if `chunks` is empty — callers (main.py) use this to
    decide the section's real/unavailable status, mirroring how
    cooccurrenceRanking already distinguishes "nothing to analyze"
    from "analyzed, found nothing".
    """
    if not chunks:
        return []

    candidates, used_fallback = _select_candidate_chunks(brand_name, chunks)
    if not candidates:
        return []

    groups: dict[str, list[DocumentChunk]] = defaultdict(list)
    for chunk in candidates:
        groups[classify_context(chunk.text)].append(chunk)

    items: list[tuple[int, str, ContextAnalysisItem]] = []
    for category, group_chunks in groups.items():
        label = CATEGORY_LABELS[category]
        evidence_count = len(group_chunks)
        sentiment = _score_sentiment([chunk.text for chunk in group_chunks])
        example_quote = _make_excerpt(group_chunks[0].text)

        if used_fallback:
            description = (
                f"「{brand_name}」を直接含む文章は見つかりませんでしたが、"
                f"関連しそうな{label}の文脈が{evidence_count}件見つかりました。"
            )
        else:
            description = (
                f"「{brand_name}」に関連する文脈のうち、{label}に関する言及が"
                f"{evidence_count}件見つかりました。"
            )

        items.append((evidence_count, category, ContextAnalysisItem(
            context=label,
            description=description,
            sentiment=sentiment,
            exampleQuote=example_quote,
        )))

    # Most-evidenced category first; ties keep CATEGORY_KEYWORDS/"general"
    # priority order (dict insertion order, stable sort).
    category_priority = {category: index for index, category in enumerate([*CATEGORY_KEYWORDS, "general"])}
    items.sort(key=lambda entry: (-entry[0], category_priority[entry[1]]))

    return [item for _, _, item in items[:max_contexts]]
