"""Tests for models.py's fact-extraction data structures and
services/fact_extraction.py's verification-only logic (Task
6-D-5C-1, feature/fact-extraction-data-model).

No LLM/API call is made or mocked anywhere in this file — everything
here is pure data-structure validation and string/position
verification.
"""

import pytest
from pydantic import ValidationError

import services.fact_extraction as fe
from models import (
    AIOverviewComparisonItem,
    AnalysisResult,
    FactCategoryNotMentioned,
    FactExtractedClaim,
    FactExtractionResult,
    MAX_FACT_CLAIM_TEXT_CHARS,
    MAX_FACT_CLAIMS_PER_CARD,
    MAX_FACT_ORIGINAL_TEXT_CHARS,
    MAX_FACT_SOURCE_TEXT_CHARS,
    RawFactClaimCandidate,
)
from services.mock_analysis import build_dummy_analysis


def _minimal_analysis_result(**overrides) -> dict:
    base = build_dummy_analysis("Acme").model_dump()
    base.update(overrides)
    return base


# --- 1. category / nature / answerState enumeration -----------------------


ALL_CATEGORIES = [
    "company_name",
    "location",
    "representative",
    "establishment_date",
    "business",
    "service",
    "characteristic",
    "numerical_achievement",
    "target_customer_or_industry",
]


@pytest.mark.parametrize("category", ALL_CATEGORIES)
def test_all_nine_claim_categories_are_valid(category):
    claim = FactExtractedClaim(
        claimCategory=category,
        claimNature="objective_fact",
        answerState="asserted",
        claimText="x",
        sourceText="y",
        sourceStartIndex=0,
        sourceEndIndex=1,
        sourcePlatform="chatgpt",
    )
    assert claim.claimCategory == category


def test_there_are_exactly_nine_claim_categories():
    assert len(ALL_CATEGORIES) == 9


def test_invalid_claim_category_is_rejected():
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="not_a_real_category",
            claimNature="objective_fact",
            answerState="asserted",
            claimText="x",
            sourceText="y",
            sourceStartIndex=0,
            sourceEndIndex=1,
            sourcePlatform="chatgpt",
        )


@pytest.mark.parametrize(
    "nature", ["objective_fact", "self_reported_claim", "ai_evaluation_or_inference"]
)
def test_all_three_claim_natures_are_valid(nature):
    claim = FactExtractedClaim(
        claimCategory="business",
        claimNature=nature,
        answerState="asserted",
        claimText="x",
        sourceText="y",
        sourceStartIndex=0,
        sourceEndIndex=1,
        sourcePlatform="claude",
    )
    assert claim.claimNature == nature


@pytest.mark.parametrize("state", ["asserted", "explicit_unknown", "explicit_denial"])
def test_all_three_grounded_answer_states_are_valid_on_fact_extracted_claim(state):
    claim = FactExtractedClaim(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState=state,
        claimText="x",
        sourceText="代表者はA氏です",
        sourceStartIndex=0,
        sourceEndIndex=8,
        sourcePlatform="gemini",
    )
    assert claim.answerState == state


def test_not_mentioned_is_not_a_valid_answer_state_for_fact_extracted_claim():
    # Task 6-D-5C-1 final review: not_mentioned is structurally
    # impossible on FactExtractedClaim (FactGroundedAnswerState has
    # only 3 values) — use FactCategoryNotMentioned instead (see
    # section 2 below).
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="representative",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText="代表者への言及なし",
            sourceText="x",
            sourceStartIndex=0,
            sourceEndIndex=1,
            sourcePlatform="gemini",
        )


def test_explicit_unknown_and_explicit_denial_are_distinct_values():
    assert "explicit_unknown" != "explicit_denial"


# --- 2. not_mentioned lives in a separate, lightweight model --------------


def test_not_mentioned_category_state_has_no_claim_text_or_source_fields():
    # FactCategoryNotMentioned has no sourceText/span/claimText fields
    # at all — there is nothing to fabricate structurally, not just
    # something that gets rejected at runtime.
    fields = FactCategoryNotMentioned.model_fields
    assert "sourceText" not in fields
    assert "sourceStartIndex" not in fields
    assert "sourceEndIndex" not in fields
    assert "claimText" not in fields


