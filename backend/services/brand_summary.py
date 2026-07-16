"""Lightweight, rule-based brand summary derived from analysis already
computed elsewhere in the pipeline.

This turns the existing Document[]/DocumentChunk[]/cooccurrenceRanking/
contextAnalysis outputs into a BrandSummary — the first time `summary`
is anything other than fixed placeholder data. Deliberately simple, in
the same spirit as services/context_analysis.py:

- No AI/LLM calls, no external API. Every value is a small formula or
  a keyword/category lookup over data already computed by
  services/cooccurrence.py and services/context_analysis.py.
- `visibilityScore` is an MVP-only, deliberately rough estimate of how
  much (not how well) the brand shows up in what could be gathered —
  not a measurement of real generative-AI visibility. It should not be
  read as more precise than that.
- `topPlatforms` never claims ChatGPT/Perplexity/Google AI Overview
  were actually measured (they aren't, anywhere in this codebase yet —
  see services/mock_analysis.py's placeholder for what real AI Overview
  comparison would look like once implemented). Instead it reports the
  Document sourceType(s) that were actually analyzed, so the label
  matches what was actually gathered.
"""

from collections import Counter

from models import (
    BrandSummary,
    ContextAnalysisItem,
    CooccurrenceKeyword,
    Document,
    DocumentChunk,
    Sentiment,
    SentimentBreakdown,
)
from services.context_analysis import CATEGORY_LABELS

# Reverse of context_analysis.CATEGORY_LABELS (label -> category key),
# so a ContextAnalysisItem.context (a display label, e.g. "料金・価格")
# can be mapped back to which keyword category produced it. Labels are
# 1:1 with categories, so this reversal is safe.
_LABEL_TO_CATEGORY: dict[str, str] = {label: category for category, label in CATEGORY_LABELS.items()}

# A category-level sentiment "leaning" used only for sentimentBreakdown
# below — deliberately coarser than context_analysis.py's own per-item
# sentiment (which scores keyword hits within the actual excerpt text).
# This is "what kind of topic is this" (e.g. risk_or_issue skews
# negative), not text sentiment analysis.
_CATEGORY_SENTIMENT_LEANING: dict[str, Sentiment] = {
    "feature": "positive",
    "use_case": "positive",
    "support": "positive",
    "reliability": "positive",
    "risk_or_issue": "negative",
    "pricing": "neutral",
    "comparison": "neutral",
    "general": "neutral",
}

# Human-readable label for each Document.sourceType, used for
# topPlatforms instead of unmeasured AI platform names (see module
# docstring). Kept in Japanese to match the rest of the (Japanese) UI
# text this field is rendered next to.
_SOURCE_TYPE_LABELS: dict[str, str] = {
    "web_fetch": "Webページ",
    "user_provided": "入力テキスト",
    "development_sample": "開発用サンプル",
    "common_crawl": "Common Crawl（未実装）",
    "dataforseo": "DataForSEO（未実装）",
}

# Caps used when scoring visibilityScore below, so no single input
# (e.g. an unusually long document) can dominate the score.
_MAX_MENTION_POINTS_INPUT = 10
_MAX_DOCUMENT_POINTS_INPUT = 10
_MAX_COOCCURRENCE_POINTS_INPUT = 8
_MAX_CONTEXT_POINTS_INPUT = 8

# When every analyzed Document came from development_sample (i.e. no
# actual user_provided text or web page was analyzed), the score is
# capped below this so a synthetic sample corpus can't read as full
# real-world visibility.
_DEVELOPMENT_SAMPLE_ONLY_SCORE_CAP = 55


def _count_mentions(brand_name: str, documents: list[Document]) -> int:
    """Counts brand_name occurrences across Document.text (already
    Normalizer-processed, so full-width/half-width variants are
    already folded to one form). Case-insensitive, substring-based —
    the same simple approach context_analysis.py uses for chunk
    matching, not a "word" boundary match.
    """
    brand_lower = brand_name.lower()
    if not brand_lower:
        return 0
    return sum(document.text.lower().count(brand_lower) for document in documents)


