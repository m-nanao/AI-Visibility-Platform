"""Tests for services/claude_websearch_provider.py's
attempt_claude_websearch_supplement() (Task 6-D-4A-2,
feature/claude-websearch-supplement).

Never touches a real database or calls a real Anthropic API:
reserve_websearch_quota_for_analysis_run()/
fetch_claude_websearch_observation() are monkeypatched at this
module's own namespace (both are imported by name into
services.claude_websearch_provider, so patching the name there is what
actually takes effect). Mirrors tests/test_chatgpt_websearch_provider.py's
structure, per this task's own "命名は既存ChatGPT実装との整合性を優先す
る" instruction.
"""

import pytest

import services.claude_websearch_provider as cwp
from services.claude_websearch_client import (
    ClaudeWebsearchCitation,
    ClaudeWebsearchCitationAnnotation,
    ClaudeWebsearchObservationResult,
)
from services.websearch_quota_reservation import (
    AnalysisQuotaExceededError,
    WebsearchQuotaAccessDeniedError,
    WebsearchQuotaAlreadyReservedError,
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
    monkeypatch.setattr(cwp, "is_claude_websearch_supplement_enabled", lambda: True)
    monkeypatch.setattr(
        cwp,
        "load_analyze_quota_settings",
        lambda: type("S", (), {"enforcement_enabled": enforcement_enabled})(),
    )


def _mock_credentials(monkeypatch, *, configured=True):
    monkeypatch.setattr(cwp, "get_claude_credentials", lambda: object() if configured else None)
    monkeypatch.setattr(cwp, "get_claude_websearch_model", lambda: "claude-sonnet-5-5")
    monkeypatch.setattr(cwp, "get_claude_websearch_max_output_tokens", lambda: 2000)


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


def _mock_fetch(monkeypatch, result: ClaudeWebsearchObservationResult):
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

    monkeypatch.setattr(cwp, "fetch_claude_websearch_observation", _fetch)
    return calls


# --- gate 1: recognition_level is None -----------------------------------


def test_not_attempted_when_recognition_level_is_none(monkeypatch):
    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs(recognition_level=None))
    assert item is None
    assert info.status == "not_attempted"


# --- gate 2: feature disabled ---------------------------------------------


def test_disabled_when_feature_flag_is_off(monkeypatch):
    monkeypatch.setattr(cwp, "is_claude_websearch_supplement_enabled", lambda: False)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "disabled"
    assert info.recognitionLevelAtTrigger == "unidentified"


# --- gate 3: quota enforcement disabled -----------------------------------


def test_skipped_when_quota_enforcement_is_disabled(monkeypatch):
    _enable(monkeypatch, enforcement_enabled=False)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

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
        ClaudeWebsearchObservationResult(success=True, reason="ok", searched=True, summary="s"),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs(recognition_level=level))

    assert len(reserve_calls) == 1
    assert reserve_calls[0]["metric"] == "anthropic_websearch"
    assert info.status == "real"


@pytest.mark.parametrize("level", ["specific_knowledge", "indeterminate"])
def test_ineligible_recognition_levels_are_rejected_before_any_reservation(monkeypatch, level):
    _enable(monkeypatch)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs(recognition_level=level))

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

    _, info_specific = cwp.attempt_claude_websearch_supplement(
        **_base_kwargs(recognition_level="specific_knowledge")
    )
    _, info_indeterminate = cwp.attempt_claude_websearch_supplement(
        **_base_kwargs(recognition_level="indeterminate")
    )

    assert info_specific.reason != info_indeterminate.reason


# --- gate 5: credentials ---------------------------------------------------


def test_skipped_when_no_credentials_configured(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, configured=False)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(cwp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

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
            metric="anthropic_websearch",
            period_type="daily",
            period_start=None,
            limit=0,
        ),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_claude_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_claude_websearch_observation", fail_if_called)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "quota_rejected"


def test_already_reserved_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaAlreadyReservedError("already reserved"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_claude_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_claude_websearch_observation", fail_if_called)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "already_reserved"


@pytest.mark.parametrize(
    "exc",
    [
        WebsearchQuotaRunNotFoundError("not found"),
        WebsearchQuotaRunNotRunningError("not running"),
        WebsearchQuotaAccessDeniedError("denied"),
    ],
)
def test_run_project_user_rejections_are_reported_as_run_invalid(monkeypatch, exc):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, exc)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "run_invalid"


