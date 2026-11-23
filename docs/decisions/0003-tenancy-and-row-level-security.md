# 0003. Workspace tenancy with application checks and PostgreSQL RLS

- **Status:** proposed
- **Date:** 2026-11-15
- **Resolves:** PRD CAR-003, CAR-004; contract §7.2
- **Supersedes:** none

## Context

Today tenant (`shop_id`) and vehicle authority are caller-supplied. Filter-in-every-query isolation
is one missed `WHERE` away from a cross-tenant leak.

## Options considered

| Option | Assessment |
| --- | --- |
| Application filtering only | Simple; a single missed filter leaks |
| Application filtering plus PostgreSQL RLS | Defense in depth; cost: context plumbing and tests |
| Database per tenant | Unwarranted operational cost |

## Decision

Every tenant-owned table carries `workspace_id` and has RLS enabled and forced; so do the identity
tables `users`, `workspaces` and `memberships`. The API role is neither owner nor `BYPASSRLS`. The
deployment login holds no privileges of its own: it is a member of `carvis_app` and
`carvis_bootstrap` with `INHERIT FALSE`, and each transaction selects one of them with
`SET LOCAL ROLE`.

A `/v1` request runs two transactions. The **bootstrap transaction** (`carvis_bootstrap`, which may
only execute `carvis.ensure_principal`) finds or provisions the verified principal's user, personal
workspace and owner membership just in time and returns the user ID and status. The **tenant
transaction** (`carvis_app`) sets `app.user_id` from that result and derives `app.workspace_ids`
from the caller's memberships under RLS, all in a SQLAlchemy `after_begin` event that refuses to
begin without context. Context is transaction-scoped (`set_config(..., true)`); missing context
yields zero rows. Provisioning is bounded at the database level to the named principal's own rows.

Workers set context from the job row; cross-tenant maintenance uses a separate narrowly granted
role. The webhook path uses a minimal `SECURITY DEFINER` `resolve_call` function. No
`SECURITY DEFINER` function is executable by `PUBLIC` or an issuer role. Policies implement tenant
isolation (plus the bounded provisioning policies); role-based permissions stay in the application.
Full specification:
[`../architecture/04-identity-tenancy-rls.md`](../architecture/04-identity-tenancy-rls.md).

## Consequences

Slightly more complex session handling and mandatory real-PostgreSQL tests. Pooler choice matters
(prepared statements, IPv4/IPv6); B1 and B2 use only transaction-scoped settings and disable
prepared statements, and compatibility with the Supabase pooler (including custom login roles and
`SET LOCAL ROLE` in transaction mode) is validated at provisioning, not assumed [?]. Rollback: policies can be disabled per
table by a migration, but only with owner approval since it removes a defense layer.

## Verification

The real-PostgreSQL tests listed in the architecture document (raw login without access, pool
leak, interleaving, filter bypass, workers, provisioning bounds and concurrency, function privileges,
catalog check for unprotected tenant tables, `resolve_call` hardening).
