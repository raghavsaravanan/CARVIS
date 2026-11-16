# 0008. Environments, deployment, backups and cost

- **Status:** proposed (prices and plan limits to be re-verified)
- **Date:** 2026-11-15
- **Resolves:** PRD §15.2 engineering gates; contract §10 device/deployment
- **Supersedes:** none

## Context

`render.yaml` uses the Free plan (cold starts) and there is one `/health` check, no staging, no
backup or restore procedure. Sized for one initial tester.

## Options considered

Render versus alternative hosts; Supabase Free versus Pro; PITR add-on versus daily backups plus an
independent dump; one environment versus staging plus production.

## Decision

Local, staging and production environments. One container image built once and promoted. Render paid
instance (2 GB for production until measured); Supabase Pro for production; nightly independent
encrypted `pg_dump` in a separate account with 30-day retention; PITR off unless the owner approves
(D-5). Typed settings, boot refusal for missing credentials, `/healthz` and `/readyz`, structured
logs, a few counters, hosted uptime check, error tracker. Estimated $70–150/month before provider
usage. Details: [`../architecture/09-deployment-operations.md`](../architecture/09-deployment-operations.md).

## Consequences

Single-instance deploys cause brief downtime; no HA by design. Changing hosts affects configuration,
not architecture. Rollback: redeploy the previous image; database rollback follows the
expand/contract rules in ADR-0001.

## Verification

Gates G3–G7 and G13: staging live-call, timed restore, migration rollback, secret rotation, synthetic
alert, load-measured sizing.
