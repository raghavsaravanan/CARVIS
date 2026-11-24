# 05 — Versioned iOS/backend API (`/v1`)

Status: **proposed until M2 B2c merges with the iOS side's explicit agreement recorded by the owner**
([ADR-0004](../decisions/0004-api-versioning-and-error-envelope.md)); from then on it is frozen as marked
below. Each part is **frozen** (changes only additively, as in "Conventions") or **provisional** (may still
change; a provisional endpoint freezes when its own package merges with iOS agreement recorded by the owner).
The iOS and platform worktrees agree on this document before either side implements against it
([`../development-workflow.md`](../development-workflow.md)).

Implemented in B2c: `GET /v1/me`, `GET /v1/workspaces`, the envelope, the `/v1` auth dependency. Their
schemas are the OpenAPI snapshot `backend/tests/fixtures/openapi-v1.json` (CI fails on any difference), with
example payloads in `backend/tests/fixtures/v1/`.

## Conventions (frozen)

- JSON over HTTPS; `Authorization: Bearer <JWT>` on every route except health checks. Exactly one
  `Authorization` header, `Bearer` (any case), one or more spaces, then the token (RFC 6750 §2.1 `b64token`);
  tokens in the query string or body are ignored. A missing bearer credential answers 401 with
  `WWW-Authenticate: Bearer`; any unacceptable credential (malformed, expired, wrong issuer or audience, bad
  signature, unknown key, non-active user, …) answers 401 with `WWW-Authenticate: Bearer error="invalid_token"`.
- `X-Workspace-Id` applies to **workspace-scoped** routes (the first lands in B3): optional, defaults to the
  caller's personal workspace, validated against the caller's memberships (malformed ⇒ 422, not a member ⇒
  404). **User-scoped** routes (`/v1/me`, `/v1/workspaces`) ignore it. It is never authority.
- `X-Client-Version` is required from iOS clients on every `/v1` request and contains the application's
  `CFBundleShortVersionString` in `MAJOR.MINOR.PATCH` format, with three nonnegative decimal integer
  components. Components are compared numerically, not lexicographically. Enforcement is not active in B2c.
  Once a minimum supported client version is configured and enforcement is enabled, a missing, malformed, or
  unsupported version receives HTTP `426` with the `unsupported_client` error code. Until enforcement is
  enabled, the server does not reject requests based on this header. The configuration mechanism for
  `min_supported_version` remains provisional.
- Mutating create endpoints accept `Idempotency-Key`.
- Cursor pagination: `?cursor=&limit=` (default 25, range 1–100). A page is
  `{"items": [...], "next_cursor": string | null}`; the cursor is an opaque string (clients never parse or
  build one); an invalid cursor or limit is 422.
- Timestamps are UTC, `YYYY-MM-DDTHH:MM:SSZ` (whole seconds).
- Every `/v1` response carries `Cache-Control: no-store` and `X-Request-ID`.
- Additive changes only within `/v1`; breaking changes require `/v2`. Deprecation announced with a
  `Sunset` header at least 90 days ahead. Clients ignore unknown fields and handle unknown enum values and
  unknown error `code`s generically, by HTTP status and `retryable`.
- Server-side authority only: no endpoint accepts `user_id`, `shop_id`, tenant, or session identity
  as authority.

### Error envelope (frozen)

```json
{"error": {"code": "vehicle_unconfirmed", "message": "Confirm the vehicle first.",
           "request_id": "01JABC…", "retryable": false}}
```

Every error the application produces for a `/v1` path uses this envelope; `request_id` equals the
response's `X-Request-ID`, and `message` is a fixed text per code (never input, token data or internal
detail). Responses the ASGI server generates before the application runs (for example Uvicorn's plain-text
400 for a malformed request line or `Content-Length`) cannot carry the envelope or headers.

| Status | `code` | `retryable` | When |
| --- | --- | --- | --- |
| 400 | `validation_failed` | false | Malformed request framing the application sees (for example `Content-Length`) |
| 401 | `unauthorized` | false | Missing or unacceptable credentials, non-active user |
| 403 | `forbidden` | false | Authenticated but not allowed (none in B2c) |
| 404 | `not_found` | false | Unknown `/v1` path, or an object not visible to the caller |
| 405 | `method_not_allowed` | false | Wrong method (`Allow` header present) |
| 413 | `payload_too_large` | false | Body over the route's cap |
| 422 | `validation_failed` | false | Invalid parameters or body |
| 426 | `unsupported_client` | false | Missing, malformed or unsupported `X-Client-Version` once enforcement is enabled (not emitted in B2c) |
| 429 | `rate_limited` | true | Rate limit (none in B2c) |
| 500 | `server_error` | false | Unexpected error |
| 503 | `service_unavailable` | true | Issuer keys, database or configuration unavailable; try later |
| other 4xx / 5xx | `validation_failed` / `server_error` | false | Any other status |

