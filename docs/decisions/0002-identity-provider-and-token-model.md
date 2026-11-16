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

Preferred: Supabase Auth as an OIDC issuer. The iOS app obtains tokens from the issuer, stores them in
the Keychain, and sends only `Authorization: Bearer <JWT>` to FastAPI. FastAPI verifies issuer,
audience, expiry and signature via cached JWKS and maps `sub` to `users.auth_subject`. Supabase's
Data API/PostgREST is disabled, `anon`/`authenticated` privileges are revoked, the service-role key
never reaches iOS, and Alembic owns the schema. Not chosen: client-side database access.
Confirm before acceptance [?]: Apple Developer account, custom SMTP, token TTL/refresh, revocation on
account deletion, asymmetric signing keys, MAU limits.

## Consequences

New dependency on the issuer's availability for sign-in (existing sessions continue until token
expiry). Replacing the issuer changes configuration and the iOS sign-in flow, not the API. Rollback:
point validation at another OIDC issuer; users re-authenticate.

## Verification

JWT validity matrix (expired, wrong `aud`/`iss`, bad signature, deleted user) against a fake JWKS in
CI; iOS Keychain persistence and sign-out cache clearing on device; no secrets in the app bundle (CI
scan).
