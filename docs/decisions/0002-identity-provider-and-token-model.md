# 0002. OIDC identity provider and token model

- **Status:** proposed
- **Date:** 2026-11-15
- **Resolves:** contract D-11 (identity half)
- **Supersedes:** none

## Context

The iOS app has no authentication (local `account.json`). V1 needs secure sign-in, Keychain-held
tokens, and a verified principal on every request, without embedding server secrets in the app (PRD
§12.3). Contracts must stay provider-agnostic.

## Options considered

| Option | Assessment |
| --- | --- |
| Supabase Auth (Sign in with Apple, email) used only as an OIDC issuer | One vendor with the database, JWKS, Apple sign-in, MFA for operators; coupling risk mitigated by provider-agnostic validation |
| Clerk / Auth0 / WorkOS / Cognito | Valid; extra vendor and cost |
| Custom credential handling | Rejected: credential-handling liability |
| Apple-only sign-in | Viable for the pilot; weaker for later platforms |

## Decision

Supabase Auth as the OIDC issuer and Supabase PostgreSQL as the database host for V1 (owner direction,
roadmap D-2, 2026-11-22); FastAPI is the only application API. Email and Sign in with Apple are the
planned sign-in methods. The iOS app obtains tokens from the issuer, stores them in the Keychain, and
sends only `Authorization: Bearer <JWT>` to FastAPI; it never talks to the database. The service-role
key never reaches iOS, and Alembic owns the schema. Not chosen: client-side database access.

Provisioning requirements (not yet done; no Supabase project is provisioned by this record): the
Supabase Data API/PostgREST must be disabled for the CARVIS database, and it must be verified that
`anon`, `authenticated` and `service_role` hold no privileges on CARVIS objects. B2a's migrations
revoke those privileges where the roles exist and CI checks the revokes against stub roles; the
live verification and the Data API setting are checked at provisioning (B10) before any production
use.

Token rules (FastAPI, issuer-neutral code; issuer, audience and JWKS URL are configuration):

- Asymmetric signatures only (an allow-list such as ES256 and RS256) verified against cached JWKS;
  `none` and HMAC algorithms are rejected, a `kid` is required, and key-location headers (`jku`,
  `x5u`, `jwk`) are ignored.
- Exact `iss` and `aud`; `exp`, `nbf` and `iat` checked with 30 s leeway; tokens whose lifetime
  (`exp − iat`) exceeds 1 hour are rejected.
- Supabase claim profile: `role` must be `authenticated` and `is_anonymous` must not be true.
- The principal is `(iss, sub)`, mapped to `users(auth_issuer, auth_subject)`. On the first verified
  request the user and a personal workspace are provisioned just in time (ADR-0003). Email is stored
  when the user is created and is never authority.
- Revocation before expiry is not checked in V1; a user whose `status` is not `active` is refused, and
  issuer-side revocation on account deletion belongs to B8.
- Transitional configuration: the issuer settings are optional until B10. While they are unset the
  `/v1` routes answer 503 and legacy routes are unaffected; a partial or non-HTTPS configuration
  refuses boot outside local.
- Library: PyJWT with its `cryptography` extra.

Assumptions gated for validation at provisioning, not verified in B2, which tests only against a fake
JWKS [?]: Supabase's issuer URL, `aud` value, JWKS path, claim names and availability of asymmetric
signing keys on the project. Deferred to provisioning (not conditions of this decision): Apple
Developer account and Sign in with Apple configuration, custom SMTP, enabling asymmetric signing keys,
Supabase plan (D-7), MAU limits, disabling the Data API. No provisioning, provider configuration or
subscription is authorized by this record.

## Consequences

New dependency on the issuer's availability for sign-in (existing sessions continue until token
expiry). Replacing the issuer changes configuration and the iOS sign-in flow, not the API. Rollback:
point validation at another OIDC issuer; users re-authenticate.

## Verification

JWT validity matrix against a fake JWKS in CI (B2a, repeated through the routes in B2c): expired,
not yet valid, lifetime over 1 hour, wrong `aud`/`iss`, bad signature, unknown `kid`, `alg=none`,
HMAC with the public key, anonymous or non-`authenticated` role, injected key-location headers,
non-active user; iOS Keychain persistence and sign-out cache clearing on device; no secrets in the app bundle (CI
scan).
