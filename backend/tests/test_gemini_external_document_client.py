"""Tests for services/gemini_external_document_client.py (Task
6-D-4C-2, feature/gemini-external-document-supplement).

Never calls a real Gemini API: httpx.post is monkeypatched.
"""

from dataclasses import dataclass

import pytest

import services.gemini_external_document_client as gedc
from models import Document
from services.gemini_settings import GeminiCredentials

CREDENTIALS = GeminiCredentials(api_key="test-key")


@dataclass
class _FakeResponse:
    status_code: int
    _payload: object

    def json(self):
        return self._payload


def _patch_post(monkeypatch, response: _FakeResponse | None = None, *, raises: Exception | None = None):
    calls: list[dict] = []

    def fake_post(url, *, json, headers, timeout):
        calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(gedc.httpx, "post", fake_post)
    return calls


def _document(url: str, text: str, *, title: str | None = None, domain: str | None = None) -> Document:
    return Document(
        id=f"doc-{url}",
        sourceType="web_fetch",
        sourceUrl=url,
        title=title,
        domain=domain or url,
        fetchedAt="2026-10-24T00:00:00Z",
        text=text,
    )


def _candidate(text: str, finish_reason: str = "STOP") -> dict:
    return {"content": {"parts": [{"text": text}], "role": "model"}, "finishReason": finish_reason}


def _payload(text: str, finish_reason: str = "STOP") -> dict:
    return {"candidates": [_candidate(text, finish_reason)]}


def _fetch(documents, **overrides):
    kwargs = dict(
        credentials=CREDENTIALS,
        brand_name="Acme",
        documents=documents,
        model="gemini-2.5-flash",
        max_output_tokens=2000,
    )
    kwargs.update(overrides)
    return gedc.fetch_gemini_external_document_observation(**kwargs)


# --- document selection / truncation ---------------------------------------


def test_select_and_truncate_keeps_documents_in_order_with_original_index():
    documents = [
        _document("https://a.example.com", "A" * 100),
        _document("https://b.example.com", "B" * 100),
        _document("https://c.example.com", "C" * 100),
    ]
    selected = gedc.select_and_truncate_documents(documents)
    assert [s.original_index for s in selected] == [0, 1, 2]
    assert [s.input_order for s in selected] == [0, 1, 2]
    assert [s.source_url for s in selected] == [
        "https://a.example.com",
        "https://b.example.com",
        "https://c.example.com",
    ]


def test_select_and_truncate_caps_at_max_input_documents():
    documents = [_document(f"https://d{i}.example.com", "X" * 10) for i in range(5)]
    selected = gedc.select_and_truncate_documents(documents)
    assert len(selected) == gedc.MAX_INPUT_DOCUMENTS == 3
    assert [s.original_index for s in selected] == [0, 1, 2]


def test_select_and_truncate_caps_each_document_at_max_chars_per_document():
    documents = [_document("https://a.example.com", "A" * (gedc.MAX_CHARS_PER_DOCUMENT + 500))]
    selected = gedc.select_and_truncate_documents(documents)
    assert selected[0].input_char_count == gedc.MAX_CHARS_PER_DOCUMENT
    assert selected[0].truncated is True


def test_select_and_truncate_distinguishes_different_urls_on_the_same_domain():
    # Task 6-D-4C-2 final review item 1: multiple URLs sharing one
    # domain must never be collapsed into a single input document —
    # this module never deduplicates by domain (unlike the display
    # reference lists in the websearch-supplement clients, which
    # dedupe by normalized URL for a different purpose).
    documents = [
        _document("https://acme.example.com/about", "About page text."),
        _document("https://acme.example.com/products", "Products page text."),
    ]
    selected = gedc.select_and_truncate_documents(documents)
    assert len(selected) == 2
    assert [s.source_url for s in selected] == [
        "https://acme.example.com/about",
        "https://acme.example.com/products",
    ]
    assert [s.text for s in selected] == ["About page text.", "Products page text."]
    assert [s.original_index for s in selected] == [0, 1]


def test_select_and_truncate_caps_total_characters_across_documents():
    # Three documents each under the per-document cap, but together
    # exceeding MAX_TOTAL_INPUT_CHARS (10000) — the third must be
    # truncated (or excluded) by the shared budget, not just by its
    # own per-document cap.
    per_doc = 4000
    documents = [_document(f"https://d{i}.example.com", "X" * per_doc) for i in range(3)]
    selected = gedc.select_and_truncate_documents(documents)
    total_chars = sum(s.input_char_count for s in selected)
    assert total_chars <= gedc.MAX_TOTAL_INPUT_CHARS
    assert selected[-1].truncated is True


def test_select_and_truncate_stops_adding_documents_once_budget_exhausted():
    # Each of the first two documents alone hits the per-document cap
    # (5000), together exactly exhausting the 10000 total budget —
    # the third document must be silently excluded entirely, never
    # added as a zero-character entry.
    documents = [
        _document("https://a.example.com", "A" * gedc.MAX_CHARS_PER_DOCUMENT),
        _document("https://b.example.com", "B" * gedc.MAX_CHARS_PER_DOCUMENT),
        _document("https://c.example.com", "C" * 100),
    ]
    selected = gedc.select_and_truncate_documents(documents)
    assert len(selected) == 2
    assert [s.source_url for s in selected] == [
        "https://a.example.com",
        "https://b.example.com",
    ]


