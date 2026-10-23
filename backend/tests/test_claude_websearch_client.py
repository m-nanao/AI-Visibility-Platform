"""Tests for services/claude_websearch_client.py (Task 6-D-4A-2,
feature/claude-websearch-supplement).

Never calls a real Anthropic API: httpx.post is monkeypatched to
return a fixture response built to match Anthropic's documented
Messages API shape for the web_search_20250305 server tool (see
https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool
and https://platform.claude.com/docs/build-with-claude/handling-stop-reasons,
both fetched 2026-10-23 as part of Task 6-D-4A-1).
"""

from dataclasses import dataclass

import pytest

import services.claude_websearch_client as cwc
from services.claude_settings import ClaudeCredentials

CREDENTIALS = ClaudeCredentials(api_key="test-key")


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

    monkeypatch.setattr(cwc.httpx, "post", fake_post)
    return calls


def _text_block(text: str, citations: list[dict] | None = None) -> dict:
    block = {"type": "text", "text": text}
    if citations is not None:
        block["citations"] = citations
    return block


def _server_tool_use_block() -> dict:
    return {
        "type": "server_tool_use",
        "id": "srvtoolu_1",
        "name": "web_search",
        "input": {"query": "Acme"},
    }


def _web_search_tool_result_block(results: list[dict]) -> dict:
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": results,
    }


def _web_search_tool_result_error_block(error_code: str) -> dict:
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": {"type": "web_search_tool_result_error", "error_code": error_code},
    }


def _citation(url: str, title: str | None = None, cited_text: str | None = None) -> dict:
    citation = {"type": "web_search_result_location", "url": url, "encrypted_index": "opaque"}
    if title is not None:
        citation["title"] = title
    if cited_text is not None:
        citation["cited_text"] = cited_text
    return citation


def _payload(content: list[dict], *, stop_reason: str = "end_turn", web_search_requests: int | None = None) -> dict:
    payload: dict = {"role": "assistant", "content": content, "stop_reason": stop_reason}
    if web_search_requests is not None:
        payload["usage"] = {
            "input_tokens": 100,
            "output_tokens": 50,
            "server_tool_use": {"web_search_requests": web_search_requests},
        }
    return payload


# --- request shape --------------------------------------------------------


def test_request_offers_web_search_tool_with_max_uses_one(monkeypatch):
    calls = _patch_post(
        monkeypatch, _FakeResponse(200, _payload([_text_block("Acme is a company.")]))
    )
    cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    body = calls[0]["json"]
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == 2000


def test_request_sends_anthropic_api_key_and_version_headers(monkeypatch):
    calls = _patch_post(
        monkeypatch, _FakeResponse(200, _payload([_text_block("Acme is a company.")]))
    )
    cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    headers = calls[0]["headers"]
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == cwc.ANTHROPIC_API_VERSION


# --- web検索ツール未使用 ----------------------------------------------------


def test_tool_not_used_is_a_valid_outcome_not_a_failure(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_text_block("Acme is a company.")])))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.searched is False
    assert result.search_error_code is None
    assert result.citations == []


# --- web検索成功、結果あり ---------------------------------------------------


