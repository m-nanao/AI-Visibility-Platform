import httpx

from services import gemini_client
from services.gemini_client import GENERATE_CONTENT_URL_TEMPLATE, fetch_gemini_observation
from services.gemini_settings import GeminiCredentials

_CREDENTIALS = GeminiCredentials(api_key="gm-super-secret-key")


def _candidate_response(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_fetch_posts_to_the_generate_content_url_for_the_given_model(monkeypatch):
    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=_candidate_response("Acme is a well-known tool."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert seen_urls == [GENERATE_CONTENT_URL_TEMPLATE.format(model="gemini-2.5-flash")]


def test_fetch_sends_x_goog_api_key_header_not_in_url(monkeypatch):
    seen_urls = []
    seen_headers = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert seen_headers == [{"x-goog-api-key": "gm-super-secret-key", "content-type": "application/json"}]
    # The API key must never appear in the URL itself (e.g. as a `?key=`
    # query parameter), since URLs are far more likely to be logged.
    assert "gm-super-secret-key" not in seen_urls[0]


def test_fetch_sends_contents_system_instruction_and_generation_config(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert len(seen_bodies) == 1
    body = seen_bodies[0]
    assert body["generationConfig"] == {"maxOutputTokens": 700}
    assert len(body["contents"]) == 1
    assert body["contents"][0]["role"] == "user"
    assert "Acme" in body["contents"][0]["parts"][0]["text"]
    assert isinstance(body["systemInstruction"]["parts"][0]["text"], str)
    assert body["systemInstruction"]["parts"][0]["text"]


def test_fetch_system_prompt_forbids_browsing(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert "Web検索は行わず" in seen_bodies[0]["systemInstruction"]["parts"][0]["text"]


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert calls["count"] == 1


def test_fetch_extracts_text_from_candidates_content_parts(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response("Acme is a well-known tool for teams."),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert "Acme is a well-known tool for teams." in result.full_summary


def test_fetch_returns_unavailable_when_no_candidates(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"candidates": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False
    assert "no readable text" in result.reason


def test_fetch_returns_unavailable_when_candidate_has_no_content(monkeypatch):
    # Can happen when a response is blocked by a safety filter.
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "SAFETY"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False
    assert "no readable text" in result.reason


def test_fetch_marks_mentioned_true_when_brand_name_is_in_the_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response("Acme is a well-known tool."),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.mentioned is True


def test_fetch_marks_mentioned_false_when_brand_name_is_absent(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response("This is a generic answer."),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.mentioned is False


def test_fetch_success_reason(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.reason == "Gemini Google API request succeeded."


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", raise_timeout)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False


def test_api_key_never_appears_in_the_reason_string_on_any_path(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", raise_timeout)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert "gm-super-secret-key" not in result.reason


def test_api_key_never_appears_in_the_reason_or_summary_on_success(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json=_candidate_response("Acme."), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert "gm-super-secret-key" not in result.reason
    assert "gm-super-secret-key" not in (result.full_summary or "")


def test_fetch_truncates_summary_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=_candidate_response(long_text), request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert len(result.summary) <= 201
    assert len(result.summary) < len(result.full_summary)
