"""Asymmetric JWT verification for the /v1 API (M2 B2a, ADR-0002). Not wired to any route in B2a.

:meth:`TokenVerifier.verify` returns a :class:`Principal` or raises :class:`InvalidToken` (the API
answers 401 with one generic message) or :class:`auth.jwks.AuthUnavailable` (503). Rules:

- At most 8 KiB, three base64url segments.
- Header: ``alg`` is ES256 or RS256 and matches the selected key's type; ``none``, every HMAC and any
  other algorithm are rejected; ``kid`` is required; tokens carrying ``jku``, ``x5u``, ``jwk``,
  ``x5c`` or ``crit`` are rejected (CARVIS never fetches keys a token points at).
- Claims: ``iss``, ``aud``, ``sub``, ``exp`` and ``iat`` are required; ``iss`` must equal the issuer
  exactly and ``aud`` must be (or contain) the audience; ``exp``, ``nbf`` and ``iat`` are checked with
  30 s leeway; ``exp − iat`` may not exceed 1 hour (no leeway on the lifetime); ``sub`` is 1–255
  characters without NUL.
- Supabase profile: ``role`` must be ``authenticated`` and ``is_anonymous``, when present, must be
  ``false``.
- ``email`` is optional (string, at most 320 characters) and is never authority.

The principal is ``(iss, sub)``; its ``repr`` shows only a short hash. Reason codes are for tests
and internal metrics, never for clients or logs of token content.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from auth.jwks import JwksCache, UnknownKey

ALLOWED_ALGORITHMS = ("ES256", "RS256")
FORBIDDEN_HEADERS = ("jku", "x5u", "jwk", "x5c", "crit")
LEEWAY_SECONDS = 30
MAX_LIFETIME_SECONDS = 3600
MAX_TOKEN_BYTES = 8 * 1024
MAX_SUBJECT_LENGTH = 255
MAX_EMAIL_LENGTH = 320
SUPABASE_ROLE = "authenticated"
TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class InvalidToken(Exception):
    """The token is not acceptable. ``reason`` is a fixed code; the message never carries token data."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Principal:
    issuer: str = field(repr=False)
    subject: str = field(repr=False)
    email: str | None = field(default=None, repr=False)

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.issuer}|{self.subject}".encode()).hexdigest()[:12]

    def __repr__(self) -> str:
        return f"Principal(fp={self.fingerprint})"

    __str__ = __repr__


class TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks: JwksCache, *, leeway: int = LEEWAY_SECONDS,
                 max_lifetime: int = MAX_LIFETIME_SECONDS, clock: Callable[[], float] = time.time) -> None:
        if not issuer or not audience:
            raise ValueError("issuer and audience are required")
        self._issuer = issuer
        self._audience = audience
        self._jwks = jwks
        self._leeway = leeway
        self._max_lifetime = max_lifetime
        self._clock = clock

    def __repr__(self) -> str:
        return "TokenVerifier()"

    async def verify(self, token: object) -> Principal:
        import jwt

        if not isinstance(token, str) or len(token.encode("utf-8", "replace")) > MAX_TOKEN_BYTES:
            raise InvalidToken("malformed")
        if not TOKEN_SHAPE.fullmatch(token):
            raise InvalidToken("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise InvalidToken("malformed") from None
        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise InvalidToken("algorithm")
        if any(name in header for name in FORBIDDEN_HEADERS):
            raise InvalidToken("header")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise InvalidToken("kid")
        try:
            key = await self._jwks.key_for(kid)
        except UnknownKey:
            raise InvalidToken("unknown_kid") from None
        if key.algorithm_name != algorithm:
            raise InvalidToken("key_mismatch")  # e.g. an ES256 header naming an RSA key
        now = self._clock()
        try:
            claims = jwt.decode(
                token, key=key.key, algorithms=[algorithm], audience=self._audience, issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["iss", "aud", "sub", "exp", "iat"], "verify_signature": True,
                         "verify_exp": True, "verify_nbf": True, "verify_iat": True, "verify_aud": True,
                         "verify_iss": True, "strict_aud": False})
        except jwt.ExpiredSignatureError:
            raise InvalidToken("expired") from None
        except jwt.ImmatureSignatureError:
            raise InvalidToken("not_yet_valid") from None
        except jwt.InvalidAudienceError:
            raise InvalidToken("audience") from None
        except jwt.InvalidIssuerError:
            raise InvalidToken("issuer") from None
        except jwt.MissingRequiredClaimError:
            raise InvalidToken("missing_claim") from None
        except jwt.InvalidSignatureError:
            raise InvalidToken("signature") from None
        except jwt.PyJWTError:
            raise InvalidToken("invalid") from None
        return self._principal(claims, now)

    def _principal(self, claims: dict, now: float) -> Principal:
        issued, expires = claims.get("iat"), claims.get("exp")
        if not _number(issued) or not _number(expires):
            raise InvalidToken("missing_claim")
        if issued > now + self._leeway:
            raise InvalidToken("not_yet_valid")
        if expires - issued > self._max_lifetime:
            raise InvalidToken("lifetime")
        if claims.get("iss") != self._issuer:
            raise InvalidToken("issuer")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not 0 < len(subject) <= MAX_SUBJECT_LENGTH or "\x00" in subject:
            raise InvalidToken("subject")
        if claims.get("role") != SUPABASE_ROLE:
            raise InvalidToken("role")
        if "is_anonymous" in claims and claims["is_anonymous"] is not False:
            raise InvalidToken("anonymous")
        email = claims.get("email")
        if email is not None and (not isinstance(email, str) or len(email) > MAX_EMAIL_LENGTH):
            raise InvalidToken("email")
        return Principal(self._issuer, subject, email or None)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def build_verifier(auth_settings, client, environment: str) -> TokenVerifier | None:
    """A verifier from :class:`settings.AuthSettings`, or ``None`` when auth is not configured."""
    from webhook_auth import LOCAL

    if not auth_settings.configured:
        return None
    jwks = JwksCache(auth_settings.jwks_url, client, allow_http=environment == LOCAL)
    return TokenVerifier(auth_settings.issuer, auth_settings.audience, jwks)
