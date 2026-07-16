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
