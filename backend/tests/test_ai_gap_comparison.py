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
    assert parse_ai_gap_comparison_json(_PURE_JSON) == _PARSED


def test_parse_json_accepts_json_tagged_code_fence():
    fenced = "```json\n" + _PURE_JSON + "\n```"
    assert parse_ai_gap_comparison_json(fenced) == _PARSED


def test_parse_json_accepts_untagged_code_fence():
    fenced = "```\n" + _PURE_JSON + "\n```"
    assert parse_ai_gap_comparison_json(fenced) == _PARSED


def test_parse_json_accepts_leading_prose_before_json():
    prefixed = "以下が比較結果です。\n\n" + _PURE_JSON
    assert parse_ai_gap_comparison_json(prefixed) == _PARSED


def test_parse_json_accepts_trailing_prose_after_json():
    suffixed = _PURE_JSON + "\n\nこの比較は補助的な見立てです。"
    assert parse_ai_gap_comparison_json(suffixed) == _PARSED


def test_parse_json_accepts_prose_outside_a_code_fence():
    messy = "以下が比較結果です。\n\n```json\n" + _PURE_JSON + "\n```\n\nご参考に。"
    assert parse_ai_gap_comparison_json(messy) == _PARSED


def test_parse_json_returns_none_for_text_with_no_json_object():
    assert parse_ai_gap_comparison_json("申し訳ございませんが比較できません。") is None


def test_parse_json_returns_none_for_empty_string():
    assert parse_ai_gap_comparison_json("") is None


def test_parse_json_returns_none_for_a_json_array_not_an_object():
    assert parse_ai_gap_comparison_json('["a", "b"]') is None


def test_parse_json_returns_none_for_unbalanced_braces():
    assert parse_ai_gap_comparison_json("{not actually json") is None


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


def test_returns_failure_when_model_output_is_not_valid_json(monkeypatch):
    _mock_credentials(monkeypatch)
    _mock_claude_response(
        monkeypatch, json_body={"content": [{"type": "text", "text": "not json at all"}]}
    )

    outcome = generate_ai_gap_comparison(brand_name="Acme", result_json=_result_json())

    assert outcome.success is False
    assert outcome.unavailable is False


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
