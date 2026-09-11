"""Verifies services/jwt_auth.py — Authorization header parsing and
Supabase JWT verification. No test in this file makes a real network
request: JWKS fetching (services.jwt_auth.get_supabase_jwks) is always
monkeypatched to return a JWKS built from a locally generated RSA key
pair, and tokens are signed locally with the matching private key.
"""

import json
import time

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

import services.jwt_auth as jwt_auth
from services.auth_settings import AuthSettings
from services.jwt_auth import (
    AuthenticatedUser,
    JWTAuthError,
    extract_bearer_token,
    verify_supabase_jwt,
)

TEST_KID = "test-key-1"
ISSUER = "https://example.supabase.co/auth/v1"
AUDIENCE = "authenticated"


def _generate_rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


_PRIVATE_KEY, _PUBLIC_KEY = _generate_rsa_keypair()
_OTHER_PRIVATE_KEY, _ = _generate_rsa_keypair()


def _jwk_for(public_key, kid: str) -> dict:
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk["kid"] = kid
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return jwk


def _jwks() -> dict:
    return {"keys": [_jwk_for(_PUBLIC_KEY, TEST_KID)]}


def _sign(
    claims: dict,
    private_key=_PRIVATE_KEY,
    kid: str | None = TEST_KID,
    algorithm: str = "RS256",
) -> str:
    headers = {"kid": kid} if kid is not None else {}
    return pyjwt.encode(claims, private_key, algorithm=algorithm, headers=headers)


def _valid_claims(**overrides) -> dict:
    claims = {
        "sub": "user-123",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "exp": int(time.time()) + 3600,
        "email": "user@example.com",
    }
    claims.update(overrides)
    return claims


def _settings(**overrides) -> AuthSettings:
    base = dict(
        jwt_enabled=True,
        provider="supabase",
        jwks_url="https://example.supabase.co/auth/v1/.well-known/jwks.json",
        issuer=ISSUER,
        audience=AUDIENCE,
    )
    base.update(overrides)
    return AuthSettings(**base)


@pytest.fixture(autouse=True)
def _mock_jwks(monkeypatch):
    """Every test in this file gets a working JWKS fetch by default;
    individual tests override this via monkeypatch when they need
    different behavior (e.g. a fetch failure or an empty key set)."""
    monkeypatch.setattr(jwt_auth, "get_supabase_jwks", lambda url, timeout=5.0: _jwks())


# --- extract_bearer_token ---------------------------------------------------


def test_extract_bearer_token_missing_header_raises():
    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token(None)
    assert exc_info.value.reason == "missing_header"


def test_extract_bearer_token_empty_header_raises():
    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token("")
    assert exc_info.value.reason == "missing_header"


def test_extract_bearer_token_without_bearer_scheme_raises():
    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token("Basic dXNlcjpwYXNz")
    assert exc_info.value.reason == "invalid_header"


def test_extract_bearer_token_lowercase_bearer_is_rejected():
    """Only the exact case-sensitive "Bearer" scheme is accepted (see
    module docstring) — this project does not treat "bearer" as
    equivalent."""
    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token("bearer sometoken")
    assert exc_info.value.reason == "invalid_header"


def test_extract_bearer_token_empty_token_raises():
    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token("Bearer ")
    assert exc_info.value.reason == "invalid_header"


def test_extract_bearer_token_success():
    assert extract_bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"


# --- verify_supabase_jwt: success -------------------------------------------


def test_verify_supabase_jwt_success_returns_authenticated_user():
    token = _sign(_valid_claims())

    user = verify_supabase_jwt(token, _settings())

    assert user == AuthenticatedUser(
        user_id="user-123", provider="supabase", email="user@example.com"
    )


def test_verify_supabase_jwt_success_without_email_claim():
    claims = _valid_claims()
    del claims["email"]
    token = _sign(claims)

    user = verify_supabase_jwt(token, _settings())

    assert user.user_id == "user-123"
    assert user.email is None


def test_verify_supabase_jwt_skips_issuer_check_when_unset():
    token = _sign(_valid_claims(iss="https://someone-else.example.com"))

    user = verify_supabase_jwt(token, _settings(issuer=None))

    assert user.user_id == "user-123"


def test_verify_supabase_jwt_skips_audience_check_when_unset():
    token = _sign(_valid_claims(aud="something-else"))

    user = verify_supabase_jwt(token, _settings(audience=None))

    assert user.user_id == "user-123"


# --- verify_supabase_jwt: failure modes --------------------------------------


def test_verify_supabase_jwt_not_configured_when_jwks_url_missing():
    token = _sign(_valid_claims())

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings(jwks_url=None))
    assert exc_info.value.reason == "not_configured"


def test_verify_supabase_jwt_jwks_fetch_failure(monkeypatch):
    def _raise(url, timeout=5.0):
        raise httpx.ConnectError("connection failed", request=httpx.Request("GET", url))

    monkeypatch.setattr(jwt_auth, "get_supabase_jwks", _raise)
    token = _sign(_valid_claims())

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "jwks_fetch_failed"


def test_verify_supabase_jwt_unknown_key_id(monkeypatch):
    monkeypatch.setattr(
        jwt_auth, "get_supabase_jwks", lambda url, timeout=5.0: {"keys": []}
    )
    token = _sign(_valid_claims())

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "unknown_key"


def test_verify_supabase_jwt_invalid_signature():
    """Signed with a different private key than the one whose public
    key is published in the JWKS — the kid still matches (an attacker
    controlling only a private key cannot forge a valid signature)."""
    token = _sign(_valid_claims(), private_key=_OTHER_PRIVATE_KEY)

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "invalid_signature"


def test_verify_supabase_jwt_expired():
    token = _sign(_valid_claims(exp=int(time.time()) - 60))

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "expired"


def test_verify_supabase_jwt_issuer_mismatch():
    token = _sign(_valid_claims(iss="https://wrong-project.supabase.co/auth/v1"))

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "invalid_issuer"


def test_verify_supabase_jwt_audience_mismatch():
    token = _sign(_valid_claims(aud="wrong-audience"))

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "invalid_audience"


def test_verify_supabase_jwt_missing_subject_claim():
    claims = _valid_claims()
    del claims["sub"]
    token = _sign(claims)

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "missing_subject"


def test_verify_supabase_jwt_empty_subject_claim_is_rejected():
    token = _sign(_valid_claims(sub=""))

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert exc_info.value.reason == "missing_subject"


def test_verify_supabase_jwt_malformed_token_string():
    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt("not-a-jwt-at-all", _settings())
    assert exc_info.value.reason == "invalid_token"


# --- token contents must never leak into an exception message --------------


def test_token_string_never_appears_in_exception_message_on_invalid_signature():
    token = _sign(_valid_claims(), private_key=_OTHER_PRIVATE_KEY)

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert token not in str(exc_info.value)


def test_token_string_never_appears_in_exception_message_on_malformed_token():
    token = "not-a-jwt-at-all"

    with pytest.raises(JWTAuthError) as exc_info:
        verify_supabase_jwt(token, _settings())
    assert token not in str(exc_info.value)


def test_bearer_header_value_never_appears_in_exception_message():
    header_value = "Bearer some-opaque-token-value"

    with pytest.raises(JWTAuthError) as exc_info:
        extract_bearer_token("Basic " + header_value)
    assert header_value not in str(exc_info.value)
