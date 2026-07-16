from models import ContextAnalysisItem, CooccurrenceKeyword, Document
from services.brand_summary import build_brand_summary


def _make_document(text: str, **overrides) -> Document:
    defaults = dict(
        id="doc-1",
        sourceType="user_provided",
        fetchedAt="2026-07-16T00:00:00+00:00",
        text=text,
    )
    defaults.update(overrides)
    return Document(**defaults)


def _context_item(context: str, sentiment: str = "neutral") -> ContextAnalysisItem:
    return ContextAnalysisItem(
        context=context, description="d", sentiment=sentiment, exampleQuote="q"
    )


def test_total_mentions_counts_brand_name_occurrences_case_insensitively():
    documents = [
        _make_document("Acmeはとても便利です。acmeのAPIも使いやすいです。"),
        _make_document("ACMEについての記事です。"),
    ]

    summary = build_brand_summary("Acme", documents, [], [], [])

    assert summary.totalMentions == 3


def test_total_mentions_is_zero_for_no_documents():
    summary = build_brand_summary("Acme", [], [], [], [])
    assert summary.totalMentions == 0


def test_sentiment_breakdown_sums_to_100_when_context_analysis_present():
    context = [_context_item("料金・価格"), _context_item("機能"), _context_item("課題・懸念点")]

    summary = build_brand_summary("Acme", [], [], [], context)

    total = (
        summary.sentimentBreakdown.positive
        + summary.sentimentBreakdown.neutral
        + summary.sentimentBreakdown.negative
    )
    assert total == 100


def test_sentiment_breakdown_is_neutral_100_when_context_analysis_is_empty():
    summary = build_brand_summary("Acme", [], [], [], [])

    assert summary.sentimentBreakdown.positive == 0
    assert summary.sentimentBreakdown.neutral == 100
    assert summary.sentimentBreakdown.negative == 0


def test_sentiment_breakdown_increases_negative_for_risk_or_issue_category():
    context = [_context_item("課題・懸念点")]

    summary = build_brand_summary("Acme", [], [], [], context)

    assert summary.sentimentBreakdown.negative == 100
    assert summary.sentimentBreakdown.positive == 0


def test_sentiment_breakdown_increases_positive_for_feature_use_case_support_reliability():
    context = [
        _context_item("機能"),
        _context_item("導入事例・活用"),
        _context_item("サポート"),
        _context_item("信頼性・セキュリティ"),
    ]

    summary = build_brand_summary("Acme", [], [], [], context)

    assert summary.sentimentBreakdown.positive == 100
    assert summary.sentimentBreakdown.negative == 0


def test_summary_text_includes_top_cooccurrence_keywords():
    cooccurrence_ranking = [
        CooccurrenceKeyword(keyword="料金プラン", count=5, trend="flat"),
        CooccurrenceKeyword(keyword="導入事例", count=3, trend="flat"),
    ]
    context = [_context_item("料金・価格")]

    summary = build_brand_summary("Acme", [], [], cooccurrence_ranking, context)

    assert "料金プラン" in summary.summaryText
    assert "導入事例" in summary.summaryText


def test_development_sample_only_does_not_claim_measured_ai_platforms():
    documents = [_make_document("Acmeのサンプル文章です。", sourceType="development_sample")]

    summary = build_brand_summary("Acme", documents, [], [], [])

    unmeasured_platform_names = {"ChatGPT", "Perplexity", "Google AI Overview", "Copilot"}
    assert not unmeasured_platform_names.intersection(summary.topPlatforms)
    assert summary.topPlatforms == ["開発用サンプル"]


def test_web_fetch_documents_do_not_claim_measured_ai_platforms():
    documents = [_make_document("Acmeについてのページです。", sourceType="web_fetch")]

    summary = build_brand_summary("Acme", documents, [], [], [])

    unmeasured_platform_names = {"ChatGPT", "Perplexity", "Google AI Overview", "Copilot"}
    assert not unmeasured_platform_names.intersection(summary.topPlatforms)


def test_visibility_score_is_capped_for_development_sample_only():
    documents = [
        _make_document(f"Acme mention {i}", sourceType="development_sample", id=f"doc-{i}")
        for i in range(20)
    ]
    cooccurrence_ranking = [
        CooccurrenceKeyword(keyword=f"kw{i}", count=1, trend="flat") for i in range(8)
    ]
    context = [_context_item(label) for label in ["料金・価格", "機能", "導入事例・活用", "サポート"]]

    summary = build_brand_summary("Acme", documents, [], cooccurrence_ranking, context)

    assert summary.visibilityScore <= 55


def test_visibility_score_is_within_0_to_100_bounds():
    documents = [
        _make_document(f"Acme mention {i}", id=f"doc-{i}") for i in range(50)
    ]
    cooccurrence_ranking = [
        CooccurrenceKeyword(keyword=f"kw{i}", count=1, trend="flat") for i in range(20)
    ]
    context = [_context_item("機能") for _ in range(10)]

    summary = build_brand_summary("Acme", documents, [], cooccurrence_ranking, context)

    assert 0 <= summary.visibilityScore <= 100


def test_build_brand_summary_does_not_raise_with_all_empty_inputs():
    summary = build_brand_summary("Acme", [], [], [], [])
    assert summary.brandName == "Acme"
