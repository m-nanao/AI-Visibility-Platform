"""Verifies services/ai_gap_comparison.py's generate_ai_gap_comparison()
— the pure logic behind POST /analysis-runs/{id}/web-ai-gap/ai-comparison
(see tests/test_main_analysis_runs_ai_gap_comparison_api.py for the
HTTP-level wiring). Mocks httpx.post directly (same convention as
tests/test_claude_client.py) so these tests never make a real network
call.
"""

import httpx

from services import ai_gap_comparison
from services.ai_gap_comparison import (
    CAUTION_TEXT,
    MESSAGES_API_URL,
    REASON_CREDENTIALS_MISSING,
    REASON_EMPTY_MODEL_OUTPUT,
    REASON_JSON_DECODE_FAILED,
    REASON_NO_JSON_OBJECT_FOUND,
    REASON_NO_TEXT_CONTENT,
    generate_ai_gap_comparison,
    parse_ai_gap_comparison_json,
)
from services.claude_settings import ClaudeCredentials


def _real_web_ai_gap(**overrides) -> dict:
    web_ai_gap = {
        "status": "real",
        "webContext": {
            "summary": "当社はSEO対策・AI検索対策・AIO/GEO/LLMOに強いWeb集客支援会社です。",
            "sourceType": "web_fetch",
            "sourceUrl": "https://example.com/",
        },
        "aiContexts": [
            {"platform": "chatgpt", "summary": "一般的なブランディング会社として紹介される。", "status": "real"},
            {"platform": "claude", "summary": "ロゴやCI/VIを手掛けるブランディング会社。", "status": "real"},
        ],
        "gapSummary": "Web上では...",
        "suggestions": ["..."],
        "note": "既存の注意文",
    }
    web_ai_gap.update(overrides)
    return web_ai_gap


def _result_json(**overrides) -> dict:
    result_json = {"webAiGap": _real_web_ai_gap()}
    result_json.update(overrides)
    return result_json


# --- parse_ai_gap_comparison_json() (fix/ai-gap-comparison-json-parse) ----
#
# Direct unit tests for the JSON-extraction helper itself, independent
# of the Anthropic call/full generate_ai_gap_comparison() flow above —
# see that function's own tests further down for how a parse failure
# vs. success propagates into AiGapComparisonOutcome.

_PURE_JSON = '{"gapSummary": "x", "recommendations": ["y"]}'
_PARSED = {"gapSummary": "x", "recommendations": ["y"]}


def test_parse_json_accepts_pure_json():
    assert parse_ai_gap_comparison_json(_PURE_JSON) == (_PARSED, None)


def test_parse_json_accepts_json_tagged_code_fence():
    fenced = "```json\n" + _PURE_JSON + "\n```"
    assert parse_ai_gap_comparison_json(fenced) == (_PARSED, None)


def test_parse_json_accepts_untagged_code_fence():
    fenced = "```\n" + _PURE_JSON + "\n```"
    assert parse_ai_gap_comparison_json(fenced) == (_PARSED, None)


def test_parse_json_accepts_leading_prose_before_json():
    prefixed = "以下が比較結果です。\n\n" + _PURE_JSON
    assert parse_ai_gap_comparison_json(prefixed) == (_PARSED, None)


def test_parse_json_accepts_trailing_prose_after_json():
    suffixed = _PURE_JSON + "\n\nこの比較は補助的な見立てです。"
    assert parse_ai_gap_comparison_json(suffixed) == (_PARSED, None)


def test_parse_json_accepts_prose_outside_a_code_fence():
    messy = "以下が比較結果です。\n\n```json\n" + _PURE_JSON + "\n```\n\nご参考に。"
    assert parse_ai_gap_comparison_json(messy) == (_PARSED, None)


def test_parse_json_returns_none_and_no_json_object_found_for_text_with_no_json_object():
    parsed, reason = parse_ai_gap_comparison_json("申し訳ございませんが比較できません。")
    assert parsed is None
    assert reason == REASON_NO_JSON_OBJECT_FOUND


def test_parse_json_returns_none_and_no_json_object_found_for_empty_string():
    parsed, reason = parse_ai_gap_comparison_json("")
    assert parsed is None
    assert reason == REASON_NO_JSON_OBJECT_FOUND


