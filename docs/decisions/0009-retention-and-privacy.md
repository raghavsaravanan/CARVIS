# 0009. Retention and privacy

- **Status:** proposed (owner decision D-12 / roadmap D-4)
- **Date:** 2026-11-15
- **Resolves:** contract D-12
- **Supersedes:** none

## Context

Retention of history, transcripts, feedback and raw audio is undefined; traces may contain questions
and vehicle context (audit blocker 9, 10 [A]).

## Options considered

Keep everything; metadata only; time-boxed text then metadata.

## Decision (proposed defaults)

No raw audio stored by CARVIS; Vapi recording/transcript storage set to the minimum. Turn text kept
90 days, then nulled while metadata and outcome remain. Feedback kept until the user deletes it or the
account. Audit events kept one year, anonymized on account deletion. Account deletion: soft-delete,
30-day grace, then purge of the personal workspace; shop workspaces transferred or refused. Export
endpoint returns the user's data. Webhook dedupe rows purged after 14 days, jobs after 30.
Transcripts, tokens and secrets are never written to logs.

## Consequences

Scheduled retention jobs, an export endpoint, data-processing agreements with vendors (owner action).
Rollback: lengthen retention by configuration; shortening requires a purge run.

## Verification

Deletion and export verified in staging (G8); log-capture test; retention job tests against seeded
data.
