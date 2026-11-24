# 05 — Versioned iOS/backend API (`/v1`)

Status: proposed contract. The iOS and platform worktrees agree on this document before either side
implements against it ([`../development-workflow.md`](../development-workflow.md)). It freezes at the
end of M2 package B2c (see [12-m2-roadmap.md](12-m2-roadmap.md)).

## Conventions

- JSON over HTTPS; `Authorization: Bearer <JWT>` on every route except health checks.
- `X-Workspace-Id` optional (defaults to the caller's personal workspace) and validated server-side.
- `X-Client-Version`; server may answer `426` with `min_supported_version`.
- Mutating create endpoints accept `Idempotency-Key`.
- Cursor pagination: `?cursor=&limit=` (default 25, max 100).
- Additive changes only within `/v1`; breaking changes require `/v2`. Deprecation announced with a
  `Sunset` header at least 90 days ahead.
- Server-side authority only: no endpoint accepts `user_id`, `shop_id`, tenant, or session identity
  as authority.

### Error envelope

```json
{"error": {"code": "vehicle_unconfirmed", "message": "Confirm the vehicle first.",
           "request_id": "01JABC…", "retryable": false}}
```

Codes include `unauthorized`, `forbidden`, `not_found`, `validation_failed`, `rate_limited`,
`vehicle_unconfirmed`, `bind_unverified`, `call_not_ready`, `stale_generation`, `brain_unavailable`,
`unsupported_client`, `server_error`. A refusal of a technical question is a **successful answer
outcome**, not an HTTP error (see turns below).

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/me`, `PATCH /v1/me`, `DELETE /v1/me` | Profile, preferences, account deletion; `GET /v1/me/export` |
| `GET /v1/workspaces` | Memberships |
| `GET/POST /v1/vehicles`; `GET/PATCH/DELETE /v1/vehicles/{id}` | Garage (DELETE archives) |
| `POST /v1/vehicles/decode` | VIN validation + decode behind a provider interface |
| `POST /v1/vehicles/{id}/confirm` | Creates the immutable `vehicle_snapshot` |
| `POST /v1/conversations`; `GET /v1/conversations`; `GET /v1/conversations/{id}` | Lifecycle, history list and detail |
| `POST /v1/conversations/{id}/calls` | Starts a call generation; returns `{call_id, generation, vapi_variables, bind_nonce, bind_expires_at}` |
| `POST /v1/calls/{id}/bind` | Body `{vapi_call_id, bind_nonce}`; see [06-vapi-ingress.md](06-vapi-ingress.md) |
| `POST /v1/calls/{id}/end` | Ends a call |
| `GET /v1/turns/{id}` | Answer with `outcome`, `refusal_reason`, `evidence[]` (document, page, revision, conditions, status) |
| `POST /v1/turns/{id}/feedback` | Report incorrect, unhelpful or missing information |
| `GET /v1/coverage` | What CARVIS covers (screen P02) |
| `POST /v1/vision/query` | Authenticated successor of `/vision-query`; camera input is deferred for V1 |
| `GET /healthz`, `GET /readyz` | Liveness; readiness (database and Qdrant) |
| `/internal/v1/…` | Operator: sources, revisions, review, publish, coverage, reconcile; separate roles |

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