def _estimate_visibility_score(
    *,
    mention_count: int,
    document_count: int,
    cooccurrence_count: int,
    context_count: int,
    source_types: list[str],
) -> int:
    """A simple, additive 0-100 estimate — see module docstring for why
    this is deliberately not a real "AI visibility" measurement.
    """
    score = 0.0
    score += min(mention_count, _MAX_MENTION_POINTS_INPUT) * 3  # up to 30
    score += min(document_count, _MAX_DOCUMENT_POINTS_INPUT) * 2  # up to 20
    score += min(cooccurrence_count, _MAX_COOCCURRENCE_POINTS_INPUT) * 2  # up to 16
    score += min(context_count, _MAX_CONTEXT_POINTS_INPUT) * 3  # up to 24
    if len(source_types) >= 2:
        score += 10
    elif len(source_types) == 1:
        score += 5

    score = max(0, min(100, round(score)))

    if source_types == ["development_sample"]:
        score = min(score, _DEVELOPMENT_SAMPLE_ONLY_SCORE_CAP)

    return score


def _estimate_sentiment_breakdown(context_analysis: list[ContextAnalysisItem]) -> SentimentBreakdown:
    """Buckets each contextAnalysis item by its category's sentiment
    leaning (see _CATEGORY_SENTIMENT_LEANING above), then converts to
    percentages that always sum to 100. Every item counts equally
    (no per-item weighting) — this is a rough topic-mix estimate, not
    a weighted sentiment score.
    """
    if not context_analysis:
        return SentimentBreakdown(positive=0, neutral=100, negative=0)

    leaning_counts: Counter[str] = Counter()
    for item in context_analysis:
        category = _LABEL_TO_CATEGORY.get(item.context, "general")
        leaning_counts[_CATEGORY_SENTIMENT_LEANING.get(category, "neutral")] += 1

    total = sum(leaning_counts.values())
    positive_pct = round(leaning_counts["positive"] / total * 100)
    negative_pct = round(leaning_counts["negative"] / total * 100)
    # neutral takes the remainder rather than its own rounded value, so
    # the three percentages always sum to exactly 100.
    neutral_pct = 100 - positive_pct - negative_pct

    return SentimentBreakdown(positive=positive_pct, neutral=neutral_pct, negative=negative_pct)


def _build_top_platforms(source_types: list[str]) -> list[str]:
    if not source_types:
        return ["データ不足"]
    return [_SOURCE_TYPE_LABELS.get(source_type, source_type) for source_type in source_types]


def _build_summary_text(
    *,
    brand_name: str,
    mention_count: int,
    source_types: list[str],
    cooccurrence_ranking: list[CooccurrenceKeyword],
    context_analysis: list[ContextAnalysisItem],
) -> str:
    if not context_analysis:
        return (
            f"{brand_name}に関する十分な文脈は取得できませんでした。"
            "URLを追加すると、より具体的な分析が可能です。"
        )

    top_categories = "・".join(item.context for item in context_analysis[:2])
    top_keywords = "・".join(keyword.keyword for keyword in cooccurrence_ranking[:3])
    keyword_sentence = f"共起語として{top_keywords}などが確認されました。" if top_keywords else ""

    if source_types == ["development_sample"]:
        return (
            f"{brand_name}は開発用サンプル文章内で分析されています。"
            f"主に{top_categories}の文脈で語られ、{keyword_sentence}"
        )

    return (
        f"{brand_name}は取得した文章内で{mention_count}回言及され、"
        f"主に{top_categories}の文脈で語られています。{keyword_sentence}"
    )


def build_brand_summary(
    brand_name: str,
    documents: list[Document],
    chunks: list[DocumentChunk],
    cooccurrence_ranking: list[CooccurrenceKeyword],
    context_analysis: list[ContextAnalysisItem],
) -> BrandSummary:
    """Builds a BrandSummary from data already computed elsewhere in
    /analyze (Document[], DocumentChunk[], cooccurrenceRanking,
    contextAnalysis) — no new fetching or analysis of its own beyond
    counting/bucketing. `chunks` isn't used directly (context_analysis
    already summarizes it) but is accepted to keep this function's
    inputs matching the rest of the Analyzer stage's shape.
    """
    mention_count = _count_mentions(brand_name, documents)
    source_types = sorted({document.sourceType for document in documents})

    return BrandSummary(
        brandName=brand_name,
        visibilityScore=_estimate_visibility_score(
            mention_count=mention_count,
            document_count=len(documents),
            cooccurrence_count=len(cooccurrence_ranking),
            context_count=len(context_analysis),
            source_types=source_types,
        ),
        totalMentions=mention_count,
        sentimentBreakdown=_estimate_sentiment_breakdown(context_analysis),
        topPlatforms=_build_top_platforms(source_types),
        summaryText=_build_summary_text(
            brand_name=brand_name,
            mention_count=mention_count,
            source_types=source_types,
            cooccurrence_ranking=cooccurrence_ranking,
            context_analysis=context_analysis,
        ),
    )
