import httpx

from services import claude_client
from services.claude_provider import (
    CLAUDE_PLATFORM_LABEL,
    build_claude_observation,
    resolve_claude_mode,
)


def _clear_claude_env(monkeypatch):
    for name in (
        "CLAUDE_API_KEY",
        "CLAUDE_PROVIDER_MODE",
        "ALLOW_CLAUDE_MODE_OVERRIDE",
        "CLAUDE_MODEL",
        "CLAUDE_MAX_OUTPUT_TOKENS",
        "CLAUDE_REQUEST_LIMIT_PER_ANALYZE",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_credentials(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-super-secret-key")


def _text_response(url, text):
    return httpx.Response(
        200,
        json={"content": [{"type": "text", "text": text}]},
        request=httpx.Request("POST", url),
    )


# --- resolve_claude_mode -----------------------------------------------------


def test_resolve_claude_mode_defaults_to_off_when_unset(monkeypatch):
    _clear_claude_env(monkeypatch)
    assert resolve_claude_mode(None) == "off"


def test_resolve_claude_mode_reads_env_default(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "anthropic")
    assert resolve_claude_mode(None) == "anthropic"


def test_resolve_claude_mode_falls_back_to_off_for_invalid_env_value(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "not-a-real-mode")
    assert resolve_claude_mode(None) == "off"


def test_resolve_claude_mode_ignores_request_override_by_default(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "off")
    assert resolve_claude_mode("anthropic") == "off"


def test_resolve_claude_mode_honors_request_override_when_allowed(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CLAUDE_MODE_OVERRIDE", "true")
    assert resolve_claude_mode("anthropic") == "anthropic"


def test_resolve_claude_mode_override_flag_is_case_insensitive(monkeypatch):
    _clear_claude_env(monkeypatch)
    monkeypatch.setenv("CLAUDE_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_CLAUDE_MODE_OVERRIDE", "TRUE")
    assert resolve_claude_mode("anthropic") == "anthropic"


# --- build_claude_observation ------------------------------------------------


def test_build_claude_observation_off_mode_returns_no_item(monkeypatch):
    _clear_claude_env(monkeypatch)

    item, status, reason, environment = build_claude_observation("Acme", "off")

    assert item is None
    assert status == "off"
    assert environment == "off"
    assert reason


def test_build_claude_observation_off_mode_never_calls_anthropic(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called in off mode")

    monkeypatch.setattr(claude_client.httpx, "post", fail_if_called)

    build_claude_observation("Acme", "off")


def test_build_claude_observation_anthropic_mode_without_api_key_is_unavailable(monkeypatch):
    _clear_claude_env(monkeypatch)

    item, status, reason, environment = build_claude_observation("Acme", "anthropic")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_build_claude_observation_anthropic_mode_without_api_key_never_calls_anthropic(monkeypatch):
    _clear_claude_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without an API key")

    monkeypatch.setattr(claude_client.httpx, "post", fail_if_called)

    build_claude_observation("Acme", "anthropic")


def test_build_claude_observation_anthropic_mode_with_request_limit_above_one_is_rejected(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CLAUDE_REQUEST_LIMIT_PER_ANALYZE", "2")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when the request limit isn't 1")

    monkeypatch.setattr(claude_client.httpx, "post", fail_if_called)

    item, status, reason, environment = build_claude_observation("Acme", "anthropic")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "Claude request limit must be 1."


def test_build_claude_observation_success_returns_an_item(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return _text_response(url, "Acme is a well-known tool for teams.")

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    item, status, reason, environment = build_claude_observation("Acme", "anthropic")

    assert status == "real"
    assert environment == "api"
    assert reason == "Claude Anthropic API request succeeded."
    assert item is not None
    assert item.platform == CLAUDE_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.rank is None
    assert "Acme" in item.summary
    assert item.fullSummary is not None
    assert item.references is None
    assert item.referenceSummary is None
    assert item.ownDomainReferenced is None


def test_build_claude_observation_sends_exactly_one_request(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return _text_response(url, "Acme.")

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    build_claude_observation("Acme", "anthropic")

    assert calls["count"] == 1


def test_build_claude_observation_uses_configured_model_and_max_output_tokens(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    monkeypatch.setenv("CLAUDE_MAX_OUTPUT_TOKENS", "1000")

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return _text_response(url, "Acme.")

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    build_claude_observation("Acme", "anthropic")

    assert seen_bodies[0]["model"] == "claude-opus-5"
    assert seen_bodies[0]["max_tokens"] == 1000


def test_build_claude_observation_uses_default_model_when_unset(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        return _text_response(url, "Acme.")

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    build_claude_observation("Acme", "anthropic")

    assert seen_bodies[0]["model"] == "claude-sonnet-4-5"


def test_build_claude_observation_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", raise_timeout)

    item, status, reason, environment = build_claude_observation("Acme", "anthropic")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


def test_build_claude_observation_reason_never_includes_the_api_key(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(claude_client.httpx, "post", raise_timeout)

    _, _, reason, _ = build_claude_observation("Acme", "anthropic")

    assert "sk-ant-super-secret-key" not in reason


def test_build_claude_observation_reason_never_includes_the_api_key_on_success(monkeypatch):
    _clear_claude_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return _text_response(url, "Acme.")

    monkeypatch.setattr(claude_client.httpx, "post", fake_post)

    _, _, reason, _ = build_claude_observation("Acme", "anthropic")

    assert "sk-ant-super-secret-key" not in reason
