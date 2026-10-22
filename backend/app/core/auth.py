import base64
import threading
import time
from typing import Callable
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.core.config import Settings, get_settings

_bearer = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    id: UUID
    email: str | None = None


class AuthError(Exception):
    """Raised when a bearer token is missing, malformed, expired or untrusted."""


class JwksUnavailable(Exception):
    """Raised when the signing keys cannot be fetched (not the caller's fault)."""


def _origin(base_url: str) -> str:
    parsed = urlparse(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _ed25519_key(jwk: dict) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(jwk["x"] + "=="))


class JwksCache:
    """Caches the Neon Auth signing keys.

    Refreshes when the cache expires, or when a token names an unknown key id (a key
    rotation) — but at most once per min_refresh_seconds, so junk key ids cannot make
    the server hit the auth service on every request.
    """

    def __init__(
        self,
        fetch: Callable[[], dict],
        ttl_seconds: int = 3600,
        min_refresh_seconds: int = 30,
    ):
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._keys: dict[str, Ed25519PublicKey] = {}
        self._loaded_at: float | None = None
        self._lock = threading.Lock()

    def _refresh(self) -> None:
        try:
            jwks = self._fetch()
            self._keys = {k["kid"]: _ed25519_key(k) for k in jwks.get("keys", [])}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise JwksUnavailable(str(exc)) from exc
        self._loaded_at = time.monotonic()

    def key_for(self, kid: str) -> Ed25519PublicKey:
        with self._lock:
            age = None if self._loaded_at is None else time.monotonic() - self._loaded_at
            if age is None or age > self._ttl or (kid not in self._keys and age >= self._min_refresh):
                self._refresh()
            if kid not in self._keys:
                raise AuthError("unknown signing key")
            return self._keys[kid]


def verify_token(token: str, base_url: str, cache: JwksCache) -> dict:
    """Verify a Neon Auth JWT (EdDSA) and return its claims."""
    if not base_url:
        raise AuthError("NEON_AUTH_BASE_URL is not configured")
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        if not kid:
            raise AuthError("token has no key id")
        origin = _origin(base_url)
        return jwt.decode(
            token,
            key=cache.key_for(kid),
            algorithms=["EdDSA"],
            issuer=origin,
            audience=origin,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc


_cache: JwksCache | None = None


def _default_cache(settings: Settings) -> JwksCache:
    global _cache
    if _cache is None:
        url = f"{settings.neon_auth_base_url.rstrip('/')}/.well-known/jwks.json"

        def fetch() -> dict:
            response = httpx.get(url, timeout=10)
            response.raise_for_status()
            return response.json()

        _cache = JwksCache(fetch)
    return _cache


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    """FastAPI dependency: the signed-in user, from the Authorization: Bearer token."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        claims = verify_token(
            credentials.credentials, settings.neon_auth_base_url, _default_cache(settings)
        )
        return AuthUser(id=UUID(claims["sub"]), email=claims.get("email"))
    except JwksUnavailable as exc:
        raise HTTPException(status_code=503, detail="Auth service unavailable") from exc
    except (AuthError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