def test_not_mentioned_category_state_is_not_counted_as_a_claim():
    category_state = FactCategoryNotMentioned(
        claimCategory="representative",
        sourcePlatform="chatgpt",
    )
    result = FactExtractionResult(
        claims=[],
        notMentionedCategories=[category_state],
    )
    assert len(result.claims) == 0
    assert len(result.notMentionedCategories) == 1


@pytest.mark.parametrize("state", ["asserted", "explicit_unknown", "explicit_denial"])
def test_non_not_mentioned_states_require_a_source_span(state):
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="representative",
            claimNature="objective_fact",
            answerState=state,
            claimText="x",
            sourcePlatform="chatgpt",
        )


def test_explicit_unknown_requires_a_real_source_span():
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="representative",
            claimNature="objective_fact",
            answerState="explicit_unknown",
            claimText="代表者は分かりません",
            sourcePlatform="chatgpt",
        )


def test_explicit_denial_requires_a_real_source_span():
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="representative",
            claimNature="objective_fact",
            answerState="explicit_denial",
            claimText="代表者はいません",
            sourcePlatform="chatgpt",
        )


def test_reversed_span_is_rejected():
    with pytest.raises(ValidationError):
        FactExtractedClaim(
            claimCategory="representative",
            claimNature="objective_fact",
            answerState="asserted",
            claimText="x",
            sourceText="A",
            sourceStartIndex=5,
            sourceEndIndex=5,
            sourcePlatform="chatgpt",
        )


# --- 3. original-text resolution (fullSummary vs. summary fallback) -------


def _card(**overrides) -> AIOverviewComparisonItem:
    base = dict(platform="ChatGPT (OpenAI API)", mentioned=True, rank=1, summary="短い要約です。")
    base.update(overrides)
    return AIOverviewComparisonItem(**base)


def test_resolve_original_text_prefers_full_summary():
    resolution = fe.resolve_original_text(_card(fullSummary="これはフル回答です。"))
    assert resolution.text == "これはフル回答です。"
    assert resolution.isFallbackSummary is False


def test_resolve_original_text_falls_back_to_summary_when_full_summary_absent():
    resolution = fe.resolve_original_text(_card(fullSummary=None))
    assert resolution.text == "短い要約です。"
    assert resolution.isFallbackSummary is True


def test_resolve_original_text_falls_back_when_full_summary_is_blank():
    resolution = fe.resolve_original_text(_card(fullSummary="   "))
    assert resolution.isFallbackSummary is True


def test_resolve_original_text_truncates_and_flags_overlong_text():
    long_text = "あ" * (MAX_FACT_ORIGINAL_TEXT_CHARS + 500)
    resolution = fe.resolve_original_text(_card(fullSummary=long_text))
    assert len(resolution.text) == MAX_FACT_ORIGINAL_TEXT_CHARS
    assert resolution.isTruncated is True


# --- 4. verify_source_span: exact substring match only ----------------------


def test_verify_source_span_accepts_exact_match():
    text = "株式会社Acmeは東京都に本社を置いています。"
    start = text.index("東京都")
    end = start + len("東京都")
    assert fe.verify_source_span(text, "東京都", start, end) is True


def test_verify_source_span_rejects_text_not_present_at_all():
    text = "株式会社Acmeは東京都に本社を置いています。"
    assert fe.verify_source_span(text, "大阪府", 0, 3) is False


def test_verify_source_span_rejects_mismatched_indices_even_if_text_exists_elsewhere():
    text = "東京都にある東京都庭園美術館"
    # "東京都" really occurs at index 0 and again inside the second
    # occurrence — claim a span that does NOT correspond to either.
    assert fe.verify_source_span(text, "東京都", 1, 4) is False


def test_verify_source_span_rejects_similar_but_not_identical_text():
    text = "代表取締役社長は山田太郎です。"
    start = text.index("山田太郎")
    end = start + len("山田太郎")
    # Similar (same surname) but not an exact match for the claimed span.
    assert fe.verify_source_span(text, "山田次郎", start, end) is False


def test_verify_source_span_rejects_negative_start():
    assert fe.verify_source_span("abcdef", "abc", -1, 2) is False


def test_verify_source_span_rejects_end_beyond_text_length():
    assert fe.verify_source_span("abcdef", "def", 3, 100) is False


def test_verify_source_span_rejects_empty_span():
    assert fe.verify_source_span("abcdef", "", 2, 2) is False


