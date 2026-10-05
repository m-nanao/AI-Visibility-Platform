from models import AIOverviewComparisonItem, CooccurrenceKeyword, Document, WebAiGapResult
from services.claude_provider import CLAUDE_PLATFORM_LABEL
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.gemini_provider import GEMINI_PLATFORM_LABEL
from services.web_ai_gap import (
    WEB_AI_GAP_NOTE,
    WEB_AI_GAP_UNAVAILABLE_NOTE,
    _WORD_LEVEL_FALLBACK_SUGGESTION,
    _is_noise_keyword,
    build_web_ai_gap,
    rebuild_web_ai_gap_for_updated_ai_contexts,
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


def test_gap_summary_uses_category_diff_when_both_sides_have_a_detectable_category():
    # This is the task's own canonical example: Web emphasizes pricing/
    # contract terms, the AI observation emphasizes service type.
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

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "real"
    assert result.gapSummary == (
        "Web上では料金・契約条件に関する説明が目立つ一方、AI回答ではサービス内容の説明が中心です。"
    )


def test_gap_summary_category_diff_when_only_web_side_has_a_detectable_category():
    documents = [_make_document("Acmeは月額プランで契約できます。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての一般的な説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.gapSummary == (
        "Web上では料金・契約条件に関する説明が目立ちますが、AI観測上の回答ではあまり触れられていません。"
    )


def test_gap_summary_category_diff_when_only_ai_side_has_a_detectable_category():
    documents = [_make_document("Acmeについての一般的な紹介です。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeは中小企業向けの法人サービスです。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.gapSummary == (
        "AI回答では対象顧客の説明が中心ですが、Web上で確認できる文脈との重なりは限定的です。"
    )


def test_gap_summary_falls_back_to_word_level_diff_when_both_sides_share_the_same_category():
    # Both sides are dominated by the same category (サービス内容) — the
    # category diff has nothing interesting to say, so this must fall
    # through to the word-level heuristic instead of silently reporting
    # "no difference" when a real (non-category) difference exists.
    documents = [
        _make_document("AcmeはSEOコンサルティングと集客支援を行います。", sourceType="web_fetch")
    ]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはWebマーケティングと制作を行う会社です。")]
    web_ranking = [_keyword("コンサルティング", 5)]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    # Falls through to the word-level sentence shape, not the
    # category-diff shape (which would say "...に関する説明が...").
    assert "に関する説明が" not in (result.gapSummary or "")


def test_gap_summary_falls_back_to_neutral_sentence_without_distinctive_keywords_or_category():
    shared_text = "Acmeについての短い紹介文です。"
    documents = [_make_document(shared_text, sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, shared_text)]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "real"
    assert result.gapSummary == "Web上の文脈とAI観測上の回答傾向に、大きな差は確認できませんでした。"


def test_gap_summary_word_level_fallback_excludes_noise_keywords():
    # Regression test for the task's own reported example: boilerplate
    # like "Vol"/"会社概要" must never be surfaced as a difference, even
    # when ranked highly — only the genuinely distinctive, non-noise
    # keyword should appear. Deliberately avoids any _CATEGORY_KEYWORDS
    # match (e.g. a region name) so this exercises the word-level
    # fallback specifically rather than the category diff.
    documents = [
        _make_document(
            "Acme株式会社の会社概要ページです。Vol.3。独自技術を提供します。",
            sourceType="web_fetch",
        )
    ]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての簡単な説明です。")]
    web_ranking = [
        _keyword("Vol", 10),
        _keyword("会社概要", 9),
        _keyword("独自技術", 6),
    ]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    assert result.gapSummary is not None
    for noisy in ("Vol", "会社概要"):
        assert noisy not in result.gapSummary
    assert "独自技術" in result.gapSummary


def test_suggestions_always_include_generic_hint():
    documents = [_make_document("Acmeについての文書です。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.suggestions
    assert "社名の近く" in result.suggestions[0]


def test_suggestions_add_category_hint_matching_the_tasks_pricing_example():
    documents = [
        _make_document(
            "Acmeは契約期間の縛りなし・初期費用0円で利用できるサービスです。",
            sourceType="web_fetch",
        )
    ]
    # Deliberately category-free on the AI side, so this exercises the
    # "web has a category, AI doesn't" branch specifically.
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての一般的な説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert len(result.suggestions) == 2
    assert "料金条件だけでなく" in result.suggestions[1]


def test_suggestions_add_category_hint_for_region_only_web_category():
    documents = [_make_document("Acmeは東京・大阪・柏に拠点があります。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての一般的な説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert len(result.suggestions) == 2
    assert "所在地情報だけでなく" in result.suggestions[1]


def test_suggestions_fall_back_to_word_level_hint_without_a_detectable_category():
    # The word-level fallback suggestion must never cite the specific
    # distinctive word verbatim (e.g. the old "「独自技術」など、Web上で
    # 強調されている内容を..." phrasing) — a依頼者 reported that citing
    # a word-level "difference" by name can read as an unnatural/noisy
    # suggestion even when the word itself isn't boilerplate, since
    # "distinctive" here only means a simple substring asymmetry was
    # found, not that the word is meaningful content worth naming.
    documents = [_make_document("Acmeは独自技術0円のサービスです。", sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての簡単な説明です。")]
    web_ranking = [_keyword("独自技術", 5)]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    assert len(result.suggestions) == 2
    assert result.suggestions[1] == _WORD_LEVEL_FALLBACK_SUGGESTION
    assert "独自技術" not in result.suggestions[1]


def test_suggestions_never_contain_noise_keywords():
    documents = [
        _make_document(
            "Acme株式会社の会社概要ページ。千葉県柏市に所在します。独自技術を提供します。",
            sourceType="web_fetch",
        )
    ]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての簡単な説明です。")]
    web_ranking = [
        _keyword("会社概要", 9),
        _keyword("千葉県", 8),
        _keyword("柏市", 7),
        _keyword("独自技術", 6),
    ]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    suggestions_text = " ".join(result.suggestions)
    for noisy in ("会社概要", "千葉県", "柏市"):
        assert noisy not in suggestions_text


def test_web_context_summary_is_truncated_and_never_empty_for_blank_document():
    long_text = "Acme" + "は非常に長い文章です。" * 50
    documents = [_make_document(long_text, sourceType="web_fetch")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.webContext is not None
    assert len(result.webContext.summary) <= 200


def test_is_noise_keyword_matches_compound_registry_token_via_substring():
    # Regression test for the task's own reported example: the simple
    # tokenizer can yield a compound run like "千葉県柏市" (no separator
    # between prefecture and city) as a single keyword, which the old
    # exact-match version of _NOISE_KEYWORDS missed even though "千葉県"
    # and "柏市" were both individually listed. Substring matching
    # catches it without needing every possible compound spelled out.
    assert _is_noise_keyword("千葉県柏市")
    assert _is_noise_keyword("千葉県柏市・本社")


def test_suggestions_never_contain_noise_keywords_including_compound_registry_token():
    documents = [
        _make_document(
            "Acme株式会社の会社概要ページ。千葉県柏市・本社にて独自技術を提供します。",
            sourceType="web_fetch",
        )
    ]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての簡単な説明です。")]
    web_ranking = [
        _keyword("千葉県柏市・本社", 9),
        _keyword("独自技術", 6),
    ]

    result = build_web_ai_gap("Acme", documents, web_ranking, ai_items)

    suggestions_text = " ".join(result.suggestions)
    assert "千葉県柏市" not in suggestions_text
    assert "本社" not in suggestions_text


def test_unavailable_when_common_crawl_document_is_blank_and_no_web_fetch_fallback():
    documents = [_make_document("   ", sourceType="common_crawl")]
    ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "Acmeについての説明です。")]

    result = build_web_ai_gap("Acme", documents, [], ai_items)

    assert result.status == "unavailable"


# --- rebuild_web_ai_gap_for_updated_ai_contexts (Gemini-only rerun) ------
#
# Supports POST /analysis-runs/{id}/rerun/gemini (services/gemini_rerun.py)
# — after a saved run's Gemini card is replaced, this recomputes
# aiContexts/gapSummary/suggestions from the already-saved webContext
# excerpt (never the original raw Document[], which isn't persisted).


def test_rebuild_updates_ai_contexts_and_gap_summary_with_new_gemini_card():
    documents = [
        _make_document(
            "Acmeは契約期間の縛りなし・初期費用0円で利用できるサービスです。",
            sourceType="web_fetch",
        )
    ]
    original_ai_items = [
        _ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはSEOコンサルティングを中心に支援する会社です。")
    ]
    existing = build_web_ai_gap("Acme", documents, [], original_ai_items)
    assert existing.status == "real"
    assert len(existing.aiContexts) == 1

    updated_ai_items = [
        *original_ai_items,
        _ai_item(GEMINI_PLATFORM_LABEL, "Acmeは中小企業向けの法人サービスを提供しています。"),
    ]

    updated = rebuild_web_ai_gap_for_updated_ai_contexts("Acme", existing, [], updated_ai_items)

    assert updated.status == "real"
    assert [c.platform for c in updated.aiContexts] == ["chatgpt", "gemini"]
    # The Web-side excerpt itself is reused as-is, not re-derived.
    assert updated.webContext == existing.webContext


def test_rebuild_replaces_gemini_context_when_card_content_changed():
    documents = [_make_document("Acmeについての公式文書です。", sourceType="web_fetch")]
    original_ai_items = [_ai_item(GEMINI_PLATFORM_LABEL, "old Gemini summary")]
    existing = build_web_ai_gap("Acme", documents, [], original_ai_items)
    assert existing.status == "real"

    updated_ai_items = [_ai_item(GEMINI_PLATFORM_LABEL, "new Gemini summary, fully re-fetched")]

    updated = rebuild_web_ai_gap_for_updated_ai_contexts("Acme", existing, [], updated_ai_items)

    assert len(updated.aiContexts) == 1
    assert updated.aiContexts[0].summary == "new Gemini summary, fully re-fetched"


def test_rebuild_leaves_result_unchanged_when_existing_status_is_unavailable():
    existing = WebAiGapResult(status="unavailable", note=WEB_AI_GAP_UNAVAILABLE_NOTE)
    updated_ai_items = [_ai_item(GEMINI_PLATFORM_LABEL, "Acmeは中小企業向けの法人サービスです。")]

    updated = rebuild_web_ai_gap_for_updated_ai_contexts("Acme", existing, [], updated_ai_items)

    # Can't invent a Web-side excerpt that was never saved — left as-is
    # rather than flipping to "real" with an incomplete comparison.
    assert updated is existing


def test_rebuild_leaves_result_unchanged_when_no_real_ai_observation_remains():
    documents = [_make_document("Acmeについての公式文書です。", sourceType="web_fetch")]
    original_ai_items = [_ai_item(CHATGPT_PLATFORM_LABEL, "AcmeはChatGPT観測での説明です。")]
    existing = build_web_ai_gap("Acme", documents, [], original_ai_items)
    assert existing.status == "real"

    # e.g. the mock AI Overview placeholder only — nothing real.
    updated_ai_items = [_ai_item("Google AI Overview", "モックのAI Overviewカードです。")]

    updated = rebuild_web_ai_gap_for_updated_ai_contexts("Acme", existing, [], updated_ai_items)

    # Never silently downgrades a previously-real comparison to nothing
    # just because this unrelated re-run feature ran.
    assert updated is existing
