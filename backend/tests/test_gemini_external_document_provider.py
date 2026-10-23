"""Tests for services/gemini_external_document_provider.py's
attempt_gemini_external_document_supplement() (Task 6-D-4C-2,
feature/gemini-external-document-supplement).

Never touches a real database or calls a real Gemini API.
"""

import pytest

import services.gemini_external_document_provider as gedp
from models import Document
from services.gemini_external_document_client import (
    GeminiExternalDocumentObservationResult,
    SelectedDocument,
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


def _web_fetch_doc(url: str, text: str = "Acme overview text.") -> Document:
    return Document(
        id=f"doc-{url}",
        sourceType="web_fetch",
        sourceUrl=url,
        fetchedAt="2026-10-24T00:00:00Z",
        text=text,
    )


def _other_source_doc(source_type: str) -> Document:
    return Document(
        id=f"doc-{source_type}",
        sourceType=source_type,
        sourceUrl="https://irrelevant.example.com" if source_type != "user_provided" else None,
        fetchedAt="2026-10-24T00:00:00Z",
        text="some text",
    )


def _base_kwargs(**overrides):
    base = dict(
        brand_name="Acme",
        recognition_level="unidentified",
        documents=[_web_fetch_doc("https://acme.example.com")],
        analysis_run_id=ANALYSIS_RUN_ID,
        project_id=PROJECT_ID,
        user_id=USER_ID,
    )
    base.update(overrides)
    return base


def _enable(monkeypatch, *, enforcement_enabled=True):
    monkeypatch.setattr(gedp, "is_gemini_external_document_supplement_enabled", lambda: True)
    monkeypatch.setattr(
        gedp,
        "load_analyze_quota_settings",
        lambda: type("S", (), {"enforcement_enabled": enforcement_enabled})(),
    )


def _mock_credentials(monkeypatch, *, configured=True, model="gemini-2.5-flash"):
    monkeypatch.setattr(gedp, "get_gemini_credentials", lambda: object() if configured else None)
    monkeypatch.setattr(gedp, "get_gemini_external_document_model", lambda: model)
    monkeypatch.setattr(gedp, "get_gemini_external_document_max_output_tokens", lambda: 2000)


def _mock_reservation_success(monkeypatch):
    calls = []

    def _reserve(**kwargs):
        calls.append(kwargs)
        return WebsearchQuotaReservation(
            analysis_run_id=kwargs["analysis_run_id"],
            project_id=kwargs["project_id"],
            metric=kwargs["metric"],
        )

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", _reserve)
    return calls


def _mock_reservation_raises(monkeypatch, exc):
    def _reserve(**kwargs):
        raise exc

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", _reserve)


def _mock_fetch(monkeypatch, result: GeminiExternalDocumentObservationResult):
    calls = []

    def _fetch(credentials, brand_name, documents, *, model, max_output_tokens):
        calls.append(
            {
                "brand_name": brand_name,
                "documents": documents,
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
        )
        return result

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", _fetch)
    return calls


# --- gate 1: recognition_level is None -----------------------------------


def test_not_attempted_when_recognition_level_is_none(monkeypatch):
    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(recognition_level=None)
    )
    assert item is None
    assert info.status == "not_attempted"


# --- gate 2: feature disabled ---------------------------------------------


def test_disabled_when_feature_flag_is_off(monkeypatch):
    monkeypatch.setattr(gedp, "is_gemini_external_document_supplement_enabled", lambda: False)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "disabled"
    assert info.recognitionLevelAtTrigger == "unidentified"


# --- gate 3: quota enforcement disabled -----------------------------------


def test_skipped_when_quota_enforcement_is_disabled(monkeypatch):
    _enable(monkeypatch, enforcement_enabled=False)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

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
        GeminiExternalDocumentObservationResult(success=True, reason="ok", summary="s"),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(recognition_level=level)
    )

    assert len(reserve_calls) == 1
    assert reserve_calls[0]["metric"] == "gemini_external_document"
    assert info.status == "real"


@pytest.mark.parametrize("level", ["specific_knowledge", "indeterminate"])
def test_ineligible_recognition_levels_are_rejected_before_any_reservation(monkeypatch, level):
    _enable(monkeypatch)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(recognition_level=level)
    )

    assert item is None
    assert info.status == "recognition_level_not_eligible"
    assert info.recognitionLevelAtTrigger == level