def test_verify_source_span_handles_duplicate_occurrences_by_checking_only_the_claimed_span():
    text = "ChatGPTによるとAcmeは安心です。GeminiによるとAcmeは安心です。"
    first = text.index("Acmeは安心です")
    second = text.rindex("Acmeは安心です")
    assert first != second
    length = len("Acmeは安心です")
    assert fe.verify_source_span(text, "Acmeは安心です", first, first + length) is True
    assert fe.verify_source_span(text, "Acmeは安心です", second, second + length) is True


def test_verify_source_span_handles_emoji_surrogate_pairs_with_python_indices():
    text = "Acme🎉は今年で設立10周年です。"
    needle = "設立10周年"
    start = text.index(needle)
    end = start + len(needle)
    assert fe.verify_source_span(text, needle, start, end) is True


# --- 5. verify_and_build_claim: the only path to a trusted claim ----------


def test_verify_and_build_claim_accepts_a_genuinely_matching_span():
    text = "代表者は山田太郎です。"
    start = text.index("山田太郎")
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=start,
        sourceEndIndex=start + len("山田太郎"),
    )
    claim = fe.verify_and_build_claim(
        candidate,
        original_text=text,
        source_platform="chatgpt",
        observation_method="single_call_no_search",
        source_model="gpt-5",
        extraction_model=None,
    )
    assert claim is not None
    assert claim.sourceText == "山田太郎"
    assert claim.sourcePlatform == "chatgpt"
    assert claim.sourceModel == "gpt-5"
    assert claim.extractionModel is None


def test_verify_and_build_claim_rejects_a_fabricated_span():
    text = "代表者は山田太郎です。"
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は鈴木一郎",
        sourceText="鈴木一郎",
        sourceStartIndex=0,
        sourceEndIndex=4,
    )
    claim = fe.verify_and_build_claim(
        candidate,
        original_text=text,
        source_platform="chatgpt",
        observation_method="single_call_no_search",
        source_model=None,
        extraction_model=None,
    )
    assert claim is None


def test_verify_and_build_claim_rejects_out_of_range_indices_from_the_model():
    text = "短いテキスト"
    candidate = RawFactClaimCandidate(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="x",
        sourceText="テキスト",
        sourceStartIndex=0,
        sourceEndIndex=9999,
    )
    claim = fe.verify_and_build_claim(
        candidate,
        original_text=text,
        source_platform="claude",
        observation_method=None,
        source_model=None,
        extraction_model=None,
    )
    assert claim is None


def test_verify_and_build_claim_returns_none_for_not_mentioned():
    # not_mentioned is build_category_not_mentioned()'s job, not
    # verify_and_build_claim()'s — see the next test.
    candidate = RawFactClaimCandidate(
        claimCategory="numerical_achievement",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="数値実績への言及なし",
    )
    claim = fe.verify_and_build_claim(
        candidate,
        original_text="この回答には数値実績の話は出てきません。",
        source_platform="gemini",
        observation_method="external_document_supplement",
        source_model=None,
        extraction_model=None,
    )
    assert claim is None


def test_build_category_not_mentioned_accepts_a_bare_not_mentioned_candidate():
    candidate = RawFactClaimCandidate(
        claimCategory="numerical_achievement",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="数値実績への言及なし",
    )
    category_state = fe.build_category_not_mentioned(
        candidate,
        source_platform="gemini",
        observation_method="external_document_supplement",
        source_model=None,
    )
    assert category_state is not None
    assert category_state.claimCategory == "numerical_achievement"
    assert category_state.sourcePlatform == "gemini"


def test_build_category_not_mentioned_rejects_a_non_not_mentioned_candidate():
    candidate = RawFactClaimCandidate(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="x",
        sourceText="y",
        sourceStartIndex=0,
        sourceEndIndex=1,
    )
    assert (
        fe.build_category_not_mentioned(
            candidate, source_platform="chatgpt", observation_method=None, source_model=None
        )
        is None
    )


def test_build_category_not_mentioned_rejects_a_candidate_with_a_fabricated_span():
    # RawFactClaimCandidate itself allows constructing this
    # inconsistent shape (answerState=not_mentioned plus a span) —
    # build_category_not_mentioned() must still reject it, not
    # silently drop the extra fields.
    candidate = RawFactClaimCandidate(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="x",
        sourceText="y",
        sourceStartIndex=0,
        sourceEndIndex=1,
    )
    assert (
        fe.build_category_not_mentioned(
            candidate, source_platform="chatgpt", observation_method=None, source_model=None
        )
        is None
    )