def test_parse_json_returns_none_and_json_decode_failed_for_a_json_array_not_an_object():
    parsed, reason = parse_ai_gap_comparison_json('["a", "b"]')
    assert parsed is None
    assert reason == REASON_JSON_DECODE_FAILED


def test_parse_json_returns_none_and_no_json_object_found_for_unbalanced_braces_with_no_closing_brace():
    """No `}` anywhere means _extract_braces() never finds a candidate
    span at all — this is indistinguishable from "no JSON attempted"
    rather than "attempted and malformed"."""
    parsed, reason = parse_ai_gap_comparison_json("{not actually json")
    assert parsed is None
    assert reason == REASON_NO_JSON_OBJECT_FOUND


def test_parse_json_returns_none_and_json_decode_failed_for_malformed_json_with_braces():
    """A `{`...`}` span exists but is genuinely malformed (unquoted
    key) — this is a decode failure, not "no JSON object found"."""
    parsed, reason = parse_ai_gap_comparison_json('{gapSummary: "x", recommendations: [}')
    assert parsed is None
    assert reason == REASON_JSON_DECODE_FAILED


# --- Light syntax repair (fix/ai-gap-comparison-diagnostics) --------------


def test_parse_json_repairs_fullwidth_quotes():
    fullwidth = '{“gapSummary”: “x”, “recommendations”: [“y”]}'
    assert parse_ai_gap_comparison_json(fullwidth) == (_PARSED, None)


def test_parse_json_repairs_trailing_comma_before_closing_brace():
    trailing_comma = '{"gapSummary": "x", "recommendations": ["y"],}'
    assert parse_ai_gap_comparison_json(trailing_comma) == (_PARSED, None)


def test_parse_json_repairs_trailing_comma_inside_nested_array():
    trailing_comma = '{"gapSummary": "x", "recommendations": ["y",]}'
    assert parse_ai_gap_comparison_json(trailing_comma) == (_PARSED, None)


def test_parse_json_repairs_leading_and_trailing_invisible_characters():
    with_bom = "﻿" + _PURE_JSON + "​"
    assert parse_ai_gap_comparison_json(with_bom) == (_PARSED, None)


def _mock_credentials(monkeypatch, configured: bool = True):
    monkeypatch.setattr(
        ai_gap_comparison,
        "get_claude_credentials",
        lambda: ClaudeCredentials(api_key="sk-ant-secret") if configured else None,
    )


def _mock_claude_response(monkeypatch, *, status_code=200, json_body=None, text_body=None, raise_error=False):
    def fake_post(url, **kwargs):
        if raise_error:
            raise httpx.ConnectError("boom", request=httpx.Request("POST", url))
        if text_body is not None:
            return httpx.Response(status_code, content=text_body, request=httpx.Request("POST", url))
        return httpx.Response(status_code, json=json_body, request=httpx.Request("POST", url))

    monkeypatch.setattr(ai_gap_comparison.httpx, "post", fake_post)


def _ai_comparison_json_text() -> str:
    return (
        '{"matchedPoints": ["SEO支援会社として言及されている"], '
        '"webStrongAiWeak": ["AI検索対策/LLMOが強いが弱い"], '
        '"aiStrongWebWeak": ["一般的なブランディング会社として説明されやすい"], '
        '"gapSummary": "WebとAIで説明が異なります。", '
        '"recommendations": ["社名の近くにSEO対策を明記する"]}'
    )


# --- not even attempted (unavailable=True, main.py returns 503) -----------


def test_returns_unavailable_when_web_ai_gap_missing(monkeypatch):
    _mock_credentials(monkeypatch)
    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json={})

    assert outcome.success is False
    assert outcome.unavailable is True
    assert outcome.comparison is None


def test_returns_unavailable_when_web_ai_gap_status_is_unavailable(monkeypatch):
    _mock_credentials(monkeypatch)
    result_json = _result_json(webAiGap=_real_web_ai_gap(status="unavailable", webContext=None, aiContexts=[]))

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=result_json)

    assert outcome.success is False
    assert outcome.unavailable is True


