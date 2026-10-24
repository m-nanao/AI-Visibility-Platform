"""Tests for services/chatgpt_websearch_provider.py's
attempt_chatgpt_websearch_supplement() (Task 6-D-3,
feature/chatgpt-websearch-supplement).

Never touches a real database or calls a real OpenAI API:
reserve_websearch_quota_for_analysis_run()/
fetch_chatgpt_websearch_observation() are monkeypatched at this
module's own namespace (both are imported by name into
services.chatgpt_websearch_provider, so patching the name there is
what actually takes effect).
"""

import pytest

import services.chatgpt_websearch_provider as cwp
from services.chatgpt_websearch_client import (
    ChatGptWebsearchObservationResult,
    WebsearchCitation,
    WebsearchCitationAnnotation,
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
    monkeypatch.setattr(cwp, "is_chatgpt_websearch_supplement_enabled", lambda: True)
    monkeypatch.setattr(
        cwp,
        "load_analyze_quota_settings",
        lambda: type("S", (), {"enforcement_enabled": enforcement_enabled})(),
    )


def _mock_credentials(monkeypatch, *, configured=True):
    monkeypatch.setattr(
        cwp, "get_chatgpt_credentials", lambda: object() if configured else None
    )
    monkeypatch.setattr(
        cwp, "get_chatgpt_settings", lambda: type("S", (), {"model": "gpt-5-mini", "max_output_tokens": 700})()
    )


def _mock_reservation_success(monkeypatch):
    calls = []

    def _reserve(**kwargs):
        calls.append(kwargs)
        return WebsearchQuotaReservation(
            analysis_run_id=kwargs["analysis_run_id"],
            project_id=kwargs["project_id"],
            metric=kwargs["metric"],
        )

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", _reserve)
    return calls


def _mock_reservation_raises(monkeypatch, exc):
    def _reserve(**kwargs):
        raise exc

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", _reserve)


def _mock_fetch(monkeypatch, result: ChatGptWebsearchObservationResult):
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

    monkeypatch.setattr(cwp, "fetch_chatgpt_websearch_observation", _fetch)
    return calls


# --- gate 1: recognition_level is None -----------------------------------


def test_not_attempted_when_recognition_level_is_none(monkeypatch):
    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs(recognition_level=None))
    assert item is None
    assert info.status == "not_attempted"


# --- gate 2: feature disabled ---------------------------------------------


def test_disabled_when_feature_flag_is_off(monkeypatch):
    monkeypatch.setattr(cwp, "is_chatgpt_websearch_supplement_enabled", lambda: False)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "disabled"
    assert info.recognitionLevelAtTrigger == "unidentified"


# --- gate 3: quota enforcement disabled -----------------------------------


def test_skipped_when_quota_enforcement_is_disabled(monkeypatch):
    _enable(monkeypatch, enforcement_enabled=False)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

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
        ChatGptWebsearchObservationResult(success=True, reason="ok", searched=True, summary="s"),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs(recognition_level=level))

    assert len(reserve_calls) == 1
    assert info.status == "real"


@pytest.mark.parametrize("level", ["specific_knowledge", "indeterminate"])
def test_ineligible_recognition_levels_are_rejected_before_any_reservation(monkeypatch, level):
    _enable(monkeypatch)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs(recognition_level=level))

    assert item is None
    assert info.status == "recognition_level_not_eligible"
    assert info.recognitionLevelAtTrigger == level


def test_specific_knowledge_and_indeterminate_have_distinguishable_reasons(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setattr(
        cwp,
        "reserve_websearch_quota_for_analysis_run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not reserve")),
    )

    _, info_specific = cwp.attempt_chatgpt_websearch_supplement(
        **_base_kwargs(recognition_level="specific_knowledge")
    )
    _, info_indeterminate = cwp.attempt_chatgpt_websearch_supplement(
        **_base_kwargs(recognition_level="indeterminate")
    )

    assert info_specific.reason != info_indeterminate.reason
    assert "indeterminate" in info_indeterminate.reason or "parse" in info_indeterminate.reason.lower() or "判定" in info_indeterminate.reason


# --- gate 5: credentials ---------------------------------------------------


def test_skipped_when_no_credentials_configured(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, configured=False)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

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
            metric="openai_websearch",
            period_type="daily",
            period_start=None,
            limit=0,
        ),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_chatgpt_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_chatgpt_websearch_observation", fail_if_called)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "quota_rejected"