Domain codes added by later packages: `vehicle_unconfirmed`, `bind_unverified`, `call_not_ready`,
`stale_generation`, `brain_unavailable`. A refusal of a technical question is a **successful answer
outcome**, not an HTTP error (see turns below).

## Endpoints

| Endpoint | Purpose | Status |
| --- | --- | --- |
| `GET /v1/me` | The caller's profile: `{id, email, display_name, created_at}` | **Frozen** (B2c) |
| `GET /v1/workspaces` | The caller's memberships: page of `{id, kind, name, role, created_at}` | **Frozen** (B2c) |
| `PATCH /v1/me` | Profile and preferences (preferences not designed yet) | Provisional |
| `DELETE /v1/me`, `GET /v1/me/export` | Account deletion and export (B8, D-4) | Provisional |
| `GET/POST /v1/vehicles`; `GET/PATCH/DELETE /v1/vehicles/{id}` | Garage (DELETE archives) | Provisional (path reserved; B3) |
| `POST /v1/vehicles/decode` | VIN validation + decode behind a provider interface | Provisional (provider) |
| `POST /v1/vehicles/{id}/confirm` | Creates the immutable `vehicle_snapshot`, the only way to establish vehicle context; binds to the vehicle version the technician saw; refuses an archived vehicle | Provisional (path reserved; B3) |
| `POST /v1/conversations`; `GET /v1/conversations`; `GET /v1/conversations/{id}` | Lifecycle, history list and detail; a conversation is bound to one confirmed vehicle snapshot for its whole life, and a vehicle switch ends it | Provisional (path reserved; B4) |
| `POST /v1/conversations/{id}/calls` | Starts a call generation; returns `{call_id, generation, vapi_variables, bind_nonce, bind_expires_at}` | Provisional (D-9, G-V1…G-V6) |
| `POST /v1/calls/{id}/bind` | Body `{vapi_call_id, bind_nonce}`; see [06-vapi-ingress.md](06-vapi-ingress.md) | Provisional (D-9) |
| `POST /v1/calls/{id}/end` | Ends a call | Provisional (D-9) |
| `GET /v1/turns/{id}` | Answer with `outcome`, `refusal_reason`, the turn's own vehicle snapshot (vehicle and resolved configuration), `evidence[]` (document, page, revision, conditions, status) | Provisional (Brain evidence, D-13) |
| `POST /v1/turns/{id}/feedback` | Report incorrect, unhelpful or missing information; the vehicle is taken from the authorized turn, never from the request | Provisional (B6) |
| `GET /v1/coverage` | What CARVIS covers (screen P02) | Provisional |
| `POST /v1/vision/query` | Authenticated successor of `/vision-query`; camera input is deferred for V1 | Provisional |
| `GET /healthz`, `GET /readyz` | Liveness; readiness (database; Qdrant later) | **Frozen** (B1) |
| `/internal/v1/…` | Operator: sources, revisions, review, publish, coverage, reconcile; separate roles | Provisional |

## Example: call start and bind

```http
POST /v1/conversations/7f…/calls
Idempotency-Key: 3b9c…

201 Created
{"call_id": "01JD…", "generation": 3, "bind_nonce": "k2…(256-bit, single use)",
 "bind_expires_at": "2026-11-16T14:00:30Z",
 "vapi_variables": {"carvis_call_id": "01JD…", "bind_nonce": "k2…"}}
```

```http
POST /v1/calls/01JD…/bind
{"vapi_call_id": "…", "bind_nonce": "k2…"}

200 {"status": "bound"}           409 {"error": {"code": "stale_generation", …}}
403 {"error": {"code": "bind_unverified", "retryable": true, …}}
```

## Legacy endpoints (protected boundaries)

`/vapi-tool`, `/upload`, `/vision-query`, `/health`, `/conversation/sessions…` keep their status
codes and shapes until a versioned migration is approved. Planned changes: `/vapi-tool` fails closed
(Track A1); `/upload` becomes operator-gated (A2); `/conversation/sessions…` gets interim abuse
limits (A3); `/vision-query`, `/upload` and session creation require authentication in Track B9, on a
date agreed with the iOS worktree (decision D-3).

## Compatibility and testing

Contract tests pin request/response schemas (generated OpenAPI snapshot diffed in CI); the iOS pure
Swift checks consume the same fixtures. Negative tests cover every route with another tenant's IDs.
