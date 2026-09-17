import httpx

from services import gemini_client
from services.gemini_client import (
    GENERATE_CONTENT_URL_TEMPLATE,
    TRUNCATION_NOTE,
    fetch_gemini_observation,
)
from services.gemini_settings import GeminiCredentials

_CREDENTIALS = GeminiCredentials(api_key="gm-super-secret-key")

# Long enough to clear _SHORT_TEXT_TRUNCATION_THRESHOLD_CHARS and to end
# on a normal sentence (no unbalanced markdown) — the "definitely not
# truncated" fixture text for tests that care about is_truncated/note.
_NORMAL_LENGTH_TEXT = (
    "Acmeは、業務効率化ツールとして広く知られています。"
    "主に中小企業のバックオフィス業務を支援する用途で言及されることが多いです。"
)


def _candidate_response(text: str, finish_reason: str | None = None) -> dict:
    candidate: dict = {"content": {"parts": [{"text": text}]}}
    if finish_reason is not None:
        candidate["finishReason"] = finish_reason
    return {"candidates": [candidate]}


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


# --- finishReason / truncation detection ------------------------------------


def test_fetch_extracts_finish_reason_stop_on_success(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response(_NORMAL_LENGTH_TEXT, finish_reason="STOP"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert result.finish_reason == "STOP"


def test_fetch_does_not_flag_truncated_on_normal_stop_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response(_NORMAL_LENGTH_TEXT, finish_reason="STOP"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.is_truncated is False
    assert result.note is None


def test_fetch_flags_truncated_when_finish_reason_is_max_tokens(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response(_NORMAL_LENGTH_TEXT, finish_reason="MAX_TOKENS"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert result.finish_reason == "MAX_TOKENS"
    assert result.is_truncated is True
    assert result.note == TRUNCATION_NOTE


def test_fetch_flags_truncated_on_unbalanced_markdown_even_with_stop(monkeypatch):
    # Reproduces the exact production report: a response that reports
    # finishReason="STOP" (or omits it) but whose text visibly cuts off
    # mid-bold-span, e.g. "...と考えられます。 - **".
    cut_off_text = (
        "サイボウズは、Web検索ユーザーが比較検討する場面で、主に以下のように説明されると考えられます。 - **"
    )

    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response(cut_off_text, finish_reason="STOP"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert result.is_truncated is True
    assert result.note == TRUNCATION_NOTE


def test_fetch_flags_truncated_on_implausibly_short_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response("短い", finish_reason="STOP"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert result.is_truncated is True
    assert result.note == TRUNCATION_NOTE


def test_fetch_truncation_note_never_claims_gemini_has_no_information():
    # Copy requirement (feature/fix task): a truncated observation must
    # never be worded as "Gemini has no information about the brand" or
    # "the AI's internal state is cut off" — only as this one attempt's
    # output possibly being incomplete.
    assert "情報がない" not in TRUNCATION_NOTE
    assert "内部" not in TRUNCATION_NOTE


def test_fetch_connects_all_text_parts_across_multiple_parts(monkeypatch):
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "Acme is a well-known tool for teams."},
                        {"text": "It is often compared with similar SaaS products."},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert "Acme is a well-known tool for teams." in result.full_summary
    assert "It is often compared with similar SaaS products." in result.full_summary


def test_fetch_skips_non_text_parts_without_dropping_text_parts(monkeypatch):
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"functionCall": {"name": "not_text", "args": {}}},
                        {"text": _NORMAL_LENGTH_TEXT},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is True
    assert _NORMAL_LENGTH_TEXT in result.full_summary


def test_fetch_finish_reason_is_included_in_reason_when_safety_blocks_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"candidates": [{"finishReason": "SAFETY"}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert result.success is False
    assert result.finish_reason == "SAFETY"
    assert "SAFETY" in result.reason
    assert result.is_truncated is False
    assert result.note is None


def test_api_key_never_appears_in_reason_or_note_on_truncated_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json=_candidate_response(_NORMAL_LENGTH_TEXT, finish_reason="MAX_TOKENS"),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    result = fetch_gemini_observation(_CREDENTIALS, "Acme", model="gemini-2.5-flash", max_output_tokens=700)

    assert "gm-super-secret-key" not in result.reason
    assert "gm-super-secret-key" not in (result.note or "")