# --- gate 5: document availability (feature-specific) -----------------------


def test_zero_documents_is_rejected_before_any_reservation_or_api_call(monkeypatch):
    _enable(monkeypatch)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    def fail_if_fetch_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_external_document_observation should not be called")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fail_if_fetch_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs(documents=[]))

    assert item is None
    assert info.status == "no_documents"
    assert info.documentsConsideredCount == 0


def test_only_user_provided_documents_is_treated_as_zero_documents(monkeypatch):
    _enable(monkeypatch)

    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(documents=[_other_source_doc("user_provided")])
    )

    assert item is None
    assert info.status == "no_documents"


def test_only_common_crawl_documents_is_treated_as_zero_documents(monkeypatch):
    _enable(monkeypatch)

    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(documents=[_other_source_doc("common_crawl")])
    )

    assert item is None
    assert info.status == "no_documents"


def test_only_development_sample_documents_is_treated_as_zero_documents(monkeypatch):
    _enable(monkeypatch)

    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(documents=[_other_source_doc("development_sample")])
    )

    assert item is None
    assert info.status == "no_documents"


def test_mixed_sources_only_counts_web_fetch_documents(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    reserve_calls = _mock_reservation_success(monkeypatch)
    fetch_calls = _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(success=True, reason="ok", summary="s"),
    )

    documents = [
        _other_source_doc("user_provided"),
        _other_source_doc("common_crawl"),
        _web_fetch_doc("https://acme.example.com"),
    ]
    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(documents=documents)
    )

    assert info.status == "real"
    assert info.documentsConsideredCount == 1
    assert len(fetch_calls[0]["documents"]) == 1
    assert fetch_calls[0]["documents"][0].sourceUrl == "https://acme.example.com"


# --- gate 6: model allowlist -------------------------------------------------


def test_disallowed_model_is_rejected_before_any_credentials_or_reservation_check(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="gemini-3-flash-preview")

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    def fail_if_fetch_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_external_document_observation should not be called")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fail_if_fetch_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "model_not_allowed"
    assert info.model == "gemini-3-flash-preview"