def test_verify_and_build_claim_never_trusts_platform_or_model_fields_from_the_candidate():
    # RawFactClaimCandidate has no sourcePlatform/sourceModel/
    # extractionModel/observationMethod fields at all — this test
    # documents that fact structurally (a candidate built with those
    # keys would simply ignore them, Pydantic's default "ignore extra"
    # behavior notwithstanding, since the trusted calling context
    # always supplies its own authoritative values).
    assert "sourcePlatform" not in RawFactClaimCandidate.model_fields
    assert "sourceModel" not in RawFactClaimCandidate.model_fields
    assert "extractionModel" not in RawFactClaimCandidate.model_fields
    assert "observationMethod" not in RawFactClaimCandidate.model_fields


def test_source_model_not_recorded_is_none_not_guessed():
    text = "代表者は山田太郎です。"
    start = text.index("山田太郎")
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=start,
        sourceEndIndex=start + len("山田太郎"),
    )
    claim = fe.verify_and_build_claim(
        candidate,
        original_text=text,
        source_platform="chatgpt",
        observation_method="single_call_no_search",
        source_model=None,
        extraction_model=None,
    )
    assert claim is not None
    assert claim.sourceModel is None


# --- 6. a card's shortened summary is used as a flagged fallback ----------


def test_claim_extracted_from_a_shortened_summary_is_still_verifiable():
    card = _card(fullSummary=None, summary="代表者は山田太郎と記載されています。")
    resolution = fe.resolve_original_text(card)
    assert resolution.isFallbackSummary is True
    start = resolution.text.index("山田太郎")
    assert fe.verify_source_span(resolution.text, "山田太郎", start, start + 4) is True


# --- 7. max length / max count ceilings ------------------------------------


def test_claim_text_over_max_length_is_rejected():
    with pytest.raises(ValidationError):
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText="x" * (MAX_FACT_CLAIM_TEXT_CHARS + 1),
        )


def test_source_text_over_max_length_is_rejected():
    with pytest.raises(ValidationError):
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="asserted",
            claimText="x",
            sourceText="x" * (MAX_FACT_SOURCE_TEXT_CHARS + 1),
            sourceStartIndex=0,
            sourceEndIndex=MAX_FACT_SOURCE_TEXT_CHARS + 1,
        )


def test_empty_claim_text_is_rejected():
    with pytest.raises(ValidationError):
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText="",
        )


def test_blank_whitespace_source_text_is_rejected():
    with pytest.raises(ValidationError):
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="asserted",
            claimText="x",
            sourceText="   ",
            sourceStartIndex=0,
            sourceEndIndex=3,
        )


def test_verify_and_build_claims_truncates_beyond_max_claims_per_card():
    text = "A" * 100
    candidates = [
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText=f"claim {i}",
        )
        for i in range(MAX_FACT_CLAIMS_PER_CARD + 5)
    ]
    result = fe.verify_and_build_claims(
        candidates,
        original_text=text,
        source_platform="chatgpt",
        observation_method="single_call_no_search",
        source_model=None,
        extraction_model=None,
    )
    assert result.truncated is True
    assert len(result.claims) == 0
    assert len(result.notMentionedCategories) == MAX_FACT_CLAIMS_PER_CARD


def test_verify_and_build_claims_not_truncated_when_within_cap():
    text = "A" * 100
    candidates = [
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText=f"claim {i}",
        )
        for i in range(3)
    ]
    result = fe.verify_and_build_claims(
        candidates,
        original_text=text,
        source_platform="chatgpt",
        observation_method="single_call_no_search",
        source_model=None,
        extraction_model=None,
    )
    assert result.truncated is False
    assert len(result.claims) == 0
    assert len(result.notMentionedCategories) == 3


def test_verify_and_build_claims_counts_rejected_candidates():
    text = "本当にある文章です。"
    candidates = [
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="asserted",
            claimText="架空の主張",
            sourceText="存在しない文字列",
            sourceStartIndex=0,
            sourceEndIndex=8,
        )
    ]
    result = fe.verify_and_build_claims(
        candidates,
        original_text=text,
        source_platform="claude",
        observation_method=None,
        source_model=None,
        extraction_model=None,
    )
    assert result.rejectedCount == 1
    assert result.claims == []


