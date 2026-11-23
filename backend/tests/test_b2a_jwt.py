"""M2 B2a: asymmetric JWT verification against a fake JWKS (mocked/unit; ADR-0002).

Keys are generated per test run and served through ``httpx.MockTransport``; nothing leaves the
process and no provider is contacted.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from auth.jwks import AuthUnavailable, JwksCache, JwksError
from auth.tokens import InvalidToken, Principal, TokenVerifier, build_verifier

ISSUER = "https://issuer.example.test/auth/v1"
AUDIENCE = "authenticated"
JWKS_URL = "https://issuer.example.test/auth/v1/.well-known/jwks.json"

EC_KEY = ec.generate_private_key(ec.SECP256R1())
RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_EC_KEY = ec.generate_private_key(ec.SECP256R1())


def public_jwk(private, kid: str, **extra) -> dict:
    algorithm = jwt.algorithms.ECAlgorithm if isinstance(private, ec.EllipticCurvePrivateKey) else \
        jwt.algorithms.RSAAlgorithm
    entry = json.loads(algorithm.to_jwk(private.public_key()))
    entry.update({"kid": kid, "use": "sig", **extra})
    return entry


class FakeIssuer:
    """Serves a JWKS document and counts requests; the document can change or fail between calls."""

    def __init__(self, keys: list[dict]) -> None:
        self.document: object = {"keys": keys}
        self.requests = 0
        self.status = 200
        self.raw: bytes | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        assert str(request.url) == JWKS_URL
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, content=self.raw if self.raw is not None else json.dumps(self.document).encode())


def default_keys() -> list[dict]:
    return [public_jwk(EC_KEY, "ec-1"), public_jwk(RSA_KEY, "rsa-1")]


@pytest.fixture
def issuer():
    return FakeIssuer(default_keys())


def verifier_for(issuer: FakeIssuer, clock=time.monotonic, **cache_options) -> TokenVerifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler))
    return TokenVerifier(ISSUER, AUDIENCE, JwksCache(JWKS_URL, client, clock=clock, **cache_options))


def claims(**overrides) -> dict:
    now = int(time.time())
    base = {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-123", "iat": now, "exp": now + 3600,
            "role": "authenticated", "is_anonymous": False, "email": "tech@example.test"}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not ...}


def sign(payload: dict, key=EC_KEY, algorithm="ES256", kid="ec-1", headers=None) -> str:
    extra = {"kid": kid} if kid is not None else {}
    extra.update(headers or {})
    return jwt.encode(payload, key, algorithm=algorithm, headers=extra)


def verify(verifier: TokenVerifier, token) -> Principal:
    return asyncio.run(verifier.verify(token))


def reason(verifier: TokenVerifier, token) -> str:
    with pytest.raises(InvalidToken) as error:
        verify(verifier, token)
    assert "user-123" not in str(error.value) and token not in str(error.value) if isinstance(token, str) else True
    return error.value.reason


# --- Accepted tokens ------------------------------------------------------------------------------

def test_valid_es256_and_rs256_tokens(issuer):
    verifier = verifier_for(issuer)
    for token in (sign(claims()), sign(claims(), RSA_KEY, "RS256", "rsa-1")):
        principal = verify(verifier, token)
        assert (principal.issuer, principal.subject, principal.email) == (ISSUER, "user-123", "tech@example.test")
    assert issuer.requests == 1, "keys are cached"


def test_audience_list_containing_ours_and_missing_optional_claims(issuer):
    verifier = verifier_for(issuer)
    assert verify(verifier, sign(claims(aud=["other", AUDIENCE], email=..., is_anonymous=...))).email is None


def test_principal_repr_is_redacted(issuer):
    principal = verify(verifier_for(issuer), sign(claims()))
    assert "user-123" not in repr(principal) and "example.test" not in repr(principal)
    assert repr(principal) == f"Principal(fp={principal.fingerprint})"


# --- Rejected tokens ------------------------------------------------------------------------------

NOW = int(time.time())


@pytest.mark.parametrize("payload,expected", [
    (claims(exp=NOW - 60, iat=NOW - 120), "expired"),
    (claims(nbf=NOW + 120), "not_yet_valid"),
    (claims(iat=NOW + 120, exp=NOW + 600), "not_yet_valid"),
    (claims(iat=NOW - 10, exp=NOW + 3600), "lifetime"),  # 3610 s
    (claims(iat=...), "missing_claim"),
    (claims(exp=...), "missing_claim"),
    (claims(iss=...), "missing_claim"),
    (claims(aud=...), "missing_claim"),
    (claims(sub=...), "missing_claim"),
    (claims(iss="https://evil.example.test/auth/v1"), "issuer"),
    (claims(iss=ISSUER + "/"), "issuer"),
    (claims(aud="anon"), "audience"),
    (claims(aud=["other", "anon"]), "audience"),
    (claims(sub=""), "subject"),
    (claims(sub="x" * 256), "subject"),
    (claims(sub="a\x00b"), "subject"),
    (claims(sub=42), "invalid"),
    (claims(role="anon"), "role"),
    (claims(role=...), "role"),
    (claims(is_anonymous=True), "anonymous"),
    (claims(is_anonymous="false"), "anonymous"),
    (claims(email=42), "email"),
    (claims(email="a" * 321), "email"),
])
def test_claim_failures(issuer, payload, expected):
    assert reason(verifier_for(issuer), sign(payload)) == expected


def test_lifetime_of_exactly_one_hour_is_accepted(issuer):
    verify(verifier_for(issuer), sign(claims(iat=NOW, exp=NOW + 3600)))


def test_bad_signature(issuer):
    token = sign(claims(), OTHER_EC_KEY)  # signed by a key the issuer does not publish under ec-1
    assert reason(verifier_for(issuer), token) == "signature"


def test_tampered_payload(issuer):
    header, payload, signature = sign(claims()).split(".")
    forged = base64.urlsafe_b64encode(json.dumps(claims(sub="admin")).encode()).rstrip(b"=").decode()
    assert reason(verifier_for(issuer), f"{header}.{forged}.{signature}") == "signature"


def test_alg_none_is_rejected(issuer):
    token = jwt.encode(claims(), None, algorithm="none", headers={"kid": "ec-1"})
    assert reason(verifier_for(issuer), token) in ("malformed", "algorithm")  # empty signature segment
    header, payload, _ = sign(claims()).split(".")
    unsigned_header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "kid": "ec-1"}).encode()).rstrip(b"=")
    assert reason(verifier_for(issuer), f"{unsigned_header.decode()}.{payload}.c2ln") == "algorithm"


def test_hmac_with_the_public_key_is_rejected(issuer):
    """Algorithm confusion: an HS256 token keyed with the RSA public key's PEM bytes."""
    pem = RSA_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "kid": "rsa-1", "typ": "JWT"}).encode())
    body = base64.urlsafe_b64encode(json.dumps(claims()).encode())
    import hashlib
    import hmac

    signing_input = header.rstrip(b"=") + b"." + body.rstrip(b"=")
    mac = base64.urlsafe_b64encode(hmac.new(pem, signing_input, hashlib.sha256).digest()).rstrip(b"=")
    assert reason(verifier_for(issuer), (signing_input + b"." + mac).decode()) == "algorithm"


