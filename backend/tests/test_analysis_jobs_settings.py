from services.analysis_jobs_settings import (
    DEFAULT_MAX_QUEUED_PER_PROJECT,
    DEFAULT_MAX_QUEUED_PER_USER,
    load_analysis_jobs_settings,
)


def _clear_env(monkeypatch):
    for name in (
        "ANALYSIS_JOBS_ENABLED",
        "ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT",
        "ANALYSIS_JOBS_MAX_QUEUED_PER_USER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_disabled(monkeypatch):
    _clear_env(monkeypatch)
    settings = load_analysis_jobs_settings()

    assert settings.enabled is False
    assert settings.max_queued_per_project == DEFAULT_MAX_QUEUED_PER_PROJECT
    assert settings.max_queued_per_user == DEFAULT_MAX_QUEUED_PER_USER


def test_enabled_true(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "true")
    assert load_analysis_jobs_settings().enabled is True


def test_enabled_is_case_insensitive_and_accepts_common_truthy_spellings(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("TRUE", "1", "yes", "on"):
        monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", value)
        assert load_analysis_jobs_settings().enabled is True


def test_invalid_enabled_falls_back_to_false(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "maybe")
    assert load_analysis_jobs_settings().enabled is False


def test_limits_can_be_overridden(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT", "10")
    monkeypatch.setenv("ANALYSIS_JOBS_MAX_QUEUED_PER_USER", "2")

    settings = load_analysis_jobs_settings()

    assert settings.max_queued_per_project == 10
    assert settings.max_queued_per_user == 2


def test_invalid_or_non_positive_limits_fall_back_to_default(monkeypatch):
    _clear_env(monkeypatch)
    for value in ("0", "-1", "not-a-number", ""):
        monkeypatch.setenv("ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT", value)
        assert (
            load_analysis_jobs_settings().max_queued_per_project
            == DEFAULT_MAX_QUEUED_PER_PROJECT
        )
