# 10 — Threat model, security acceptance tests, release gates

## Threats and controls

| Threat | Control | Acceptance test |
| --- | --- | --- |
| Tenant spoofing | Authority only from JWT, memberships and the bound call row | Another tenant's IDs or `shop_id` on every route ⇒ 404/403 |
| IDOR | Membership lookup plus RLS | User A × every ID of user B ⇒ 404; RLS-only variant (filter removed) still isolates |
| RLS context leak (pool/worker) | `SET LOCAL` in `after_begin`, `FORCE RLS` | Tests 1–10 in [04](04-identity-tenancy-rls.md) |
| Webhook forgery | Credential, fail-closed boot, constant-time compare | None/wrong credential ⇒ 401; no boot without credential |
| Call hijack, echoed-token abuse | JWT-owned row ∧ Vapi-confirmed nonce ∧ unique unbound mapping | Adversarial tests in [06](06-vapi-ingress.md) |
| Webhook replay | `webhook_events`, generation fence | Replay ⇒ stored response, one turn |
| Unauthorized ingestion | `/internal` with `brain_reviewer` ≠ `brain_publisher`; size and magic checks | Non-operator ⇒ 403 |
| Stale, withdrawn or tampered evidence spoken | Four-condition invariant in both stores (status, digest, equal `state_version`, no blocking tombstone); alias-independent control collection | Acceptance cases 1–12 in [07](07-brain.md#serve-time-invariant-tombstone-and-alias-swap-acceptance-cases) |
| Withdrawal lost to a failed PostgreSQL transaction or an alias swap | Tombstone-first with intent/commit markers; tombstones and counters outside swapped collections; activation guards | Cases 4, 6, 7, 11 in [07](07-brain.md#serve-time-invariant-tombstone-and-alias-swap-acceptance-cases) |
| Cross-tenant evidence | Server-derived `brain_scopes` | Shop A evidence never returned to shop B or global users |
| Source-rights leakage | `rights_basis` gate, scope | Activation blocked without rights basis |
| LLM hallucination or vision injection | Verification unchanged; measurement scrub | Existing grounding and `test_vision_guesses_*` tests stay green |
| Token theft or account takeover | Short JWT TTL, Keychain, operator MFA | Expired, wrong-audience or deleted-user token ⇒ 401 |
| Retention and privacy | Purge jobs, deletion endpoint | Deletion verified in staging |
| DoS and session eviction | Durable sessions, rate limits | Unauthenticated floods ⇒ 429, no eviction |
| Secrets in logs | Redaction | Log-capture test |
| Silent double rollback of Brain state | Mandatory quarantine on restore; operator ops-log record | Restore drill (G14) |

## Release gates (objective; passing unit tests alone does not declare readiness)

- **G1** All tests above pass in CI on real PostgreSQL, including the RLS-only variant.
- **G2** The existing verification suites (`test_specs_v2.py`, `test_ride_height.py`,
  `test_conversation.py`, `test_main.py`, `test_vapi_assistant.py`) are unchanged and green.
- **G3** The promoted image on staging, with the real identity provider and database, completes a
  live Vapi call from a physical iPhone (labelled live-provider validation).
- **G4** Timed restore drill: Supabase backup and nightly dump.
- **G5** Migration upgrade/downgrade and old-app-on-new-schema on a seeded staging copy.
- **G6** Secret rotation drill (webhook credential, operator token).
- **G7** A synthetic alert fires end to end.
- **G8** Account deletion verified in staging.
- **G9** Reconciliation reports zero unresolved discrepancies.
- **G10** Independent review (`/carvis-pr-review`) and security review recorded for each PR.
- **G11** `rights_basis` recorded for every active source.
- **G12** SpacetimeDB removed: suite green with its variables unset.
- **G13** Production memory and latency measured under scripted call load.
- **G14** Brain restore drill: restore to before a withdrawal in staging ⇒ quarantine → reconcile →
  rebuild → exit; the "no continuity proof" variant forces reapproval. Also passes the 12 serve-time,
  tombstone and alias-swap acceptance cases in [07](07-brain.md#serve-time-invariant-tombstone-and-alias-swap-acceptance-cases),
  including a withdrawal whose PostgreSQL transaction is forced to fail and an alias swap after a withdrawal.
- **G15** Vapi gates G-V1…G-V6 validated with a real staging call; adversarial bind tests pass
  against the captured response shapes.

Mocked, simulator, physical-device and live-provider results are always reported separately.
