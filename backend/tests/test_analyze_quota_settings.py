"""Tests for services/analyze_quota_settings.py (Task 6-B4,
feature/sync-analyze-jwt-project-auth)."""

from services.analyze_quota_settings import load_analyze_quota_settings

_ALL_ENV_NAMES = [
    "ANALYZE_QUOTA_ENFORCEMENT_ENABLED",
    "ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA",
    "ANALYZE_QUOTA_MAX_USER_DAILY",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_SANDBOX",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_SANDBOX",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_LIVE",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_LIVE",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_OPENAI",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY_ANTHROPIC",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_ANTHROPIC",
    "ANALYZE_QUOTA_MAX_PROJECT_DAILY_GOOGLE",
    "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_GOOGLE",
]


def _clear_env(monkeypatch):
    for name in _ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_everything_unset(monkeypatch):
    _clear_env(monkeypatch)
    settings = load_analyze_quota_settings()

    assert settings.enforcement_enabled is False
    assert settings.allow_auth_without_quota is False
    assert settings.max_user_daily == 20
    assert settings.max_project_daily == 50
    assert settings.max_project_monthly == 500
    assert settings.max_project_daily_by_metric == {
        "dataforseo_sandbox": 50,
        "dataforseo_live": 0,
        "openai": 0,
        "anthropic": 0,
        "google": 0,
    }
    assert settings.max_project_monthly_by_metric == {
        "dataforseo_sandbox": 500,
        "dataforseo_live": 0,
        "openai": 0,
        "anthropic": 0,
        "google": 0,
    }


def test_zero_is_a_valid_explicit_value_for_every_paid_provider_limit(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_SANDBOX", "0")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_USER_DAILY", "0")

    settings = load_analyze_quota_settings()

    assert settings.max_user_daily == 0
    assert settings.max_project_daily_by_metric["dataforseo_sandbox"] == 0


def test_negative_value_falls_back_to_the_safe_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI", "-5")

    settings = load_analyze_quota_settings()

    assert settings.max_project_daily_by_metric["openai"] == 0


def test_non_integer_value_falls_back_to_the_safe_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_ANTHROPIC", "unlimited")

    settings = load_analyze_quota_settings()

    assert settings.max_project_monthly_by_metric["anthropic"] == 0


def test_blank_value_falls_back_to_the_safe_default(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_DAILY_GOOGLE", "   ")

    settings = load_analyze_quota_settings()

    assert settings.max_project_daily_by_metric["google"] == 0


def test_an_invalid_paid_provider_value_never_falls_back_to_a_permissive_default(monkeypatch):
    """The core safety property this module exists for: whatever goes
    wrong with a paid-provider env var (missing, blank, negative,
    non-numeric), the result must be the provider's own safe default
    (0 for every paid provider), never silently promoted to the
    "all_analyses"-style non-zero defaults used elsewhere."""
    _clear_env(monkeypatch)
    for name in [
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_DATAFORSEO_LIVE",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_LIVE",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_OPENAI",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_ANTHROPIC",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_ANTHROPIC",
        "ANALYZE_QUOTA_MAX_PROJECT_DAILY_GOOGLE",
        "ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_GOOGLE",
    ]:
        monkeypatch.setenv(name, "not-a-number")

    settings = load_analyze_quota_settings()

    for metric in ("dataforseo_live", "openai", "anthropic", "google"):
        assert settings.max_project_daily_by_metric[metric] == 0
        assert settings.max_project_monthly_by_metric[metric] == 0


def test_explicit_positive_value_raises_the_cap(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_DAILY_OPENAI", "15")
    monkeypatch.setenv("ANALYZE_QUOTA_MAX_PROJECT_MONTHLY_DATAFORSEO_LIVE", "30")

    settings = load_analyze_quota_settings()

    assert settings.max_project_daily_by_metric["openai"] == 15
    assert settings.max_project_monthly_by_metric["dataforseo_live"] == 30


def test_enforcement_and_override_flags_default_to_false_and_parse_booleans(monkeypatch):
    _clear_env(monkeypatch)
    assert load_analyze_quota_settings().enforcement_enabled is False
    assert load_analyze_quota_settings().allow_auth_without_quota is False

    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "true")
    monkeypatch.setenv("ANALYZE_ALLOW_AUTH_WITHOUT_QUOTA", "true")
    settings = load_analyze_quota_settings()
    assert settings.enforcement_enabled is True
    assert settings.allow_auth_without_quota is True


def test_invalid_boolean_value_falls_back_to_false(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ANALYZE_QUOTA_ENFORCEMENT_ENABLED", "maybe")

    settings = load_analyze_quota_settings()

    assert settings.enforcement_enabled is False