def test_es256_header_naming_an_rsa_key_is_rejected(issuer):
    token = sign(claims(), EC_KEY, "ES256", "rsa-1")
    assert reason(verifier_for(issuer), token) == "key_mismatch"


@pytest.mark.parametrize("name,value", [("jku", "https://evil.test/jwks"), ("x5u", "https://evil.test/c"),
                                        ("jwk", {"kty": "EC"}), ("x5c", ["MIIB"]), ("crit", ["exp"])])
def test_key_location_and_crit_headers_are_rejected(issuer, name, value):
    # crit is refused by the parser itself ("malformed"); the others by CARVIS's header rule.
    assert reason(verifier_for(issuer), sign(claims(), headers={name: value})) in ("header", "malformed")


def test_missing_kid_is_rejected(issuer):
    assert reason(verifier_for(issuer), sign(claims(), kid=None)) == "kid"


@pytest.mark.parametrize("token", ["", "abc", "a.b", "a.b.c.d", "a.b.c", "x" * 9000, None, 12,
                                   "eyJ.eyJ.sig with space"])
def test_malformed_tokens(issuer, token):
    with pytest.raises(InvalidToken) as error:
        verify(verifier_for(issuer), token)
    assert error.value.reason == "malformed"


# --- JWKS cache behaviour -------------------------------------------------------------------------

class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_unknown_kid_triggers_at_most_one_throttled_refresh(issuer):
    clock = Clock()
    verifier = verifier_for(issuer, clock=clock)
    verify(verifier, sign(claims()))
    assert issuer.requests == 1
    for _ in range(5):
        assert reason(verifier, sign(claims(), kid="unknown")) == "unknown_kid"
    assert issuer.requests == 1, "within 60 s of the last fetch, unknown kids never refetch"
    clock.now += 61
    for _ in range(5):
        assert reason(verifier, sign(claims(), kid="unknown")) == "unknown_kid"
    assert issuer.requests == 2, "after 60 s, exactly one refresh for any number of unknown kids"


