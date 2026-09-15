from services.gemini_settings import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
    get_gemini_credentials,
    get_gemini_settings,
)


def _clear_gemini_env(monkeypatch):
    for name in (
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "GEMINI_MAX_OUTPUT_TOKENS",
        "GEMINI_REQUEST_LIMIT_PER_ANALYZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_get_gemini_credentials_is_none_when_api_key_unset(monkeypatch):
    _clear_gemini_env(monkeypatch)
    assert get_gemini_credentials() is None


def test_get_gemini_credentials_returns_api_key_when_set(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    credentials = get_gemini_credentials()
    assert credentials is not None
    assert credentials.api_key == "gm-test-key"


def test_gemini_credentials_repr_never_exposes_the_api_key(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-super-secret-key")
    credentials = get_gemini_credentials()
    assert "gm-super-secret-key" not in repr(credentials)


def test_get_gemini_settings_default_is_not_configured(monkeypatch):
    _clear_gemini_env(monkeypatch)
    settings = get_gemini_settings()
    assert settings.is_configured is False
    assert settings.model == DEFAULT_MODEL
    assert settings.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert settings.request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_get_gemini_settings_is_configured_when_api_key_set(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-test-key")
    assert get_gemini_settings().is_configured is True


def test_gemini_model_env_override(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    assert get_gemini_settings().model == "gemini-2.5-pro"


def test_gemini_model_empty_falls_back_to_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MODEL", "   ")
    assert get_gemini_settings().model == DEFAULT_MODEL


def test_gemini_max_output_tokens_env_override(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "1000")
    assert get_gemini_settings().max_output_tokens == 1000


def test_gemini_max_output_tokens_non_integer_falls_back_to_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "not-a-number")
    assert get_gemini_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_gemini_max_output_tokens_below_minimum_falls_back_to_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "50")
    assert get_gemini_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_gemini_max_output_tokens_above_maximum_falls_back_to_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_OUTPUT_TOKENS", "5000")
    assert get_gemini_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_gemini_request_limit_env_override(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_REQUEST_LIMIT_PER_ANALYZE", "2")
    # Deliberately NOT clamped back to 1 here — an explicit non-1 value
    # is a gate failure decided by services/gemini_provider.py, not
    # silently corrected by settings (mirrors Claude's design).
    assert get_gemini_settings().request_limit_per_analyze == 2


def test_gemini_request_limit_non_integer_falls_back_to_default(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_REQUEST_LIMIT_PER_ANALYZE", "not-a-number")
    assert get_gemini_settings().request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_gemini_settings_repr_never_exposes_the_api_key(monkeypatch):
    _clear_gemini_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gm-super-secret-key")
    settings = get_gemini_settings()
    assert "gm-super-secret-key" not in repr(settings)
