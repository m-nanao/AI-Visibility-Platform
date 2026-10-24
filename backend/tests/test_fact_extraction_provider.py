"""Tests for services/fact_extraction_provider.py's
attempt_fact_extraction() (Task 6-D-5C-2,
feature/claude-fact-extraction-mvp).

Never touches a real database or calls a real Claude API.
"""

import pytest

import services.fact_extraction_provider as fep
from models import AIOverviewComparisonItem
from services.chatgpt_provider import CHATGPT_PLATFORM_LABEL
from services.chatgpt_websearch_provider import CHATGPT_WEBSEARCH_PLATFORM_LABEL
from services.claude_settings import ClaudeCredentials
from services.fact_extraction_client import FactExtractionClientResult
from services.websearch_quota_reservation import (
    AnalysisQuotaExceededError,
    WebsearchQuotaAccessDeniedError,
    WebsearchQuotaAlreadyReservedError,
    WebsearchQuotaLeaseInvalidError,
    WebsearchQuotaReservationError,
    WebsearchQuotaRunNotFoundError,
    WebsearchQuotaRunNotRunningError,
)
from models import RawFactClaimCandidate

ANALYSIS_RUN_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"


def _chatgpt_no_search_card(**overrides) -> AIOverviewComparisonItem:
    base = dict(
        platform=CHATGPT_PLATFORM_LABEL,
        mentioned=True,
        rank=1,
        summary="短い要約です。",
        fullSummary="代表者は山田太郎です。主要事業はSEO支援です。",
        observationMethod=None,
        model="gpt-5",
    )
    base.update(overrides)
    return AIOverviewComparisonItem(**base)


def _base_kwargs(**overrides):
    base = dict(
        brand_name="Acme",
        ai_overview_comparison=[_chatgpt_no_search_card()],
        analysis_run_id=ANALYSIS_RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    base.update(overrides)
    return base


def _enable(monkeypatch, *, enforcement_enabled=True):
    monkeypatch.setattr(fep, "is_fact_extraction_enabled", lambda: True)
    monkeypatch.setattr(
        fep,
        "load_analyze_quota_settings",
        lambda: type("S", (), {"enforcement_enabled": enforcement_enabled})(),
    )


def _mock_credentials(monkeypatch, *, configured=True, model="claude-sonnet-5-5"):
    monkeypatch.setattr(
        fep, "get_claude_credentials", lambda: ClaudeCredentials(api_key="k") if configured else None
    )
    monkeypatch.setattr(fep, "get_fact_extraction_model", lambda: model)
    monkeypatch.setattr(fep, "get_fact_extraction_max_output_tokens", lambda: 4000)


def _mock_reservation_success(monkeypatch):
    calls = []

    def _reserve(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(fep, "reserve_websearch_quota_for_analysis_run", _reserve)
    return calls


def _mock_reservation_raises(monkeypatch, exc):
    def _reserve(**kwargs):
        raise exc

    monkeypatch.setattr(fep, "reserve_websearch_quota_for_analysis_run", _reserve)


def _mock_fetch(monkeypatch, result: FactExtractionClientResult):
    calls = []

    def _fetch(credentials, brand_name, original_text, *, model, max_output_tokens):
        calls.append(
            {
                "brand_name": brand_name,
                "original_text": original_text,
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        return result

    monkeypatch.setattr(fep, "fetch_fact_extraction", _fetch)
    return calls


def _fully_enabled(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)


# --- scenario 1: feature OFF -> no API call --------------------------------


def test_disabled_feature_flag_makes_no_api_call(monkeypatch):
    monkeypatch.setattr(fep, "is_fact_extraction_enabled", lambda: False)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "disabled"
    assert fetch_calls == []


# --- scenario 3: quota enforcement disabled -> no API call -----------------


def test_quota_enforcement_disabled_makes_no_api_call(monkeypatch):
    _enable(monkeypatch, enforcement_enabled=False)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "quota_enforcement_disabled"
    assert fetch_calls == []


# --- scenario 4: no eligible card -> skip -----------------------------------


def test_no_chatgpt_no_search_card_is_skipped(monkeypatch):
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[]))

    assert result.status == "no_eligible_card"
    assert fetch_calls == []


def test_chatgpt_websearch_supplement_card_alone_is_not_eligible(monkeypatch):
    # Only the websearch-supplement card is present — no plain no-search
    # card — MVP must not fall back to it.
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))
    websearch_card = _chatgpt_no_search_card(
        platform=CHATGPT_WEBSEARCH_PLATFORM_LABEL, observationMethod="websearch_supplement"
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[websearch_card]))

    assert result.status == "no_eligible_card"
    assert fetch_calls == []


