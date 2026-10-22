import base64
import time
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import auth
from app.core.auth import AuthError, AuthUser, JwksCache, current_user, verify_token
from app.core.config import Settings, get_settings

BASE_URL = "https://ep-test.aws.neon.tech/neondb/auth"
ORIGIN = "https://ep-test.aws.neon.tech"


def make_key(kid="key-1"):
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    jwk = {"kty": "OKP", "crv": "Ed25519", "kid": kid,
           "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}
    return private, jwk


def sign(private, kid="key-1", **overrides):
    claims = {"sub": str(uuid4()), "email": "pm@example.com", "iss": ORIGIN, "aud": ORIGIN,
              "iat": int(time.time()), "exp": int(time.time()) + 600}
    claims.update(overrides)
    return jwt.encode(claims, private, algorithm="EdDSA", headers={"kid": kid})


@pytest.fixture
def key():
    return make_key()


@pytest.fixture
def cache(key):
    _, jwk = key
    return JwksCache(lambda: {"keys": [jwk]})


def test_valid_token(key, cache):
    private, _ = key
    sub = str(uuid4())
    claims = verify_token(sign(private, sub=sub), BASE_URL, cache)
    assert claims["sub"] == sub


def test_expired_token(key, cache):
    private, _ = key
    with pytest.raises(AuthError):
        verify_token(sign(private, exp=int(time.time()) - 10), BASE_URL, cache)


def test_wrong_issuer(key, cache):
    private, _ = key
    with pytest.raises(AuthError):
        verify_token(sign(private, iss="https://evil.example"), BASE_URL, cache)


def test_wrong_audience(key, cache):
    private, _ = key
    with pytest.raises(AuthError):
        verify_token(sign(private, aud="https://evil.example"), BASE_URL, cache)


def test_unknown_key_id(key, cache):
    private, _ = key
    with pytest.raises(AuthError):
        verify_token(sign(private, kid="other"), BASE_URL, cache)


def test_token_signed_by_another_key(cache):
    stranger, _ = make_key()
    with pytest.raises(AuthError):
        verify_token(sign(stranger), BASE_URL, cache)


def test_garbage_token(cache):
    with pytest.raises(AuthError):
        verify_token("not-a-jwt", BASE_URL, cache)


def test_unconfigured_base_url(key, cache):
    private, _ = key
    with pytest.raises(AuthError):
        verify_token(sign(private), "", cache)


def test_cache_refetches_when_key_is_rotated():
    old_private, old_jwk = make_key("old")
    new_private, new_jwk = make_key("new")
    served = [{"keys": [old_jwk]}]
    cache = JwksCache(lambda: served[0], min_refresh_seconds=0)
    verify_token(sign(old_private, kid="old"), BASE_URL, cache)
    served[0] = {"keys": [old_jwk, new_jwk]}  # Neon rotated keys
    verify_token(sign(new_private, kid="new"), BASE_URL, cache)


def test_unknown_key_ids_do_not_hammer_the_auth_service(key):
    private, jwk = key
    fetches = []

    def fetch():
        fetches.append(1)
        return {"keys": [jwk]}

    cache = JwksCache(fetch)  # default 30 s throttle
    verify_token(sign(private), BASE_URL, cache)
    for i in range(20):
        with pytest.raises(AuthError):
            verify_token(sign(private, kid=f"junk-{i}"), BASE_URL, cache)
    assert len(fetches) == 1


def test_jwks_outage_is_not_reported_as_a_bad_token(key, monkeypatch):
    private, _ = key

    def fetch():
        raise httpx.ConnectError("auth service down")

    monkeypatch.setattr(auth, "_default_cache", lambda settings: JwksCache(fetch))
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: Settings(neon_auth_base_url=BASE_URL)

    @app.get("/me")
    def me(user: AuthUser = Depends(current_user)):
        return {"id": str(user.id)}

    response = TestClient(app).get("/me", headers={"Authorization": f"Bearer {sign(private)}"})
    assert response.status_code == 503


def test_current_user_dependency(key, cache, monkeypatch):
    private, _ = key
    monkeypatch.setattr(auth, "_default_cache", lambda settings: cache)
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: Settings(neon_auth_base_url=BASE_URL)

    @app.get("/me")
    def me(user: AuthUser = Depends(current_user)):
        return {"id": str(user.id), "email": user.email}

    client = TestClient(app)
    assert client.get("/me").status_code == 401  # no token
    assert client.get("/me", headers={"Authorization": "Bearer junk"}).status_code == 401

    sub = str(uuid4())
    ok = client.get("/me", headers={"Authorization": f"Bearer {sign(private, sub=sub)}"})
    assert ok.status_code == 200
    assert ok.json() == {"id": sub, "email": "pm@example.com"}
