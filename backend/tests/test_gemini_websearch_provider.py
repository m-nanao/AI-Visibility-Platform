"""Tests for services/gemini_websearch_provider.py's
attempt_gemini_websearch_supplement() (Task 6-D-4B-2,
feature/gemini-websearch-supplement).

Never touches a real database or calls a real Gemini API. Mirrors
tests/test_claude_websearch_provider.py's structure, plus the one
extra gate this provider alone has: the model allowlist.
"""

import pytest

import services.gemini_websearch_provider as gwp
from services.gemini_websearch_client import (
    GeminiWebsearchGroundingChunk,
    GeminiWebsearchGroundingSupport,
    GeminiWebsearchObservationResult,
    GeminiWebsearchReference,
)
from services.websearch_quota_reservation import (
    AnalysisQuotaExceededError,
    WebsearchQuotaAccessDeniedError,
    WebsearchQuotaAlreadyReservedError,
    WebsearchQuotaLeaseInvalidError,
    WebsearchQuotaReservation,
    WebsearchQuotaReservationError,
    WebsearchQuotaRunNotFoundError,
    WebsearchQuotaRunNotRunningError,
)

ANALYSIS_RUN_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"


def _base_kwargs(**overrides):
    base = dict(
        brand_name="Acme",
        recognition_level="unidentified",
        analysis_run_id=ANALYSIS_RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    base.update(overrides)
    return base


def _enable(monkeypatch, *, enforcement_enabled=True):
    monkeypatch.setattr(gwp, "is_gemini_websearch_supplement_enabled", lambda: True)
    monkeypatch.setattr(
        gwp,
        "load_analyze_quota_settings",
        lambda: type("S", (), {"enforcement_enabled": enforcement_enabled})(),
    )


def _mock_credentials(monkeypatch, *, configured=True, model="gemini-2.5-flash"):
    monkeypatch.setattr(gwp, "get_gemini_credentials", lambda: object() if configured else None)
    monkeypatch.setattr(gwp, "get_gemini_websearch_model", lambda: model)
    monkeypatch.setattr(gwp, "get_gemini_websearch_max_output_tokens", lambda: 2000)


def _mock_reservation_success(monkeypatch):
    calls = []

    def _reserve(**kwargs):
        calls.append(kwargs)
        return WebsearchQuotaReservation(
            analysis_run_id=kwargs["analysis_run_id"],
            project_id=kwargs["project_id"],
            metric=kwargs["metric"],
        )

    monkeypatch.setattr(gwp, "reserve_websearch_quota_for_analysis_run", _reserve)
    return calls


def _mock_reservation_raises(monkeypatch, exc):
    def _reserve(**kwargs):
        raise exc

    monkeypatch.setattr(gwp, "reserve_websearch_quota_for_analysis_run", _reserve)


def _mock_fetch(monkeypatch, result: GeminiWebsearchObservationResult):
    calls = []

    def _fetch(credentials, brand_name, official_url, *, model, max_output_tokens):
        calls.append(
            {
                "brand_name": brand_name,
                "official_url": official_url,
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        return result

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", _fetch)
    return calls


# --- gate 1: recognition_level is None -----------------------------------


def test_not_attempted_when_recognition_level_is_none(monkeypatch):
    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs(recognition_level=None))
    assert item is None
    assert info.status == "not_attempted"


# --- gate 2: feature disabled ---------------------------------------------


def test_disabled_when_feature_flag_is_off(monkeypatch):
    monkeypatch.setattr(gwp, "is_gemini_websearch_supplement_enabled", lambda: False)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "disabled"
    assert info.recognitionLevelAtTrigger == "unidentified"


# --- gate 3: quota enforcement disabled -----------------------------------


def test_skipped_when_quota_enforcement_is_disabled(monkeypatch):
    _enable(monkeypatch, enforcement_enabled=False)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "quota_enforcement_disabled"


# --- gate 4: recognition level eligibility --------------------------------


@pytest.mark.parametrize("level", ["partial_knowledge", "unidentified", "name_inference_only"])
def test_eligible_recognition_levels_proceed_past_this_gate(monkeypatch, level):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=True, reason="ok", searched=True, summary="s"),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs(recognition_level=level))

    assert len(reserve_calls) == 1
    assert reserve_calls[0]["metric"] == "google_websearch"
    assert info.status == "real"