def test_already_reserved_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(
        monkeypatch, WebsearchQuotaAlreadyReservedError("already reserved")
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_chatgpt_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_chatgpt_websearch_observation", fail_if_called)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

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

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "run_invalid"


def test_reservation_db_error_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaReservationError("db down"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_chatgpt_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_chatgpt_websearch_observation", fail_if_called)

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "reservation_error"


# --- Task 6-D-5C-4G: async_worker_id wiring --------------------------------


def test_async_worker_id_defaults_to_none_and_is_passed_through(monkeypatch):
    """The synchronous caller (backend/main.py, via the orchestrator)
    never passes this kwarg — confirms the default stays None all the
    way through to reserve_websearch_quota_for_analysis_run()."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch, ChatGptWebsearchObservationResult(success=True, reason="ok", searched=True)
    )

    cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert reserve_calls[0]["async_worker_id"] is None


def test_async_worker_id_is_passed_through_when_given(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch, ChatGptWebsearchObservationResult(success=True, reason="ok", searched=True)
    )

    cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs(async_worker_id="worker-1"))

    assert reserve_calls[0]["async_worker_id"] == "worker-1"


# --- success path ----------------------------------------------------------


def test_success_builds_an_item_with_the_stable_observation_method(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            mentioned=True,
            summary="Acme summary",
            full_summary="Acme full summary",
            citations=[WebsearchCitation(url="https://acme.example.com", title="Acme")],
        ),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is not None
    assert item.observationMethod == "websearch_supplement"
    assert item.platform == cwp.CHATGPT_WEBSEARCH_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.summary == "Acme summary"
    assert item.fullSummary == "Acme full summary"
    assert item.references is not None
    assert item.references[0].url == "https://acme.example.com"
    assert item.references[0].title == "Acme"
    assert info.status == "real"
    assert info.searched is True
    assert info.recognitionLevelAtTrigger == "unidentified"


def test_success_with_truncated_result_surfaces_truncation_on_the_item(monkeypatch):
    """Task 6-D-3B: an incomplete-but-usable websearch-supplement
    answer must still be surfaced via isTruncated/finishReason/note,
    while status stays "real" (never a failure)."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="partial",
            is_truncated=True,
            finish_reason="max_output_tokens",
            note="truncated note",
        ),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is not None
    assert item.isTruncated is True
    assert item.finishReason == "max_output_tokens"
    assert item.note == "truncated note"
    assert info.status == "real"


def test_success_surfaces_full_summary_truncated_independently_of_is_truncated(monkeypatch):
    """Task 6-D-3D: a storage-safety truncation (full_summary_truncated)
    must propagate onto the item, and must be reportable independently
    of the API-level is_truncated signal."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="s",
            full_summary="truncated for storage…",
            is_truncated=False,
            full_summary_truncated=True,
        ),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item.isTruncated is False
    assert item.fullSummaryTruncated is True


def test_success_propagates_raw_citation_annotations_separately_from_references(monkeypatch):
    """Task 6-D-3D follow-up: citationAnnotations (raw, pre-dedup) and
    references (de-duplicated display list) must both reach the item,
    independently."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="s",
            citations=[WebsearchCitation(url="https://acme.example.com/about", title="About")],
            citations_truncated=False,
            citation_annotations=[
                WebsearchCitationAnnotation(
                    url="https://acme.example.com/about?utm_source=openai",
                    title="About",
                    start_index=10,
                    end_index=20,
                ),
                WebsearchCitationAnnotation(
                    url="https://acme.example.com/about?utm_source=openai",
                    title="About",
                    start_index=50,
                    end_index=60,
                ),
            ],
            citation_annotations_total_count=2,
        ),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item.citationAnnotations is not None
    assert len(item.citationAnnotations) == 2
    assert item.citationAnnotations[0].url == "https://acme.example.com/about?utm_source=openai"
    assert item.citationAnnotations[0].startIndex == 10
    assert item.citationAnnotations[0].endIndex == 20
    assert item.citationAnnotationsTotalCount == 2
    assert item.citationsTruncated is False
    # references stays the separate, normalized display list.
    assert item.references[0].url == "https://acme.example.com/about"


def test_success_with_no_citation_annotations_leaves_the_new_fields_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(success=True, reason="ok", summary="s"),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item.citationAnnotations is None
    assert item.citationAnnotationsTotalCount is None
    assert item.citationsTruncated is False


def test_success_with_no_citations_leaves_references_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(success=True, reason="ok", searched=False, summary="s"),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item.references is None
    assert info.searched is False


def test_official_url_is_never_derived_from_anything_and_is_always_none(monkeypatch):
    """Task 6-D-3 follow-up correction: this codebase has no verified
    "official site URL" field, so attempt_chatgpt_websearch_supplement()
    must never guess one from any input (there is no `urls` parameter
    at all any more — see this function's own signature/docstring) —
    official_url is always passed through to the client as None."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(success=True, reason="ok", summary="s"),
    )

    cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert fetch_calls[0]["official_url"] is None


def test_attempt_chatgpt_websearch_supplement_has_no_urls_parameter():
    """Defends against this fix regressing: no code path should be
    able to pass a caller-supplied URL list into this function at
    all."""
    import inspect

    signature = inspect.signature(cwp.attempt_chatgpt_websearch_supplement)
    assert "urls" not in signature.parameters


# --- API failure after a successful reservation ---------------------------


def test_api_failure_after_successful_reservation_reports_unavailable(monkeypatch):
    """Task 6-D-3 item D/H: a reservation can succeed and the API call
    can still fail — the reserved quota slot is never refunded (no
    code here attempts to), and this must be reported distinctly from
    every "skipped before reservation" status."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ChatGptWebsearchObservationResult(
            success=False, reason="OpenAI websearch-supplement request failed due to a network or timeout error.", searched=False
        ),
    )

    item, info = cwp.attempt_chatgpt_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "unavailable"
    assert len(reserve_calls) == 1
