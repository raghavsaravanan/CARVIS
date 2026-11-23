# 04 — Identity, tenancy and row-level security

## Authentication

Hosted OIDC issuer: Supabase Auth with Sign in with Apple and email (ADR-0002), used only as an
issuer. The iOS app stores tokens in the Keychain and sends `Authorization: Bearer <access JWT>` to
FastAPI only; it never talks to the database. FastAPI verifies the asymmetric signature against
cached JWKS, exact `iss` and `aud`, and `exp`/`nbf`/`iat` with 30 s leeway, rejects tokens living
longer than 1 hour, and maps `(iss, sub)` to `users(auth_issuer, auth_subject)` (token rules in
ADR-0002). Operators receive `platform_roles` (`brain_reviewer`, `brain_publisher`,
`support_readonly`), require MFA at the issuer, and use `/internal/v1` only.

Deferred to provisioning [?]: Apple Developer account and Sign in with Apple service configuration,
custom SMTP for email (default sending is rate limited), refresh settings, issuer-side revocation on
account deletion (B8), monthly-active-user limits, and the Supabase token shape (issuer URL, `aud`,
JWKS path, claims), which B2 tests only against a fake JWKS.

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
| `carvis_bootstrap` | Bootstrap transaction (B2a) | `NOLOGIN`; `USAGE` on `carvis` and `EXECUTE` on `carvis.ensure_principal` only; no table privileges |
| `carvis_provisioner` | Owner of `ensure_principal` (B2a) | `NOLOGIN`; owns no tables; no permanent members (see "Function ownership and migration membership"); `USAGE` on `carvis` plus only the column grants and policies in "Provisioning" (`CREATE` on `carvis` only inside the migration that creates its function, revoked in the same migration) |
| deployment login | Runtime connection | `LOGIN`, created at provisioning with a credential outside the repository; member of `carvis_app` and `carvis_bootstrap` **`WITH INHERIT FALSE, SET TRUE`** and of nothing else; not superuser, `CREATEROLE`, `CREATEDB`, `REPLICATION` or `BYPASSRLS`; owns nothing, no role settings or ACL entries. Granted by an owner-run command at provisioning, never on deploy |
| `carvis_maintenance` | Cross-tenant jobs (retention purge, reconciliation) | Granted only needed tables; named policies; **not** `BYPASSRLS` |
| `carvis_resolver` | Owner of `resolve_call` | `NOLOGIN`; column-level read on one view |

Because the login inherits nothing, it can read or change no CARVIS object until a transaction runs
`SET LOCAL ROLE carvis_app` or `SET LOCAL ROLE carvis_bootstrap`. Readiness also switches to
`carvis_app` before reading the version table. The first database use checks the login's attributes
and memberships; a superuser, `BYPASSRLS` or object-owning login keeps `/readyz` not ready and `/v1`
at 503 outside local.

Tables use `ENABLE` **and `FORCE ROW LEVEL SECURITY`**. On Supabase the default `postgres` role may
bypass RLS [?]; custom roles are created by Alembic and the app never connects as `postgres`.

### Function privileges

PostgreSQL grants `EXECUTE` on every new function to `PUBLIC` by default, and that default is global:
`ALTER DEFAULT PRIVILEGES … IN SCHEMA` cannot remove it. Migrations therefore run
`ALTER DEFAULT PRIVILEGES FOR ROLE carvis_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` (and the same
for `carvis_provisioner`, and later `carvis_resolver`, in the migration that creates that role)
**without** `IN SCHEMA`, and every sensitive function
additionally gets an explicit `REVOKE ALL ON FUNCTION … FROM PUBLIC`, a revoke from `anon`,
`authenticated` and `service_role` where those roles exist, and then only its intended grant
(`ensure_principal`: `carvis_bootstrap`; `resolve_call`: `carvis_app`). A CI catalog check treats a
NULL `proacl` as `PUBLIC` `EXECUTE` and requires every `SECURITY DEFINER` function in CARVIS schemas
to have exactly its allow-listed ACL, a pinned `search_path`, and a non-superuser owner that owns no
tables. Supabase's default grants to `anon`, `authenticated` and `service_role` are scoped to
objects `postgres` creates in `public` [?]; CARVIS objects are created by `carvis_owner` or a definer
owner in `carvis`, never by `postgres`, and CI simulates hostile defaults with stub issuer roles.

