# 04 — Identity, tenancy and row-level security

## Authentication

Hosted OIDC issuer (preferred: Supabase Auth with Sign in with Apple and email), used only as an
issuer. The iOS app stores tokens in the Keychain and sends `Authorization: Bearer <access JWT>` to
FastAPI only; it never talks to the database. FastAPI verifies signature, `iss`, `aud`, `exp` against
cached JWKS (asymmetric signing keys preferred over a shared HS256 secret [?]) and maps `sub` to
`users.auth_subject`. Operators receive `platform_roles` (`brain_reviewer`, `brain_publisher`,
`support_readonly`), require MFA at the issuer, and use `/internal/v1` only.

Items to confirm before ADR-0002 is accepted [?]: Apple Developer account and Sign in with Apple
service configuration, custom SMTP for email (default sending is rate limited), token TTL and
refresh settings, token revocation on account deletion, monthly-active-user limits.

## Authorization

1. Principal comes from the verified JWT. `user_id`, `shop_id`, workspace, vehicle and session
   identifiers in a body, query or header are never authority.
2. Workspace comes from `X-Workspace-Id`, validated against the caller's memberships.
3. Every object ID is looked up *through* the caller's memberships. A miss returns 404 regardless of
   whether the object exists elsewhere.
4. Roles (owner, admin, member) live in the application; V1 is effectively owner-only personal
   workspaces plus operator-provisioned shop association.
5. Brain scope is server-derived: `brain_scopes = ["global"] + the caller's workspaces with an active
   shop-licensed corpus`. Clients cannot influence it.

## Row-level security (second layer)

### Roles

| Role | Purpose | Notes |
| --- | --- | --- |
| `carvis_owner` | Migrations only; table owner | Not used at runtime |
| `carvis_app` | API runtime | Not superuser, not owner, no `BYPASSRLS` |
| `carvis_worker` | Tenant-scoped jobs | Same policies as `carvis_app` |
| `carvis_maintenance` | Cross-tenant jobs (retention purge, reconciliation) | Granted only needed tables; named policies; **not** `BYPASSRLS` |
| `carvis_resolver` | Owner of `resolve_call` | `NOLOGIN`; column-level read on one view |

Tables use `ENABLE` **and `FORCE ROW LEVEL SECURITY`**. On Supabase the default `postgres` role may
bypass RLS [?]; custom roles are created by Alembic and the app never connects as `postgres`.

### Context carrier

`SET LOCAL` semantics via `set_config(name, value, true)` for `app.user_id` and `app.workspace_ids`,
executed in a SQLAlchemy `after_begin` session event so a request-path transaction cannot start
without context. Policies read `nullif(current_setting('app.workspace_ids', true), '')`; missing
context yields NULL and therefore zero rows (fail closed). Plain `SET` is forbidden because it would
persist on a pooled connection.

### Pooling

Transaction-scoped context is safe with SQLAlchemy `QueuePool` and with transaction-mode poolers.
Poolers in transaction mode require disabling driver prepared-statement caching (asyncpg
`statement_cache_size=0`, or psycopg 3 `prepare_threshold=None`) [?]. Use `pool_pre_ping=True` and
`pool_reset_on_return="rollback"`. Default for V1: session-mode pooler or direct connection with a
small pool on one instance. Supabase direct hosts are IPv6-only without an add-on and Render IPv6
egress is unconfirmed [?], so plan on the pooler endpoint. One unit of work per request is one
transaction; no autocommit sessions on the request path.

### Workers

A job row carries `workspace_id`. The worker opens a transaction as `carvis_worker` and sets context
from the job row, never from payload content. Cross-tenant jobs run as `carvis_maintenance` in small
batches and write one audit event per batch.

### Webhook path and `resolve_call`

`resolve_call(p_vapi_call_id text)` is the only read allowed before tenant context exists.

- Returns at most one row `(call_id, workspace_id, user_id, generation)`; exact match on the UNIQUE
  `vapi_call_id`; no LIKE, range, dynamic SQL; input length ≤ 128.
- Returns **no rows, identically,** for unknown, unbound, ended and stale-generation calls, so it is
  not an existence oracle.
- `SECURITY DEFINER`, owned by `carvis_resolver`, which can read only the needed columns through a
  view filtered to bound/active calls, and nothing else; not superuser, no `BYPASSRLS`; its own named
  policy.
- `SET search_path = pg_catalog, pg_temp` on the function; all references schema-qualified; `STABLE`.
- `REVOKE ALL … FROM PUBLIC` and from Supabase `anon`, `authenticated`, `service_role`;
  `GRANT EXECUTE` only to `carvis_app`.
- Called only after the Vapi credential check, with per-credential/IP rate limiting.
- Afterwards the transaction sets the tenant GUCs and everything runs under RLS.
- CI catalog check: every `SECURITY DEFINER` function must have a pinned `search_path`, a
  non-superuser definer that owns no tenant tables, explicit EXECUTE grants, and an allow-list entry.

### Policy scope

Policies implement tenant isolation only (one shape). Role-based permissions remain in the
application for V1.

## Validation (real PostgreSQL in CI, no mocks)

1. `carvis_app` is not superuser/owner/`BYPASSRLS`; every `workspace_id` table has RLS enabled and forced.
2. No context ⇒ zero rows; INSERT fails `WITH CHECK`.
3. Pool-leak: user A commits, the connection returns to a pool of size 1, the next checkout sees no context.
4. Interleaving: concurrent async requests alternating users A/B on a small pool produce zero cross-reads.
5. Context is cleared after rollback or exception.
6. App-filter bypass: queries missing the `workspace_id` filter still return only the caller's rows.
7. Worker for workspace X cannot read or write workspace Y; `carvis_maintenance` limited to granted tables.
8. Membership revocation applies on the next transaction.
9. Policies use indexed `workspace_id = ANY(...)` (EXPLAIN check on conversation and turn lists).
10. A new table with `workspace_id` but no forced RLS fails a catalog check.
11. `resolve_call`: search-path hijack attempt has no effect; returns only whitelisted columns; identical
    empty result for unknown/unbound/ended/other-tenant calls; `anon`/`authenticated`/PUBLIC lack
    EXECUTE; the definer role has no privileges on any other table (introspection test).

## Account lifecycle

Deletion sets `users.status=deleting`, revokes tokens at the issuer, then a retention job deletes the
personal workspace data after the grace period; shop workspaces are transferred or the request is
refused; audit events are anonymized. Export returns the user's conversations, vehicles and feedback.
