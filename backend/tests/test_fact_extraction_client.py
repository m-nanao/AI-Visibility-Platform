"""Tests for services/fact_extraction_client.py (Task 6-D-5C-2,
feature/claude-fact-extraction-mvp).

Never calls a real Anthropic API: httpx.post is monkeypatched.
"""

from dataclasses import dataclass

import httpx
import pytest

import services.fact_extraction_client as fec
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

    monkeypatch.setattr(fec.httpx, "post", fake_post)
    return calls


def _text_response(text: str, status_code: int = 200) -> _FakeResponse:
    return _FakeResponse(status_code, {"content": [{"type": "text", "text": text}]})


def _claim_json(
    category="representative",
    nature="objective_fact",
    state="asserted",
    claim_text="代表者は山田太郎",
    source_text="代表者は山田太郎です",
    start=0,
    end=10,
) -> dict:
    item = {
        "claimCategory": category,
        "claimNature": nature,
        "answerState": state,
        "claimText": claim_text,
    }
    if state != "not_mentioned":
        item["sourceText"] = source_text
        item["sourceStartIndex"] = start
        item["sourceEndIndex"] = end
    item["uncertaintyMarkers"] = []
    return item


def _fetch(monkeypatch, response, *, raises: Exception | None = None):
    calls = _patch_post(monkeypatch, response, raises=raises)
    result = fec.fetch_fact_extraction(
        CREDENTIALS, "Acme", "代表者は山田太郎です。", model="claude-sonnet-5-5", max_output_tokens=4000
    )
    return result, calls


# --- 1 call per attempt, single request shape -----------------------------


def test_makes_exactly_one_http_request():
    pass  # covered by _patch_post's calls list in other tests


def test_single_request_uses_given_model_and_api_key(monkeypatch):
    response = _text_response('{"claims": []}')
    result, calls = _fetch(monkeypatch, response)
    assert len(calls) == 1
    assert calls[0]["json"]["model"] == "claude-sonnet-5-5"
    assert calls[0]["headers"]["x-api-key"] == "test-key"
    assert result.success is True


# --- normal JSON parsing ---------------------------------------------------


def test_parses_normal_json_with_one_claim(monkeypatch):
    response = _text_response('{"claims": [%s]}' % __import__("json").dumps(_claim_json()))
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert len(result.candidates) == 1
    assert result.candidates[0].claimCategory == "representative"


def test_parses_code_fenced_json(monkeypatch):
    import json as _json

    fenced = "```json\n" + _json.dumps({"claims": [_claim_json()]}) + "\n```"
    response = _text_response(fenced)
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert len(result.candidates) == 1


def test_parses_json_with_leading_and_trailing_sentences(monkeypatch):
    import json as _json

    text = "以下が結果です。\n" + _json.dumps({"claims": []}) + "\nご確認ください。"
    response = _text_response(text)
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert result.candidates == []


def test_empty_claims_array_is_a_valid_success(monkeypatch):
    response = _text_response('{"claims": []}')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert result.candidates == []
    assert result.malformed_candidate_count == 0


# --- malformed / unparseable JSON ------------------------------------------


def test_completely_invalid_json_is_an_explicit_failure(monkeypatch):
    response = _text_response("これはJSONではなく普通の文章です。")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_NO_JSON_OBJECT_FOUND


def test_malformed_json_object_is_an_explicit_failure(monkeypatch):
    # Has a {...} shape but invalid syntax inside (trailing comma AND
    # an unquoted bare word) — not repairable by _repair_json_candidate().
    response = _text_response('{"claims": [1, 2, nonsense,]}')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_JSON_DECODE_FAILED


def test_no_brace_at_all_is_no_json_object_found(monkeypatch):
    response = _text_response('{"claims": [')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_NO_JSON_OBJECT_FOUND


def test_missing_claims_field_is_an_explicit_failure(monkeypatch):
    response = _text_response('{"notClaims": []}')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_CLAIMS_FIELD_MISSING_OR_INVALID


def test_claims_field_not_a_list_is_an_explicit_failure(monkeypatch):
    response = _text_response('{"claims": "not a list"}')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_CLAIMS_FIELD_MISSING_OR_INVALID


# --- per-item malformed candidate rejection (never aborts the batch) ------


def test_one_malformed_item_is_dropped_without_aborting_the_whole_batch(monkeypatch):
    import json as _json

    good = _claim_json()
    bad = {"claimCategory": "not_a_real_category", "claimNature": "objective_fact", "answerState": "not_mentioned", "claimText": "x"}
    response = _text_response(_json.dumps({"claims": [good, bad]}))
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert len(result.candidates) == 1
    assert result.malformed_candidate_count == 1


def test_a_non_dict_item_is_counted_as_malformed(monkeypatch):
    import json as _json

    response = _text_response(_json.dumps({"claims": ["not a dict", _claim_json()]}))
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert len(result.candidates) == 1
    assert result.malformed_candidate_count == 1


