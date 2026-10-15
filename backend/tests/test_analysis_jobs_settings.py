from services.analysis_jobs_settings import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_QUEUED_PER_PROJECT,
    DEFAULT_MAX_QUEUED_PER_USER,
    DEFAULT_POLL_INTERVAL_SECONDS,
    load_analysis_jobs_settings,
)


def _clear_env(monkeypatch):
    for name in (
        "ANALYSIS_JOBS_ENABLED",
        "ANALYSIS_JOBS_WORKER_ENABLED",
        "ANALYSIS_JOBS_MAX_QUEUED_PER_PROJECT",
        "ANALYSIS_JOBS_MAX_QUEUED_PER_USER",
        "ANALYSIS_JOBS_LEASE_SECONDS",
        "ANALYSIS_JOBS_POLL_INTERVAL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_disabled(monkeypatch):
    _clear_env(monkeypatch)
    settings = load_analysis_jobs_settings()

    assert settings.enabled is False
    assert settings.worker_enabled is False
    assert settings.max_queued_per_project == DEFAULT_MAX_QUEUED_PER_PROJECT
    assert settings.max_queued_per_user == DEFAULT_MAX_QUEUED_PER_USER
    assert settings.lease_seconds == DEFAULT_LEASE_SECONDS
    assert settings.poll_interval_seconds == DEFAULT_POLL_INTERVAL_SECONDS


def test_worker_enabled_is_independent_of_jobs_enabled(monkeypatch):
    """ANALYSIS_JOBS_ENABLED and ANALYSIS_JOBS_WORKER_ENABLED must be
    settable independently — a job-API-on/worker-off configuration is
    intentional (docs/40_async_analysis_jobs_design.md, module
    docstring)."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_ENABLED", "true")

    settings = load_analysis_jobs_settings()

    assert settings.enabled is True
    assert settings.worker_enabled is False


def test_worker_enabled_true(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_WORKER_ENABLED", "true")
    assert load_analysis_jobs_settings().worker_enabled is True


def test_lease_and_poll_interval_can_be_overridden(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYSIS_JOBS_LEASE_SECONDS", "60")
    monkeypatch.setenv("ANALYSIS_JOBS_POLL_INTERVAL_SECONDS", "2")

    settings = load_analysis_jobs_settings()

    assert settings.lease_seconds == 60
    assert settings.poll_interval_seconds == 2


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
