"""Tests for services/fact_extraction_settings.py (Task 6-D-5C-2,
feature/claude-fact-extraction-mvp).
"""

import services.fact_extraction_settings as fes


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTION_ENABLED", raising=False)
    assert fes.is_fact_extraction_enabled() is False


def test_enabled_when_set_true(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "true")
    assert fes.is_fact_extraction_enabled() is True


def test_unrecognized_boolean_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_ENABLED", "maybe")
    assert fes.is_fact_extraction_enabled() == fes.DEFAULT_FACT_EXTRACTION_ENABLED


def test_default_model_is_on_the_allowlist():
    assert fes.DEFAULT_FACT_EXTRACTION_MODEL in fes.FACT_EXTRACTION_ALLOWED_MODELS


def test_model_env_override(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_MODEL", "claude-custom")
    assert fes.get_fact_extraction_model() == "claude-custom"


def test_model_falls_back_to_default_when_unset(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTION_MODEL", raising=False)
    assert fes.get_fact_extraction_model() == fes.DEFAULT_FACT_EXTRACTION_MODEL


def test_max_output_tokens_default(monkeypatch):
    monkeypatch.delenv("FACT_EXTRACTION_MAX_OUTPUT_TOKENS", raising=False)
    assert fes.get_fact_extraction_max_output_tokens() == fes.DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS


def test_max_output_tokens_out_of_range_falls_back(monkeypatch):
    monkeypatch.setenv("FACT_EXTRACTION_MAX_OUTPUT_TOKENS", "999999")
    assert fes.get_fact_extraction_max_output_tokens() == fes.DEFAULT_FACT_EXTRACTION_MAX_OUTPUT_TOKENS


def test_max_api_requests_per_run_is_one():
    assert fes.MAX_API_REQUESTS_PER_ANALYSIS_RUN == 1