def test_search_success_with_results_sets_searched_true_and_builds_references(monkeypatch):
    content = [
        _server_tool_use_block(),
        _web_search_tool_result_block(
            [{"type": "web_search_result", "url": "https://acme.example.com", "title": "Acme"}]
        ),
        _text_block(
            "Acme is a technology company.",
            citations=[_citation("https://acme.example.com", "Acme", "a technology company")],
        ),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.searched is True
    assert result.citations == [cwc.ClaudeWebsearchCitation(url="https://acme.example.com", title="Acme")]
    assert result.citation_annotations == [
        cwc.ClaudeWebsearchCitationAnnotation(
            url="https://acme.example.com", title="Acme", cited_text="a technology company"
        )
    ]
    assert result.citation_annotations_total_count == 1


# --- web検索成功、結果0件 ----------------------------------------------------


def test_search_success_with_zero_results_is_still_searched_true(monkeypatch):
    content = [
        _server_tool_use_block(),
        _web_search_tool_result_block([]),
        _text_block("Acme could not be found via search."),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.searched is True
    assert result.citations == []
    assert result.citation_annotations == []


# --- web_search_tool_result_error -----------------------------------------


@pytest.mark.parametrize(
    "error_code",
    ["too_many_requests", "invalid_tool_input", "max_uses_exceeded", "query_too_long", "request_too_large", "unavailable"],
)
def test_search_tool_error_sets_searched_false_and_records_error_code(monkeypatch, error_code):
    content = [
        _server_tool_use_block(),
        _web_search_tool_result_error_block(error_code),
        _text_block("I could not search, but here is what I know about Acme."),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.searched is False
    assert result.search_error_code == error_code


def test_searched_is_not_inferred_from_server_tool_use_block_alone(monkeypatch):
    # The model decided to search (server_tool_use is present) but no
    # matching web_search_tool_result ever arrived in this fixture —
    # searched must stay False, never inferred from the request alone.
    content = [_server_tool_use_block(), _text_block("Acme is a company.")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.searched is False


# --- HTTP/APIエラー ----------------------------------------------------------


def test_network_error_is_reported_safely(monkeypatch):
    import httpx

    _patch_post(monkeypatch, raises=httpx.ConnectError("boom"))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is False
    assert "network or timeout" in result.reason


def test_non_200_response_is_reported_safely(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(401, {"error": "unauthorized"}))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is False
    assert "HTTP 401" in result.reason


def test_non_json_response_is_reported_safely(monkeypatch):
    @dataclass
    class _BadJsonResponse:
        status_code: int = 200

        def json(self):
            raise ValueError("not json")

    _patch_post(monkeypatch, _BadJsonResponse())
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is False
    assert "not valid JSON" in result.reason


# --- stop_reason: max_tokens / pause_turn / model_context_window_exceeded --


@pytest.mark.parametrize("stop_reason", ["max_tokens", "pause_turn", "model_context_window_exceeded"])
def test_truncating_stop_reasons_set_is_truncated_true(monkeypatch, stop_reason):
    content = [_text_block("Acme is a comp")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content, stop_reason=stop_reason)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.is_truncated is True
    assert result.finish_reason == stop_reason
    assert result.note == cwc.TRUNCATION_NOTE


def test_end_turn_is_not_truncated(monkeypatch):
    content = [_text_block("Acme is a company.")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content, stop_reason="end_turn")))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.is_truncated is False
    assert result.note is None


# --- stop_reason: refusal --------------------------------------------------


def test_refusal_with_text_is_success_but_not_truncated(monkeypatch):
    content = [_text_block("I'm not able to help with that.")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content, stop_reason="refusal")))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.is_truncated is False
    assert result.finish_reason == "refusal"
    assert result.note == cwc.REFUSAL_NOTE


def test_refusal_with_no_text_is_a_failure_mentioning_refusal(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload([], stop_reason="refusal")))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is False
    assert "refusal" in result.reason


# --- stop_reason: tool_use (defensive/unexpected) --------------------------


def test_unexpected_tool_use_stop_reason_is_treated_as_truncated(monkeypatch):
    content = [_text_block("Acme is a comp")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content, stop_reason="tool_use")))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.is_truncated is True
    assert result.finish_reason == "tool_use"


# --- usage.server_tool_use.web_search_requests -----------------------------


def test_web_search_requests_usage_is_captured_but_not_used_for_searched(monkeypatch):
    # usage reports 1 search request, but no web_search_tool_result
    # block is present in content — searched must still be False;
    # web_search_requests is purely diagnostic.
    content = [_text_block("Acme is a company.")]
    _patch_post(
        monkeypatch,
        _FakeResponse(200, _payload(content, web_search_requests=1)),
    )
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.web_search_requests == 1
    assert result.searched is False


