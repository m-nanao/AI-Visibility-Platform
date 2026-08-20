from services.db_settings import load_db_settings, is_db_save_configured


def _clear_db_env(monkeypatch):
    for name in ("DB_SAVE_ENABLED", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_disabled(monkeypatch):
    _clear_db_env(monkeypatch)
    settings = load_db_settings()

    assert settings.save_enabled is False
    assert settings.database_url is None
    assert is_db_save_configured(settings) is False


def test_save_enabled_true(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_SAVE_ENABLED", "true")
    assert load_db_settings().save_enabled is True


def test_save_enabled_is_case_insensitive_and_accepts_common_truthy_spellings(monkeypatch):
    _clear_db_env(monkeypatch)
    for value in ("TRUE", "1", "yes", "on"):
        monkeypatch.setenv("DB_SAVE_ENABLED", value)
        assert load_db_settings().save_enabled is True


def test_invalid_save_enabled_falls_back_to_false(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_SAVE_ENABLED", "not-a-boolean")
    assert load_db_settings().save_enabled is False


def test_database_url_is_read_verbatim(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    assert load_db_settings().database_url == "postgresql://user:pass@host:5432/db"


def test_blank_database_url_is_none(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "   ")
    assert load_db_settings().database_url is None


# --- is_db_save_configured ----------------------------------------------


def test_is_db_save_configured_requires_both_enabled_and_url(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DB_SAVE_ENABLED", "true")
    # DATABASE_URL still unset.
    assert is_db_save_configured() is False

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    assert is_db_save_configured() is True


def test_is_db_save_configured_false_when_url_set_but_disabled(monkeypatch):
    _clear_db_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/db")
    assert is_db_save_configured() is False
