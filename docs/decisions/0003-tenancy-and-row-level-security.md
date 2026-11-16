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

Every tenant-owned table carries `workspace_id` and has RLS enabled and forced. The API role is
neither owner nor `BYPASSRLS`. Tenant context is a transaction-scoped GUC set in a SQLAlchemy
`after_begin` event; missing context yields zero rows. Workers set context from the job row;
cross-tenant maintenance uses a separate narrowly granted role. The webhook path uses a minimal
`SECURITY DEFINER` `resolve_call` function. Policies implement tenant isolation only; role-based
permissions stay in the application. Full specification:
[`../architecture/04-identity-tenancy-rls.md`](../architecture/04-identity-tenancy-rls.md).

## Consequences

Slightly more complex session handling and mandatory real-PostgreSQL tests. Pooler choice matters
(prepared statements, IPv4/IPv6) and is validated in B1/B2. Rollback: policies can be disabled per
table by a migration, but only with owner approval since it removes a defense layer.

## Verification

Ten-plus RLS tests listed in the architecture document (pool leak, interleaving, filter bypass,
workers, catalog check for unprotected tenant tables, `resolve_call` hardening).
