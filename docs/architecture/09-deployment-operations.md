# 09 — Deployment, operations, privacy and recovery

Sized for one initial tester; shaped so that growth means resizing and adding replicas, not
redesign. Prices and plan limits below are **order-of-magnitude [W]** from vendor documentation and
third-party summaries; verify on the vendors' pricing pages before ADR-0008 is accepted.

## Vendor facts used [W]

- Supabase Free: no automatic backups or PITR, projects pause after about a week of inactivity, two
  active projects ⇒ unsuitable for production. Pro: daily backups with 7-day retention; PITR is a
  paid add-on (listed around $100/month per 7 days of retention, outside the spend cap) and replaces
  daily backups when enabled; paid projects are not paused.
- Render Free web services sleep after about 15 minutes idle (about a minute to wake) ⇒ unusable for
  voice, and today's `render.yaml` uses `plan: free`. Starter is about $7/month with 512 MB RAM;
  background workers start at Starter; a workspace plan fee may apply.
- Memory [V + ?]: the API loads fastembed `TextEmbedding` at startup (`backend/main.py:1105`).
  512 MB may be insufficient; budget a 2 GB instance for production until measured (gate G13).

## Environments

| Env | Compute | Database | Qdrant | Vapi |
| --- | --- | --- | --- | --- |
| local | docker-compose PostgreSQL and Qdrant | local | local | mocks |
| staging | Render paid instance (not Free) | Supabase project (Free tolerated: pause and no backups) or Pro | separate collection or cluster | separate assistant and credential |
| production | Render 2 GB instance, one replica, `/readyz` health check | Supabase **Pro** | Qdrant Cloud, separate from staging | production assistant and credential |

Estimated monthly cost before Vapi/LLM usage: about $70–150 (production compute ≈ $25–32,
Supabase Pro ≈ $25 plus compute if needed, Qdrant ≈ $0–30, staging ≈ $7–25). PITR would add about $100.

## Build and configuration

One container image built once and promoted staging → production. `uv` lockfile, pinned Python 3.12,
runtime and dev dependencies split (pytest out of runtime). A typed `Settings` object validates every
required variable per environment at startup; staging and production refuse to boot without the Vapi
credential. Secrets live in Render environment groups; nothing in the repository (the CI scan stays).
`scripts/doctor.sh` performs a preflight (versions, variables present, database and Qdrant reachable).

## Backups and recovery

- Supabase daily backups (RPO up to 24 h) **plus** a nightly independent `pg_dump` (encrypted, stored
  in a separate account or bucket, 30-day retention) to remove single-vendor dependence.
- PITR add-on: owner decision D-5. Recommended off for the pilot: history and feedback are low-loss
  data and the Brain is rebuildable from PostgreSQL plus stored revisions.
- Mandatory before the pilot: a timed restore into staging (gate G4) and the Brain restore drill in
  [07-brain.md](07-brain.md) (gate G14).
- Qdrant: weekly snapshot and a documented rebuild from PostgreSQL plus stored revisions.
- Targets for the pilot: RPO ≤ 24 h (≤ minutes only if PITR is approved), RTO ≤ 2 h.

## Observability

Structured JSON logs with `request_id`, `call_id`, generation; counters and histograms for ask
latency, refusal reasons, webhook 401 and duplicates, bind failures, projection lag, reconciliation
discrepancies; a hosted uptime check on `/readyz`; an error tracker (vendor to confirm); alerts to one
channel. Transcripts, tokens and secrets are never logged (CI log-capture test). OpenTelemetry is
deferred.

## Abuse controls and degradation

Per-user and per-IP rate limits on `/v1`, strict limits on `/internal`; body caps (8 MiB images,
50 MiB PDFs with `%PDF-` magic check); bounded in-process maps. Qdrant down ⇒ explicit "cannot verify
right now" refusal; PostgreSQL down ⇒ 503 retryable and technical refusal; Vapi errors ⇒ the existing
tool error shape; quarantine ⇒ `brain_unavailable`.

## Privacy

No raw audio stored by CARVIS; Vapi recording and transcript settings reviewed and set to the minimum
the retention decision allows; PII minimization; export and deletion endpoints; data-processing
agreements with the identity, database, Vapi and LLM vendors (owner action); no real customer data,
manuals or transcripts in the repository.

## Known limitations (documented, accepted for V1)

Single instance ⇒ brief downtime on deploy; camera long-poll requests are process-local and drop on
deploy; no HA or multi-region; Supabase maintenance windows [?]; provider timeouts degrade to refusals.

## Runbooks to write in M2 (PR B10)

Webhook credential and operator token rotation; restore from Supabase backup and from the nightly dump
(including mandatory Brain quarantine); alias rollback; reconciliation discrepancy; Qdrant outage;
account-deletion failure; incident communication to the pilot tester.