def test_gemini_card_alone_is_not_eligible_for_this_mvp(monkeypatch):
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))
    gemini_card = AIOverviewComparisonItem(
        platform="Gemini (Google API)",
        mentioned=True,
        rank=1,
        summary="s",
        fullSummary="代表者は山田太郎です。",
        observationMethod=None,
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[gemini_card]))

    assert result.status == "no_eligible_card"
    assert fetch_calls == []


def test_gemini_google_search_grounding_card_is_never_selected_even_alongside_chatgpt(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(
        monkeypatch, FactExtractionClientResult(success=True, candidates=[])
    )
    grounding_card = AIOverviewComparisonItem(
        platform="Gemini (Google API, Web検索補完)",
        mentioned=True,
        rank=1,
        summary="s",
        fullSummary="グラウンディングされた回答",
        observationMethod="websearch_supplement",
    )

    result = fep.attempt_fact_extraction(
        **_base_kwargs(ai_overview_comparison=[grounding_card, _chatgpt_no_search_card()])
    )

    assert result.status in {"real", "partial"}
    assert len(fetch_calls) == 1
    assert "グラウンディング" not in fetch_calls[0]["original_text"]


# --- scenario 5: no eligible original text -> skip --------------------------


def test_blank_full_summary_and_blank_summary_is_skipped(monkeypatch):
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))
    card = _chatgpt_no_search_card(fullSummary=None, summary="")

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "insufficient_input"
    assert fetch_calls == []


def test_blank_brand_name_is_skipped(monkeypatch):
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs(brand_name="   "))

    assert result.status == "insufficient_input"
    assert fetch_calls == []


# --- scenario 6: char limit exceeded -> skip --------------------------------


def test_overlong_original_text_is_skipped(monkeypatch):
    _fully_enabled(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))
    card = _chatgpt_no_search_card(fullSummary="あ" * 25000)

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "input_too_long"
    assert fetch_calls == []


# --- model allowlist / credentials -----------------------------------------


def test_model_not_on_allowlist_is_skipped(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="claude-not-allowed")
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "model_not_allowed"
    assert fetch_calls == []


def test_missing_credentials_is_skipped(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, configured=False)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "no_credentials"
    assert fetch_calls == []


# --- scenario 7/8: quota reservation gates ----------------------------------


def test_successful_reservation_leads_to_exactly_one_api_request(monkeypatch):
    _fully_enabled(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[]))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert len(reserve_calls) == 1
    assert reserve_calls[0]["metric"] == "fact_extraction"
    assert len(fetch_calls) == 1
    assert result.apiRequestCount == 1


def test_already_reserved_makes_no_api_call(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaAlreadyReservedError())
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "already_reserved"
    assert fetch_calls == []


def test_quota_exceeded_makes_no_api_call(monkeypatch):
    import datetime

    _fully_enabled(monkeypatch)
    _mock_reservation_raises(
        monkeypatch,
        AnalysisQuotaExceededError(
            scope_type="project",
            scope_id=PROJECT_ID,
            metric="fact_extraction",
            period_type="daily",
            period_start=datetime.datetime.now(datetime.timezone.utc),
            limit=0,
        ),
    )
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "quota_rejected"
    assert fetch_calls == []


def test_run_invalid_makes_no_api_call(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaRunNotRunningError())
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "run_invalid"
    assert fetch_calls == []


def test_lease_invalid_is_reported_as_run_invalid_and_makes_no_api_call(monkeypatch):
    """Task 6-D-5C-4G: WebsearchQuotaLeaseInvalidError is handled the
    exact same way as the other run/project/user rejections above —
    no new FactExtractionResult status was added for this case."""
    _fully_enabled(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaLeaseInvalidError())
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "run_invalid"
    assert fetch_calls == []


# --- Task 6-D-5C-4G: async_worker_id wiring --------------------------------


