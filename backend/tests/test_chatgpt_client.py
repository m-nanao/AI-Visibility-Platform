import httpx

from services import chatgpt_client
from services.chatgpt_client import RESPONSES_API_URL, fetch_chatgpt_observation
from services.chatgpt_settings import ChatGptCredentials

_CREDENTIALS = ChatGptCredentials(api_key="sk-super-secret-key")


def test_fetch_posts_to_the_responses_api_url(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(
            200, json={"output_text": "Acme is a well-known tool."}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert seen_urls == [RESPONSES_API_URL]


def test_fetch_sends_authorization_bearer_header(monkeypatch):
    seen_headers = []

    def fake_post(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert seen_headers == [{"Authorization": "Bearer sk-super-secret-key", "Content-Type": "application/json"}]


def test_fetch_sends_model_input_max_output_tokens_and_store_false(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert len(seen_bodies) == 1
    body = seen_bodies[0]
    assert body["model"] == "gpt-5-mini"
    assert body["max_output_tokens"] == 700
    assert body["temperature"] == 0.2
    assert body["store"] is False
    assert body["input"][0]["role"] == "system"
    assert body["input"][1]["role"] == "user"
    assert "Acme" in body["input"][1]["content"]


def test_fetch_sends_the_given_temperature(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.7)

    assert seen_bodies[0]["temperature"] == 0.7


def test_fetch_system_prompt_forbids_browsing(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    system_content = seen_bodies[0]["input"][0]["content"]
    assert "Web検索は行わず" in system_content


def test_fetch_user_prompt_asks_for_three_to_five_sentences_and_no_references(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    user_content = seen_bodies[0]["input"][1]["content"]
    assert "3〜5文程度" in user_content
    assert "参照元やURLは挙げないでください" in user_content
    assert "Acme" in user_content


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert calls["count"] == 1


def test_fetch_extracts_output_text_field_when_present(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"output_text": "Acme is a well-known tool for teams."},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert "Acme is a well-known tool for teams." in result.full_summary


def test_fetch_falls_back_to_output_content_text_when_output_text_missing(monkeypatch):
    payload = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Acme helps teams collaborate."}],
            }
        ]
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert "Acme helps teams collaborate." in result.full_summary


def test_fetch_returns_unavailable_when_no_readable_text_found(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "no readable text" in result.reason


def test_fetch_marks_mentioned_true_when_brand_name_is_in_the_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200, json={"output_text": "Acme is a well-known tool."}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.mentioned is True


def test_fetch_marks_mentioned_false_when_brand_name_is_absent(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200, json={"output_text": "This is a generic answer."}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.mentioned is False


def test_fetch_truncates_summary_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": long_text}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert len(result.summary) <= 201
    assert len(result.summary) < len(result.full_summary)


def test_fetch_truncates_full_summary_far_beyond_the_short_summary_cap(monkeypatch):
    long_text = "Acme " + ("word " * 1000)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": long_text}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert len(result.full_summary) <= chatgpt_client._FULL_SUMMARY_MAX_CHARS + 1
    assert result.full_summary.endswith("…")


def test_fetch_success_reason(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.reason == "ChatGPT OpenAI API request succeeded."


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False


def test_password_never_appears_in_the_reason_string_on_any_failure_path(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert "sk-super-secret-key" not in result.reason


def test_api_key_never_appears_in_the_reason_string_on_success(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert "sk-super-secret-key" not in result.reason
    assert "sk-super-secret-key" not in (result.full_summary or "")
