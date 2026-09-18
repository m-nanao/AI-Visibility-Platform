from models import AIOverviewComparisonItem, CooccurrenceKeyword, Document
from services.claude_provider import CLAUDE_PLATFORM_LABEL
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.gemini_provider import GEMINI_PLATFORM_LABEL
from services.web_ai_gap import (
    WEB_AI_GAP_NOTE,
    WEB_AI_GAP_UNAVAILABLE_NOTE,
    build_web_ai_gap,
)


def _make_document(text: str, **overrides) -> Document:
    defaults = dict(
        id="doc-1",
        sourceType="user_provided",
        fetchedAt="2026-09-19T00:00:00+00:00",
        text=text,
    )
    defaults.update(overrides)
    return Document(**defaults)


def _ai_item(platform: str, summary: str) -> AIOverviewComparisonItem:
    return AIOverviewComparisonItem(platform=platform, mentioned=True, rank=None, summary=summary)


def _keyword(word: str, count: int = 1) -> CooccurrenceKeyword:
    return CooccurrenceKeyword(keyword=word, count=count, trend="flat")


def test_unavailable_when_no_common_crawl_or_web_fetch_document():
    documents = [_make_document("Acmeは初期費用0円で契約期間の縛りなく利用できます。", sourceType="user_provided")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはSEOコンサルティングを中心に支援しています。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "unavailable"
    assert result.webContext is None
    assert result.aiContexts == []
    assert result.note == WEB_AI_GAP_UNAVAILABLE_NOTE


def test_unavailable_when_no_real_ai_observation():
    documents = [_make_document("Acmeは初期費用0円で契約期間の縛りなく利用できます。", sourceType="web_fetch")]
    # Mock AI Overview fixture — not a real single-shot observation.
    ai_items = [_ai_item("Google AI Overview", "Acmeは比較記事で言及される。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "unavailable"
    assert result.note == WEB_AI_GAP_UNAVAILABLE_NOTE


def test_real_result_prefers_common_crawl_document_over_web_fetch():
    documents = [
        _make_document(
            "Acmeは初期費用0円のWebページ文書です。",
            id="doc-web",
            sourceType="web_fetch",
            sourceUrl="https://example.com/web",
        ),
        _make_document(
            "AcmeはCommon Crawl由来の文書で、契約期間の縛りなし・初期費用0円で利用できます。",
            id="doc-cc",
            sourceType="common_crawl",
            sourceUrl="https://example.com/cc",
        ),
    ]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはSEOコンサルティングを中心に支援する会社です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "real"
    assert result.webContext is not None
    assert result.webContext.sourceType == "common_crawl"
    assert result.webContext.sourceUrl == "https://example.com/cc"
    assert "Common Crawl由来" in result.webContext.summary
    assert result.note == WEB_AI_GAP_NOTE


def test_ai_contexts_ordered_chatgpt_claude_gemini_ai_overview_and_excludes_mock():
    documents = [_make_document("Acmeについての公式文書です。", sourceType="web_fetch")]
    ai_items = [
        _ai_item("Google AI Overview", "モックのAI Overviewカードです。"),  # excluded (mock)
        _ai_item("Google AI Mode (DataForSEO Sandbox)", "AcmeはAI Overview上で紹介される。"),
        _ai_item(GEMINI_PLATFORM_LABEL, "AcmeはGemini観測での説明です。"),
        _ai_item(CLAUDE_PLATFORM_LABEL, "AcmeはClaude観測での説明です。"),
        _ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはChatGPT観測での説明です。"),
    ]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "real"
    assert [context.platform for context in result.aiContexts] == [
        "chatgpt",
        "claude",
        "gemini",
        "ai_overview",
    ]
    assert all(context.status == "real" for context in result.aiContexts)


def test_gap_summary_reports_distinctive_keywords_on_each_side():
    documents = [
        _make_document(
            "Acmeは契約期間の縛りなし・初期費用0円で利用できるサービスです。",
            sourceType="web_fetch",
        )
    ]
    ai_items = [
        _ai_item(
            CHATGPT_PLATFORM_LABEL,
            "AcmeはSEOコンサルティングを中心にWebマーケティング支援を行う会社です。",
        )
    ]
    web_ranking = [_keyword("初期費用", 3), _keyword("契約期間", 2)]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    assert result.status == "real"
    assert result.gapSummary is not None
    assert "初期費用" in result.gapSummary or "契約期間" in result.gapSummary


def test_gap_summary_falls_back_to_neutral_sentence_without_distinctive_keywords():
    shared_text = "Acmeについての短い紹介文です。"
    documents = [_make_document(shared_text, sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, shared_text)]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "real"
    assert result.gapSummary == "Web上の文脈とAI観測上の回答傾向に、大きな差は確認できませんでした。"


def test_suggestions_always_include_generic_hint():
    documents = [_make_document("Acmeについての文書です。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.suggestions
    assert "社名の近く" in result.suggestions[0]


def test_suggestions_add_second_hint_when_web_side_has_distinctive_keywords():
    documents = [_make_document("Acmeは初期費用0円のサービスです。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはSEOコンサルティングの会社です。")]
    web_ranking = [_keyword("初期費用", 5)]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    assert len(result.suggestions) == 2
    assert "初期費用" in result.suggestions[1]


def test_web_context_summary_is_truncated_and_never_empty_for_blank_document():
    long_text = "Acme" + "は非常に長い文章です。" * 50
    documents = [_make_document(long_text, sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.webContext is not None
    assert len(result.webContext.summary) <= 200


def test_unavailable_when_common_crawl_document_is_blank_and_no_web_fetch_fallback():
    documents = [_make_document("   ", sourceType="common_crawl")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "unavailable"
