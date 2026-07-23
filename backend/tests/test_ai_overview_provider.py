import httpx

from services import dataforseo_client
from services.ai_overview_provider import build_ai_overview_comparison, resolve_ai_overview_mode


def test_resolve_ai_overview_mode_defaults_to_mock_when_unset(monkeypatch):
    monkeypatch.delenv("AI_OVERVIEW_PROVIDER_MODE", raising=False)
    monkeypatch.delenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", raising=False)

    assert resolve_ai_overview_mode(None) == "mock"


def test_resolve_ai_overview_mode_reads_env_default(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "off")

    assert resolve_ai_overview_mode(None) == "off"


def test_resolve_ai_overview_mode_falls_back_to_mock_for_invalid_env_value(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "not-a-real-mode")

    assert resolve_ai_overview_mode(None) == "mock"


def test_resolve_ai_overview_mode_ignores_request_override_by_default(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.delenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", raising=False)

    assert resolve_ai_overview_mode("off") == "mock"


def test_resolve_ai_overview_mode_honors_request_override_when_allowed(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")

    assert resolve_ai_overview_mode("off") == "off"


def test_resolve_ai_overview_mode_override_flag_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "TRUE")

    assert resolve_ai_overview_mode("dataforseo") == "dataforseo"


def test_build_ai_overview_comparison_mock_mode_returns_items_with_mock_status():
    items, status, reason = build_ai_overview_comparison("Acme", "mock")

    assert status == "mock"
    assert len(items) > 0
    assert reason


def test_build_ai_overview_comparison_off_mode_returns_empty_and_unavailable():
    items, status, reason = build_ai_overview_comparison("Acme", "off")

    assert items == []
    assert status == "unavailable"
    assert reason


def _clear_dataforseo_env(monkeypatch):
    for name in (
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "DATAFORSEO_API_ENV",
        "DATAFORSEO_LIVE_API_ENABLED",
        "DATAFORSEO_SERP_ENDPOINT",
        "DATAFORSEO_LOCATION_CODE",
        "DATAFORSEO_LANGUAGE_CODE",
        "DATAFORSEO_DEVICE",
        "DATAFORSEO_OS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_ai_overview_comparison_dataforseo_mode_returns_empty_and_unavailable_without_credentials(
    monkeypatch,
):
    _clear_dataforseo_env(monkeypatch)

    items, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_reason_reports_missing_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_never_calls_the_sandbox_client_without_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    build_ai_overview_comparison("Acme", "dataforseo")


def test_dataforseo_mode_sandbox_success_reports_real_status(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "real"
    assert len(items) == 1
    assert items[0].mentioned is True
    assert items[0].platform == "Google AI Mode (DataForSEO Sandbox)"
    assert "sandbox" in reason.lower() or "Sandbox" in reason


def test_dataforseo_mode_calls_the_ai_mode_endpoint_by_default(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    build_ai_overview_comparison("Acme", "dataforseo")

    assert len(seen_urls) == 1
    assert seen_urls[0].endswith("/v3/serp/google/ai_mode/live/advanced")


def test_dataforseo_mode_forwards_endpoint_location_language_device_os_settings(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")
    monkeypatch.setenv("DATAFORSEO_SERP_ENDPOINT", "google_organic_live_advanced")
    monkeypatch.setenv("DATAFORSEO_LOCATION_CODE", "2840")
    monkeypatch.setenv("DATAFORSEO_LANGUAGE_CODE", "en")
    monkeypatch.setenv("DATAFORSEO_DEVICE", "mobile")
    monkeypatch.setenv("DATAFORSEO_OS", "android")

    seen_urls = []
    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        seen_bodies.append(kwargs.get("json"))
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    build_ai_overview_comparison("Acme", "dataforseo")

    assert seen_urls[0].endswith("/v3/serp/google/organic/live/advanced")
    assert seen_bodies == [
        [
            {
                "keyword": "Acme",
                "location_code": 2840,
                "language_code": "en",
                "device": "mobile",
                "os": "android",
            }
        ]
    ]


def test_dataforseo_mode_sandbox_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    items, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert reason


def test_dataforseo_mode_reason_reports_live_not_implemented(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "Live API" in reason
    assert "not implemented" in reason


def test_dataforseo_mode_never_calls_the_sandbox_client_for_live_env(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should never be called when DATAFORSEO_API_ENV=live")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    build_ai_overview_comparison("Acme", "dataforseo")


def test_dataforseo_mode_reason_never_includes_credential_values(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason
