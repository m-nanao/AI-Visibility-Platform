"""Tests for services/gemini_websearch_client.py (Task 6-D-4B-2,
feature/gemini-websearch-supplement).

Never calls a real Gemini API: httpx.post is monkeypatched to return a
fixture response built to match the generateContent response shape
documented at
https://ai.google.dev/gemini-api/docs/generate-content/google-search
(fetched 2026-10-24).
"""

from dataclasses import dataclass

import pytest

import services.gemini_websearch_client as gwc
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

    monkeypatch.setattr(gwc.httpx, "post", fake_post)
    return calls


def _candidate(
    text: str,
    *,
    finish_reason: str = "STOP",
    grounding_metadata: dict | None = None,
    no_grounding_metadata_key: bool = False,
) -> dict:
    candidate: dict = {
        "content": {"parts": [{"text": text}], "role": "model"},
        "finishReason": finish_reason,
    }
    if not no_grounding_metadata_key:
        candidate["groundingMetadata"] = grounding_metadata if grounding_metadata is not None else {}
    return candidate


def _payload(candidates: list[dict]) -> dict:
    return {"candidates": candidates}


def _fetch(**overrides):
    kwargs = dict(
        credentials=CREDENTIALS,
        brand_name="Acme",
        official_url=None,
        model="gemini-2.5-flash",
        max_output_tokens=2000,
    )
    kwargs.update(overrides)
    return gwc.fetch_gemini_websearch_observation(**kwargs)


# --- request shape --------------------------------------------------------


def test_request_uses_the_documented_google_search_tool_shape(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate("Acme is a company.")])))
    _fetch()
    body = calls[0]["json"]
    assert body["tools"] == [{"google_search": {}}]
    assert body["generationConfig"]["maxOutputTokens"] == 2000


def test_request_sends_api_key_header(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate("Acme is a company.")])))
    _fetch()
    assert calls[0]["headers"]["x-goog-api-key"] == "test-key"


def test_request_url_uses_the_given_model(monkeypatch):
    calls = _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate("Acme is a company.")])))
    _fetch(model="gemini-2.5-flash")
    assert "gemini-2.5-flash" in calls[0]["url"]


# --- グラウンディング情報なし（groundingMetadataキー自体が存在しない） ------


def test_no_grounding_metadata_key_is_searched_false(monkeypatch):
    content = [_candidate("Acme is a company.", no_grounding_metadata_key=True)]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.success is True
    assert result.grounding_metadata_present is False
    assert result.searched is False
    assert result.web_search_queries_count == 0
    assert result.references == []
    assert result.grounding_chunks == []


# --- グラウンディング情報あり・検索クエリ情報あり（searched=True） ----------


