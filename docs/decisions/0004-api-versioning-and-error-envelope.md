# 0004. Versioned REST API and structured error envelope

- **Status:** accepted (owner, 2026-11-23)
- **Date:** 2026-11-15
- **Resolves:** contract §11 item 4
- **Supersedes:** none

## Context

Existing endpoints (`/vapi-tool`, `/upload`, `/vision-query`, `/conversation/sessions…`) have mixed
error shapes and are protected boundaries in [`../../AGENTS.md`](../../AGENTS.md).

## Options considered

URL-prefix versioning (`/v1`) versus header versioning versus GraphQL; keep legacy shapes versus
rewrite them.

## Decision

New resources live under `/v1` with typed request/response schemas and a single error envelope
`{"error": {"code", "message", "request_id", "retryable"}}`. Changes inside `/v1` are additive only;
`X-Client-Version` with `426` for unsupported clients; `Sunset` header at least 90 days ahead.
The envelope applies to `/v1` routes only; legacy endpoints keep their shapes until a scoped,
versioned migration is approved. A technical refusal is a successful answer outcome, not an HTTP
error. Contract: [`../architecture/05-api-v1.md`](../architecture/05-api-v1.md).

Contract freeze (M2 B2c): each endpoint in the contract is marked **frozen** or **provisional**.
Conventions, the envelope and the endpoints whose behavior is settled are frozen; endpoints that
depend on unvalidated provider behavior (call start and bind, pending D-9 and gates G-V1…G-V6) or on
unfinished design (coverage, vision) stay provisional and may still change. The freeze takes effect
only when B2c merges with the iOS side's explicit agreement recorded by the owner; until then the
whole contract remains proposed. The `X-Client-Version`/`426` convention is frozen, and enforcing it
waits until a minimum supported version exists.

## Consequences

An OpenAPI snapshot is diffed in CI; iOS consumes shared fixtures. Rollback: unversioned legacy
routes remain available until retired.

## Verification

OpenAPI snapshot test; per-route negative tenant tests; iOS contract fixtures decode in the pure Swift
checks.