def test_async_worker_id_defaults_to_none_and_is_passed_through(monkeypatch):
    _fully_enabled(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    fep.attempt_fact_extraction(**_base_kwargs())

    assert reserve_calls[0]["async_worker_id"] is None


def test_async_worker_id_is_passed_through_when_given(monkeypatch):
    _fully_enabled(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    fep.attempt_fact_extraction(**_base_kwargs(async_worker_id="worker-1"))

    assert reserve_calls[0]["async_worker_id"] == "worker-1"


def test_reservation_db_error_makes_no_api_call(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaReservationError("db down"))
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "reservation_error"
    assert fetch_calls == []


# --- scenario 9: API failure never raises / never fails the run -----------


def test_api_failure_is_reported_not_raised(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=False, reason="network_error"),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "api_error"
    assert result.apiRequestCount == 1


def test_parse_failure_is_reported_not_raised(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=False, reason="no_json_object_found"),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "parse_error"
    assert result.apiRequestCount == 1


# --- real extraction: span verification is actually applied ---------------


def test_real_extraction_with_a_genuinely_matching_claim(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary="代表者は山田太郎です。")
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "real"
    assert len(result.claims) == 1
    assert result.claims[0].claimId is not None
    assert result.claims[0].sourcePlatform == "chatgpt"
    assert result.claims[0].extractionModel == "claude-sonnet-5-5"


def test_fabricated_span_is_rejected_and_counted(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary="代表者は山田太郎です。")
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は鈴木一郎",
        sourceText="鈴木一郎",
        sourceStartIndex=0,
        sourceEndIndex=4,
    )
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "partial"
    assert result.claims == []
    assert result.rejectedCount == 1


def test_malformed_candidate_count_is_included_in_rejected_count(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary="代表者は山田太郎です。")
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=True, candidates=[], malformed_candidate_count=2),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "partial"
    assert result.rejectedCount == 2


# --- not_mentioned handling --------------------------------------------------


def test_not_mentioned_candidate_goes_to_not_mentioned_categories_not_claims(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary="代表者は山田太郎です。")
    candidate = RawFactClaimCandidate(
        claimCategory="numerical_achievement",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="数値実績の言及なし",
    )
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    # Task 6-D-5C-2A final review: notMentionedCategories alone (no
    # actual claim) must never report "real" — that would overstate
    # this as a substantively successful extraction.
    assert result.status == "partial"
    assert result.claims == []
    assert len(result.notMentionedCategories) == 1
    assert result.notMentionedCategories[0].claimCategory == "numerical_achievement"


def test_real_status_requires_at_least_one_actual_claim_not_just_not_mentioned(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    original_text = "代表者は山田太郎です。"
    card = _chatgpt_no_search_card(fullSummary=original_text)
    real_claim = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    not_mentioned = RawFactClaimCandidate(
        claimCategory="numerical_achievement",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="数値実績の言及なし",
    )
    _mock_fetch(
        monkeypatch, FactExtractionClientResult(success=True, candidates=[real_claim, not_mentioned])
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "real"
    assert len(result.claims) == 1
    assert len(result.notMentionedCategories) == 1


# --- source model / fallback flags are correctly surfaced ------------------


def test_source_model_none_when_card_never_recorded_one(monkeypatch):
    _fully_enabled(monkeypatch)
    card = _chatgpt_no_search_card(model=None, fullSummary=None, summary="")
    fetch_calls = _mock_fetch(monkeypatch, FactExtractionClientResult(success=True))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.sourceModel is None
    assert fetch_calls == []


def test_fallback_to_summary_is_recorded(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary=None, summary="代表者は山田太郎です。")
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[]))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.sourceFallbackToSummary is True


# --- claims and notMentionedCategories never overlap -----------------------


def test_claims_truncated_flag_propagates_from_the_batch_cap(monkeypatch):
    import models as m

    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    card = _chatgpt_no_search_card(fullSummary="代表者は山田太郎です。")
    candidates = [
        RawFactClaimCandidate(
            claimCategory="business",
            claimNature="objective_fact",
            answerState="not_mentioned",
            claimText=f"claim {i}",
        )
        for i in range(m.MAX_FACT_CLAIMS_PER_CARD + 3)
    ]
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=candidates))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.claimsTruncated is True


def test_same_category_claim_and_not_mentioned_never_both_appear(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    original_text = "代表者は山田太郎です。"
    card = _chatgpt_no_search_card(fullSummary=original_text)

    real_claim = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    conflicting_not_mentioned = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="not_mentioned",
        claimText="代表者への言及なし",
    )
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(
            success=True, candidates=[real_claim, conflicting_not_mentioned]
        ),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    claim_categories = {c.claimCategory for c in result.claims}
    not_mentioned_categories = {c.claimCategory for c in result.notMentionedCategories}
    assert claim_categories & not_mentioned_categories == set()
    assert "representative" in claim_categories
    assert "representative" not in not_mentioned_categories
    assert result.rejectedCount == 1