def test_key_rotation_is_picked_up_on_unknown_kid(issuer):
    clock = Clock()
    verifier = verifier_for(issuer, clock=clock)
    verify(verifier, sign(claims()))
    issuer.document = {"keys": [public_jwk(OTHER_EC_KEY, "ec-2")]}
    clock.now += 61
    verify(verifier, sign(claims(), OTHER_EC_KEY, kid="ec-2"))
    assert reason(verifier, sign(claims())) == "unknown_kid", "the rotated-out key is gone"


def test_jwks_down_without_cache_is_unavailable_not_invalid(issuer):
    issuer.status = 503
    with pytest.raises(AuthUnavailable):
        verify(verifier_for(issuer), sign(claims()))


def test_jwks_down_with_cache_keeps_last_good_keys_for_at_most_an_hour(issuer):
    clock = Clock()
    verifier = verifier_for(issuer, clock=clock)
    verify(verifier, sign(claims()))
    issuer.status = 500
    clock.now += 601  # cache expired: refresh fails, stale keys still serve
    verify(verifier, sign(claims()))
    clock.now += 3600  # more than an hour after the last good fetch
    with pytest.raises(AuthUnavailable):
        verify(verifier, sign(claims()))


def test_oversized_jwks_is_refused_while_streaming(issuer):
    issuer.raw = b'{"keys": [' + b" " * (70 * 1024) + b"]}"
    with pytest.raises(AuthUnavailable):
        verify(verifier_for(issuer), sign(claims()))


@pytest.mark.parametrize("keys", [
    [public_jwk(EC_KEY, "ec-1", use="enc")],
    [public_jwk(EC_KEY, "ec-1", alg="RS256")],
    [public_jwk(rsa.generate_private_key(public_exponent=65537, key_size=1024), "ec-1")],
    [public_jwk(ec.generate_private_key(ec.SECP384R1()), "ec-1")],
])
def test_unusable_keys_are_never_selected(keys):
    issuer = FakeIssuer(keys)
    with pytest.raises((InvalidToken, AuthUnavailable)):
        verify(verifier_for(issuer), sign(claims()))


@pytest.mark.parametrize("document,code", [
    ({"keys": [public_jwk(EC_KEY, "ec-1"), public_jwk(RSA_KEY, "ec-1")]}, "duplicate_kid"),
    ({"keys": [public_jwk(EC_KEY, f"k{i}") for i in range(21)]}, "too_many_keys"),
    ({"keys": [dict(public_jwk(EC_KEY, "ec-1"), d="secret")]}, "secret_key_material"),
    ({"nokeys": []}, "not_a_jwks"),
])
def test_rejected_jwks_documents(document, code):
    from auth.jwks import _parse_keys

    with pytest.raises(JwksError) as error:
        _parse_keys(document)
    assert str(error.value) == code


def test_http_jwks_url_refused_unless_local():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(JwksError):
        JwksCache("http://issuer.example.test/jwks", client)
    JwksCache("http://localhost:9999/jwks", client, allow_http=True)
    with pytest.raises(JwksError):
        JwksCache("https://user:pw@issuer.example.test/jwks", client)


def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://evil.example.test/jwks"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = TokenVerifier(ISSUER, AUDIENCE, JwksCache(JWKS_URL, client))
    with pytest.raises(AuthUnavailable):
        verify(verifier, sign(claims()))
    assert calls == [JWKS_URL]


# --- Settings and construction --------------------------------------------------------------------

def test_auth_settings_all_or_nothing():
    from settings import AuthConfigurationError, load_auth_settings

    full = {"CARVIS_AUTH_ISSUER": ISSUER, "CARVIS_AUTH_AUDIENCE": AUDIENCE, "CARVIS_AUTH_JWKS_URL": JWKS_URL}
    assert load_auth_settings("production", {}).status == "unconfigured"
    assert load_auth_settings("production", full).status == "configured"
    for missing in full:
        partial = {k: v for k, v in full.items() if k != missing}
        with pytest.raises(AuthConfigurationError, match=missing):
            load_auth_settings("production", partial)
        assert load_auth_settings("local", partial).status == "invalid"
    http = dict(full, CARVIS_AUTH_JWKS_URL="http://issuer.example.test/jwks")
    with pytest.raises(AuthConfigurationError):
        load_auth_settings("staging", http)
    assert load_auth_settings("local", http).status == "configured"
    assert ISSUER not in repr(load_auth_settings("production", full))


