"""Supabase Auth JWT verification (Authorization: Bearer <token>).

Phase 1 of docs/32_backend_jwt_verification_design.md's staged plan
("8. HISTORY_READ_TOKENからの移行方針") — this module is deliberately
NOT wired into any API endpoint yet. It exists so the verification
logic itself can be built and tested in isolation before a later task
adds project-level authorization (docs/32 "9. project権限判定") and
integrates it into main.py alongside the existing HISTORY_READ_TOKEN
gate. Verifying a JWT alone must never be treated as authorization to
read another user's history — see docs/32 "対象外".

Never logs or includes the raw token (or any claim value) in an
exception message — every failure is represented by JWTAuthError.reason,
a fixed short string, so callers/logs can distinguish failure types
without ever interpolating token contents.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import jwt

from .auth_settings import AuthSettings

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "

# Supabase issues RS256-signed access tokens when a project's JWKS
# endpoint is enabled; ES256 is accepted for forward compatibility with
# Supabase's asymmetric-key rollout. HS256 is intentionally excluded —
# a JWKS document only ever contains public keys, so a symmetric HS256
# token could never be verified against one anyway.
SUPPORTED_ALGORITHMS = ["RS256", "ES256"]


@dataclass(frozen=True)
class AuthenticatedUser:
    """Result of a successful JWT verification. Deliberately minimal —
    raw claims are never returned, only the fields a caller needs.
    `user_id` is the token's `sub` claim (Supabase Auth's user id).
    """

    user_id: str
    provider: str = "supabase"
    email: str | None = None


class JWTAuthError(Exception):
    """Raised for every JWT verification failure. `reason` is a fixed,
    short machine-readable string — never the token itself or a raw
    claim value.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def extract_bearer_token(authorization_header: str | None) -> str:
    """Parses an `Authorization` header value and returns the bearer
    token. Only the exact `Bearer <token>` form (case-sensitive
    "Bearer", single space, non-empty token) is accepted — this project
    does not accept a lowercase "bearer" scheme or any other variant.
    Raises JWTAuthError("missing_header", ...) when the header itself
    is absent/empty, or JWTAuthError("invalid_header", ...) when it is
    present but malformed.
    """
    if not authorization_header:
        raise JWTAuthError("missing_header", "Authorization header is missing")

    if not authorization_header.startswith(BEARER_PREFIX):
        raise JWTAuthError(
            "invalid_header", "Authorization header must use the Bearer scheme"
        )

    token = authorization_header[len(BEARER_PREFIX) :].strip()
    if not token:
        raise JWTAuthError("invalid_header", "Bearer token is empty")

    return token


def get_supabase_jwks(jwks_url: str, timeout: float = 5.0) -> dict:
    """Fetches the JWKS document from Supabase. This is the only
    network I/O in this module — tests must monkeypatch this function
    rather than exercising a real request (no external JWKS endpoint is
    reachable in CI/local test runs).
    """
    response = httpx.get(jwks_url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _find_signing_key_data(jwks: dict, kid: str | None) -> dict | None:
    for key in jwks.get("keys", []):
        if kid is None or key.get("kid") == kid:
            return key
    return None


def verify_supabase_jwt(token: str, settings: AuthSettings) -> AuthenticatedUser:
    """Verifies a Supabase Auth access token against the project's
    JWKS and returns the authenticated user. Raises JWTAuthError for
    every failure mode (JWKS fetch failure, unknown key, bad signature,
    expired, wrong issuer/audience, missing subject) — never returns a
    partial or "best effort" result.

    `issuer`/`audience` checks are skipped when the corresponding
    setting is unset (both are optional per
    docs/32_backend_jwt_verification_design.md "6. 必要env案"); `exp`
    and `sub` are always required.
    """
    if settings.jwks_url is None:
        raise JWTAuthError("not_configured", "JWT verification is not configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise JWTAuthError("invalid_token", "token could not be parsed") from None

    try:
        jwks = get_supabase_jwks(settings.jwks_url)
    except httpx.HTTPError:
        raise JWTAuthError(
            "jwks_fetch_failed", "failed to fetch signing keys"
        ) from None

    key_data = _find_signing_key_data(jwks, header.get("kid"))
    if key_data is None:
        raise JWTAuthError("unknown_key", "no matching signing key found")

    try:
        signing_key = jwt.PyJWK(key_data).key
    except (jwt.InvalidKeyError, jwt.PyJWKError, ValueError):
        raise JWTAuthError("unknown_key", "signing key could not be parsed") from None

    decode_kwargs: dict = {
        "algorithms": SUPPORTED_ALGORITHMS,
        # verify_iss/verify_aud default to True whenever the token
        # itself carries an iss/aud claim, regardless of whether this
        # process passes an expected value — explicitly disabling them
        # when the corresponding setting is unset is what actually
        # makes issuer/audience checks optional (confirmed against
        # PyJWT 2.13's behavior; omitting `issuer=`/`audience=` alone
        # is not enough).
        "options": {
            "require": ["exp", "sub"],
            "verify_iss": bool(settings.issuer),
            "verify_aud": bool(settings.audience),
        },
    }
    if settings.issuer:
        decode_kwargs["issuer"] = settings.issuer
    if settings.audience:
        decode_kwargs["audience"] = settings.audience

    try:
        claims = jwt.decode(token, key=signing_key, **decode_kwargs)
    except jwt.ExpiredSignatureError:
        raise JWTAuthError("expired", "token has expired") from None
    except jwt.InvalidIssuerError:
        raise JWTAuthError("invalid_issuer", "token issuer does not match") from None
    except jwt.InvalidAudienceError:
        raise JWTAuthError(
            "invalid_audience", "token audience does not match"
        ) from None
    except jwt.MissingRequiredClaimError:
        raise JWTAuthError(
            "missing_subject", "token is missing required claims"
        ) from None
    except jwt.InvalidSignatureError:
        raise JWTAuthError("invalid_signature", "token signature is invalid") from None
    except jwt.InvalidTokenError:
        raise JWTAuthError("invalid_token", "token could not be verified") from None

    user_id = claims.get("sub")
    if not user_id:
        raise JWTAuthError("missing_subject", "token has no subject claim")

    return AuthenticatedUser(user_id=user_id, email=claims.get("email"))