def test_select_and_truncate_skips_documents_without_source_url_or_text_defensively():
    documents = [
        Document(
            id="bad",
            sourceType="web_fetch",
            sourceUrl=None,
            fetchedAt="2026-10-24T00:00:00Z",
            text="some text",
        ),
        _document("https://good.example.com", "good text"),
    ]
    selected = gedc.select_and_truncate_documents(documents)
    assert len(selected) == 1
    assert selected[0].source_url == "https://good.example.com"
    # original_index is preserved relative to the full input list.
    assert selected[0].original_index == 1


def test_no_documents_returns_empty_selection():
    assert gedc.select_and_truncate_documents([]) == []


# --- request shape: no tools field, ever ------------------------------------


def test_request_never_includes_a_tools_field(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a company that makes widgets.")))
    _fetch([_document("https://acme.example.com", "Acme overview text.")])
    body = calls[0]["json"]
    assert "tools" not in body


def test_request_never_includes_the_google_search_tool_specifically(monkeypatch):
    # Defensive, explicit check beyond the generic "no tools key" test
    # above — this is the one property Task 6-D-4C-2 explicitly
    # forbids ever sending.
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a company that makes widgets.")))
    _fetch([_document("https://acme.example.com", "Acme overview text.")])
    body = calls[0]["json"]
    assert "google_search" not in str(body)


def test_request_uses_generation_config_max_output_tokens(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a company that makes widgets.")))
    _fetch([_document("https://acme.example.com", "Acme overview text.")], max_output_tokens=1234)
    assert calls[0]["json"]["generationConfig"]["maxOutputTokens"] == 1234


def test_prompt_includes_document_url_and_text(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a company that makes widgets.")))
    _fetch([_document("https://acme.example.com", "Acme makes widgets.", title="Acme Inc.")])
    prompt_text = calls[0]["json"]["contents"][0]["parts"][0]["text"]
    assert "https://acme.example.com" in prompt_text
    assert "Acme makes widgets." in prompt_text
    assert "Acme Inc." in prompt_text


def test_system_prompt_forbids_treating_document_content_as_instructions(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a company that makes widgets.")))
    _fetch([_document("https://acme.example.com", "Acme overview text.")])
    system_text = calls[0]["json"]["systemInstruction"]["parts"][0]["text"]
    assert "指示・命令文" in system_text
    assert "Web検索は一切行っていません" in system_text
    assert "公式サイトであるとは断定しない" in system_text


# --- API success / failure --------------------------------------------------


def test_success_returns_full_summary_and_mentioned(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a well-known widget company.")))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is True
    assert result.mentioned is True
    assert result.full_summary == "Acme is a well-known widget company."


def test_network_error_is_reported_safely(monkeypatch):
    import httpx

    _patch_post(monkeypatch, raises=httpx.ConnectError("boom"))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is False
    assert "network or timeout" in result.reason


def test_non_200_response_is_reported_safely(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(401, {"error": "unauthorized"}))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is False
    assert "HTTP 401" in result.reason


def test_non_json_response_is_reported_safely(monkeypatch):
    @dataclass
    class _BadJsonResponse:
        status_code: int = 200

        def json(self):
            raise ValueError("not json")

    _patch_post(monkeypatch, _BadJsonResponse())
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is False
    assert "not valid JSON" in result.reason


def test_no_readable_text_is_a_failure(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, {"candidates": [{"finishReason": "SAFETY"}]}))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is False
    assert "SAFETY" in result.reason


# --- finishReason: STOP / MAX_TOKENS / SAFETY -------------------------------


def test_finish_reason_stop_is_not_truncated(monkeypatch):
    _patch_post(
        monkeypatch,
        _FakeResponse(200, _payload("Acme is a well-established technology company.", "STOP")),
    )
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.is_truncated is False
    assert result.finish_reason == "STOP"
    assert result.note is None


def test_finish_reason_max_tokens_is_truncated(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload("Acme is a comp", "MAX_TOKENS")))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.is_truncated is True
    assert result.finish_reason == "MAX_TOKENS"
    assert result.note == gedc.TRUNCATION_NOTE


def test_finish_reason_safety_with_text_still_present_is_success(monkeypatch):
    _patch_post(
        monkeypatch,
        _FakeResponse(200, _payload("Acme is a well-established technology company.", "SAFETY")),
    )
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.success is True
    assert result.finish_reason == "SAFETY"


# --- fullSummary / fullSummaryTruncated -------------------------------------


def test_full_summary_is_truncated_at_the_safety_ceiling(monkeypatch):
    text = "A" * (gedc._FULL_SUMMARY_SAFETY_MAX_CHARS + 500)
    _patch_post(monkeypatch, _FakeResponse(200, _payload(text)))
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert result.full_summary_truncated is True
    assert len(result.full_summary) <= gedc._FULL_SUMMARY_SAFETY_MAX_CHARS + 1


# --- input documents vs. actual citations: no citation parsing at all ------


def test_result_never_parses_urls_out_of_the_models_answer_text(monkeypatch):
    # Even if the model's answer text contains a URL-shaped string,
    # this client must never register it as a "source" — the only
    # sources this module ever reports are the documents it was given
    # as input (selected_documents), never anything parsed from the
    # response text.
    _patch_post(
        monkeypatch,
        _FakeResponse(
            200, _payload("Acme is discussed at https://totally-made-up-citation.example.com")
        ),
    )
    result = _fetch([_document("https://acme.example.com", "Acme overview text.")])
    assert len(result.selected_documents) == 1
    assert result.selected_documents[0].source_url == "https://acme.example.com"
    assert "totally-made-up-citation" not in str(result.selected_documents)
