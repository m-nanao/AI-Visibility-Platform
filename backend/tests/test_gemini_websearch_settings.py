"""Tests for services/gemini_websearch_settings.py (Task 6-D-4B-2,
feature/gemini-websearch-supplement)."""

from services.gemini_websearch_settings import (
    DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
    DEFAULT_GEMINI_WEBSEARCH_MODEL,
    GEMINI_WEBSEARCH_ALLOWED_MODELS,
    MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
    MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS,
    get_gemini_websearch_max_output_tokens,
    get_gemini_websearch_model,
    is_gemini_websearch_supplement_enabled,
)

_ENABLED_ENV = "GEMINI_WEBSEARCH_SUPPLEMENT_ENABLED"
_MODEL_ENV = "GEMINI_WEBSEARCH_MODEL"
_MAX_OUTPUT_TOKENS_ENV = "GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS"


def _clear_env(monkeypatch):
    monkeypatch.delenv(_ENABLED_ENV, raising=False)
    monkeypatch.delenv(_MODEL_ENV, raising=False)
    monkeypatch.delenv(_MAX_OUTPUT_TOKENS_ENV, raising=False)


def test_defaults_to_false_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert is_gemini_websearch_supplement_enabled() is False


def test_true_values_enable_it(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv(_ENABLED_ENV, value)
        assert is_gemini_websearch_supplement_enabled() is True


def test_false_values_keep_it_disabled(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv(_ENABLED_ENV, value)
        assert is_gemini_websearch_supplement_enabled() is False


def test_unrecognized_value_falls_back_to_false(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENABLED_ENV, "maybe")
    assert is_gemini_websearch_supplement_enabled() is False


def test_default_model_is_gemini_2_5_flash_and_is_on_the_allowlist(monkeypatch):
    _clear_env(monkeypatch)
    assert get_gemini_websearch_model() == "gemini-2.5-flash"
    assert DEFAULT_GEMINI_WEBSEARCH_MODEL in GEMINI_WEBSEARCH_ALLOWED_MODELS


def test_allowlist_contains_only_gemini_2_5_flash():
    # Task 6-D-4B-2: Gemini 3+ models must never be on this allowlist —
    # see module docstring on unbounded per-query billing.
    assert GEMINI_WEBSEARCH_ALLOWED_MODELS == frozenset({"gemini-2.5-flash"})


def test_model_env_override_is_resolved_even_though_not_yet_allowlist_checked(monkeypatch):
    # This module only resolves the configured value — it does not
    # enforce the allowlist itself (see get_gemini_websearch_model()'s
    # own docstring; the enforcement lives in
    # services/gemini_websearch_provider.py).
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MODEL_ENV, "gemini-3-flash-preview")
    assert get_gemini_websearch_model() == "gemini-3-flash-preview"
    assert "gemini-3-flash-preview" not in GEMINI_WEBSEARCH_ALLOWED_MODELS


def test_blank_model_env_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MODEL_ENV, "   ")
    assert get_gemini_websearch_model() == DEFAULT_GEMINI_WEBSEARCH_MODEL


def test_max_output_tokens_defaults_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert get_gemini_websearch_max_output_tokens() == DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_env_override_within_range_is_honored(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, "3000")
    assert get_gemini_websearch_max_output_tokens() == 3000


def test_max_output_tokens_non_integer_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, "not-a-number")
    assert get_gemini_websearch_max_output_tokens() == DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_below_minimum_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, str(MIN_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS - 1))
    assert get_gemini_websearch_max_output_tokens() == DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_above_maximum_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, str(MAX_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS + 1))
    assert get_gemini_websearch_max_output_tokens() == DEFAULT_GEMINI_WEBSEARCH_MAX_OUTPUT_TOKENS
