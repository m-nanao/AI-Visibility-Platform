from services.auth_settings import (
    load_auth_settings,
    is_jwt_verification_configured,
)


def _clear_auth_env(monkeypatch):
    for name in (
        "AUTH_JWT_ENABLED",
        "AUTH_PROVIDER",
        "SUPABASE_JWKS_URL",
        "SUPABASE_JWT_ISSUER",
        "SUPABASE_JWT_AUDIENCE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_disabled(monkeypatch):
    _clear_auth_env(monkeypatch)
    settings = load_auth_settings()

    assert settings.jwt_enabled is False
    assert settings.provider == "supabase"
    assert settings.jwks_url is None
    assert settings.issuer is None
    assert settings.audience is None
    assert is_jwt_verification_configured(settings) is False


def test_jwt_enabled_true(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    assert load_auth_settings().jwt_enabled is True


def test_jwt_enabled_is_case_insensitive_and_accepts_common_truthy_spellings(
    monkeypatch,
):
    _clear_auth_env(monkeypatch)
    for value in ("TRUE", "1", "yes", "on"):
        monkeypatch.setenv("AUTH_JWT_ENABLED", value)
        assert load_auth_settings().jwt_enabled is True


def test_invalid_jwt_enabled_falls_back_to_false(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "not-a-boolean")
    assert load_auth_settings().jwt_enabled is False


def test_provider_defaults_to_supabase_when_unset(monkeypatch):
    _clear_auth_env(monkeypatch)
    assert load_auth_settings().provider == "supabase"


def test_provider_is_read_verbatim_when_set(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_PROVIDER", "custom-provider")
    assert load_auth_settings().provider == "custom-provider"


def test_jwks_url_is_read_verbatim(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    )
    assert (
        load_auth_settings().jwks_url
        == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    )


def test_blank_jwks_url_is_treated_as_unset(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "   ")
    assert load_auth_settings().jwks_url is None


def test_issuer_and_audience_are_read_verbatim(monkeypatch):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", "https://example.supabase.co/auth/v1")
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "authenticated")

    settings = load_auth_settings()

    assert settings.issuer == "https://example.supabase.co/auth/v1"
    assert settings.audience == "authenticated"


def test_is_jwt_verification_configured_requires_both_enabled_and_jwks_url(
    monkeypatch,
):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("AUTH_JWT_ENABLED", "true")
    # AUTH_JWT_ENABLED alone (no SUPABASE_JWKS_URL) must not be enough.
    assert is_jwt_verification_configured(load_auth_settings()) is False

    monkeypatch.setenv(
        "SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    )
    assert is_jwt_verification_configured(load_auth_settings()) is True


def test_is_jwt_verification_configured_false_when_jwks_url_set_but_disabled(
    monkeypatch,
):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    )
    # SUPABASE_JWKS_URL alone (AUTH_JWT_ENABLED still false) must not be enough.
    assert is_jwt_verification_configured(load_auth_settings()) is False