def test_returns_unavailable_when_web_context_summary_is_empty(monkeypatch):
    _mock_credentials(monkeypatch)
    result_json = _result_json(
        webAiGap=_real_web_ai_gap(webContext={"summary": "", "sourceType": "web_fetch", "sourceUrl": None})
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=result_json)

    assert outcome.success is False
    assert outcome.unavailable is True


def test_returns_unavailable_when_no_ai_context_has_a_summary(monkeypatch):
    _mock_credentials(monkeypatch)
    result_json = _result_json(webAiGap=_real_web_ai_gap(aiContexts=[]))

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=result_json)

    assert outcome.success is False
    assert outcome.unavailable is True


def test_returns_unavailable_when_claude_api_key_is_not_configured(monkeypatch):
    _mock_credentials(monkeypatch, configured=False)

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is True
    assert outcome.reason == "Anthropic API key is not configured."
    assert outcome.internal_reason == REASON_CREDENTIALS_MISSING


def test_never_calls_anthropic_when_input_is_insufficient(monkeypatch):
    _mock_credentials(monkeypatch)
    post_calls = []
    monkeypatch.setattr(
        ai_gap_comparison.httpx, "post", lambda *a, **k: post_calls.append((a, k))
    )

    generate_ai_gap_comparison(brand_name="Acme", result_json={})

    assert post_calls == []


# --- attempted and failed (unavailable=False, main.py returns 502) --------


def test_returns_failure_on_network_error(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, raise_error=True)

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False


def test_returns_failure_on_non_200_status(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, status_code=500, json_body={"error": "boom"})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False


def test_returns_failure_on_invalid_json_response(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, status_code=200, text_body=b"not json")

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False


def test_returns_failure_when_no_text_block_in_response(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, json_body={"content": []})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False
    assert outcome.internal_reason == REASON_NO_TEXT_CONTENT


def test_returns_no_text_content_when_only_non_text_content_blocks_are_present(monkeypatch):
    """パターン: Anthropicがtext以外のcontent block(例: tool_use)だけを
    返した場合も no_text_content として扱う。"""
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch,
        json_body={"content": [{"type": "tool_use", "id": "x", "input": {}}]},
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False
    assert outcome.internal_reason == REASON_NO_TEXT_CONTENT


def test_returns_empty_model_output_when_text_block_is_blank(monkeypatch):
    """text typeのcontent blockは存在するが、本文が空文字/空白のみの場合
    は no_text_content ではなく empty_model_output として区別する。"""
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": "   "}]}
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False
    assert outcome.internal_reason == REASON_EMPTY_MODEL_OUTPUT


