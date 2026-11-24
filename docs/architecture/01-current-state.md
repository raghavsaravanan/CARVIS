# 01 — Current-state assessment

> **Historical snapshot.** This is the repository as of 2026-11-15, before M2 Track A and the
> Track B packages merged after it (see [12-m2-roadmap.md](12-m2-roadmap.md) and
> [11-traceability-matrix.md](11-traceability-matrix.md) for current status). Its observations are
> preserved unchanged as audit evidence; verify current behavior against code and tests.

Snapshot of the repository at `main` as of 2026-11-15. Claims are verified against code unless
labeled [A]. Line numbers drift; re-check before relying on them.

## What works and must be preserved

| Property | Evidence |
| --- | --- |
| Deterministic verified answers: exact Qdrant filters → full `scroll` (limit 257, overflow refuses) → Python revalidation → conflict, revision, incomplete-procedure refusals → digest-bound review → ranking only selects the citation | [V] `backend/spec_retrieval.py:211-255`, `backend/spec_schema.py` (`evidence_errors`), `backend/qdrant_v2.py` |
| No cross-vehicle or cross-shop fallback; invented numbers blocked (`ungrounded_numbers`); vision output scrubbed of measurements | [V] `backend/tests/test_specs_v2.py::test_no_cross_vehicle_or_shop_fallback`, `backend/conversation.py` |
| Conversation state machine: spoken vehicle confirmation gate, dependent-memory invalidation, generation-fenced calls, camera request states, `toolCallId` idempotency cache | [V] `backend/conversation.py`, `backend/tests/test_conversation.py` |
| Safe ingestion/review tooling: staging-only writes, review bound to PDF SHA-256 and evidence digest, validate then atomic alias activation, same command as rollback | [V] `backend/ingest.py`, `backend/migrate_v2.py`, `qdrant_v2.assert_staging` |
| Pure-Swift state machines with tests | [V] `ios/Carvis/Carvis/Assistant`, `ios/Tests` |
| CI: SHA-pinned actions, forbidden-path and credential scans, pure Swift checks | [V] `.github/workflows/ci.yml` |

## Defects and gaps

1. **Webhook fails open.** `/vapi-tool` skips authentication when `VAPI_WEBHOOK_SECRET` is unset and
   compares with `!=` (`backend/main.py:1797-1803`).
2. **Call binding is overwritable.** `ConversationStore.bind_call` replaces any existing
   `vapi_call_id` mapping; `session_for_webhook` trusts a payload-supplied `carvis_session_id`;
   `_calls` is never pruned (`backend/conversation.py:339-369`).
3. **Unauthenticated, caller-scoped endpoints.** `POST /conversation/sessions`, `/vision-query` and
   `/upload` take `shop_id`, owner and vehicle from the caller (`backend/main.py:1303,1492,1694`).
   `/upload` has no size cap or PDF magic check and can trigger paid LlamaParse work. The legacy
   sessionless `/vapi-tool` path takes `shop_id` from model-supplied arguments with default
   `shop_demo`.
4. **All conversation state is in process memory** (4 h TTL, 256-session cap with LRU eviction on
   unauthenticated create, restart loses everything).
5. **No CORS policy, rate limiting, request IDs, structured logging, or retention policy.**
6. **SpacetimeDB is best-effort telemetry only.** Only `/vision-query` writes to it, through one
   service identity; raw questions and answers are sent; Python calls reducer `start_shop_query`
   while the module exports `startShopQuery` (the SDK name mapping is unconfirmed); `startShopQuery`
   upserts by `id` without an ownership check; `joinShopByCode` uses a long-lived bearer code
   (`backend/main.py:62-82,1345`, `backend/spacetimedb/module/src/index.ts:518-653`).
7. **Operational hygiene.** Unpinned `backend/requirements.txt` with `pytest` in runtime
   dependencies and no lockfile; `setup.sh` sources `.env` as shell; `render.yaml` uses
   `plan: free`; hard-coded `shop_demo`, `hackutd`, `george_specs` defaults; the review CLI accepts
   an unauthenticated reviewer string. The serving process loads fastembed `TextEmbedding` at startup
   (`backend/main.py:1105`), which matters for instance sizing.
8. **iOS.** No sign-in or Keychain; JSON files in Documents; one car; free-text VIN; user-editable
   `serverOverride`; machine-specific HTTP `.local` base URL; simulated jobs/shop views that
   conflict with contract D-06; no Garage, History, evidence, feedback or settings screens.

## Re-check of the historical audit

Confirmed: CAR-001, 004, 005, 011, 051, 053 missing; security blockers 1–8 and 12. Not re-verified
[A]: monitoring (blocker 11) and source rights (blocker 13). The audit remains a checklist of
claims, not current truth.

## Existing test coverage gaps that M2 must close

No test covers: webhook behavior when the secret is unset, authentication on `/upload` or
`/vision-query`, cross-shop authorization beyond data-level fallback, `bind_call` hijack, session-cap
eviction, or SpacetimeDB reducer names.