def test_not_mentioned_item_without_span_parses_successfully(monkeypatch):
    import json as _json

    item = _claim_json(category="numerical_achievement", state="not_mentioned", claim_text="言及なし")
    response = _text_response(_json.dumps({"claims": [item]}))
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert len(result.candidates) == 1
    assert result.candidates[0].answerState == "not_mentioned"
    assert result.candidates[0].sourceText is None


# --- network / HTTP errors -------------------------------------------------


def test_network_error_is_reported_without_raising(monkeypatch):
    result, _ = _fetch(monkeypatch, None, raises=httpx.ConnectTimeout("timeout"))
    assert result.success is False
    assert result.reason == fec.REASON_NETWORK_ERROR


def test_non_200_response_is_reported_as_http_error(monkeypatch):
    response = _FakeResponse(500, {"error": "internal"})
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_HTTP_ERROR


def test_no_text_content_block_is_reported(monkeypatch):
    response = _FakeResponse(200, {"content": [{"type": "tool_use"}]})
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_NO_TEXT_CONTENT


def test_blank_text_block_is_reported_as_empty_output(monkeypatch):
    response = _text_response("   ")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_EMPTY_MODEL_OUTPUT


# --- prompt never asks the model to self-report provenance ---------------


def test_system_prompt_never_asks_for_source_platform_or_model_fields():
    assert "sourcePlatform" not in fec.SYSTEM_PROMPT
    assert "observationMethod" not in fec.SYSTEM_PROMPT
    assert "sourceModel" not in fec.SYSTEM_PROMPT
    assert "extractionModel" not in fec.SYSTEM_PROMPT


def test_user_prompt_marks_original_text_as_data_not_instructions():
    body = fec.build_fact_extraction_request_body(
        "Acme", "回答本文", model="claude-sonnet-5-5", max_output_tokens=4000
    )
    user_content = body["messages"][0]["content"]
    assert "回答本文" in user_content
    assert "データ" in user_content


# --- Task 6-D-5C-2A final review: stop_reason checked before parsing ------


def _text_response_with_stop_reason(text: str, stop_reason: str, status_code: int = 200) -> _FakeResponse:
    return _FakeResponse(
        status_code, {"content": [{"type": "text", "text": text}], "stop_reason": stop_reason}
    )


def test_max_tokens_stop_reason_is_a_hard_failure_even_with_valid_looking_json(monkeypatch):
    # The captured text happens to be perfectly valid, complete JSON —
    # but Claude itself reports the generation was cut off by
    # max_tokens, so it must still be rejected, never trusted.
    response = _text_response_with_stop_reason('{"claims": []}', "max_tokens")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_MAX_TOKENS_TRUNCATED


def test_max_tokens_stop_reason_rejects_even_before_attempting_to_parse(monkeypatch):
    # Genuinely truncated (invalid) JSON, with stop_reason confirming why.
    response = _text_response_with_stop_reason('{"claims": [{"claimCategory": "bus', "max_tokens")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_MAX_TOKENS_TRUNCATED


def test_end_turn_stop_reason_proceeds_normally(monkeypatch):
    response = _text_response_with_stop_reason('{"claims": []}', "end_turn")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True


def test_missing_stop_reason_proceeds_normally_for_backward_compatibility(monkeypatch):
    # Older/mock responses in this test file never set stop_reason at
    # all — must not be treated as a failure.
    response = _text_response('{"claims": []}')
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True


def test_unexpected_stop_reason_is_rejected(monkeypatch):
    response = _text_response_with_stop_reason('{"claims": []}', "refusal")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_UNEXPECTED_STOP_REASON


def test_stop_sequence_stop_reason_is_rejected_as_unexpected(monkeypatch):
    response = _text_response_with_stop_reason('{"claims": []}', "stop_sequence")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_UNEXPECTED_STOP_REASON


# --- multiple / mixed content blocks ---------------------------------------


def test_multiple_text_blocks_are_concatenated(monkeypatch):
    response = _FakeResponse(
        200,
        {
            "content": [
                {"type": "text", "text": '{"claims": ['},
                {"type": "text", "text": "]}"},
            ]
        },
    )
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert result.candidates == []


def test_tool_use_block_without_any_text_block_is_no_text_content(monkeypatch):
    response = _FakeResponse(200, {"content": [{"type": "tool_use", "id": "x", "input": {}}]})
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert result.reason == fec.REASON_NO_TEXT_CONTENT


def test_mixed_tool_use_and_text_blocks_uses_only_the_text_block(monkeypatch):
    response = _FakeResponse(
        200,
        {
            "content": [
                {"type": "tool_use", "id": "x", "input": {}},
                {"type": "text", "text": '{"claims": []}'},
            ]
        },
    )
    result, _ = _fetch(monkeypatch, response)
    assert result.success is True
    assert result.candidates == []


# --- secrets/original text never leak into a reported reason --------------


def test_failure_reason_never_contains_the_api_key(monkeypatch):
    response = _FakeResponse(500, {"error": "internal"})
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert "test-key" not in (result.reason or "")


def test_failure_reason_never_contains_the_original_text(monkeypatch):
    response = _text_response("これはJSONではなく普通の文章です。")
    result, _ = _fetch(monkeypatch, response)
    assert result.success is False
    assert "代表者は山田太郎です" not in (result.reason or "")