def test_web_search_requests_absent_from_usage_is_none(monkeypatch):
    content = [_text_block("Acme is a company.")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.web_search_requests is None


# --- citation duplicates / raw vs. display separation -----------------------


def test_same_url_cited_multiple_times_is_preserved_raw_but_deduplicated_for_display(monkeypatch):
    content = [
        _web_search_tool_result_block(
            [{"type": "web_search_result", "url": "https://acme.example.com", "title": "Acme"}]
        ),
        _text_block(
            "Acme does X. Acme also does Y.",
            citations=[
                _citation("https://acme.example.com", "Acme", "does X"),
                _citation("https://acme.example.com", "Acme", "does Y"),
                _citation("https://acme.example.com?utm_source=anthropic", "Acme", "does Y again"),
            ],
        ),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert len(result.citation_annotations) == 3
    assert result.citation_annotations_total_count == 3
    assert result.citation_annotations[0].url == "https://acme.example.com"
    assert result.citation_annotations[2].url == "https://acme.example.com?utm_source=anthropic"
    # Display list collapses all three (after utm_source stripping) to one.
    assert result.citations == [cwc.ClaudeWebsearchCitation(url="https://acme.example.com", title="Acme")]
    assert result.citations_truncated is False


def test_raw_url_keeps_tracking_params_display_url_strips_them(monkeypatch):
    tracked_url = "https://acme.example.com/about?utm_source=anthropic&id=42"
    content = [
        _text_block("Acme overview.", citations=[_citation(tracked_url, "Acme")]),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.citation_annotations[0].url == tracked_url
    assert result.citations[0].url == "https://acme.example.com/about?id=42"


def test_eleven_unique_urls_sets_citations_truncated(monkeypatch):
    citations = [_citation(f"https://example{i}.com", f"Example {i}") for i in range(11)]
    content = [_text_block("Acme overview.", citations=citations)]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert len(result.citations) == 10
    assert result.citations_truncated is True
    assert result.citation_annotations_total_count == 11


def test_raw_annotations_beyond_storage_ceiling_are_capped_but_total_count_is_exact(monkeypatch):
    repeat_count = cwc._MAX_RAW_CITATION_ANNOTATIONS + 20
    citations = [_citation("https://acme.example.com", "Acme") for _ in range(repeat_count)]
    content = [_text_block("Acme overview.", citations=citations)]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert len(result.citation_annotations) == cwc._MAX_RAW_CITATION_ANNOTATIONS
    assert result.citation_annotations_total_count == repeat_count
    # Display list is unaffected — one URL repeated, so one entry, no truncation.
    assert result.citations == [cwc.ClaudeWebsearchCitation(url="https://acme.example.com", title="Acme")]
    assert result.citations_truncated is False


def test_citation_without_cited_text_or_title_is_preserved_with_none(monkeypatch):
    content = [
        _text_block("Acme overview.", citations=[{"type": "web_search_result_location", "url": "https://acme.example.com"}]),
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.citation_annotations == [
        cwc.ClaudeWebsearchCitationAnnotation(url="https://acme.example.com", title=None, cited_text=None)
    ]


def test_no_citations_is_a_valid_outcome_not_a_failure(monkeypatch):
    content = [_text_block("Acme is a company, no sources cited.")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.success is True
    assert result.citations == []
    assert result.citation_annotations == []
    assert result.citation_annotations_total_count == 0


# --- full_summary / full_summary_truncated ----------------------------------


def test_full_summary_is_the_complete_text_when_short(monkeypatch):
    text = "Acme is a company that makes widgets."
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_text_block(text)])))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.full_summary == text
    assert result.full_summary_truncated is False


def test_full_summary_is_truncated_at_the_safety_ceiling(monkeypatch):
    text = "A" * (cwc._FULL_SUMMARY_SAFETY_MAX_CHARS + 500)
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_text_block(text)])))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.full_summary_truncated is True
    assert len(result.full_summary) <= cwc._FULL_SUMMARY_SAFETY_MAX_CHARS + 1


def test_mentioned_is_a_case_insensitive_substring_check(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_text_block("I know nothing about this company.")])))
    result = cwc.fetch_claude_websearch_observation(
        CREDENTIALS, "Acme", None, model="claude-sonnet-5-5", max_output_tokens=2000
    )
    assert result.mentioned is False
