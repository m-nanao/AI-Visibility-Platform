"""Reads backend JWT-verification-related environment variables into a
small settings object.

Placed under services/ to match the existing convention of every other
settings module living here (see services/db_settings.py,
services/common_crawl_settings.py, services/dataforseo_settings.py,
services/chatgpt_settings.py).

This is Phase 1 of docs/32_backend_jwt_verification_design.md's staged
migration ("8. HISTORY_READ_TOKENからの移行方針") — JWT verification
support only, not wired into any API endpoint. `AUTH_JWT_ENABLED`
defaults to False so existing deployments (which don't set any of these
vars) are unaffected. None of these values are secrets in the strict
sense (a JWKS URL and issuer/audience strings are public by design —
Supabase's JWKS endpoint serves public keys), but they're still never
logged verbatim in case an operator points SUPABASE_JWKS_URL at a
non-public URL.
"""

import os
from dataclasses import dataclass

DEFAULT_AUTH_PROVIDER = "supabase"
DEFAULT_JWT_ENABLED = False


@dataclass(frozen=True)
class AuthSettings:
    """Snapshot of backend JWT-verification configuration for the
    current process."""

    jwt_enabled: bool
    provider: str
    jwks_url: str | None
    issuer: str | None
    audience: str | None


def _resolve_jwt_enabled() -> bool:
    raw = os.environ.get("AUTH_JWT_ENABLED", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _resolve_provider() -> str:
    raw = os.environ.get("AUTH_PROVIDER", "").strip()
    return raw or DEFAULT_AUTH_PROVIDER


def _resolve_jwks_url() -> str | None:
    raw = os.environ.get("SUPABASE_JWKS_URL", "").strip()
    return raw or None


def _resolve_issuer() -> str | None:
    raw = os.environ.get("SUPABASE_JWT_ISSUER", "").strip()
    return raw or None


def _resolve_audience() -> str | None:
    raw = os.environ.get("SUPABASE_JWT_AUDIENCE", "").strip()
    return raw or None


def load_auth_settings() -> AuthSettings:
    """Reads AUTH_JWT_ENABLED/AUTH_PROVIDER/SUPABASE_JWKS_URL/
    SUPABASE_JWT_ISSUER/SUPABASE_JWT_AUDIENCE env vars fresh on every
    call (mirrors load_db_settings() and friends elsewhere in this
    codebase). Defaults to jwt_enabled=False — JWT verification is
    never attempted unless explicitly turned on.
    """
    return AuthSettings(
        jwt_enabled=_resolve_jwt_enabled(),
        provider=_resolve_provider(),
        jwks_url=_resolve_jwks_url(),
        issuer=_resolve_issuer(),
        audience=_resolve_audience(),
    )


def is_jwt_verification_configured(settings: AuthSettings | None = None) -> bool:
    """True only when JWT verification should be attempted at all —
    AUTH_JWT_ENABLED=true AND SUPABASE_JWKS_URL is set. `issuer` and
    `audience` are optional claim checks applied during verification
    itself (see jwt_auth.verify_supabase_jwt()) rather than gating
    whether verification is attempted at all.
    """
    settings = settings or load_auth_settings()
    return settings.jwt_enabled and settings.jwks_url is not None
