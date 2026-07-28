from services.common_crawl_settings import (
    DEFAULT_INDEX,
    DEFAULT_MAX_RESULTS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    load_common_crawl_settings,
)


def _clear_common_crawl_env(monkeypatch):
    for name in (
        "COMMON_CRAWL_ENABLED",
        "COMMON_CRAWL_INDEX",
        "COMMON_CRAWL_MAX_RESULTS",
        "COMMON_CRAWL_TIMEOUT_SECONDS",
        "COMMON_CRAWL_USER_AGENT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_all_safe(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    settings = load_common_crawl_settings()

    assert settings.enabled is False
    assert settings.index == DEFAULT_INDEX
    assert settings.max_results == DEFAULT_MAX_RESULTS
    assert settings.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert settings.user_agent == DEFAULT_USER_AGENT


# --- enabled -----------------------------------------------------------


def test_enabled_true(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_ENABLED", "true")
    assert load_common_crawl_settings().enabled is True


def test_enabled_false(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_ENABLED", "false")
    assert load_common_crawl_settings().enabled is False


def test_enabled_is_case_insensitive_and_accepts_common_truthy_spellings(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    for value in ("TRUE", "1", "yes", "on"):
        monkeypatch.setenv("COMMON_CRAWL_ENABLED", value)
        assert load_common_crawl_settings().enabled is True


def test_invalid_enabled_falls_back_to_false(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_ENABLED", "not-a-boolean")
    assert load_common_crawl_settings().enabled is False


# --- index ---------------------------------------------------------------


def test_index_defaults_to_latest(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    assert load_common_crawl_settings().index == "latest"


def test_index_accepts_cc_main_id(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_INDEX", "CC-MAIN-2026-08")
    assert load_common_crawl_settings().index == "CC-MAIN-2026-08"


def test_index_normalizes_case(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_INDEX", "cc-main-2026-08")
    assert load_common_crawl_settings().index == "CC-MAIN-2026-08"


def test_index_accepts_latest_explicitly_in_any_case(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_INDEX", "LATEST")
    assert load_common_crawl_settings().index == "latest"


def test_invalid_index_falls_back_to_latest(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_INDEX", "not-a-real-index")
    assert load_common_crawl_settings().index == "latest"


def test_index_missing_week_number_falls_back_to_latest(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_INDEX", "CC-MAIN-2026")
    assert load_common_crawl_settings().index == "latest"


# --- max_results -----------------------------------------------------------


def test_max_results_accepts_1(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "1")
    assert load_common_crawl_settings().max_results == 1


def test_max_results_accepts_5(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "5")
    assert load_common_crawl_settings().max_results == 5


def test_max_results_accepts_10(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "10")
    assert load_common_crawl_settings().max_results == 10


def test_max_results_non_integer_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "not-a-number")
    assert load_common_crawl_settings().max_results == DEFAULT_MAX_RESULTS


def test_max_results_below_minimum_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "0")
    assert load_common_crawl_settings().max_results == DEFAULT_MAX_RESULTS


def test_max_results_above_maximum_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_MAX_RESULTS", "11")
    assert load_common_crawl_settings().max_results == DEFAULT_MAX_RESULTS


# --- timeout_seconds -------------------------------------------------------


def test_timeout_accepts_3(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "3")
    assert load_common_crawl_settings().timeout_seconds == 3.0


def test_timeout_accepts_10(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "10")
    assert load_common_crawl_settings().timeout_seconds == 10.0


def test_timeout_accepts_30(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "30")
    assert load_common_crawl_settings().timeout_seconds == 30.0


def test_timeout_non_numeric_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "not-a-number")
    assert load_common_crawl_settings().timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_timeout_below_minimum_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "2")
    assert load_common_crawl_settings().timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_timeout_above_maximum_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_TIMEOUT_SECONDS", "31")
    assert load_common_crawl_settings().timeout_seconds == DEFAULT_TIMEOUT_SECONDS


# --- user_agent --------------------------------------------------------


def test_user_agent_empty_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_USER_AGENT", "   ")
    assert load_common_crawl_settings().user_agent == DEFAULT_USER_AGENT


def test_user_agent_custom_value_is_used(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_USER_AGENT", "MyCustomAgent/1.0")
    assert load_common_crawl_settings().user_agent == "MyCustomAgent/1.0"


def test_user_agent_too_long_falls_back_to_default(monkeypatch):
    _clear_common_crawl_env(monkeypatch)
    monkeypatch.setenv("COMMON_CRAWL_USER_AGENT", "x" * 500)
    assert load_common_crawl_settings().user_agent == DEFAULT_USER_AGENT


def test_settings_contain_no_secret_by_design(monkeypatch):
    # Common Crawl is public/unauthenticated — there is no credential
    # field or type in this module at all, unlike DataForSEO/ChatGPT.
    _clear_common_crawl_env(monkeypatch)
    settings = load_common_crawl_settings()
    field_names = {f for f in settings.__dataclass_fields__}
    assert field_names == {"enabled", "index", "max_results", "timeout_seconds", "user_agent"}
