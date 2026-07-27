import httpx

from services import dataforseo_client
from services.ai_overview_provider import (
    _build_reference_summary,
    _classify_reference_category,
    build_ai_overview_comparison,
    resolve_ai_overview_mode,
)
from services.dataforseo_client import DataForSEOSerpReference

_LIVE_CONFIRM_TEXT = "ALLOW_DATAFORSEO_LIVE_ONCE"


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
    items, status, reason, environment = build_ai_overview_comparison("Acme", "mock")

    assert status == "mock"
    assert environment == "mock"
    assert len(items) > 0
    assert reason


def test_build_ai_overview_comparison_off_mode_returns_empty_and_unavailable():
    items, status, reason, environment = build_ai_overview_comparison("Acme", "off")

    assert items == []
    assert status == "unavailable"
    assert environment == "off"
    assert reason


def _clear_dataforseo_env(monkeypatch):
    for name in (
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "DATAFORSEO_API_ENV",
        "DATAFORSEO_LIVE_API_ENABLED",
        "DATAFORSEO_LIVE_CONFIRM_TEXT",
        "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE",
        "DATAFORSEO_SERP_ENDPOINT",
        "DATAFORSEO_LOCATION_CODE",
        "DATAFORSEO_LANGUAGE_CODE",
        "DATAFORSEO_DEVICE",
        "DATAFORSEO_OS",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_credentials(monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")


def _set_all_live_gates(monkeypatch):
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")


def test_build_ai_overview_comparison_dataforseo_mode_returns_empty_and_unavailable_without_credentials(
    monkeypatch,
):
    _clear_dataforseo_env(monkeypatch)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_reason_reports_missing_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    _, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_never_calls_the_sandbox_client_without_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    build_ai_overview_comparison("Acme", "dataforseo")


def test_dataforseo_mode_sandbox_success_reports_real_status(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "real"
    assert environment == "sandbox"
    assert len(items) == 1
    assert items[0].mentioned is True
    assert items[0].platform == "Google AI Mode (DataForSEO Sandbox)"
    assert "sandbox" in reason.lower() or "Sandbox" in reason


def test_dataforseo_mode_calls_the_ai_mode_endpoint_by_default(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
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
    assert seen_urls[0].startswith("https://sandbox.dataforseo.com")


def test_dataforseo_mode_forwards_endpoint_location_language_device_os_settings(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
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
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


# --- Live manual-check gate ------------------------------------------------


def test_dataforseo_mode_live_env_alone_is_rejected_and_never_calls_httpx(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    # None of the other live gates (LIVE_API_ENABLED / LIVE_CONFIRM_TEXT)
    # are set — this is the common/default misconfiguration case.

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when live gates are unmet")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "DataForSEO Live API is disabled" in reason


def test_dataforseo_mode_live_env_with_enabled_but_wrong_confirm_text_is_rejected(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "not-the-right-text")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called with a wrong confirm text")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "DataForSEO Live API requires explicit manual confirmation."


def test_dataforseo_mode_live_env_with_request_limit_above_one_is_rejected(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "2")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when the request limit isn't 1")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "DataForSEO Live API request limit must be 1."


def test_dataforseo_mode_live_env_without_credentials_is_rejected_before_the_live_gate_check(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")
    # DATAFORSEO_LOGIN/PASSWORD deliberately left unset.

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_live_env_with_all_gates_satisfied_calls_the_live_host(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    seen_urls = []
    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert seen_urls == ["https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"]
    assert status == "real"
    assert environment == "live"
    assert len(items) == 1
    assert items[0].mentioned is True
    assert items[0].platform == "Google AI Mode (DataForSEO Live)"
    assert reason == "DataForSEO Live AI Mode request succeeded."


def test_dataforseo_mode_live_env_sends_only_one_keyword_even_with_all_gates_satisfied(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    seen_bodies = []

    def fake_post(url, **kwargs):
        seen_bodies.append(kwargs.get("json"))
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    build_ai_overview_comparison("Acme", "dataforseo")

    assert len(seen_bodies) == 1
    assert len(seen_bodies[0]) == 1


def test_dataforseo_mode_live_env_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


def test_dataforseo_mode_reason_never_includes_credential_values_when_live_gates_are_unmet(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    _, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert environment == "unavailable"
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason


# --- explicit dataforseo_sandbox / dataforseo_live modes -------------------


def test_dataforseo_sandbox_mode_forces_sandbox_host_regardless_of_api_env(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    # Deliberately set to "live" — dataforseo_sandbox must ignore this.
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")

    seen_urls = []

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_sandbox")

    assert seen_urls[0].startswith("https://sandbox.dataforseo.com")
    assert environment == "unavailable"  # no ai_overview item in this payload
    assert items == []
    assert status == "unavailable"
    assert reason


def test_dataforseo_sandbox_mode_reports_sandbox_environment_on_success(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")  # still ignored

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "text": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_sandbox")

    assert status == "real"
    assert environment == "sandbox"
    assert len(items) == 1
    assert items[0].platform == "Google AI Mode (DataForSEO Sandbox)"
    assert reason


def test_dataforseo_sandbox_mode_requires_no_live_gate_and_never_checks_it(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    # None of the live gates are set at all — dataforseo_sandbox must not care.
    monkeypatch.delenv("DATAFORSEO_LIVE_API_ENABLED", raising=False)
    monkeypatch.delenv("DATAFORSEO_LIVE_CONFIRM_TEXT", raising=False)

    def fake_post(url, **kwargs):
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    _, status, _, environment = build_ai_overview_comparison("Acme", "dataforseo_sandbox")

    # Reaches the sandbox call (not rejected by a gate check) — status is
    # "unavailable" only because the fake payload has no ai_overview item.
    assert environment == "unavailable"
    assert status == "unavailable"


def test_dataforseo_sandbox_mode_without_credentials_never_calls_httpx(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_sandbox")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_dataforseo_live_mode_rejected_when_api_env_is_not_live(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when DATAFORSEO_API_ENV isn't live")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "DataForSEO Live mode was requested, but DATAFORSEO_API_ENV is not live."


def test_dataforseo_live_mode_rejected_when_live_api_enabled_is_false(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")
    # DATAFORSEO_LIVE_API_ENABLED deliberately left unset (false).

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when LIVE_API_ENABLED isn't true")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "DataForSEO Live mode was requested, but DATAFORSEO_LIVE_API_ENABLED is not true."


def test_dataforseo_live_mode_rejected_when_confirm_text_does_not_match(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", "not-the-right-text")
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called with a wrong confirm text")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert (
        reason
        == "DataForSEO Live mode was requested, but DATAFORSEO_LIVE_CONFIRM_TEXT does not match "
        "the required confirmation text."
    )


def test_dataforseo_live_mode_rejected_when_request_limit_is_not_one(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "2")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called when the request limit isn't 1")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason == "DataForSEO Live mode was requested, but request limit is not 1."


def test_dataforseo_live_mode_rejected_when_credentials_are_missing(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")
    monkeypatch.setenv("DATAFORSEO_LIVE_CONFIRM_TEXT", _LIVE_CONFIRM_TEXT)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "1")
    # DATAFORSEO_LOGIN/PASSWORD deliberately left unset.

    def fail_if_called(*args, **kwargs):
        raise AssertionError("httpx.post should not be called without credentials")

    monkeypatch.setattr(dataforseo_client.httpx, "post", fail_if_called)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert "not configured" in reason


def test_dataforseo_live_mode_calls_the_live_host_when_all_gates_are_satisfied(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    seen_urls = []
    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        seen_urls.append(url)
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert seen_urls == ["https://api.dataforseo.com/v3/serp/google/ai_mode/live/advanced"]
    assert status == "real"
    assert environment == "live"
    assert len(items) == 1
    assert items[0].platform == "Google AI Mode (DataForSEO Live)"
    assert reason == "DataForSEO Live AI Mode request succeeded."


def test_dataforseo_live_mode_sends_only_one_request_when_all_gates_satisfied(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)
    calls = {"count": 0}

    def fake_post(url, **kwargs):
        calls["count"] += 1
        payload = {"status_code": 20000, "tasks": [{"result": [{"items": []}]}]}
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    build_ai_overview_comparison("Acme", "dataforseo_live")

    assert calls["count"] == 1


def test_dataforseo_live_mode_failure_reports_unavailable_without_crashing(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    def raise_timeout(url, **kwargs):
        raise httpx.ConnectTimeout("timeout", request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", raise_timeout)

    items, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert items == []
    assert status == "unavailable"
    assert environment == "unavailable"
    assert reason


def test_dataforseo_live_mode_reason_never_includes_credential_values(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    _, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert status == "unavailable"
    assert environment == "unavailable"
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason


def test_dataforseo_live_mode_reason_never_includes_credential_values_on_success(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme is great."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    _, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo_live")

    assert status == "real"
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason


def test_resolve_ai_overview_mode_accepts_dataforseo_sandbox_and_dataforseo_live(monkeypatch):
    monkeypatch.setenv("AI_OVERVIEW_PROVIDER_MODE", "mock")
    monkeypatch.setenv("ALLOW_AI_OVERVIEW_MODE_OVERRIDE", "true")

    assert resolve_ai_overview_mode("dataforseo_sandbox") == "dataforseo_sandbox"
    assert resolve_ai_overview_mode("dataforseo_live") == "dataforseo_live"


# --- fullSummary / references / ownDomainReferenced ------------------------


def _payload_with_reference(domain: str) -> dict:
    return {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "type": "ai_overview",
                                "rank_absolute": 1,
                                "markdown": "Acme is a well-reviewed tool for teams.",
                                "references": [
                                    {"domain": domain, "url": f"https://{domain}/about", "title": "About"}
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }


def test_dataforseo_mode_sandbox_success_includes_full_summary_and_references(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = _payload_with_reference("acme.example.com")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, status, _, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "real"
    assert environment == "sandbox"
    assert items[0].fullSummary == "Acme is a well-reviewed tool for teams."
    assert len(items[0].references) == 1
    assert items[0].references[0].domain == "acme.example.com"


def test_dataforseo_mode_own_domain_referenced_is_none_without_input_urls(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = _payload_with_reference("acme.example.com")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison("Acme", "dataforseo", None)

    assert items[0].ownDomainReferenced is None


def test_dataforseo_mode_own_domain_referenced_true_when_input_url_domain_matches_a_reference(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = _payload_with_reference("acme.example.com")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison(
        "Acme", "dataforseo", ["https://acme.example.com/pricing"]
    )

    assert items[0].ownDomainReferenced is True


def test_dataforseo_mode_own_domain_referenced_matches_ignoring_www_prefix(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = _payload_with_reference("www.acme.example.com")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison(
        "Acme", "dataforseo", ["https://acme.example.com/pricing"]
    )

    assert items[0].ownDomainReferenced is True


def test_dataforseo_mode_own_domain_referenced_false_when_input_url_domain_does_not_match(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = _payload_with_reference("acme.example.com")

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison(
        "Acme", "dataforseo", ["https://unrelated.example.org/"]
    )

    assert items[0].ownDomainReferenced is False


def test_dataforseo_mode_reason_never_includes_credential_values_on_live_success(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_all_live_gates(monkeypatch)

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    _, status, reason, environment = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "real"
    assert environment == "live"
    assert "someone@example.com" not in reason
    assert "super-secret-password" not in reason


# --- reference category classification -------------------------------------


def _reference(domain: str | None = None, url: str | None = None) -> DataForSEOSerpReference:
    return DataForSEOSerpReference(domain=domain, url=url)


def test_classify_reference_category_own_domain_match_is_official():
    reference = _reference(domain="cybozu.co.jp")
    assert _classify_reference_category(reference, {"cybozu.co.jp"}) == "official"


def test_classify_reference_category_subdomain_of_own_domain_is_official():
    reference = _reference(domain="docs.cybozu.co.jp")
    assert _classify_reference_category(reference, {"cybozu.co.jp"}) == "official"


def test_classify_reference_category_wikipedia_subdomain_is_wikipedia():
    reference = _reference(domain="ja.wikipedia.org")
    assert _classify_reference_category(reference, set()) == "wikipedia"


def test_classify_reference_category_qiita_is_ugc():
    assert _classify_reference_category(_reference(domain="qiita.com"), set()) == "ugc"


def test_classify_reference_category_note_is_ugc():
    assert _classify_reference_category(_reference(domain="note.com"), set()) == "ugc"


def test_classify_reference_category_zenn_is_ugc():
    assert _classify_reference_category(_reference(domain="zenn.dev"), set()) == "ugc"


def test_classify_reference_category_youtube_is_video():
    assert _classify_reference_category(_reference(domain="youtube.com"), set()) == "video"


def test_classify_reference_category_x_com_is_sns():
    assert _classify_reference_category(_reference(domain="x.com"), set()) == "sns"


def test_classify_reference_category_twitter_com_is_sns():
    assert _classify_reference_category(_reference(domain="twitter.com"), set()) == "sns"


def test_classify_reference_category_news_domain_is_news():
    assert _classify_reference_category(_reference(domain="nikkei.com"), set()) == "news"


def test_classify_reference_category_unclassified_domain_is_other():
    assert _classify_reference_category(_reference(domain="example-blog.example.com"), set()) == "other"


def test_classify_reference_category_own_domain_wins_over_hardcoded_lists():
    # If a brand's own domain happened to be one of the hardcoded
    # category domains, "official" must still win — an own-domain match
    # is checked first (see _classify_reference_category's docstring).
    reference = _reference(domain="x.com")
    assert _classify_reference_category(reference, {"x.com"}) == "official"


def test_classify_reference_category_falls_back_to_url_when_no_domain():
    reference = _reference(url="https://ja.wikipedia.org/wiki/Acme")
    assert _classify_reference_category(reference, set()) == "wikipedia"


def test_classify_reference_category_is_other_when_neither_domain_nor_url():
    assert _classify_reference_category(_reference(), set()) == "other"


# --- reference summary ------------------------------------------------------


def test_build_reference_summary_is_none_for_no_references():
    assert _build_reference_summary(None) is None
    assert _build_reference_summary([]) is None


def test_build_reference_summary_counts_total_official_and_third_party(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [
            {
                "result": [
                    {
                        "items": [
                            {
                                "type": "ai_overview",
                                "rank_absolute": 1,
                                "markdown": "Acme summary.",
                                "references": [
                                    {"domain": "acme.example.com"},
                                    {"domain": "ja.wikipedia.org"},
                                    {"domain": "x.com"},
                                    {"domain": "qiita.com"},
                                    {"domain": "unclassified.example.org"},
                                ],
                            }
                        ]
                    }
                ]
            }
        ],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison(
        "Acme", "dataforseo", ["https://acme.example.com/pricing"]
    )

    summary = items[0].referenceSummary
    assert summary is not None
    assert summary.total == 5
    assert summary.official == 1
    assert summary.thirdParty == 4
    assert summary.categories.official == 1
    assert summary.categories.wikipedia == 1
    assert summary.categories.sns == 1
    assert summary.categories.ugc == 1
    assert summary.categories.other == 1
    assert summary.categories.news is None
    assert summary.categories.video is None
    assert summary.categories.media is None

    domains_to_categories = {r.domain: r.category for r in items[0].references}
    assert domains_to_categories["acme.example.com"] == "official"
    assert domains_to_categories["ja.wikipedia.org"] == "wikipedia"
    assert domains_to_categories["x.com"] == "sns"
    assert domains_to_categories["qiita.com"] == "ugc"
    assert domains_to_categories["unclassified.example.org"] == "other"


def test_reference_summary_is_none_when_item_has_no_references(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    _set_credentials(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "sandbox")

    payload = {
        "status_code": 20000,
        "tasks": [{"result": [{"items": [{"type": "ai_overview", "rank_absolute": 1, "markdown": "Acme."}]}]}],
    }

    def fake_post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(dataforseo_client.httpx, "post", fake_post)

    items, _, _, _ = build_ai_overview_comparison("Acme", "dataforseo")

    assert items[0].references is None
    assert items[0].referenceSummary is None
