"""Bounded JWKS cache for asymmetric JWT verification (M2 B2a, ADR-0002).

- Fetched with an injected ``httpx.AsyncClient``: one GET, no redirects, a 2 s timeout, and a body
  capped at 64 KiB *while streaming* (an oversized body is abandoned, not read).
- Only signature keys CARVIS accepts are kept: EC P-256 (ES256) and RSA of at least 2048 bits
  (RS256), with ``use`` absent or ``sig`` and an ``alg``, when given, that matches. A document with a
  duplicate ``kid`` or more than 20 keys is rejected as a whole.
- Keys are cached for 10 minutes. An unknown ``kid`` triggers at most one refresh per 60 s
  (single-flight), so a flood of tokens with random ``kid`` values cannot amplify requests.
- When a refresh fails, the last good keys keep working for at most 1 hour after they were fetched;
  with no usable keys :class:`AuthUnavailable` is raised (the API answers 503 in B2c, never 401).

Errors carry fixed reason codes; URLs, bodies and keys are never logged or placed in messages.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Callable
from urllib.parse import urlsplit

ALGORITHM_FOR_KEY = {"EC": "ES256", "RSA": "RS256"}
MIN_RSA_BITS = 2048
MAX_JWKS_BYTES = 64 * 1024
MAX_KEYS = 20
FETCH_TIMEOUT_SECONDS = 2.0
CACHE_SECONDS = 600.0
MIN_REFRESH_INTERVAL_SECONDS = 60.0
MAX_STALE_SECONDS = 3600.0


class AuthUnavailable(RuntimeError):
    """No usable verification keys (issuer unreachable or misconfigured). Not the caller's fault."""


class UnknownKey(LookupError):
    """The token names a ``kid`` the issuer does not publish."""


class JwksError(ValueError):
    """A JWKS response that CARVIS refuses to use. Carries a reason code only."""


def _parse_keys(document: object) -> dict:
    """``kid`` → ``PyJWK`` for the usable signature keys; unusable keys are skipped, never trusted."""
    import jwt

    if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
        raise JwksError("not_a_jwks")
    entries = document["keys"]
    if len(entries) > MAX_KEYS:
        raise JwksError("too_many_keys")
    seen: set[str] = set()
    keys: dict = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise JwksError("bad_key")
        if any(name in entry for name in ("d", "p", "q", "dp", "dq", "qi", "k")):
            raise JwksError("secret_key_material")  # a JWKS must publish public keys only
        kid = entry.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 256:
            continue  # a key without a usable kid can never be selected
        if kid in seen:
            raise JwksError("duplicate_kid")
        seen.add(kid)
        algorithm = ALGORITHM_FOR_KEY.get(entry.get("kty"))
        if (algorithm is None or entry.get("use") not in (None, "sig") or entry.get("alg") not in (None, algorithm)
                or (entry.get("kty") == "EC" and entry.get("crv") != "P-256")):
            continue
        try:
            key = jwt.PyJWK(entry, algorithm=algorithm)
        except Exception:  # noqa: BLE001 - malformed key material is skipped; never echoed
            continue
        if algorithm == "RS256" and getattr(key.key, "key_size", 0) < MIN_RSA_BITS:
            continue
        keys[kid] = key
    return keys


def validate_jwks_url(url: str, allow_http: bool) -> str:
    parts = urlsplit(url)
    if parts.scheme not in (("https", "http") if allow_http else ("https",)) or not parts.hostname:
        raise JwksError("bad_jwks_url")
    if parts.username or parts.password:
        raise JwksError("bad_jwks_url")
    return url


class JwksCache:
    def __init__(self, url: str, client, *, allow_http: bool = False, cache_seconds: float = CACHE_SECONDS,
                 min_refresh_interval: float = MIN_REFRESH_INTERVAL_SECONDS,
                 max_stale_seconds: float = MAX_STALE_SECONDS, max_bytes: int = MAX_JWKS_BYTES,
                 timeout: float = FETCH_TIMEOUT_SECONDS, clock: Callable[[], float] = time.monotonic) -> None:
        self._url = validate_jwks_url(url, allow_http)
        self._client = client
        self._cache_seconds = cache_seconds
        self._min_refresh_interval = min_refresh_interval
        self._max_stale = max_stale_seconds
        self._max_bytes = max_bytes
        self._timeout = timeout
        self._clock = clock
        self._keys: dict = {}
        self._fetched_at: float | None = None
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()
        self.fetches = 0

    def __repr__(self) -> str:
        return f"JwksCache(keys={len(self._keys)})"

    def _fresh(self, now: float) -> bool:
        return self._fetched_at is not None and now < self._fetched_at + self._cache_seconds

    def _may_refresh(self, now: float) -> bool:
        return self._last_attempt is None or now - self._last_attempt >= self._min_refresh_interval

    async def key_for(self, kid: str):
        now = self._clock()
        if self._fresh(now) and kid in self._keys:
            return self._keys[kid]
        if not self._fresh(now) or (kid not in self._keys and self._may_refresh(now)):
            async with self._lock:
                now = self._clock()
                if not self._fresh(now) or (kid not in self._keys and self._may_refresh(now)):
                    await self._refresh(now)
        # _refresh drops keys once they are older than the stale window and a refresh has failed.
        if self._fetched_at is None or not self._keys:
            raise AuthUnavailable("no_verification_keys")
        key = self._keys.get(kid)
        if key is None:
            raise UnknownKey("unknown_kid")
        return key

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now
        self.fetches += 1
        try:
            keys = _parse_keys(await self._fetch())
        except Exception:  # noqa: BLE001 - keep the last good keys within the stale window
            if self._fetched_at is not None and now - self._fetched_at > self._max_stale:
                self._keys = {}
            return
        self._keys = keys
        self._fetched_at = self._clock()

    async def _fetch(self) -> object:
        body = bytearray()
        async with asyncio.timeout(self._timeout):
            async with self._client.stream("GET", self._url, follow_redirects=False,
                                           headers={"Accept": "application/json"}) as response:
                if response.status_code != 200:
                    raise JwksError("bad_status")
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_bytes:
                        raise JwksError("too_large")
        return json.loads(bytes(body))
