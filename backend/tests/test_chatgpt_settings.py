from services.chatgpt_settings import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_REQUEST_LIMIT_PER_ANALYZE,
    DEFAULT_TEMPERATURE,
    get_chatgpt_credentials,
    get_chatgpt_settings,
)


def _clear_chatgpt_env(monkeypatch):
    for name in (
        "OPENAI_API_KEY",
        "CHATGPT_MODEL",
        "CHATGPT_MAX_OUTPUT_TOKENS",
        "CHATGPT_REQUEST_LIMIT_PER_ANALYZE",
        "CHATGPT_TEMPERATURE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_get_chatgpt_credentials_is_none_when_api_key_unset(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    assert get_chatgpt_credentials() is None


def test_get_chatgpt_credentials_returns_api_key_when_set(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    credentials = get_chatgpt_credentials()
    assert credentials is not None
    assert credentials.api_key == "sk-test-key"


def test_chatgpt_credentials_repr_never_exposes_the_api_key(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    credentials = get_chatgpt_credentials()
    assert "sk-super-secret-key" not in repr(credentials)


def test_get_chatgpt_settings_default_is_not_configured(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    settings = get_chatgpt_settings()
    assert settings.is_configured is False
    assert settings.model == DEFAULT_MODEL
    assert settings.max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
    assert settings.request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE
    assert settings.temperature == DEFAULT_TEMPERATURE


def test_get_chatgpt_settings_is_configured_when_api_key_set(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    assert get_chatgpt_settings().is_configured is True


def test_chatgpt_model_env_override(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MODEL", "gpt-5")
    assert get_chatgpt_settings().model == "gpt-5"


def test_chatgpt_model_empty_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MODEL", "   ")
    assert get_chatgpt_settings().model == DEFAULT_MODEL


def test_chatgpt_max_output_tokens_env_override(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MAX_OUTPUT_TOKENS", "1000")
    assert get_chatgpt_settings().max_output_tokens == 1000


def test_chatgpt_max_output_tokens_non_integer_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MAX_OUTPUT_TOKENS", "not-a-number")
    assert get_chatgpt_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_chatgpt_max_output_tokens_below_minimum_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MAX_OUTPUT_TOKENS", "50")
    assert get_chatgpt_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_chatgpt_max_output_tokens_above_maximum_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_MAX_OUTPUT_TOKENS", "5000")
    assert get_chatgpt_settings().max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS


def test_chatgpt_request_limit_env_override(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_REQUEST_LIMIT_PER_ANALYZE", "2")
    # Deliberately NOT clamped back to 1 here — an explicit non-1 value
    # is a gate failure decided by services/chatgpt_provider.py, not
    # silently corrected by settings (mirrors DataForSEO's design).
    assert get_chatgpt_settings().request_limit_per_analyze == 2


def test_chatgpt_request_limit_non_integer_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_REQUEST_LIMIT_PER_ANALYZE", "not-a-number")
    assert get_chatgpt_settings().request_limit_per_analyze == DEFAULT_REQUEST_LIMIT_PER_ANALYZE


def test_chatgpt_temperature_default_is_0_2(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    assert get_chatgpt_settings().temperature == 0.2
    assert DEFAULT_TEMPERATURE == 0.2


def test_chatgpt_temperature_env_override(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "0.5")
    assert get_chatgpt_settings().temperature == 0.5


def test_chatgpt_temperature_non_numeric_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "not-a-number")
    assert get_chatgpt_settings().temperature == DEFAULT_TEMPERATURE


def test_chatgpt_temperature_below_minimum_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "-1")
    assert get_chatgpt_settings().temperature == DEFAULT_TEMPERATURE


def test_chatgpt_temperature_above_maximum_falls_back_to_default(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "1.5")
    assert get_chatgpt_settings().temperature == DEFAULT_TEMPERATURE


def test_chatgpt_temperature_minimum_boundary_0_0_is_valid(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "0.0")
    assert get_chatgpt_settings().temperature == 0.0


def test_chatgpt_temperature_maximum_boundary_1_0_is_valid(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("CHATGPT_TEMPERATURE", "1.0")
    assert get_chatgpt_settings().temperature == 1.0


def test_chatgpt_settings_repr_never_exposes_the_api_key(monkeypatch):
    _clear_chatgpt_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    settings = get_chatgpt_settings()
    assert "sk-super-secret-key" not in repr(settings)