def test_build_verifier_only_when_configured():
    from settings import AuthSettings

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    assert build_verifier(AuthSettings("unconfigured"), client, "production") is None
    assert isinstance(build_verifier(AuthSettings("configured", ISSUER, AUDIENCE, JWKS_URL), client, "production"),
                      TokenVerifier)


def test_load_settings_refuses_partial_auth_outside_local(monkeypatch):
    from settings import AuthConfigurationError, load_settings

    for name, value in {"CARVIS_ENV": "production", "VAPI_WEBHOOK_SECRET": "s", "CARVIS_DEFAULT_SHOP_ID": "shop",
                        "CARVIS_QDRANT_COLLECTION": "carvis_specs_v2", "CARVIS_AUTH_ISSUER": ISSUER}.items():
        monkeypatch.setenv(name, value)
    for name in ("SPACETIMEDB_URI", "SPACETIMEDB_TOKEN", "SPACETIMEDB_DB_NAME", "RENDER", "CARVIS_DATABASE_URL",
                 "CARVIS_AUTH_AUDIENCE", "CARVIS_AUTH_JWKS_URL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(AuthConfigurationError):
        load_settings()
    monkeypatch.delenv("CARVIS_AUTH_ISSUER")
    assert load_settings().auth.status == "unconfigured"


# --- Guards that sit behind other checks (mutation-tested individually) ---------------------------

def test_iat_in_the_future_by_our_clock_is_rejected(issuer):
    """CARVIS's own iat check, independent of the library's (a verifier clock behind real time)."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(issuer.handler))
    verifier = TokenVerifier(ISSUER, AUDIENCE, JwksCache(JWKS_URL, client), clock=lambda: time.time() - 120)
    assert reason(verifier, sign(claims())) == "not_yet_valid"


def test_oversized_but_well_formed_token_is_rejected(issuer):
    token = sign(claims(padding="x" * 9000))
    assert len(token) > 8192
    assert reason(verifier_for(issuer), token) == "malformed"


def test_oversized_but_valid_jwks_is_refused(issuer):
    document = json.dumps(issuer.document).encode()
    issuer.raw = document[:-1] + b" " * (70 * 1024) + document[-1:]
    json.loads(issuer.raw)  # still a valid JWKS: only the size cap can refuse it
    with pytest.raises(AuthUnavailable):
        verify(verifier_for(issuer), sign(claims()))


def test_token_signed_by_a_weak_rsa_key_is_rejected():
    weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    issuer = FakeIssuer([public_jwk(weak, "weak-1"), public_jwk(EC_KEY, "ec-1")])
    assert reason(verifier_for(issuer), sign(claims(), weak, "RS256", "weak-1")) == "unknown_kid"


# --- Round-1 review: refresh throttling during an issuer outage -----------------------------------

def test_expired_cache_with_failing_issuer_refetches_at_most_once_per_interval(issuer):
    clock = Clock()
    verifier = verifier_for(issuer, clock=clock)
    token = sign(claims())
    verify(verifier, token)
    issuer.status = 500
    clock.now += 700  # cache expired
    for _ in range(50):
        verify(verifier, token)  # stale keys keep serving
    assert issuer.requests == 2, "one failed refresh, not one per verification"
    clock.now += 61
    for _ in range(50):
        verify(verifier, token)
    assert issuer.requests == 3


def test_concurrent_callers_do_not_queue_behind_a_hanging_refresh():
    hanging = asyncio.Event()
    calls = []

    async def handler(request):
        calls.append(1)
        if len(calls) > 1:
            await hanging.wait()  # the issuer hangs after the first good response
        return httpx.Response(200, content=json.dumps({"keys": default_keys()}).encode())

    clock = Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    verifier = TokenVerifier(ISSUER, AUDIENCE, JwksCache(JWKS_URL, client, clock=clock, timeout=0.5))
    token = sign(claims())

    async def scenario():
        await verifier.verify(token)
        clock.now += 700
        started = time.monotonic()
        refresher = asyncio.create_task(verifier.verify(token))  # takes the lock, waits on the issuer
        await asyncio.sleep(0.05)
        others = await asyncio.gather(*(verifier.verify(token) for _ in range(10)))
        quick = time.monotonic() - started
        await refresher
        return others, quick

    others, quick = asyncio.run(scenario())
    assert len(others) == 10 and quick < 0.3, "callers with a usable key are served without waiting"
    assert len(calls) == 2, "exactly one refresh attempt for all concurrent callers"
