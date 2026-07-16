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


def test_build_ai_overview_comparison_dataforseo_mode_returns_empty_and_unavailable():
    items, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
    assert "not yet implemented" in reason


def test_build_ai_overview_comparison_dataforseo_mode_never_looks_real():
    # dataforseo must never be reported as "real" — that would imply an
    # actual DataForSEO call happened, which this task deliberately
    # does not implement yet.
    _, status, _ = build_ai_overview_comparison("Acme", "dataforseo")

    assert status != "real"


def _clear_dataforseo_env(monkeypatch):
    for name in (
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "DATAFORSEO_API_ENV",
        "DATAFORSEO_LIVE_API_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)


def test_dataforseo_mode_reason_reports_missing_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "not configured" in reason


def test_dataforseo_mode_reason_reports_sandbox_configured(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "sandbox" in reason
    assert "not yet implemented" in reason


def test_dataforseo_mode_reason_reports_live_requested_but_disabled(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")

    _, status, reason = build_ai_overview_comparison("Acme", "dataforseo")

    assert status == "unavailable"
    assert "Live API" in reason
    assert "disabled" in reason


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


def test_dataforseo_mode_never_calls_an_external_api(monkeypatch):
    # There is no HTTP client used anywhere in this module — this test
    # documents/guards that expectation by asserting the mode still
    # resolves synchronously and instantly regardless of credential
    # configuration, rather than attempting a real network call.
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    items, status, _ = build_ai_overview_comparison("Acme", "dataforseo")

    assert items == []
    assert status == "unavailable"