def test_returns_failure_when_model_output_is_not_valid_json(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": "not json at all"}]}
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False
    assert outcome.internal_reason == REASON_NO_JSON_OBJECT_FOUND


# --- success ----------------------------------------------------------------


def test_success_parses_comparison_fields(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch,
        json_body={"content": [{"type": "text", "text": _ai_comparison_json_text()}]},
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison is not None
    assert outcome.comparison.matchedPoints == ["SEO支援会社として言及されている"]
    assert outcome.comparison.webStrongAiWeak == ["AI検索対策/LLMOが強いが弱い"]
    assert outcome.comparison.aiStrongWebWeak == ["一般的なブランディング会社として説明されやすい"]
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"
    assert outcome.comparison.recommendations == ["社名の近くにSEO対策を明記する"]
    assert outcome.comparison.status == "real"
    assert outcome.comparison.method == "ai_comparison"


def test_success_always_uses_the_fixed_caution_text_regardless_of_model_output(monkeypatch):
    _mock_credentials(monkeypatch)
    text = (
        '{"matchedPoints": [], "webStrongAiWeak": [], "aiStrongWebWeak": [], '
        '"gapSummary": null, "recommendations": [], '
        '"caution": "AIは絶対にこう認識しています"}'
    )
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": text}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.caution == CAUTION_TEXT


def test_success_strips_markdown_code_fence_from_model_output(monkeypatch):
    _mock_credentials(monkeypatch)
    fenced = "```json\n" + _ai_comparison_json_text() + "\n```"
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": fenced}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"


def test_success_strips_code_fence_without_json_language_tag(monkeypatch):
    """パターンC: ```json ではなく ``` だけのコードフェンス。"""
    _mock_credentials(monkeypatch)
    fenced = "```\n" + _ai_comparison_json_text() + "\n```"
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": fenced}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"


def test_success_extracts_json_with_leading_prose(monkeypatch):
    """パターンD: 前置き文 + JSON。"""
    _mock_credentials(monkeypatch)
    prefixed = "以下が比較結果です。\n\n" + _ai_comparison_json_text()
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": prefixed}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"


def test_success_extracts_json_with_trailing_prose(monkeypatch):
    """パターンE: JSON + 後置き文。"""
    _mock_credentials(monkeypatch)
    suffixed = _ai_comparison_json_text() + "\n\nこの比較は補助的な見立てです。"
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": suffixed}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"


def test_success_extracts_json_with_leading_and_trailing_prose_inside_fence(monkeypatch):
    """前置き文・後置き文がコードフェンスの外にある、さらに崩れたケース。"""
    _mock_credentials(monkeypatch)
    messy = (
        "以下が比較結果です。\n\n```json\n"
        + _ai_comparison_json_text()
        + "\n```\n\nご参考にしてください。"
    )
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": messy}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary == "WebとAIで説明が異なります。"


def test_success_defaults_missing_gap_summary_and_recommendations(monkeypatch):
    """必須扱いのフィールドが欠けていてもdefault補完され、失敗しない。"""
    _mock_credentials(monkeypatch)
    text = '{"matchedPoints": ["a"], "webStrongAiWeak": [], "aiStrongWebWeak": []}'
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": text}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.gapSummary is None
    assert outcome.comparison.recommendations == []


def test_success_coerces_a_bare_string_matched_points_into_a_list(monkeypatch):
    _mock_credentials(monkeypatch)
    text = (
        '{"matchedPoints": "単一の一致点です", "webStrongAiWeak": [], "aiStrongWebWeak": [], '
        '"gapSummary": "x", "recommendations": []}'
    )
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": text}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.matchedPoints == ["単一の一致点です"]


def test_success_coerces_a_bare_string_recommendations_into_a_list(monkeypatch):
    _mock_credentials(monkeypatch)
    text = (
        '{"matchedPoints": [], "webStrongAiWeak": [], "aiStrongWebWeak": [], '
        '"gapSummary": "x", "recommendations": "単一の改善ヒントです"}'
    )
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": text}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.recommendations == ["単一の改善ヒントです"]


def test_returns_parse_failed_reason_when_no_json_object_exists_at_all(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch,
        json_body={"content": [{"type": "text", "text": "申し訳ございませんが比較できません。"}]},
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False
    assert outcome.reason == (
        "AI比較の生成結果を読み取れませんでした。時間をおいて再度お試しください。"
    )


def test_parse_failure_never_logs_the_raw_model_output(monkeypatch, caplog):
    _mock_credentials(monkeypatch)
    secret_looking_text = "no json here, but sk-ant-shouldnotleak and brand secrets"
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": secret_looking_text}]}
    )

    import logging

    with caplog.at_level(logging.WARNING):
        generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert secret_looking_text not in caplog.text


def test_success_truncates_lists_to_max_five_items(monkeypatch):
    _mock_credentials(monkeypatch)
    text = (
        '{"matchedPoints": ["a", "b", "c", "d", "e", "f", "g"], '
        '"webStrongAiWeak": [], "aiStrongWebWeak": [], '
        '"gapSummary": "x", "recommendations": []}'
    )
    _mock_claude_response(monkeypatch, json_body={"content": [{"type": "text", "text": text}]})

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is True
    assert outcome.comparison.matchedPoints == ["a", "b", "c", "d", "e"]


def test_posts_to_the_messages_api_url_with_expected_headers(monkeypatch):
    _mock_credentials(monkeypatch)
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers")
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": _ai_comparison_json_text()}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(ai_gap_comparison.httpx, "post", fake_post)

    generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert seen["url"] == MESSAGES_API_URL
    assert seen["headers"]["x-api-key"] == "sk-ant-secret"


def test_never_includes_api_key_in_the_failure_reason(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, raise_error=True)

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert "sk-ant-secret" not in outcome.reason


def test_does_not_call_any_other_provider_or_fetch(monkeypatch):
    """Only httpx.post to the Anthropic Messages API is touched — no
    DataForSEO/Common Crawl/web fetch/other provider module is
    imported or called by this service at all."""
    import services.ai_gap_comparison as module

    assert not hasattr(module, "search_common_crawl_domain")
    assert not hasattr(module, "fetch_url_texts")
    assert not hasattr(module, "build_chatgpt_observation")
    assert not hasattr(module, "build_gemini_observation")


# --- _extract_output_text() (fix/ai-gap-comparison-diagnostics) -----------
#
# Direct unit tests for the content-extraction helper, independent of
# the full generate_ai_gap_comparison() flow — isolates exactly what
# diagnostics are captured (content_types/text_block_count) and which
# of the two previously-indistinguishable failure stages
# (no_text_content vs. empty_model_output) applies.


def test_extract_output_text_joins_multiple_text_blocks():
    extraction = ai_gap_comparison._extract_output_text(
        {"content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]}
    )

    assert extraction.text == "first\n\nsecond"
    assert extraction.content_types == ["text", "text"]
    assert extraction.text_block_count == 2
    assert extraction.reason is None


def test_extract_output_text_no_text_content_when_payload_is_not_a_dict():
    extraction = ai_gap_comparison._extract_output_text("not a dict")

    assert extraction.text is None
    assert extraction.reason == REASON_NO_TEXT_CONTENT


def test_extract_output_text_no_text_content_when_content_is_missing():
    extraction = ai_gap_comparison._extract_output_text({})

    assert extraction.text is None
    assert extraction.reason == REASON_NO_TEXT_CONTENT
    assert extraction.content_types == []


def test_extract_output_text_no_text_content_when_only_non_text_blocks_present():
    extraction = ai_gap_comparison._extract_output_text(
        {"content": [{"type": "tool_use", "id": "x"}]}
    )

    assert extraction.text is None
    assert extraction.reason == REASON_NO_TEXT_CONTENT
    assert extraction.content_types == ["tool_use"]
    assert extraction.text_block_count == 0


def test_extract_output_text_empty_model_output_when_text_block_is_blank():
    extraction = ai_gap_comparison._extract_output_text(
        {"content": [{"type": "text", "text": "   "}]}
    )

    assert extraction.text is None
    assert extraction.reason == REASON_EMPTY_MODEL_OUTPUT
    assert extraction.content_types == ["text"]
    assert extraction.text_block_count == 1


# --- Safe diagnostic logging (fix/ai-gap-comparison-diagnostics) ---------


def test_parse_failure_logs_safe_diagnostics_including_content_types_and_length(monkeypatch, caplog):
    import logging

    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": "not json at all"}]}
    )

    with caplog.at_level(logging.WARNING):
        generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json(), analysis_run_id="run-123")

    assert "no_json_object_found" in caplog.text
    assert "run-123" in caplog.text
    assert "content_types=['text']" in caplog.text
    assert "raw_length=15" in caplog.text


def test_content_extraction_failure_logs_safe_diagnostics(monkeypatch, caplog):
    import logging

    _mock_credentials(monkeypatch)
    _mock_claude_response(monkeypatch, json_body={"content": []})

    with caplog.at_level(logging.WARNING):
        generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json(), analysis_run_id="run-456")

    assert "no_text_content" in caplog.text
    assert "run-456" in caplog.text


def test_log_lines_never_include_the_api_key(monkeypatch, caplog):
    import logging

    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": "not json at all"}]}
    )

    with caplog.at_level(logging.WARNING):
        generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert "sk-ant-secret" not in caplog.text


# --- SYSTEM_PROMPT content (fix/ai-gap-comparison-diagnostics) -----------


def test_system_prompt_forbids_markdown_and_prose_and_requires_json_only():
    prompt = ai_gap_comparison.SYSTEM_PROMPT

    assert "JSONオブジェクト1つのみ" in prompt
    assert "Markdown" in prompt
    assert "{" in prompt and "}" in prompt
    assert "recommendations" in prompt
    assert "1件以上" in prompt
