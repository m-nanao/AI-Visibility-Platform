"""Verifies services/ai_gap_comparison.py's generate_ai_gap_comparison()
— the pure logic behind POST /analysis-runs/{id}/web-ai-gap/ai-comparison
(see tests/test_main_analysis_runs_ai_gap_comparison_api.py for the
HTTP-level wiring). Mocks httpx.post directly (same convention as
tests/test_claude_client.py) so these tests never make a real network
call.
"""

import httpx

from services import ai_gap_comparison
from services.ai_gap_comparison import CAUTION_TEXT, MESSAGES_API_URL, generate_ai_gap_comparison
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
