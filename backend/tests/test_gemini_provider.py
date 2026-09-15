import httpx

from services import gemini_client
from services.gemini_provider import (
    GEMINI_PLATFORM_LABEL,
    build_gemini_observation,
    resolve_gemini_mode,
)


def _clear_gemini_env(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_PROVIDER_MODE",
        "ALLOW_GEMINI_MODE_OVERRIDE",
        "GEMINI_MODEL",
        "GEMINI_MAX_OUTPUT_TOKENS",
        "GEMINI_REQUEST_LIMIT_PER_ANALYZE",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_credentials(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gm-super-secret-key")


def _text_response(url, text):
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": text}]}}]},
        request=httpx.Request("POST", url),
    )


# --- resolve_gemini_mode ------------------------------------------------------


def test_resolve_gemini_mode_defaults_to_off_when_unset(monkeypatch):
    _clear_gemini_env(monkeypatch)
    assert resolve_gemini_mode(None) == "off"


def test_resolve_gemini_mode_reads_env_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "google")
    assert resolve_gemini_mode(None) == "google"


def test_resolve_gemini_mode_falls_back_to_off_for_invalid_env_value(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "not-a-real-mode")
    assert resolve_gemini_mode(None) == "off"


def test_resolve_gemini_mode_ignores_request_override_by_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "off")
    assert resolve_gemini_mode("google") == "off"


def test_resolve_gemini_mode_honors_request_override_when_allowed(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_GEMINI_MODE_OVERRIDE", "true")
    assert resolve_gemini_mode("google") == "google"


def test_resolve_gemini_mode_override_flag_is_case_insensitive(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_PROVIDER_MODE", "off")
    monkeypatch.setenv("ALLOW_GEMINI_MODE_OVERRIDE", "TRUE")
    assert resolve_gemini_mode("google") == "google"


# --- build_gemini_observation -------------------------------------------------


def test_build_gemini_observation_off_mode_returns_no_item(monkeypatch):
    _clear_gemini_env(monkeypatch)

    item, status, reason, environment = build_gemini_observation("Acme", "off")

    assert item is None
    assert status == "off"
    assert environment == "off"
    assert reason


def test_build_gemini_observation_off_mode_never_calls_gemini(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called in off mode")

    monkeypatch.setattr(gemini_client.httpx, "post", fail_if_called)

    build_gemini_observation("Acme", "off")


def test_build_gemini_observation_google_mode_without_api_key_is_unavailable(monkeypatch):
    _clear_gemini_env(monkeypatch)

    item, status, reason, environment = build_gemini_observation("Acme", "google")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_build_gemini_observation_google_mode_without_api_key_never_calls_gemini(monkeypatch):
    _clear_gemini_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without an API key")

    monkeypatch.setattr(gemini_client.httpx, "post", fail_if_called)

    build_gemini_observation("Acme", "google")


def test_build_gemini_observation_google_mode_with_request_limit_above_one_is_rejected(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("GEMINI_REQUEST_LIMIT_PER_ANALYZE", "2")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when the request limit isn't 1")

    monkeypatch.setattr(gemini_client.httpx, "post", fail_if_called)

    item, status, reason, environment = build_gemini_observation("Acme", "google")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "Gemini request limit must be 1."


def test_build_gemini_observation_success_returns_an_item(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return _text_response(url, "Acme is a well-known tool for teams.")

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    item, status, reason, environment = build_gemini_observation("Acme", "google")

    assert status == "real"
    assert environment == "api"
    assert reason == "Gemini Google API request succeeded."
    assert item is not None
    assert item.platform == GEMINI_PLATFORM_LABEL
    assert item.mentioned is True
    assert item.rank is None
    assert "Acme" in item.summary
    assert item.fullSummary is not None
    assert item.references is None
    assert item.referenceSummary is None
    assert item.ownDomainReferenced is None


def test_build_gemini_observation_sends_exactly_one_request(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        return _text_response(url, "Acme.")

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    build_gemini_observation("Acme", "google")

    assert calls["count"] == 1


def test_build_gemini_observation_uses_configured_model_and_max_output_tokens(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "1000")

    seen_urls = []
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        seen_bodies.append(kwargs.get("json"))
        return _text_response(url, "Acme.")

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    build_gemini_observation("Acme", "google")

    assert "gemini-2.5-pro" in seen_urls[0]
    assert seen_bodies[0]["generationConfig"]["maxOutputTokens"] == 1000


def test_build_gemini_observation_uses_default_model_when_unset(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return _text_response(url, "Acme.")

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    build_gemini_observation("Acme", "google")

    assert "gemini-2.5-flash" in seen_urls[0]


def test_build_gemini_observation_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", raise_timeout)

    item, status, reason, environment = build_gemini_observation("Acme", "google")

    assert item is None
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


def test_build_gemini_observation_reason_never_includes_the_api_key(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(gemini_client.httpx, "post", raise_timeout)

    _, _, reason, _ = build_gemini_observation("Acme", "google")

    assert "gm-super-secret-key" not in reason


def test_build_gemini_observation_reason_never_includes_the_api_key_on_success(monkeypatch):
    _clear_gemini_env(monkeypatch)
    _set_credentials(monkeypatch)

    def fake_post(url, **kwargs):
        return _text_response(url, "Acme.")

    monkeypatch.setattr(gemini_client.httpx, "post", fake_post)

    _, _, reason, _ = build_gemini_observation("Acme", "google")

    assert "gm-super-secret-key" not in reason
