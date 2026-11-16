# 0004. Versioned REST API and structured error envelope

- **Status:** proposed
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
Legacy endpoints keep their shapes until a scoped, versioned migration is approved. A technical
refusal is a successful answer outcome, not an HTTP error. Contract:
[`../architecture/05-api-v1.md`](../architecture/05-api-v1.md).

## Consequences

An OpenAPI snapshot is diffed in CI; iOS consumes shared fixtures. Rollback: unversioned legacy
routes remain available until retired.

## Verification

OpenAPI snapshot test; per-route negative tenant tests; iOS contract fixtures decode in the pure Swift
checks.
