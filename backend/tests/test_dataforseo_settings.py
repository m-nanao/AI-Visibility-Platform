from services.dataforseo_settings import (
    DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
    MAX_REQUEST_LIMIT_PER_ANALYZE,
    get_dataforseo_settings,
)


def _clear_dataforseo_env(monkeypatch):
    for name in (
        "DATAFORSEO_LOGIN",
        "DATAFORSEO_PASSWORD",
        "DATAFORSEO_API_ENV",
        "DATAFORSEO_LIVE_API_ENABLED",
        "DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_is_configured_false_when_credentials_are_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.is_configured is False


def test_is_configured_true_when_login_and_password_are_set(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")

    settings = get_dataforseo_settings()

    assert settings.is_configured is True
    assert settings.password_configured is True


def test_is_configured_false_when_only_login_is_set(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")

    settings = get_dataforseo_settings()

    assert settings.is_configured is False


def test_password_value_never_appears_in_repr_or_str(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")

    settings = get_dataforseo_settings()

    assert "super-secret-password" not in repr(settings)
    assert "super-secret-password" not in str(settings)
    # The login value itself is also masked in repr/str as defense in
    # depth, even though it isn't the secret half of the credential pair.
    assert "someone@example.com" not in repr(settings)
    assert "someone@example.com" not in str(settings)


def test_password_is_not_stored_as_an_attribute(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")

    settings = get_dataforseo_settings()

    assert not hasattr(settings, "password")


def test_api_env_defaults_to_sandbox_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.api_env == "sandbox"


def test_api_env_falls_back_to_sandbox_for_invalid_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "not-a-real-env")

    settings = get_dataforseo_settings()

    assert settings.api_env == "sandbox"


def test_live_env_without_live_api_enabled_cannot_use_live_api(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")

    settings = get_dataforseo_settings()

    assert settings.api_env == "live"
    assert settings.live_api_enabled is False
    assert settings.can_use_live_api is False


def test_can_use_live_api_true_only_with_env_live_and_flag_and_credentials(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOGIN", "someone@example.com")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "super-secret-password")
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    settings = get_dataforseo_settings()

    assert settings.can_use_live_api is True


def test_can_use_live_api_false_without_credentials_even_if_live_enabled(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_API_ENV", "live")
    monkeypatch.setenv("DATAFORSEO_LIVE_API_ENABLED", "true")

    settings = get_dataforseo_settings()

    assert settings.is_configured is False
    assert settings.can_use_live_api is False


def test_request_limit_defaults_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_request_limit_falls_back_to_default_for_non_integer_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "not-a-number")

    settings = get_dataforseo_settings()

    assert settings.request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_request_limit_falls_back_to_default_for_negative_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "-1")

    settings = get_dataforseo_settings()

    assert settings.request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_request_limit_is_capped_at_the_safety_ceiling(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_REQUEST_LIMIT_PER_ANALYZE", "999999")

    settings = get_dataforseo_settings()

    assert settings.request_limit_per_analyze == MAX_REQUEST_LIMIT_PER_ANALYZE