def test_grounding_metadata_with_queries_is_searched_true(monkeypatch):
    content = [
        _candidate(
            "Acme is a technology company.",
            grounding_metadata={
                "webSearchQueries": ["Acme company overview"],
                "groundingChunks": [{"web": {"uri": "https://acme.example.com", "title": "Acme"}}],
                "groundingSupports": [
                    {
                        "segment": {"startIndex": 0, "endIndex": 10, "text": "Acme is a"},
                        "groundingChunkIndices": [0],
                    }
                ],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.success is True
    assert result.grounding_metadata_present is True
    assert result.searched is True
    assert result.web_search_queries_count == 1
    assert result.references == [gwc.GeminiWebsearchReference(uri="https://acme.example.com", title="Acme")]


# --- グラウンディング情報あり・検索クエリ情報なし（searched=None、不確定） --


def test_grounding_metadata_without_queries_is_searched_none():
    assert gwc._classify_searched(True, []) is None


def test_grounding_metadata_present_but_empty_web_search_queries_array(monkeypatch):
    content = [_candidate("Acme is a company.", grounding_metadata={"webSearchQueries": []})]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.grounding_metadata_present is True
    assert result.searched is None
    assert result.web_search_queries_count == 0


def test_web_search_queries_excludes_blank_entries_from_the_count(monkeypatch):
    content = [
        _candidate(
            "Acme is a company.",
            grounding_metadata={"webSearchQueries": ["Acme", "", "   ", "Acme overview"]},
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.web_search_queries_count == 2
    assert result.searched is True


# --- groundingChunks 複数件・groundingSupportsの多対多 ----------------------


def test_grounding_support_can_reference_multiple_chunks(monkeypatch):
    content = [
        _candidate(
            "Acme makes widgets and gadgets.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "groundingChunks": [
                    {"web": {"uri": "https://a.example.com", "title": "A"}},
                    {"web": {"uri": "https://b.example.com", "title": "B"}},
                ],
                "groundingSupports": [
                    {
                        "segment": {"startIndex": 0, "endIndex": 30, "text": "Acme makes widgets and gadgets"},
                        "groundingChunkIndices": [1, 0],
                        "confidenceScores": [0.9, 0.8],
                    }
                ],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert len(result.grounding_chunks) == 2
    assert len(result.grounding_supports) == 1
    support = result.grounding_supports[0]
    assert support.grounding_chunk_indices == [1, 0]
    assert support.confidence_scores == [0.9, 0.8]
    assert support.start_index == 0
    assert support.end_index == 30
    assert support.text == "Acme makes widgets and gadgets"


def test_grounding_chunks_and_supports_index_correspondence_is_preserved(monkeypatch):
    content = [
        _candidate(
            "Acme overview.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "groundingChunks": [
                    {"web": {"uri": "https://first.example.com"}},
                    {"web": {"uri": "https://second.example.com"}},
                    {"web": {"uri": "https://third.example.com"}},
                ],
                "groundingSupports": [
                    {"segment": {"startIndex": 0, "endIndex": 5}, "groundingChunkIndices": [2]},
                ],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    # groundingChunkIndices [2] must still point at the third original
    # chunk (https://third.example.com) — order/positions must never
    # be reshuffled when converting to the stored dataclasses.
    assert result.grounding_chunks[2].uri == "https://third.example.com"
    assert result.grounding_supports[0].grounding_chunk_indices == [2]


# --- 引用位置・インデックス保持（startIndex/endIndexがbool/非intの防御） ----


def test_bool_start_index_is_not_coerced(monkeypatch):
    content = [
        _candidate(
            "Acme.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "groundingSupports": [{"segment": {"startIndex": True, "endIndex": 5}}],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.grounding_supports[0].start_index is None
    assert result.grounding_supports[0].end_index == 5


# --- domain field is optional ----------------------------------------------


def test_grounding_chunk_domain_is_optional(monkeypatch):
    content = [
        _candidate(
            "Acme.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "groundingChunks": [{"web": {"uri": "https://acme.example.com", "title": "Acme"}}],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.grounding_chunks[0].domain is None


def test_grounding_chunk_domain_is_preserved_when_present(monkeypatch):
    content = [
        _candidate(
            "Acme.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "groundingChunks": [
                    {"web": {"uri": "https://acme.example.com", "title": "Acme", "domain": "acme.example.com"}}
                ],
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.grounding_chunks[0].domain == "acme.example.com"


# --- finishReason: STOP / MAX_TOKENS / SAFETY -------------------------------


def test_finish_reason_stop_is_not_truncated(monkeypatch):
    content = [_candidate("Acme is a well-established technology company.", finish_reason="STOP")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.is_truncated is False
    assert result.finish_reason == "STOP"
    assert result.note is None


def test_finish_reason_max_tokens_is_truncated(monkeypatch):
    content = [_candidate("Acme is a comp", finish_reason="MAX_TOKENS")]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.is_truncated is True
    assert result.finish_reason == "MAX_TOKENS"
    assert result.note == gwc.TRUNCATION_NOTE


def test_finish_reason_safety_with_no_text_is_a_failure(monkeypatch):
    content = [{"finishReason": "SAFETY"}]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.success is False
    assert "SAFETY" in result.reason


# --- APIエラー ---------------------------------------------------------------


def test_network_error_is_reported_safely(monkeypatch):
    import httpx

    _patch_post(monkeypatch, raises=httpx.ConnectError("boom"))
    result = _fetch()
    assert result.success is False
    assert "network or timeout" in result.reason


def test_non_200_response_is_reported_safely(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(401, {"error": "unauthorized"}))
    result = _fetch()
    assert result.success is False
    assert "HTTP 401" in result.reason


def test_non_json_response_is_reported_safely(monkeypatch):
    @dataclass
    class _BadJsonResponse:
        status_code: int = 200

        def json(self):
            raise ValueError("not json")

    _patch_post(monkeypatch, _BadJsonResponse())
    result = _fetch()
    assert result.success is False
    assert "not valid JSON" in result.reason


# --- 参照元10件上限 ----------------------------------------------------------


def test_eleven_unique_uris_sets_citations_truncated(monkeypatch):
    chunks = [{"web": {"uri": f"https://example{i}.com", "title": f"Example {i}"}} for i in range(11)]
    content = [
        _candidate("Acme overview.", grounding_metadata={"webSearchQueries": ["Acme"], "groundingChunks": chunks})
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert len(result.references) == 10
    assert result.citations_truncated is True
    assert result.grounding_chunks_total_count == 11


def test_same_uri_cited_multiple_times_is_deduplicated_for_display(monkeypatch):
    chunks = [
        {"web": {"uri": "https://acme.example.com", "title": "Acme"}},
        {"web": {"uri": "https://acme.example.com?utm_source=google", "title": "Acme"}},
    ]
    content = [
        _candidate("Acme overview.", grounding_metadata={"webSearchQueries": ["Acme"], "groundingChunks": chunks})
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.references == [gwc.GeminiWebsearchReference(uri="https://acme.example.com", title="Acme")]
    assert result.grounding_chunks_total_count == 2
    assert len(result.grounding_chunks) == 2  # raw list keeps both, unlike the display list


# --- 生grounding情報の保存上限 ------------------------------------------------


def test_grounding_chunks_beyond_storage_ceiling_are_capped_but_total_count_is_exact(monkeypatch):
    repeat_count = gwc._MAX_GROUNDING_CHUNKS_STORED + 20
    chunks = [{"web": {"uri": f"https://example{i}.com"}} for i in range(repeat_count)]
    content = [
        _candidate("Acme overview.", grounding_metadata={"webSearchQueries": ["Acme"], "groundingChunks": chunks})
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert len(result.grounding_chunks) == gwc._MAX_GROUNDING_CHUNKS_STORED
    assert result.grounding_chunks_total_count == repeat_count


def test_grounding_supports_beyond_storage_ceiling_are_capped_but_total_count_is_exact(monkeypatch):
    repeat_count = gwc._MAX_GROUNDING_SUPPORTS_STORED + 20
    supports = [{"segment": {"startIndex": i, "endIndex": i + 1}} for i in range(repeat_count)]
    content = [
        _candidate("Acme overview.", grounding_metadata={"webSearchQueries": ["Acme"], "groundingSupports": supports})
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert len(result.grounding_supports) == gwc._MAX_GROUNDING_SUPPORTS_STORED
    assert result.grounding_supports_total_count == repeat_count


# --- Search Suggestions (searchEntryPoint.renderedContent) ------------------


def test_search_entry_point_rendered_content_is_preserved_verbatim(monkeypatch):
    html = "<div class='search-suggestion'>...</div>"
    content = [
        _candidate(
            "Acme overview.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "searchEntryPoint": {"renderedContent": html},
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.rendered_content == html
    assert result.rendered_content_truncated is False


def test_search_entry_point_rendered_content_beyond_ceiling_is_truncated(monkeypatch):
    html = "A" * (gwc._MAX_RENDERED_CONTENT_CHARS + 500)
    content = [
        _candidate(
            "Acme overview.",
            grounding_metadata={
                "webSearchQueries": ["Acme"],
                "searchEntryPoint": {"renderedContent": html},
            },
        )
    ]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.rendered_content_truncated is True
    assert len(result.rendered_content) == gwc._MAX_RENDERED_CONTENT_CHARS


def test_no_search_entry_point_leaves_rendered_content_none(monkeypatch):
    content = [_candidate("Acme overview.", grounding_metadata={"webSearchQueries": ["Acme"]})]
    _patch_post(monkeypatch, _FakeResponse(200, _payload(content)))
    result = _fetch()
    assert result.rendered_content is None
    assert result.rendered_content_truncated is False


# --- fullSummary / fullSummaryTruncated -------------------------------------


def test_full_summary_is_the_complete_text_when_short(monkeypatch):
    text = "Acme is a company that makes widgets."
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate(text)])))
    result = _fetch()
    assert result.full_summary == text
    assert result.full_summary_truncated is False


def test_full_summary_is_truncated_at_the_safety_ceiling(monkeypatch):
    text = "A" * (gwc._FULL_SUMMARY_SAFETY_MAX_CHARS + 500)
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate(text)])))
    result = _fetch()
    assert result.full_summary_truncated is True
    assert len(result.full_summary) <= gwc._FULL_SUMMARY_SAFETY_MAX_CHARS + 1


def test_mentioned_is_a_case_insensitive_substring_check(monkeypatch):
    _patch_post(monkeypatch, _FakeResponse(200, _payload([_candidate("I know nothing about this company.")])))
    result = _fetch()
    assert result.mentioned is False