# --- Task 6-D-5C-2A: max_tokens truncation / unexpected stop_reason -------


def test_max_tokens_truncation_is_reported_as_parse_error_not_success(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=False, reason="max_tokens_truncated"),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "parse_error"
    assert "max_tokens_truncated" in result.note
    assert result.apiRequestCount == 1


def test_unexpected_stop_reason_is_reported_as_parse_error_not_success(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=False, reason="unexpected_stop_reason"),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs())

    assert result.status == "parse_error"


# --- mixed outcome: some candidates valid, some rejected -------------------


def test_mixed_valid_and_invalid_candidates_is_real_not_partial(monkeypatch):
    """Task 6-D-5C-2A review item 3: when some candidates survive
    verification and others don't, the overall status is "real" (at
    least one usable claim was found) — "partial" is reserved for the
    case where literally nothing survived. rejectedCount still
    reflects the ones that didn't."""
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    original_text = "代表者は山田太郎です。"
    card = _chatgpt_no_search_card(fullSummary=original_text)

    valid_claim = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    fabricated_claim = RawFactClaimCandidate(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="架空の主張",
        sourceText="存在しない文字列",
        sourceStartIndex=0,
        sourceEndIndex=8,
    )
    _mock_fetch(
        monkeypatch,
        FactExtractionClientResult(success=True, candidates=[valid_claim, fabricated_claim]),
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "real"
    assert len(result.claims) == 1
    assert result.rejectedCount == 1


# --- claimId does not collide across runs/categories -----------------------


def test_claim_id_differs_across_different_analysis_runs(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    original_text = "代表者は山田太郎です。"
    card = _chatgpt_no_search_card(fullSummary=original_text)
    candidate = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=4,
        sourceEndIndex=8,
    )
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))

    result_a = fep.attempt_fact_extraction(
        **_base_kwargs(ai_overview_comparison=[card], analysis_run_id="11111111-1111-1111-1111-111111111111")
    )
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=True, candidates=[candidate]))
    result_b = fep.attempt_fact_extraction(
        **_base_kwargs(ai_overview_comparison=[card], analysis_run_id="22222222-2222-2222-2222-222222222222")
    )

    assert result_a.claims[0].claimId != result_b.claims[0].claimId


def test_claim_id_differs_across_categories_in_the_same_run(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    original_text = "代表者は山田太郎です。主要事業はSEO支援です。"
    card = _chatgpt_no_search_card(fullSummary=original_text)
    rep_claim = RawFactClaimCandidate(
        claimCategory="representative",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="代表者は山田太郎",
        sourceText="山田太郎",
        sourceStartIndex=original_text.index("山田太郎"),
        sourceEndIndex=original_text.index("山田太郎") + 4,
    )
    business_claim = RawFactClaimCandidate(
        claimCategory="business",
        claimNature="objective_fact",
        answerState="asserted",
        claimText="主要事業はSEO支援",
        sourceText="SEO支援",
        sourceStartIndex=original_text.index("SEO支援"),
        sourceEndIndex=original_text.index("SEO支援") + 5,
    )
    _mock_fetch(
        monkeypatch, FactExtractionClientResult(success=True, candidates=[rep_claim, business_claim])
    )

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    ids = [c.claimId for c in result.claims]
    assert len(ids) == 2
    assert len(set(ids)) == 2


def test_claim_id_is_stable_for_identical_inputs(monkeypatch):
    """Redisplaying/re-deriving the same claim from the same run must
    produce the same id, not a fresh random one."""
    id_1 = fep._deterministic_claim_id("run-1", "chatgpt", None, "representative", 4, 8)
    id_2 = fep._deterministic_claim_id("run-1", "chatgpt", None, "representative", 4, 8)
    assert id_1 == id_2


# --- secrets / original text never leak into FactExtractionResult.note ----


def test_note_never_exposes_the_original_text_or_api_key(monkeypatch):
    _fully_enabled(monkeypatch)
    _mock_reservation_success(monkeypatch)
    secret_text = "代表者は山田太郎です。これは機密情報を含む原文です。"
    card = _chatgpt_no_search_card(fullSummary=secret_text)
    _mock_fetch(monkeypatch, FactExtractionClientResult(success=False, reason="network_error"))

    result = fep.attempt_fact_extraction(**_base_kwargs(ai_overview_comparison=[card]))

    assert result.status == "api_error"
    assert secret_text not in (result.note or "")
    assert "k" != (result.note or "")  # sanity: note is not just the raw credential
