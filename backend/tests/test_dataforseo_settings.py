from services.dataforseo_settings import (
    DEFAULT_DEVICE,
    DEFAULT_LANGUAGE_CODE,
    DEFAULT_LOCATION_CODE,
    DEFAULT_OS,
    DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
    DEFAULT_SERP_ENDPOINT,
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
        "DATAFORSEO_SERP_ENDPOINT",
        "DATAFORSEO_LOCATION_CODE",
        "DATAFORSEO_LANGUAGE_CODE",
        "DATAFORSEO_DEVICE",
        "DATAFORSEO_OS",
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


def test_serp_endpoint_defaults_to_ai_mode_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.serp_endpoint == DEFAULT_SERP_ENDPOINT
    assert settings.serp_endpoint == "google_ai_mode_live_advanced"


def test_serp_endpoint_can_be_set_to_organic(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_SERP_ENDPOINT", "google_organic_live_advanced")

    settings = get_dataforseo_settings()

    assert settings.serp_endpoint == "google_organic_live_advanced"


def test_serp_endpoint_falls_back_to_default_for_invalid_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_SERP_ENDPOINT", "not-a-real-endpoint")

    settings = get_dataforseo_settings()

    assert settings.serp_endpoint == DEFAULT_SERP_ENDPOINT


def test_location_code_defaults_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.location_code == DEFAULT_LOCATION_CODE
    assert settings.location_code == 2392


def test_location_code_falls_back_to_default_for_non_integer_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOCATION_CODE", "not-a-number")

    settings = get_dataforseo_settings()

    assert settings.location_code == DEFAULT_LOCATION_CODE


def test_location_code_can_be_overridden(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LOCATION_CODE", "2840")

    settings = get_dataforseo_settings()

    assert settings.location_code == 2840


def test_language_code_defaults_to_ja_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.language_code == DEFAULT_LANGUAGE_CODE
    assert settings.language_code == "ja"


def test_language_code_defaults_to_ja_when_empty(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_LANGUAGE_CODE", "   ")

    settings = get_dataforseo_settings()

    assert settings.language_code == "ja"


def test_device_defaults_to_desktop_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.device == DEFAULT_DEVICE
    assert settings.device == "desktop"


def test_device_can_be_set_to_mobile(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_DEVICE", "mobile")

    settings = get_dataforseo_settings()

    assert settings.device == "mobile"


def test_device_falls_back_to_desktop_for_invalid_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_DEVICE", "tablet")

    settings = get_dataforseo_settings()

    assert settings.device == "desktop"


def test_os_defaults_to_windows_when_unset(monkeypatch):
    _clear_dataforseo_env(monkeypatch)

    settings = get_dataforseo_settings()

    assert settings.os == DEFAULT_OS
    assert settings.os == "windows"


def test_os_can_be_set_to_a_valid_alternative(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_OS", "android")

    settings = get_dataforseo_settings()

    assert settings.os == "android"


def test_os_falls_back_to_windows_for_invalid_value(monkeypatch):
    _clear_dataforseo_env(monkeypatch)
    monkeypatch.setenv("DATAFORSEO_OS", "not-a-real-os")

    settings = get_dataforseo_settings()

    assert settings.os == "windows"
