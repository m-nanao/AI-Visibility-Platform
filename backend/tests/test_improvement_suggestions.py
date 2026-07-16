from models import BrandSummary, ContextAnalysisItem, CooccurrenceKeyword, SentimentBreakdown
from services.improvement_suggestions import MAX_SUGGESTIONS, build_improvement_suggestions


def _summary(**overrides) -> BrandSummary:
    defaults = dict(
        brandName="Acme",
        visibilityScore=60,
        totalMentions=10,
        sentimentBreakdown=SentimentBreakdown(positive=50, neutral=50, negative=0),
        topPlatforms=["Webページ"],
        summaryText="...",
    )
    defaults.update(overrides)
    return BrandSummary(**defaults)


def _context_item(context: str, sentiment: str = "neutral") -> ContextAnalysisItem:
    return ContextAnalysisItem(context=context, description="d", sentiment=sentiment, exampleQuote="q")


def _keyword(keyword: str, count: int = 5) -> CooccurrenceKeyword:
    return CooccurrenceKeyword(keyword=keyword, count=count, trend="flat")


# A "well covered" context set: one item per category except risk_or_issue,
# used as a baseline so individual tests can drop just the category they
# want to exercise without also triggering the other missing-category rules.
_ALL_CATEGORIES_EXCEPT_RISK = [
    _context_item("料金・価格"),
    _context_item("機能"),
    _context_item("導入事例・活用"),
    _context_item("サポート"),
    _context_item("信頼性・セキュリティ"),
    _context_item("比較検討"),
]

_AMPLE_COOCCURRENCE = [_keyword(f"kw{i}") for i in range(6)]


def test_missing_pricing_context_triggers_pricing_suggestion():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "料金・価格"]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    titles = {s.title for s in suggestions}
    assert "料金・プラン情報の明確化" in titles


def test_missing_pricing_with_cooccurrence_hint_is_medium_priority():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "料金・価格"]
    cooccurrence = _AMPLE_COOCCURRENCE + [_keyword("料金プラン")]

    suggestions = build_improvement_suggestions("Acme", _summary(), cooccurrence, context)

    pricing = next(s for s in suggestions if s.title == "料金・プラン情報の明確化")
    assert pricing.priority == "medium"


def test_missing_pricing_without_any_hint_is_high_priority():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "料金・価格"]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    pricing = next(s for s in suggestions if s.title == "料金・プラン情報の明確化")
    assert pricing.priority == "high"


def test_missing_use_case_context_triggers_use_case_suggestion():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "導入事例・活用"]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    titles = {s.title for s in suggestions}
    assert "導入事例・活用シーンの追加" in titles


def test_missing_support_context_triggers_support_suggestion():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "サポート"]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    titles = {s.title for s in suggestions}
    assert "FAQ・サポート情報の構造化" in titles


def test_missing_reliability_context_triggers_reliability_suggestion():
    context = [c for c in _ALL_CATEGORIES_EXCEPT_RISK if c.context != "信頼性・セキュリティ"]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    titles = {s.title for s in suggestions}
    assert "信頼性・セキュリティ情報の強化" in titles


def test_risk_or_issue_context_triggers_high_priority_suggestion():
    context = _ALL_CATEGORIES_EXCEPT_RISK + [_context_item("課題・懸念点", sentiment="negative")]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(), _AMPLE_COOCCURRENCE, context
    )

    risk_suggestion = next(
        s for s in suggestions if s.title == "誤解されやすい表現・課題文脈の改善"
    )
    assert risk_suggestion.priority == "high"


def test_sparse_context_and_cooccurrence_triggers_keyword_diversity_suggestion():
    suggestions = build_improvement_suggestions(
        "Acme", _summary(totalMentions=1), [], [_context_item("料金・価格")]
    )

    titles = {s.title for s in suggestions}
    assert "重要キーワードとの関連性強化" in titles


def test_suggestion_count_never_exceeds_max_suggestions():
    context = [_context_item("課題・懸念点", sentiment="negative")]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(totalMentions=0, visibilityScore=10), [], context
    )

    assert len(suggestions) <= MAX_SUGGESTIONS


def test_suggestions_are_sorted_by_priority_high_first():
    context = [_context_item("課題・懸念点", sentiment="negative")]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(totalMentions=0, visibilityScore=10), [], context
    )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [priority_rank[s.priority] for s in suggestions]
    assert ranks == sorted(ranks)


def test_development_sample_only_caps_priority_below_high():
    context = [_context_item("課題・懸念点", sentiment="negative")]

    suggestions = build_improvement_suggestions(
        "Acme",
        _summary(totalMentions=0, visibilityScore=10),
        [],
        context,
        source_types=["development_sample"],
    )

    assert all(s.priority != "high" for s in suggestions)


def test_returns_fallback_suggestion_when_nothing_is_triggered():
    context = _ALL_CATEGORIES_EXCEPT_RISK
    summary = _summary(totalMentions=50, visibilityScore=90)
    cooccurrence = _AMPLE_COOCCURRENCE + [_keyword(f"extra{i}") for i in range(4)]

    suggestions = build_improvement_suggestions("Acme", summary, cooccurrence, context)

    assert len(suggestions) == 1
    assert suggestions[0].priority == "low"


def test_suggestion_titles_are_unique():
    # ImprovementSuggestionsSection.tsx uses item.title as a React key,
    # so titles must not repeat within one response.
    context = [_context_item("課題・懸念点", sentiment="negative")]

    suggestions = build_improvement_suggestions(
        "Acme", _summary(totalMentions=0, visibilityScore=10), [], context
    )

    titles = [s.title for s in suggestions]
    assert len(titles) == len(set(titles))


def test_does_not_raise_with_all_empty_inputs():
    suggestions = build_improvement_suggestions("Acme", _summary(totalMentions=0), [], [])
    assert len(suggestions) >= 1
