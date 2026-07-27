import httpx

from services import chatgpt_client
from services.chatgpt_provider import (
    CHATGPT_PLATFORM_LABEL,
    build_chatgpt_observation,
    resolve_chatgpt_mode,
)


def _clear_chatgpt_env(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CHATGPT_PROVIDER_MODE",
        "ALLOW_CHATGPT_MODE_OVERRIDE",
        "CHATGPT_MODEL",
        "CHATGPT_MAX_OUTPUT_TOKENS",
        "CHATGPT_REQUEST_LIMIT_PER_ANALYZE",
        "CHATGPT_TEMPERATURE",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")


# --- resolve_chatgpt_mode ---------------------------------------------------


def test_resolve_chatgpt_mode_defaults_to_off_when_unset(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    assert resolve_chatgpt_mode(None) == "off"


def test_resolve_chatgpt_mode_reads_env_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "openai")
    assert resolve_chatgpt_mode(None) == "openai"


def test_resolve_chatgpt_mode_falls_back_to_off_for_invalid_env_value(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "not-a-real-mode")
    assert resolve_chatgpt_mode(None) == "off"


def test_resolve_chatgpt_mode_ignores_request_override_by_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    assert resolve_chatgpt_mode("openai") == "off"


def test_resolve_chatgpt_mode_honors_request_override_when_allowed(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "true")
    assert resolve_chatgpt_mode("openai") == "openai"


def test_resolve_chatgpt_mode_override_flag_is_case_insensitive(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CHATGPT_MODE_OVERRIDE", "TRUE")
    assert resolve_chatgpt_mode("openai") == "openai"


# --- build_chatgpt_observation ----------------------------------------------


def test_build_chatgpt_observation_off_mode_returns_no_item(monkeypatch):
    _clear_chatgpt_env(monkeypatch)

    item, status, reason, environment = build_chatgpt_observation("Acme", "off")

    assert item is None
    assert status == "off"
    assert environment == "off"
    assert reason


def test_build_chatgpt_observation_off_mode_never_calls_openai(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called in off mode")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    build_chatgpt_observation("Acme", "off")


def test_build_chatgpt_observation_openai_mode_without_api_key_is_unavailable(monkeypatch):
    _clear_chatgpt_env(monkeypatch)

    item, status, reason, environment = build_chatgpt_observation("Acme", "openai")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_build_chatgpt_observation_openai_mode_without_api_key_never_calls_openai(monkeypatch):
    _clear_chatgpt_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without an API key")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    build_chatgpt_observation("Acme", "openai")


def test_build_chatgpt_observation_openai_mode_with_request_limit_above_one_is_rejected(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CHATGPT_REQUEST_LIMIT_PER_ANALYZE", "2")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when the request limit isn't 1")

    monkeypatch.setattr(chatgpt_client.httpx, "post", fail_if_called)

    item, status, reason, environment = build_chatgpt_observation("Acme", "openai")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "ChatGPT request limit must be 1."


def test_build_chatgpt_observation_success_returns_an_item(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return httpx.Response(
            200,
            json={"output_text": "Acme is a well-known tool for teams."},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    item, status, reason, environment = build_chatgpt_observation("Acme", "openai")

    assert status == "real"
    assert environment == "api"
    assert reason == "ChatGPT OpenAI API request succeeded."
    assert item is not None
    assert item.platform == CHATGPT_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.rank is None
    assert "Acme" in item.summary
    assert item.fullSummary is not None
    assert item.references is None
    assert item.referenceSummary is None
    assert item.ownDomainReferenced is None


def test_build_chatgpt_observation_sends_exactly_one_request(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    build_chatgpt_observation("Acme", "openai")

    assert calls["count"] == 1


def test_build_chatgpt_observation_uses_configured_model_and_max_output_tokens(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CHATGPT_MODEL", "gpt-5")
    monkeypatch.setenv("CHATGPT_MAX_OUTPUT_TOKENS", "1000")

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    build_chatgpt_observation("Acme", "openai")

    assert seen_bodies[0]["model"] == "gpt-5"
    assert seen_bodies[0]["max_output_tokens"] == 1000


def test_build_chatgpt_observation_uses_configured_temperature(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)
    # A temperature-supporting model — gpt-5* models omit temperature
    # from the request entirely (see chatgpt_client.should_send_temperature
    # and the dedicated gpt-5 tests below), so this test uses a model
    # where the configured value is actually expected to be forwarded.
    monkeypatch.setenv("CHATGPT_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "0.7")

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    build_chatgpt_observation("Acme", "openai")

    assert seen_bodies[0]["temperature"] == 0.7


def test_build_chatgpt_observation_uses_default_temperature_when_unset(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CHATGPT_MODEL", "gpt-4.1-mini")

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    build_chatgpt_observation("Acme", "openai")

    assert seen_bodies[0]["temperature"] == 0.2


def test_build_chatgpt_observation_omits_temperature_for_the_default_gpt5_mini_model(monkeypatch):
    # CHATGPT_MODEL deliberately left unset here, so this exercises
    # chatgpt_settings.DEFAULT_MODEL ("gpt-5-mini") end-to-end through
    # build_chatgpt_observation() — the scenario that originally caused
    # an HTTP 400 from OpenAI when combined with CHATGPT_TEMPERATURE.
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    item, status, _, _ = build_chatgpt_observation("Acme", "openai")

    assert "temperature" not in seen_bodies[0]
    assert status == "real"
    assert item is not None


def test_build_chatgpt_observation_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    item, status, reason, environment = build_chatgpt_observation("Acme", "openai")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


def test_build_chatgpt_observation_reason_never_includes_the_api_key(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", raise_timeout)

    _, _, reason, _ = build_chatgpt_observation("Acme", "openai")

    assert "sk-super-secret-key" not in reason


def test_build_chatgpt_observation_reason_never_includes_the_api_key_on_success(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={"output_text": "Acme."}, request=httpx.Request("POST", url))

    monkeypatch.setattr(chatgpt_client.httpx, "post", fake_post)

    _, _, reason, _ = build_chatgpt_observation("Acme", "openai")

    assert "sk-super-secret-key" not in reason