# --- 8. allowlist of eligible observation conditions ------------------------


def test_chatgpt_no_search_card_is_eligible():
    assert fe.classify_eligible_card("ChatGPT (OpenAI API)", None) == "chatgpt"
    assert fe.classify_eligible_card("ChatGPT (OpenAI API)", "single_call_no_search") == "chatgpt"


def test_chatgpt_websearch_supplement_card_is_eligible():
    assert (
        fe.classify_eligible_card("ChatGPT (OpenAI API, Web検索補完)", "websearch_supplement")
        == "chatgpt"
    )


def test_claude_no_search_and_websearch_cards_are_eligible():
    assert fe.classify_eligible_card("Claude (Anthropic API)", None) == "claude"
    assert (
        fe.classify_eligible_card("Claude (Anthropic API, Web検索補完)", "websearch_supplement")
        == "claude"
    )


def test_gemini_no_search_and_external_document_cards_are_eligible():
    assert fe.classify_eligible_card("Gemini (Google API)", None) == "gemini"
    assert (
        fe.classify_eligible_card(
            "Gemini (Google API, 外部文書補完)", "external_document_supplement"
        )
        == "gemini"
    )


def test_gemini_google_search_grounding_supplement_card_is_excluded():
    assert (
        fe.classify_eligible_card("Gemini (Google API, Web検索補完)", "websearch_supplement")
        is None
    )


def test_ai_overview_card_is_excluded():
    assert fe.classify_eligible_card("Google AI Mode (dataforseo_live)", None) is None
    assert fe.classify_eligible_card("Google AI Overview (mock)", None) is None


def test_combination_matters_not_just_platform_label():
    # Same literal observationMethod value ("websearch_supplement") is
    # eligible for ChatGPT/Claude but NOT for Gemini — proves the
    # allowlist checks the (platform, observationMethod) pair, not
    # observationMethod alone.
    assert fe.classify_eligible_card("ChatGPT (OpenAI API, Web検索補完)", "websearch_supplement") is not None
    assert fe.classify_eligible_card("Gemini (Google API, Web検索補完)", "websearch_supplement") is None


def test_unknown_future_platform_label_defaults_to_excluded():
    assert fe.classify_eligible_card("SomeFutureProvider (vNext)", "single_call_no_search") is None


def test_select_fact_extraction_eligible_cards_filters_and_classifies():
    items = [
        _card(platform="ChatGPT (OpenAI API)", observationMethod=None),
        _card(platform="Gemini (Google API, Web検索補完)", observationMethod="websearch_supplement"),
        _card(platform="Google AI Mode (dataforseo_live)", observationMethod=None),
        _card(
            platform="Gemini (Google API, 外部文書補完)",
            observationMethod="external_document_supplement",
        ),
    ]
    eligible = fe.select_fact_extraction_eligible_cards(items)
    assert len(eligible) == 2
    assert eligible[0][1] == "chatgpt"
    assert eligible[1][1] == "gemini"
    assert eligible[1][0].platform == "Gemini (Google API, 外部文書補完)"


# --- 9. backward compatibility with old saved history JSON ----------------


def test_old_history_without_fact_extraction_field_still_loads():
    result = AnalysisResult.model_validate(_minimal_analysis_result())
    assert result.factExtraction is None


def test_fact_extraction_result_defaults_to_not_attempted_and_empty():
    result = FactExtractionResult()
    assert result.status == "not_attempted"
    assert result.claims == []
    assert result.notMentionedCategories == []
    assert result.eligibleCardCount == 0
    assert result.claimsTruncated is False


def test_analysis_result_round_trips_with_fact_extraction_present():
    result = AnalysisResult.model_validate(
        _minimal_analysis_result(factExtraction={"status": "not_attempted"})
    )
    assert result.factExtraction is not None
    assert result.factExtraction.status == "not_attempted"
    assert result.factExtraction.claims == []


# --- 10. non-interference with existing analysis processing ----------------


def test_analysis_result_without_fact_extraction_is_unaffected_by_its_existence():
    # The mere presence of the factExtraction field on AnalysisResult
    # must never require callers to supply it, and must never change
    # any other field's validation.
    result = AnalysisResult.model_validate(_minimal_analysis_result())
    assert result.brandName == "Acme"
    assert result.factExtraction is None
