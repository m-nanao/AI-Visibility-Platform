"""Tests for services/claude_websearch_settings.py (Task 6-D-4A-2,
feature/claude-websearch-supplement)."""

from services.claude_websearch_settings import (
    DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
    DEFAULT_CLAUDE_WEBSEARCH_MODEL,
    MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
    MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS,
    get_claude_websearch_max_output_tokens,
    get_claude_websearch_model,
    is_claude_websearch_supplement_enabled,
)

_ENABLED_ENV = "CLAUDE_WEBSEARCH_SUPPLEMENT_ENABLED"
_MODEL_ENV = "CLAUDE_WEBSEARCH_MODEL"
_MAX_OUTPUT_TOKENS_ENV = "CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS"


def _clear_env(monkeypatch):
    monkeypatch.delenv(_ENABLED_ENV, raising=False)
    monkeypatch.delenv(_MODEL_ENV, raising=False)
    monkeypatch.delenv(_MAX_OUTPUT_TOKENS_ENV, raising=False)


def test_defaults_to_false_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert is_claude_websearch_supplement_enabled() is False


def test_true_values_enable_it(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv(_ENABLED_ENV, value)
        assert is_claude_websearch_supplement_enabled() is True


def test_false_values_keep_it_disabled(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv(_ENABLED_ENV, value)
        assert is_claude_websearch_supplement_enabled() is False


def test_unrecognized_value_falls_back_to_false(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENABLED_ENV, "maybe")
    assert is_claude_websearch_supplement_enabled() is False


def test_model_defaults_to_claude_sonnet_5_5_not_the_no_search_default(monkeypatch):
    # Task 6-D-4A-1/6-D-4A-2: the no-search default (services/
    # claude_settings.py's DEFAULT_MODEL, "claude-sonnet-4-5") is an
    # Anthropic-deprecated model (deprecated 2026-09-30, tentative
    # retirement 2026-11-30) — this module's own default must never be
    # that value.
    _clear_env(monkeypatch)
    assert get_claude_websearch_model() == DEFAULT_CLAUDE_WEBSEARCH_MODEL
    assert get_claude_websearch_model() != "claude-sonnet-4-5"


def test_model_env_override_is_honored(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MODEL_ENV, "claude-opus-5-5")
    assert get_claude_websearch_model() == "claude-opus-5-5"


def test_blank_model_env_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MODEL_ENV, "   ")
    assert get_claude_websearch_model() == DEFAULT_CLAUDE_WEBSEARCH_MODEL


def test_max_output_tokens_defaults_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert get_claude_websearch_max_output_tokens() == DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_env_override_within_range_is_honored(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, "3000")
    assert get_claude_websearch_max_output_tokens() == 3000


def test_max_output_tokens_non_integer_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, "not-a-number")
    assert get_claude_websearch_max_output_tokens() == DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_below_minimum_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, str(MIN_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS - 1))
    assert get_claude_websearch_max_output_tokens() == DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS


def test_max_output_tokens_above_maximum_falls_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_MAX_OUTPUT_TOKENS_ENV, str(MAX_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS + 1))
    assert get_claude_websearch_max_output_tokens() == DEFAULT_CLAUDE_WEBSEARCH_MAX_OUTPUT_TOKENS
