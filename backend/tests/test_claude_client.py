import httpx

from services import claude_client
from services.claude_client import ANTHROPIC_API_VERSION, MESSAGES_API_URL, fetch_claude_observation
from services.claude_settings import ClaudeCredentials

_CREDENTIALS = ClaudeCredentials(api_key="sk-ant-super-secret-key")


def test_fetch_posts_to_the_messages_api_url(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme is a well-known tool."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert seen_urls == [MESSAGES_API_URL]


def test_fetch_sends_x_api_key_and_anthropic_version_headers(monkeypatch):
    seen_headers = []

    def fake_post(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert seen_headers == [
        {
            "x-api-key": "sk-ant-super-secret-key",
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }
    ]


def test_fetch_sends_model_max_tokens_top_level_system_and_user_message(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert len(seen_bodies) == 1
    body = seen_bodies[0]
    assert body["model"] == "claude-sonnet-4-5"
    assert body["max_tokens"] == 700
    # system prompt must be a top-level field, NOT a message with
    # role="system" inside `messages` (Anthropic Messages API shape).
    assert isinstance(body["system"], str) and body["system"]
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"
    assert "Acme" in body["messages"][0]["content"]


def test_fetch_system_prompt_forbids_browsing(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert "Web検索は行わず" in seen_bodies[0]["system"]


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert calls["count"] == 1


def test_fetch_extracts_text_from_content_blocks(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "Acme is a well-known tool for teams."},
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is True
    assert "Acme is a well-known tool for teams." in result.full_summary


def test_fetch_ignores_non_text_content_blocks(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={
                "content": [
                    {"type": "tool_use", "id": "x", "name": "y", "input": {}},
                    {"type": "text", "text": "Acme helps teams collaborate."},
                ]
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is True
    assert "Acme helps teams collaborate." in result.full_summary


def test_fetch_returns_unavailable_when_no_readable_text_found(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"content": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is False
    assert "no readable text" in result.reason


def test_fetch_marks_mentioned_true_when_brand_name_is_in_the_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme is a well-known tool."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.mentioned is True


def test_fetch_marks_mentioned_false_when_brand_name_is_absent(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "This is a generic answer."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.mentioned is False


def test_fetch_success_reason(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.reason == "Claude Anthropic API request succeeded."


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", raise_timeout)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is False


def test_api_key_never_appears_in_the_reason_string_on_any_path(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", raise_timeout)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert "sk-ant-super-secret-key" not in result.reason


def test_api_key_never_appears_in_the_reason_or_summary_on_success(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Acme."}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert "sk-ant-super-secret-key" not in result.reason
    assert "sk-ant-super-secret-key" not in (result.full_summary or "")


def test_fetch_truncates_summary_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)

    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"content": [{"type": "text", "text": long_text}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    result = fetch_claude_observation(_CREDENTIALS, "Acme", model="claude-sonnet-4-5", max_output_tokens=700)

    assert result.success is True
    assert len(result.summary) <= 201
    assert len(result.summary) < len(result.full_summary)
