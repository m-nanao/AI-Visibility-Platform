import httpx

from services import chatgpt_client
from services.ai_observation_prompts import build_user_prompt
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

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert seen_urls == [RESPONSES_API_URL]


def test_fetch_sends_authorization_bearer_header(monkeypatch):
    seen_headers = []

    def fake_post(url, **kwargs):
        seen_headers.append(kwargs.get("headers"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert seen_headers == [{"Authorization": "Bearer sk-super-secret-key", "Content-Type": "application/json"}]


def test_fetch_sends_model_input_max_output_tokens_and_store_false(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert len(seen_bodies) == 1
    body = seen_bodies[0]
    assert body["model"] == "gpt-4.1-mini"
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

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.7)

    assert seen_bodies[0]["temperature"] == 0.7


# --- should_send_temperature / per-model temperature omission --------------


def test_should_send_temperature_is_true_for_gpt41_mini():
    assert chatgpt_client.should_send_temperature("gpt-4.1-mini") is True


def test_should_send_temperature_is_true_for_gpt4o_mini():
    assert chatgpt_client.should_send_temperature("gpt-4o-mini") is True


def test_should_send_temperature_is_false_for_gpt5_mini():
    assert chatgpt_client.should_send_temperature("gpt-5-mini") is False


def test_should_send_temperature_is_false_for_gpt5():
    assert chatgpt_client.should_send_temperature("gpt-5") is False


def test_should_send_temperature_is_case_insensitive():
    assert chatgpt_client.should_send_temperature("GPT-5-MINI") is False
    assert chatgpt_client.should_send_temperature("GPT-4.1-MINI") is True


def test_fetch_includes_temperature_for_gpt41_mini(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert "temperature" in seen_bodies[0]
    assert seen_bodies[0]["temperature"] == 0.2


def test_fetch_includes_temperature_for_gpt4o_mini(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4o-mini", max_output_tokens=700, temperature=0.2)

    assert "temperature" in seen_bodies[0]
    assert seen_bodies[0]["temperature"] == 0.2


def test_fetch_omits_temperature_for_gpt5_mini(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert "temperature" not in seen_bodies[0]


def test_fetch_omits_temperature_for_gpt5(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5", max_output_tokens=700, temperature=0.2)

    assert "temperature" not in seen_bodies[0]


def test_fetch_omits_temperature_for_gpt5_mini_with_mixed_case(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="GPT-5-MINI", max_output_tokens=700, temperature=0.2)

    assert "temperature" not in seen_bodies[0]


def test_fetch_still_sends_model_max_output_tokens_and_store_false_for_gpt5_mini(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    body = seen_bodies[0]
    assert body["model"] == "gpt-5-mini"
    assert body["max_output_tokens"] == 700
    assert body["store"] is False
    assert body["input"][0]["role"] == "system"
    assert body["input"][1]["role"] == "user"


def test_fetch_gpt5_mini_success_response_still_parses_correctly(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"output_text": "Acme is a well-known tool for teams."},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert result.mentioned is True
    assert "Acme is a well-known tool for teams." in result.full_summary
    assert result.reason == "ChatGPT OpenAI API request succeeded."


def test_fetch_api_key_never_appears_in_reason_for_gpt5_mini_failure(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(400, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "400" in result.reason
    assert "sk-super-secret-key" not in result.reason


def test_fetch_system_prompt_forbids_browsing(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    system_content = seen_bodies[0]["input"][0]["content"]
    assert "Web検索は行わず" in system_content


def test_fetch_user_prompt_uses_the_shared_unified_prompt(monkeypatch):
    """Task 6-C Review Prep 1: ChatGPT now uses the exact same user
    prompt as Claude/Gemini (services/ai_observation_prompts.py's
    build_user_prompt()), so all three providers ask the same
    question about the brand."""
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    user_content = seen_bodies[0]["input"][1]["content"]
    assert user_content == build_user_prompt("Acme")
    assert "対象を具体的に識別できる場合は" in user_content
    assert "名称の印象だけから事業内容や特徴を推測しないでください。" in user_content
    assert "Acme" in user_content


def test_fetch_sends_exactly_one_request(monkeypatch):
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert calls["count"] == 1


def test_fetch_extracts_output_text_field_when_present(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"output_text": "Acme is a well-known tool for teams."},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

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

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert "Acme helps teams collaborate." in result.full_summary


def test_fetch_returns_unavailable_when_no_readable_text_found(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output": []}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "no readable text" in result.reason


def test_fetch_marks_mentioned_true_when_brand_name_is_in_the_text(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200, json={"output_text": "Acme is a well-known tool."}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.mentioned is True


def test_fetch_marks_mentioned_false_when_brand_name_is_absent(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(
            200, json={"output_text": "This is a generic answer."}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.mentioned is False


def test_fetch_truncates_summary_to_a_short_excerpt(monkeypatch):
    long_text = "Acme " + ("word " * 100)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": long_text}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is True
    assert len(result.summary) <= 201
    assert len(result.summary) < len(result.full_summary)


def test_fetch_preserves_the_complete_full_summary_well_beyond_the_old_2500_char_cap(monkeypatch):
    """Task 6-D-3D: fullSummary must hold the complete answer text for
    downstream fact-comparison/diff use — a ~5000-char answer (well
    under the new, far larger safety ceiling) must come back intact,
    not silently cut at the old display-oriented 2500-char limit."""
    long_text = "Acme " + ("word " * 1000)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": long_text}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.full_summary == long_text.strip()
    assert not result.full_summary.endswith("…")
    assert result.full_summary_truncated is False


def test_fetch_full_summary_safety_ceiling_still_applies_to_a_pathological_response(monkeypatch):
    """A response far beyond anything max_output_tokens could
    realistically produce still gets bounded, with the truncation
    explicitly flagged (never silent) — see
    _FULL_SUMMARY_SAFETY_MAX_CHARS's own comment."""
    pathological_text = "Acme " + ("word " * 10000)
    assert len(pathological_text) > chatgpt_client._FULL_SUMMARY_SAFETY_MAX_CHARS

    def fake_post(url, **kwargs):
        return httpx.Response(
            200, json={"output_text": pathological_text}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert len(result.full_summary) <= chatgpt_client._FULL_SUMMARY_SAFETY_MAX_CHARS + 1
    assert result.full_summary.endswith("…")
    assert result.full_summary_truncated is True
    # This storage-safety truncation is a different concept entirely
    # from the API-level incomplete signal — never conflated.
    assert result.is_truncated is False


def test_fetch_success_reason(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.reason == "ChatGPT OpenAI API request succeeded."


def test_fetch_fails_safely_on_network_error(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "network or timeout error" in result.reason


def test_fetch_fails_safely_on_non_200_response(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(500, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False
    assert "500" in result.reason


def test_fetch_fails_safely_on_invalid_json(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, text="not json", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert result.success is False


def test_password_never_appears_in_the_reason_string_on_any_failure_path(monkeypatch):
    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert "sk-super-secret-key" not in result.reason


def test_api_key_never_appears_in_the_reason_string_on_success(monkeypatch):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    result = fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)

    assert "sk-super-secret-key" not in result.reason
    assert "sk-super-secret-key" not in (result.full_summary or "")


# --- recognition_level / prompt_version (Task 6-D-1) ------------------------


def _fetch_with_text(monkeypatch, text: str):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": text}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)
    return fetch_chatgpt_observation(_CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2)


def test_fetch_classifies_specific_knowledge_response(monkeypatch):
    result = _fetch_with_text(
        monkeypatch, "Acmeは架空の企業で、SaaS事業を展開しています。\n認識レベル：具体的な認識あり"
    )
    assert result.recognition_level == "specific_knowledge"
    assert result.prompt_version == "no_search_v1"


def test_fetch_classifies_partial_knowledge_response(monkeypatch):
    result = _fetch_with_text(
        monkeypatch, "Acmeについては一部の情報のみ把握しています。\n認識レベル：部分的な認識"
    )
    assert result.recognition_level == "partial_knowledge"


def test_fetch_classifies_unidentified_response(monkeypatch):
    result = _fetch_with_text(
        monkeypatch, "Acmeという企業を具体的に識別できません。\n認識レベル：対象企業を識別できない"
    )
    assert result.recognition_level == "unidentified"


def test_fetch_classifies_name_inference_only_response(monkeypatch):
    result = _fetch_with_text(
        monkeypatch, "名称から推測すると技術系の企業と思われます。\n認識レベル：名称からの推測のみ"
    )
    assert result.recognition_level == "name_inference_only"


def test_fetch_defaults_to_indeterminate_when_label_line_is_missing_or_corrupted(monkeypatch):
    result = _fetch_with_text(monkeypatch, "Acmeについて説明しますが、ラベル行がありません。")
    assert result.recognition_level == "indeterminate"


def test_fetch_strips_the_recognition_label_line_from_the_visible_summary(monkeypatch):
    result = _fetch_with_text(
        monkeypatch, "これは本文です。\n認識レベル：具体的な認識あり"
    )
    assert "認識レベル" not in (result.full_summary or "")
    assert "認識レベル" not in (result.summary or "")


# --- incomplete-response detection (Task 6-D-3B) -----------------------------


def _fetch_with_payload(monkeypatch, payload: dict):
    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)
    return fetch_chatgpt_observation(
        _CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2
    )


def test_status_completed_is_not_flagged_as_truncated(monkeypatch):
    result = _fetch_with_payload(
        monkeypatch,
        {"status": "completed", "output_text": "Acmeは架空の企業です。\n認識レベル：具体的な認識あり"},
    )
    assert result.success is True
    assert result.is_truncated is False
    assert result.finish_reason is None
    assert result.note is None


def test_status_incomplete_with_max_output_tokens_reason_is_flagged_truncated(monkeypatch):
    result = _fetch_with_payload(
        monkeypatch,
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": "Acmeは株式会社であり、主な事業内容は",
        },
    )
    assert result.success is True
    assert result.is_truncated is True
    assert result.finish_reason == "max_output_tokens"
    assert result.note is not None
    # recognitionLevel safely falls back to indeterminate — the label
    # line was never reached — never guessed as something else.
    assert result.recognition_level == "indeterminate"


def test_status_incomplete_but_some_text_was_produced_is_still_success(monkeypatch):
    """Task 6-D-3B item 1/3: partial-but-nonempty text is still a
    usable (if incomplete) observation — never a hard failure."""
    result = _fetch_with_payload(
        monkeypatch,
        {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output_text": "Acmeについて説明します。",
        },
    )
    assert result.success is True
    assert result.summary
    assert result.is_truncated is True


def test_status_incomplete_with_no_text_at_all_is_a_distinct_failure_reason(monkeypatch):
    """Task 6-D-3B item 1: "本文がない場合" vs "不完全だが本文がある場合"
    must be distinguishable — this is the no-text case, and the reason
    string must say the response was incomplete, not just "no text"."""
    result = _fetch_with_payload(
        monkeypatch,
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
    )
    assert result.success is False
    assert "incomplete" in result.reason
    assert "max_output_tokens" in result.reason


def test_status_completed_with_no_text_uses_the_plain_no_text_reason(monkeypatch):
    result = _fetch_with_payload(monkeypatch, {"status": "completed"})
    assert result.success is False
    assert result.reason == "OpenAI API returned no readable text."


def test_missing_status_field_is_treated_as_not_truncated(monkeypatch):
    """A response shape that simply doesn't include `status` at all
    (e.g. an older/different API shape) must not be mistaken for an
    incomplete one."""
    result = _fetch_with_payload(monkeypatch, {"output_text": "Acmeについて説明します。"})
    assert result.success is True
    assert result.is_truncated is False


def test_request_body_includes_low_reasoning_effort_for_gpt5_models(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(
        _CREDENTIALS, "Acme", model="gpt-5-mini", max_output_tokens=700, temperature=0.2
    )

    assert seen_bodies[0]["reasoning"] == {"effort": "low"}


def test_request_body_omits_reasoning_effort_for_non_reasoning_models(monkeypatch):
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    fetch_chatgpt_observation(
        _CREDENTIALS, "Acme", model="gpt-4.1-mini", max_output_tokens=700, temperature=0.2
    )

    assert "reasoning" not in seen_bodies[0]
