"""Tests for services/chatgpt_websearch_settings.py (Task 6-D-3,
feature/chatgpt-websearch-supplement)."""

from services.chatgpt_websearch_settings import is_chatgpt_websearch_supplement_enabled

_ENV_NAME = "CHATGPT_WEBSEARCH_SUPPLEMENT_ENABLED"


def _clear_env(monkeypatch):
    monkeypatch.delenv(_ENV_NAME, raising=False)


def test_defaults_to_false_when_unset(monkeypatch):
    _clear_env(monkeypatch)
    assert is_chatgpt_websearch_supplement_enabled() is False


def test_true_values_enable_it(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("1", "true", "True", "yes", "on"):
        monkeypatch.setenv(_ENV_NAME, value)
        assert is_chatgpt_websearch_supplement_enabled() is True


def test_false_values_keep_it_disabled(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("0", "false", "False", "no", "off"):
        monkeypatch.setenv(_ENV_NAME, value)
        assert is_chatgpt_websearch_supplement_enabled() is False


def test_unrecognized_value_falls_back_to_false(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv(_ENV_NAME, "maybe")
    assert is_chatgpt_websearch_supplement_enabled() is False