### Function ownership and migration membership

Default privileges apply according to the role that **creates** an object, and they are fixed at
creation (a later owner change keeps the ACL). Ownership and creating role per function:

| Function | Owner | Created while the current role is | Default privileges that apply |
| --- | --- | --- | --- |
| `carvis.ensure_principal` (B2b) | `carvis_provisioner` | `carvis_provisioner` (`SET LOCAL ROLE`) | `carvis_provisioner`'s |
| `carvis.resolve_call` (B4/B5) | `carvis_resolver` | `carvis_resolver` | `carvis_resolver`'s |
| Invoker helpers and trigger functions (for example the UUID v7 helper and the membership trigger) | `carvis_owner` | `carvis_owner` (B1's `as_owner`) | `carvis_owner`'s |

Definer owners have **no permanent members**. A non-superuser migration login (Supabase's
`postgres` is one [?]) cannot otherwise `SET ROLE` to them, which PostgreSQL 16 requires both to
create an object as that role and to run `ALTER DEFAULT PRIVILEGES FOR ROLE` for it. So the
migration that creates (or later drops) a definer function does all of the following **inside its
one migration transaction** (Alembic runs each revision in its own transaction):

1. Refuse to continue if the login already holds a membership in the definer owner beyond
   PostgreSQL 16's automatic administrative grant (below), or the owner already has members.
2. If the login is not a superuser: `GRANT <owner> TO CURRENT_USER WITH INHERIT FALSE, SET TRUE`.
3. When creating: as the schema owner, grant the definer owner `CREATE` on `carvis`.
4. Under `SET LOCAL ROLE <owner>`: `ALTER DEFAULT PRIVILEGES FOR ROLE <owner> REVOKE EXECUTE ON
   FUNCTIONS FROM PUBLIC`; create the function; `REVOKE ALL ON FUNCTION … FROM PUBLIC` and from the
   issuer roles that exist; `GRANT EXECUTE` only to its intended caller; then `RESET ROLE`.
5. Revoke any `CREATE` on `carvis` from the owner, and
   `REVOKE <owner> FROM CURRENT_USER GRANTED BY CURRENT_USER`.

On success, the only membership left in the definer owner is the automatic administrative grant
that PostgreSQL 16 gives a non-superuser `CREATEROLE` login on a role it creates (`ADMIN OPTION`,
`INHERIT FALSE`, `SET FALSE`, granted by the bootstrap superuser). It confers no privileges and no
`SET ROLE`. This is the same allowance B1's `0002_roles` makes, and the role-hardening revision
in B2a decides whether it can and should also be revoked. Because grants, `SET LOCAL ROLE`,
default-privilege changes and DDL are all transactional, a failed step rolls back every change of
that migration, leaving no membership, `CREATE` grant, ownership or ACL drift. Downgrade uses the
same temporary grant to drop the function. A catalog check after upgrade and downgrade asserts no
member of a definer owner other than that administrative grant, and no `CREATE` on `carvis` for it.
`carvis_resolver` follows the same procedure when B4/B5 create it.

This procedure is specified, not yet executed. B2a and B2b must validate it on real PostgreSQL 16
with a non-superuser `CREATEROLE` migration login, including forced failure at each step.

### Context carrier

Each `/v1` request runs two transactions on the pooled login, each under one role. Settings use
`set_config(name, value, true)` (transaction-scoped); plain `SET` is forbidden because it would
persist on a pooled connection. A SQLAlchemy `after_begin` listener refuses to begin any request-path
transaction whose session carries neither a bootstrap nor a tenant context; only two session
factories set them.

1. **Bootstrap transaction.** The JWT is verified in Python first. The listener runs
   `SET LOCAL ROLE carvis_bootstrap`; the transaction calls
   `carvis.ensure_principal(iss, sub, email)`, which returns `(user_id, status)`, and commits. A
   status other than `active` ends the request with 401 and no tenant transaction.
2. **Tenant transaction.** The listener runs `SET LOCAL ROLE carvis_app`, sets `app.user_id` from the
   committed bootstrap result, reads the caller's memberships (policy `user_id = app.user_id`) and
   sets `app.workspace_ids` from them, all before any request query. A membership revoked before
   this transaction begins is not seen.

Policies read `nullif(current_setting('app.…', true), '')`; missing context yields NULL and therefore
zero rows, and inserts fail `WITH CHECK`. Policy shapes: tenant tables
`workspace_id = ANY(app.workspace_ids)`; `users` `id = app.user_id`; `memberships`
`user_id = app.user_id`; `workspaces` `id = ANY(app.workspace_ids)`. `carvis_app` has `SELECT` only
on the identity tables in B2 and no `EXECUTE` on `ensure_principal`. Independent fail-closed layers:
the listener raises without context; without `SET LOCAL ROLE` the login is denied every object;
with the role but no settings every policy matches nothing; settings end with the transaction.

### Provisioning (`ensure_principal`)

`carvis.ensure_principal(p_issuer text, p_subject text, p_email text) RETURNS (user_id, status)` is
the only path that creates identity rows in B2. It is `SECURITY DEFINER`, owned by
`carvis_provisioner`, with `SET search_path = pg_catalog, pg_temp`, schema-qualified references, and
exact-equality matching only (issuer and subject non-empty, at most 255 characters, no NUL; email at
most 320 or NULL). Keys: `users (auth_issuer, auth_subject)` UNIQUE; `workspaces.personal_owner_user_id`
references `users`, is set if and only if `kind = 'personal'` (`CHECK`) and is UNIQUE, so a user has
at most one personal workspace; `memberships (workspace_id, user_id)` UNIQUE.

Steps, all in the bootstrap transaction (READ COMMITTED):

1. Set `app.bootstrap_issuer` and `app.bootstrap_subject` from the arguments, unconditionally, and
   clear `app.bootstrap_user_id`.
2. `INSERT` the user `ON CONFLICT (auth_issuer, auth_subject) DO NOTHING` (email only on creation),
   then `SELECT id, status` for that principal. A concurrent first request waits on the unique key
   and then reads the committed row.
3. If the status is not `active`, return it without creating anything.
4. Set `app.bootstrap_user_id`. `INSERT` the personal workspace
   `ON CONFLICT (personal_owner_user_id) DO NOTHING`, then `SELECT` its `id` by
   `personal_owner_user_id`: an existing workspace is reused, and concurrent requests converge on the
   one row the unique key allows.
5. `INSERT` the owner membership for that workspace `ON CONFLICT (workspace_id, user_id) DO NOTHING`.
6. Clear the three bootstrap settings and return `(user_id, status)` only.

Database-level bounds, which hold even if the function body is wrong:

- `carvis_provisioner` grants: `SELECT (id, status, auth_issuer, auth_subject)` and
  `INSERT (auth_issuer, auth_subject, email)` on `users`; `SELECT (id, kind, personal_owner_user_id)`
  and `INSERT` on `workspaces`; `SELECT (workspace_id, user_id, role)` and `INSERT` on `memberships`;
  `USAGE` on schema `carvis`. No `UPDATE`, `DELETE` or `TRUNCATE`, so it cannot change or remove an
  existing row. The `SELECT` grants exist because `ON CONFLICT` with a conflict target requires
  `SELECT` on the target columns and applies the `SELECT` policies to the proposed row, for
  `DO NOTHING` as well.
- Policies `TO carvis_provisioner` (RLS is forced, so they bind the definer too): `users` rows only
  where `auth_issuer = app.bootstrap_issuer AND auth_subject = app.bootstrap_subject`; `workspaces`
  rows only where `kind = 'personal' AND personal_owner_user_id = app.bootstrap_user_id`;
  `memberships` rows readable only where `user_id = app.bootstrap_user_id`, and insert only
  `WITH CHECK (user_id = app.bootstrap_user_id AND role = 'owner' AND
  workspace_id = (SELECT id FROM carvis.workspaces WHERE kind = 'personal' AND
  personal_owner_user_id = app.bootstrap_user_id))`. Provisioning therefore cannot read another
  user's row, attach to a shop workspace, or create an owner membership in another user's workspace.
- A constraint trigger on `memberships`, for every role, rejects a membership in a personal workspace
  unless the member is that workspace's `personal_owner_user_id` with role `owner`, and fails closed
  when the workspace is not visible to the inserting role.
- `carvis_bootstrap` holds no table privileges, so a forged `app.bootstrap_*` setting grants nothing
  outside the function, which overwrites those settings before its first statement.

Residual trust: the database cannot check a JWT. A caller holding the runtime login can name any
`(issuer, subject)` and learn only that principal's `(user_id, status)`, or create that principal's
own personal rows. That is the same trust RLS places in `app.user_id`; JWT verification in FastAPI
is the authority, and RLS defends against missed filters and context leaks.

### Pooling

Transaction-scoped context is safe with SQLAlchemy `QueuePool` and with transaction-mode poolers.
Poolers in transaction mode require disabling driver prepared-statement caching (asyncpg
`statement_cache_size=0`, or psycopg 3 `prepare_threshold=None`) [?]. Use `pool_pre_ping=True` and
`pool_reset_on_return="rollback"`. Default for V1: session-mode pooler or direct connection with a
small pool on one instance. Supabase direct hosts are IPv6-only without an add-on and Render IPv6
egress is unconfirmed [?], so plan on the pooler endpoint. Pooler support for a custom login role
and `SET LOCAL ROLE` in transaction mode is validated at provisioning [?]. Each `/v1` request is one
bootstrap transaction followed by one tenant unit of work in one transaction; no autocommit sessions
on the request path.

### Workers

A job row carries `workspace_id`. The worker opens a transaction as `carvis_worker` and sets context
from the job row, never from payload content. Cross-tenant jobs run as `carvis_maintenance` in small
batches and write one audit event per batch.

### Webhook path and `resolve_call`

`resolve_call(p_vapi_call_id text)` is the only read allowed on the webhook path before tenant
context exists (`ensure_principal` serves only the JWT-authenticated `/v1` bootstrap).

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

Policies implement tenant isolation only: the tenant-table shape, the identity-table shapes in
"Context carrier", and the bounded provisioner policies. Role-based permissions remain in the
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
12. The raw deployment login, without `SET ROLE`, is denied every relation, sequence and function in
    the CARVIS schemas; each refusal condition of the login check is triggered on its own.
13. `carvis_bootstrap` is denied every table and can execute only `ensure_principal`; `carvis_app`,
    `carvis_worker`, PUBLIC and stub `anon`/`authenticated`/`service_role` cannot execute it.
14. `ensure_principal`: calls for one principal leave every other user's rows unchanged; an existing
    personal workspace is reused; 50 concurrent first requests yield exactly one user, one personal
    workspace and one owner membership; an owner membership in another user's workspace, or any
    membership in a personal workspace for someone other than its owner, is rejected by the database
    even when attempted directly as `carvis_provisioner` (policies and trigger, independent of the
    function body); a non-active user gets no new rows; search-path hijack has no effect.
15. Function privileges: the catalog check fails on any CARVIS function with a NULL `proacl` or a
    `PUBLIC` or issuer-role `EXECUTE`, and on a function created after migration without an explicit
    grant (default-privilege revoke works, globally scoped).
16. Fail-closed layers, each disabled in turn: no listener context ⇒ the transaction does not begin
    and no SQL is sent; listener removed ⇒ permission denied; role set without settings ⇒ zero rows.

Tests 1–8, 10 and 12–16 cover the identity tables in B2 (B2a: 12 and the default-privilege part of
15; B2b: the rest, once `ensure_principal` and the tables exist); 9 on conversation and turn lists lands with B4, 11 with B4/B5, and the `carvis_maintenance`
part of 7 with B8.

## Account lifecycle

Deletion sets `users.status=deleting`, revokes tokens at the issuer, then a retention job deletes the
personal workspace data after the grace period; shop workspaces are transferred or the request is
refused; audit events are anonymized. Export returns the user's conversations, vehicles and feedback.