@pytest.mark.parametrize("level", ["specific_knowledge", "indeterminate"])
def test_ineligible_recognition_levels_are_rejected_before_any_reservation(monkeypatch, level):
    _enable(monkeypatch)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs(recognition_level=level))

    assert item is None
    assert info.status == "recognition_level_not_eligible"
    assert info.recognitionLevelAtTrigger == level


# --- gate 5: model allowlist (Gemini-specific) ------------------------------


def test_disallowed_model_is_rejected_before_any_credentials_or_reservation_check(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="gemini-3-flash-preview")

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    def fail_if_fetch_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_websearch_observation should not be called")

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", fail_if_fetch_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "model_not_allowed"
    assert info.model == "gemini-3-flash-preview"


def test_allowed_model_passes_this_gate(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="gemini-2.5-flash")
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=True, reason="ok", searched=True, summary="s"),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert info.status == "real"
    assert info.model == "gemini-2.5-flash"


def test_model_rejection_never_falls_back_to_the_allowed_model(monkeypatch):
    """Task 6-D-4B-2: a disallowed configured model must be rejected
    outright, never silently swapped for gemini-2.5-flash."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="gemini-4-argon")

    fetch_calls = []

    def fake_fetch(*args, **kwargs):
        fetch_calls.append(kwargs)
        return GeminiWebsearchObservationResult(success=True, reason="ok")

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", fake_fetch)
    monkeypatch.setattr(
        gwp,
        "reserve_websearch_quota_for_analysis_run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not reserve")),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "model_not_allowed"
    assert len(fetch_calls) == 0


# --- gate 6: credentials ---------------------------------------------------


def test_skipped_when_no_credentials_configured(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, configured=False)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "no_credentials"


# --- quota reservation outcomes -------------------------------------------


def test_quota_exceeded_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(
        monkeypatch,
        AnalysisQuotaExceededError(
            scope_type="project",
            scope_id=PROJECT_ID,
            metric="google_websearch",
            period_type="daily",
            period_start=None,
            limit=0,
        ),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_websearch_observation should not be called")

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", fail_if_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "quota_rejected"


def test_already_reserved_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaAlreadyReservedError("already reserved"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_websearch_observation should not be called")

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", fail_if_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "already_reserved"


@pytest.mark.parametrize(
    "exc",
    [
        WebsearchQuotaRunNotFoundError("not found"),
        WebsearchQuotaRunNotRunningError("not running"),
        WebsearchQuotaAccessDeniedError("denied"),
        WebsearchQuotaLeaseInvalidError("lease invalid"),
    ],
)
def test_run_project_user_rejections_are_reported_as_run_invalid(monkeypatch, exc):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, exc)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "run_invalid"


def test_reservation_db_error_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaReservationError("db down"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_websearch_observation should not be called")

    monkeypatch.setattr(gwp, "fetch_gemini_websearch_observation", fail_if_called)

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "reservation_error"


# --- API failure after a successful reservation ----------------------------


def test_api_failure_after_reservation_is_unavailable_quota_not_refunded(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=False, reason="Gemini API down"),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "unavailable"
    assert info.reason == "Gemini API down"
    assert info.model == "gemini-2.5-flash"


# --- Task 6-D-5C-4G: async_worker_id wiring --------------------------------


def test_async_worker_id_defaults_to_none_and_is_passed_through(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(monkeypatch, GeminiWebsearchObservationResult(success=True, reason="ok", searched=True))

    gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert reserve_calls[0]["async_worker_id"] is None


def test_async_worker_id_is_passed_through_when_given(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(monkeypatch, GeminiWebsearchObservationResult(success=True, reason="ok", searched=True))

    gwp.attempt_gemini_websearch_supplement(**_base_kwargs(async_worker_id="worker-1"))

    assert reserve_calls[0]["async_worker_id"] == "worker-1"


# --- success path ----------------------------------------------------------


def test_success_builds_an_item_with_the_stable_observation_method(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            grounding_metadata_present=True,
            web_search_queries_count=1,
            mentioned=True,
            summary="Acme summary",
            full_summary="Acme full summary",
            references=[GeminiWebsearchReference(uri="https://acme.example.com", title="Acme")],
        ),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item is not None
    assert item.observationMethod == "websearch_supplement"
    assert item.platform == gwp.GEMINI_WEBSEARCH_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.summary == "Acme summary"
    assert item.fullSummary == "Acme full summary"
    assert item.references is not None
    assert item.references[0].url == "https://acme.example.com"
    assert item.references[0].title == "Acme"
    assert item.model == "gemini-2.5-flash"
    assert info.status == "real"
    assert info.searched is True
    assert info.groundingMetadataPresent is True
    assert info.webSearchQueriesCount == 1
    assert info.recognitionLevelAtTrigger == "unidentified"


def test_success_with_truncated_result_surfaces_truncation_on_the_item(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True,
            reason="ok",
            summary="partial",
            is_truncated=True,
            finish_reason="MAX_TOKENS",
            note="truncated note",
        ),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.isTruncated is True
    assert item.finishReason == "MAX_TOKENS"
    assert item.note == "truncated note"
    assert info.status == "real"


def test_success_surfaces_full_summary_truncated_independently_of_is_truncated(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True,
            reason="ok",
            summary="s",
            full_summary="truncated for storage…",
            is_truncated=False,
            full_summary_truncated=True,
        ),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.isTruncated is False
    assert item.fullSummaryTruncated is True


def test_success_propagates_grounding_chunks_and_supports_with_index_correspondence(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True,
            reason="ok",
            summary="s",
            references=[GeminiWebsearchReference(uri="https://acme.example.com/about", title="About")],
            citations_truncated=False,
            grounding_chunks=[
                GeminiWebsearchGroundingChunk(uri="https://acme.example.com/about", title="About", domain="acme.example.com"),
                GeminiWebsearchGroundingChunk(uri="https://other.example.com", title="Other"),
            ],
            grounding_chunks_total_count=2,
            grounding_supports=[
                GeminiWebsearchGroundingSupport(
                    start_index=0,
                    end_index=10,
                    text="Acme makes",
                    grounding_chunk_indices=[1, 0],
                    confidence_scores=[0.9, 0.8],
                )
            ],
            grounding_supports_total_count=1,
        ),
    )

    item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.references == [gwp.AIOverviewReference(url="https://acme.example.com/about", title="About")]
    assert item.geminiGroundingChunks is not None
    assert len(item.geminiGroundingChunks) == 2
    assert item.geminiGroundingChunks[1].uri == "https://other.example.com"
    assert item.geminiGroundingChunksTotalCount == 2
    assert item.geminiGroundingSupports is not None
    assert item.geminiGroundingSupports[0].groundingChunkIndices == [1, 0]
    assert item.geminiGroundingSupports[0].confidenceScores == [0.9, 0.8]
    assert item.geminiGroundingSupportsTotalCount == 1
    assert item.citationsTruncated is False


def test_success_with_no_grounding_data_leaves_the_new_fields_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=True, reason="ok", searched=False, summary="s"),
    )

    item, _info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.references is None
    assert item.geminiGroundingChunks is None
    assert item.geminiGroundingChunksTotalCount is None
    assert item.geminiGroundingSupports is None
    assert item.geminiGroundingSupportsTotalCount is None


def test_success_propagates_rendered_content_and_its_truncated_flag(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True,
            reason="ok",
            summary="s",
            rendered_content="<div>...</div>",
            rendered_content_truncated=False,
        ),
    )

    item, _info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.geminiSearchEntryPointRenderedContent == "<div>...</div>"
    assert item.geminiSearchEntryPointRenderedContentTruncated is False


def test_success_with_no_rendered_content_leaves_its_truncated_flag_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=True, reason="ok", summary="s", rendered_content=None),
    )

    item, _info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert item.geminiSearchEntryPointRenderedContent is None
    assert item.geminiSearchEntryPointRenderedContentTruncated is None


# --- tri-state searched propagation ----------------------------------------


def test_searched_none_is_propagated_as_is_not_coerced_to_a_boolean(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(
            success=True, reason="ok", searched=None, grounding_metadata_present=True, summary="s"
        ),
    )

    _item, info = gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert info.searched is None
    assert info.groundingMetadataPresent is True


# --- official_url is never a caller-supplied guess --------------------------


def test_official_url_is_always_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(
        monkeypatch,
        GeminiWebsearchObservationResult(success=True, reason="ok", summary="s"),
    )

    gwp.attempt_gemini_websearch_supplement(**_base_kwargs())

    assert fetch_calls[0]["official_url"] is None


# --- non-interference with the OpenAI/Claude websearch supplements ---------


def test_module_never_imports_or_calls_chatgpt_or_claude_websearch_functions():
    assert not hasattr(gwp, "fetch_chatgpt_websearch_observation")
    assert not hasattr(gwp, "attempt_chatgpt_websearch_supplement")
    assert not hasattr(gwp, "fetch_claude_websearch_observation")
    assert not hasattr(gwp, "attempt_claude_websearch_supplement")
