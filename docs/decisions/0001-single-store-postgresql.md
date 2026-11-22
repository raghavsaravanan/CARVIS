# 0001. PostgreSQL as the single canonical transactional store

- **Status:** accepted (owner, 2026-11-22; roadmap D-1)
- **Date:** 2026-11-15
- **Resolves:** contract D-08, D-11 (store half)
- **Supersedes:** none

## Context

V1 needs durable users, workspaces, vehicles, conversations, evidence references, feedback and audit
data with server-enforced tenancy (contract §7). Today all state is in process memory or local iOS
JSON, and SpacetimeDB holds only best-effort telemetry ([`../architecture/01-current-state.md`](../architecture/01-current-state.md)).
Solo operator, one initial tester, must scale without redesign.

## Options considered

| Option | Assessment |
| --- | --- |
| Managed PostgreSQL with SQLAlchemy 2 and Alembic | Transactions, foreign keys, CHECK constraints, mature migrations, RLS, PITR on managed tiers, broad tooling |
| Supabase Postgres | Same engine; see ADR-0002 for hosting terms |
| Neutral managed Postgres (Neon/RDS) | Valid fallback; more vendors to wire |
| Retain SpacetimeDB | No relational constraints or migration story for audit data, no iOS path, no approved deployment (ADR-0007) |
| Firestore/Firebase | No relational integrity; weak fit for evidence and audit joins |

## Decision

One PostgreSQL database per environment is the only transactional store. Schema is owned by a single
linear Alembic chain. Qdrant remains an evidence index and never holds identity or transactions.
Not chosen: a second store for the same data, an ORM-less ad hoc schema, microservices.

## Consequences

Adds SQLAlchemy, Alembic, a PostgreSQL service in CI and local compose. Migrations follow
expand/contract ([`../architecture/08-migration-and-spacetimedb.md`](../architecture/08-migration-and-spacetimedb.md)).
Rollback: schema changes are reversible until a contract step; the application can run on the
previous image against an expanded schema.

## Verification

Alembic upgrade/downgrade/upgrade schema-identity test; linear-history check; old-app-on-new-schema
smoke test; restore drill (gate G4).
