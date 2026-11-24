# 02 — Target architecture

## Overview

```text
iPhone ──HTTPS, Bearer JWT──► FastAPI (one container, modular monolith)
  │  └─ Vapi SDK ─► Vapi ──webhook (credential-authenticated)──► api/vapi
  │                              ├─ api/v1   api/internal   domain   verification (UNCHANGED)   infra   jobs
  └── Identity provider (OIDC/JWKS) ◄──────┘          │                      │
                                          PostgreSQL (authority, RLS)   Qdrant (evidence projection,
                                                                         gated at serve time by PostgreSQL)
```

Trust boundaries:

1. Device ↔ API: untrusted client. Only a verified bearer JWT carries identity.
2. Vapi ↔ API: provider authenticated by credential; the call is additionally verified server-side
   ([06-vapi-ingress.md](06-vapi-ingress.md)).
3. API ↔ PostgreSQL/Qdrant: least-privilege database roles, RLS enforced.
4. Operator ↔ `/internal/v1`: privileged, separate roles for review and publish.
5. LLM output and tool arguments: untrusted; never authority for tenant, user or vehicle.

## Modular monolith

`backend/main.py` remains the FastAPI entry point (`backend/AGENTS.md`). Code moves into packages
incrementally behind it, never as a big-bang rewrite:

```text
api/v1/        routers, request/response DTOs, error envelope
api/vapi/      webhook ingress, call resolution, deduplication
api/internal/  operator endpoints (ingest, review, publish, coverage, reconcile)
domain/        identity, garage, conversation, brain, feedback services
verification/  existing spec_retrieval / spec_schema logic (unchanged)
infra/         db session + RLS context, qdrant, vapi client, vision, settings, logging
jobs/          retention and Brain projection loop (same image, FOR UPDATE SKIP LOCKED)
```

## Ask flow

1. JWT verified → memberships loaded → workspace chosen from `X-Workspace-Id` and checked.
2. The vehicle must have a confirmed immutable `vehicle_snapshot`.
3. `POST /v1/conversations/{id}/calls` creates a `calls` row (generation N) server-side.
4. The app starts the Vapi call and calls `POST /v1/calls/{id}/bind`; the server proves the call is
   this row's ([06-vapi-ingress.md](06-vapi-ingress.md)).
5. Vapi tool call → credential check → `resolve_call` → tenant, vehicle and snapshot read **from the
   bound row**, never from arguments.
6. Existing verification runs; the Brain serve-time gate in [07-brain.md](07-brain.md) is applied.
7. `turns` and `evidence_references` are written in one transaction; the spoken answer returns.

Restart recovery: calls, turns and state live in PostgreSQL. Only camera long-poll requests (30 s
deadline) stay process-local; a deploy mid-call drops that request and nothing else.

## Database and identity choice (summary; see ADR-0001, ADR-0002)

PostgreSQL with SQLAlchemy 2 and Alembic. Supabase is the host and OIDC issuer (Sign in
with Apple; accepted ADR-0002) **used strictly as plain PostgreSQL plus an OIDC issuer**: the Data API is disabled,
`anon`/`authenticated` privileges are revoked, the service-role key never reaches iOS, and our
Alembic chain owns the schema. FastAPI validates JWTs provider-agnostically (issuer, audience,
expiry, JWKS) so the issuer can be replaced. SpacetimeDB retirement is proposed ([ADR-0007](../decisions/0007-retire-spacetimedb.md)) and not yet decided.

## External reference review (pattern level only)

A separate, read-only architectural reference was reviewed for patterns. No code, identifiers,
credentials or data from it are reproduced here. Conclusions:

| Pattern | Decision for CARVIS |
| --- | --- |
| Service-per-domain topology on a shared database | Reject: coupling and operations cost outweigh benefit for one operator |
| `api / application / infra` layering | Adapt inside one package |
| Single linear migration chain, no editing applied revisions, `timestamptz`, CI history check, destructive-change preflight | Adopt; add real upgrade/downgrade runs in CI |
| Server-resolved tenant context, tenant column on every tenant row, tenant-isolation tests | Adopt; add RLS because filter-in-every-query alone is fragile |
| Fine-grained relationship-based authorization service | Reject for V1; a role→permission table in code suffices |
| Shared secret for internal calls | Reject; use scoped credentials |
| Shared cross-repository library | Reject; internal `common/` module |
| Agent catalog and connector platform | Reject; one assistant with deterministic tools |
| Locked dependency installs, pinned interpreter, CI concurrency and timeouts, build-once-promote, a preflight "doctor" script, committed deterministic evaluation set | Adopt |
| Idempotency and durable-state gaps (weak webhook dedupe, ad hoc cross-store writes) | Fix in CARVIS design: `webhook_events`, serve-time Brain gate |

## Compatibility rules

Preserve `/vapi-tool`, `/upload`, `/vision-query`, `/health` and `/conversation/sessions…` until a
scoped, versioned migration is approved ([`../../AGENTS.md`](../../AGENTS.md) protected boundaries).
New resources live under `/v1`. Hardening that does not change response shape ships first
([12-m2-roadmap.md](12-m2-roadmap.md) Track A).