def test_reservation_db_error_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaReservationError("db down"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_claude_websearch_observation should not be called")

    monkeypatch.setattr(cwp, "fetch_claude_websearch_observation", fail_if_called)

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "reservation_error"


# --- API failure after a successful reservation ----------------------------


def test_api_failure_after_reservation_is_unavailable_quota_not_refunded(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(success=False, reason="Anthropic API down"),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "unavailable"
    assert info.reason == "Anthropic API down"
    # model is still recorded even on failure (Task 6-D-4A-2 item 1).
    assert info.model == "claude-sonnet-5-5"


# --- success path ----------------------------------------------------------


def test_success_builds_an_item_with_the_stable_observation_method(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            mentioned=True,
            summary="Acme summary",
            full_summary="Acme full summary",
            citations=[ClaudeWebsearchCitation(url="https://acme.example.com", title="Acme")],
        ),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is not None
    assert item.observationMethod == "websearch_supplement"
    assert item.platform == cwp.CLAUDE_WEBSEARCH_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.summary == "Acme summary"
    assert item.fullSummary == "Acme full summary"
    assert item.references is not None
    assert item.references[0].url == "https://acme.example.com"
    assert item.references[0].title == "Acme"
    assert info.status == "real"
    assert info.searched is True
    assert info.recognitionLevelAtTrigger == "unidentified"
    assert info.model == "claude-sonnet-5-5"
    # Task 6-D-4A-2 final review item 1: the item itself (not only the
    # provider-info meta) must also record the model actually used.
    assert item.model == "claude-sonnet-5-5"


def test_success_with_truncated_result_surfaces_truncation_on_the_item(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="partial",
            is_truncated=True,
            finish_reason="max_tokens",
            note="truncated note",
        ),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item is not None
    assert item.isTruncated is True
    assert item.finishReason == "max_tokens"
    assert item.note == "truncated note"
    assert info.status == "real"


def test_success_surfaces_full_summary_truncated_independently_of_is_truncated(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="s",
            full_summary="truncated for storage…",
            is_truncated=False,
            full_summary_truncated=True,
        ),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item.isTruncated is False
    assert item.fullSummaryTruncated is True


def test_success_propagates_raw_citation_annotations_separately_from_references(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=True,
            summary="s",
            citations=[ClaudeWebsearchCitation(url="https://acme.example.com/about", title="About")],
            citations_truncated=False,
            citation_annotations=[
                ClaudeWebsearchCitationAnnotation(
                    url="https://acme.example.com/about?utm_source=anthropic",
                    title="About",
                    cited_text="Acme makes widgets",
                ),
                ClaudeWebsearchCitationAnnotation(
                    url="https://acme.example.com/about?utm_source=anthropic",
                    title="About",
                    cited_text="Acme was founded in 2001",
                ),
            ],
            citation_annotations_total_count=2,
        ),
    )

    item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item.references == [cwp.AIOverviewReference(url="https://acme.example.com/about", title="About")]
    assert item.claudeCitationAnnotations is not None
    assert len(item.claudeCitationAnnotations) == 2
    assert item.claudeCitationAnnotations[0].url == "https://acme.example.com/about?utm_source=anthropic"
    assert item.claudeCitationAnnotations[0].citedText == "Acme makes widgets"
    assert item.claudeCitationAnnotationsTotalCount == 2
    assert item.citationsTruncated is False


def test_success_with_no_citation_annotations_leaves_the_new_fields_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(success=True, reason="ok", searched=False, summary="s"),
    )

    item, _info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert item.references is None
    assert item.claudeCitationAnnotations is None
    assert item.claudeCitationAnnotationsTotalCount is None


def test_success_propagates_search_error_code(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(
            success=True,
            reason="ok",
            searched=False,
            search_error_code="max_uses_exceeded",
            summary="s",
        ),
    )

    _item, info = cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert info.searched is False
    assert info.searchErrorCode == "max_uses_exceeded"


# --- official_url is never a caller-supplied guess --------------------------


def test_official_url_is_always_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(
        monkeypatch,
        ClaudeWebsearchObservationResult(success=True, reason="ok", searched=False, summary="s"),
    )

    cwp.attempt_claude_websearch_supplement(**_base_kwargs())

    assert fetch_calls[0]["official_url"] is None


# --- OpenAI websearch supplement independence -------------------------------


def test_module_never_imports_or_calls_openai_websearch_functions():
    # Sanity check that this module's own namespace carries no
    # reference to the ChatGPT websearch client/provider at all — the
    # two features must be able to succeed/fail/ be enabled
    # independently of one another.
    assert not hasattr(cwp, "fetch_chatgpt_websearch_observation")
    assert not hasattr(cwp, "attempt_chatgpt_websearch_supplement")