def test_model_rejection_never_falls_back_to_the_allowed_model(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, model="gemini-4-argon")

    fetch_calls = []

    def fake_fetch(*args, **kwargs):
        fetch_calls.append(kwargs)
        return GeminiExternalDocumentObservationResult(success=True, reason="ok")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fake_fetch)
    monkeypatch.setattr(
        gedp,
        "reserve_websearch_quota_for_analysis_run",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not reserve")),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "model_not_allowed"
    assert len(fetch_calls) == 0


# --- gate 7: credentials ---------------------------------------------------


def test_skipped_when_no_credentials_configured(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch, configured=False)

    def fail_if_called(**kwargs):
        raise AssertionError("reserve_websearch_quota_for_analysis_run should not be called")

    monkeypatch.setattr(gedp, "reserve_websearch_quota_for_analysis_run", fail_if_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

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
            metric="gemini_external_document",
            period_type="daily",
            period_start=None,
            limit=0,
        ),
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_external_document_observation should not be called")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fail_if_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "quota_rejected"


def test_already_reserved_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaAlreadyReservedError("already reserved"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_external_document_observation should not be called")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fail_if_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

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

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "run_invalid"


def test_reservation_db_error_is_reported_and_no_api_call_happens(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_raises(monkeypatch, WebsearchQuotaReservationError("db down"))

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_gemini_external_document_observation should not be called")

    monkeypatch.setattr(gedp, "fetch_gemini_external_document_observation", fail_if_called)

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "reservation_error"


# --- API failure after a successful reservation ----------------------------


def test_api_failure_after_reservation_is_unavailable_quota_not_refunded(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(success=False, reason="Gemini API down"),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is None
    assert info.status == "unavailable"
    assert info.reason == "Gemini API down"
    assert info.model == "gemini-2.5-flash"


# --- success path ----------------------------------------------------------


def test_success_builds_an_item_with_the_stable_observation_method(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(
            success=True,
            reason="ok",
            mentioned=True,
            summary="Acme summary",
            full_summary="Acme full summary",
            selected_documents=[
                SelectedDocument(
                    source_url="https://acme.example.com",
                    title="Acme",
                    domain="acme.example.com",
                    original_index=0,
                    input_order=0,
                    text="Acme overview text.",
                    input_char_count=20,
                    truncated=False,
                )
            ],
        ),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item is not None
    assert item.observationMethod == "external_document_supplement"
    assert item.platform == gedp.GEMINI_EXTERNAL_DOCUMENT_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.summary == "Acme summary"
    assert item.fullSummary == "Acme full summary"
    assert item.model == "gemini-2.5-flash"
    assert item.references is None  # never a "references" field for this feature.
    assert item.geminiExternalDocumentSources is not None
    assert len(item.geminiExternalDocumentSources) == 1
    source = item.geminiExternalDocumentSources[0]
    assert source.sourceUrl == "https://acme.example.com"
    assert source.title == "Acme"
    assert source.domain == "acme.example.com"
    assert source.originalIndex == 0
    assert source.inputOrder == 0
    assert source.inputCharCount == 20
    assert source.truncated is False
    assert item.geminiExternalDocumentSourcesConsideredCount == 1
    assert info.status == "real"
    assert info.documentsConsideredCount == 1
    assert info.documentsUsedCount == 1
    assert info.recognitionLevelAtTrigger == "unidentified"


def test_success_with_truncated_result_surfaces_truncation_on_the_item(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(
            success=True,
            reason="ok",
            summary="partial",
            is_truncated=True,
            finish_reason="MAX_TOKENS",
            note="truncated note",
        ),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

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
        GeminiExternalDocumentObservationResult(
            success=True,
            reason="ok",
            summary="s",
            full_summary="truncated for storage…",
            is_truncated=False,
            full_summary_truncated=True,
        ),
    )

    item, info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item.isTruncated is False
    assert item.fullSummaryTruncated is True


def test_success_with_no_selected_documents_leaves_source_fields_none(monkeypatch):
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(success=True, reason="ok", summary="s"),
    )

    item, _info = gedp.attempt_gemini_external_document_supplement(**_base_kwargs())

    assert item.geminiExternalDocumentSources is None
    assert item.geminiExternalDocumentSourcesConsideredCount is None


def test_excluded_documents_are_identifiable_via_original_index_gap(monkeypatch):
    """Task 6-D-4C-2 item 3: which available documents were excluded
    must be determinable after the fact — via the gap between
    originalIndex values present and documentsConsideredCount, not a
    separate "excluded" list."""
    _enable(monkeypatch)
    _mock_credentials(monkeypatch)
    _mock_reservation_success(monkeypatch)
    _mock_fetch(
        monkeypatch,
        GeminiExternalDocumentObservationResult(
            success=True,
            reason="ok",
            summary="s",
            selected_documents=[
                SelectedDocument(
                    source_url="https://a.example.com",
                    title=None,
                    domain=None,
                    original_index=0,
                    input_order=0,
                    text="a",
                    input_char_count=1,
                    truncated=False,
                ),
                SelectedDocument(
                    source_url="https://c.example.com",
                    title=None,
                    domain=None,
                    original_index=2,
                    input_order=1,
                    text="c",
                    input_char_count=1,
                    truncated=False,
                ),
            ],
        ),
    )

    documents = [
        _web_fetch_doc("https://a.example.com"),
        _web_fetch_doc("https://b.example.com"),
        _web_fetch_doc("https://c.example.com"),
    ]
    item, info = gedp.attempt_gemini_external_document_supplement(
        **_base_kwargs(documents=documents)
    )

    assert info.documentsConsideredCount == 3
    used_indices = {s.originalIndex for s in item.geminiExternalDocumentSources}
    assert used_indices == {0, 2}
    # original_index 1 (https://b.example.com) is absent — i.e. excluded.


# --- non-interference with other websearch/document supplements -----------


def test_module_never_imports_or_calls_other_providers_functions():
    assert not hasattr(gedp, "fetch_chatgpt_websearch_observation")
    assert not hasattr(gedp, "attempt_chatgpt_websearch_supplement")
    assert not hasattr(gedp, "fetch_claude_websearch_observation")
    assert not hasattr(gedp, "attempt_claude_websearch_supplement")
    assert not hasattr(gedp, "fetch_gemini_websearch_observation")
    assert not hasattr(gedp, "attempt_gemini_websearch_supplement")
