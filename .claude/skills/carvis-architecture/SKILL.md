---
name: carvis-architecture
description: Investigate the CARVIS repository and produce architecture work before any code changes — transactional database and auth selection, multi-tenant authorization design, V1/V2 domain model, versioned API contracts, migration plans, threat model, and architecture decision records. Use when asked to design, compare, plan, or decide how identity, persistence, tenancy, or API contracts should work.
allowed-tools: Read Grep Glob Bash(git status *) Bash(git log *) Bash(git diff *) Bash(git ls-files *) Bash(wc *) Bash(ls *)
---

# CARVIS architecture workflow

This skill produces designs and records, not application code. Application code, provider
configuration, Qdrant aliases, SpacetimeDB publishes, and cloud resources stay untouched
(`AGENTS.md`, "Protected boundaries").

## 1. Ground yourself first (in this order)

1. `AGENTS.md`, then the scoped `backend/AGENTS.md`, `backend/spacetimedb/AGENTS.md`, `ios/AGENTS.md`.
2. `docs/README.md` for precedence. `docs/PRD.md` = requirements. `docs/product/v1-product-experience-contract.md`
   = approved V1 pilot scope: §7 (data/access contract), §8 (V1→V2), §11 (required first deliverables),
   §12 (open questions). Decisions D-06 to D-09 are proposed defaults; **D-11 and D-12 are unresolved.**
   Do not silently resolve them; write a proposed ADR and ask the owner.
3. `docs/audits/2026-11-15-p0-readiness-audit.md` is a **historical snapshot**. Use its gap matrix (§4)
   and security blockers (§7) as a checklist of claims to re-verify, never as current fact.
4. `docs/backend/architecture.md`, `docs/backend/qdrant-v2-migration.md`, `docs/development-workflow.md`.

## 2. Investigate the actual repository

Re-verify every audit claim against code before relying on it:

```bash
git status --short --branch && git log --oneline -8
grep -nE '^@app\.' backend/main.py                      # every route; note which take a principal
grep -nE 'shop_id|owner|session_id' backend/main.py     # caller-supplied authority
grep -nE '^(class|def) ' backend/conversation.py        # ConversationStore: in-memory, TTL, 256 cap
grep -nE 'table\(|ctx\.sender|senderAuth|reducer' backend/spacetimedb/module/src/index.ts
ls ios/Carvis/Carvis/Models ios/Carvis/Carvis/Backend   # AppStores.swift, ConversationClient.swift, VisionClient.swift
```

Record for each protected route: who authenticates, where tenant/vehicle authority comes from, and what
is persisted. Anything derived from a request body, form field, or header the caller controls is untrusted.

## 3. Database and auth selection

Compare options against the real constraints in contract §7, not generic preference: migrations and
tooling, OIDC/JWT integration with a native iOS client (Keychain tokens), transaction guarantees,
backup and point-in-time recovery, operational overhead for a solo operator, multi-tenant enforcement
(row-level policies versus application-only checks), cost, data-residency/retention controls, and
deletion/export support. Evaluate SpacetimeDB **fairly** alongside a conventional managed relational
store: its module already has `ctx.sender`-based membership checks, but it has no iOS bindings, no
approved deployment, and only best-effort telemetry from FastAPI today (re-verify).

Rules: exactly one canonical transactional store; Qdrant stays a reviewed-evidence index and never
holds identity or transactions; FastAPI stays the policy enforcement point; no microservices. Do
**not** use connected database/MCP tools (for example Supabase) to create projects, apply
migrations, or run SQL against any real project during evaluation. Use vendor documentation and
local scratch schemas only.

## 4. Multi-tenant authorization design

- Principal comes from a verified bearer credential (provider-agnostic OIDC/JWT); tenant comes from
  server-side membership lookups. Never accept `user_id`, `shop_id`, vehicle, or session identifiers as authority.
- Every object ID in a path or body is looked up *through* the principal's memberships; a miss returns
  not-found/forbidden without revealing existence.
- Vapi webhooks authenticate by bound call/session identity and a mandatory secret that fails closed
  (see `test_webhook_requires_the_vapi_secret` and `test_session_requires_its_own_token`).
- Review/ingestion/coverage endpoints are internal admin operations with distinct review and publish privileges.
- Specify defense in depth (application check plus database constraint or row policy) and the Qdrant
  `shop` filter for shop-specific evidence versus explicitly global evidence.

## 5. V1/V2 domain model

Start from contract §7.1 entities (User, Workspace/Shop, Membership, Vehicle, VehicleSnapshot,
Conversation, Call, Turn/AnswerOutcome, EvidenceReference, Feedback, SourceDocument, EvidenceRecord,
ReviewDecision, CoverageManifest, UsageEvent, AuditEvent). Design one additive canonical schema:
V1 tables are the V2 foundation; V2 items in contract §8 are named, not built. Produce an ER diagram,
a field dictionary, ownership and tenant-scoping rules, retention and deletion behavior per entity,
and immutability rules (VehicleSnapshot, ReviewDecision, AuditEvent).

## 6. API contracts and migration planning

- Preserve `/vapi-tool`, `/upload`, `/vision-query`, `/health`, and the
  `/conversation/sessions…` family unless a scoped, versioned migration is approved. Introduce new
  resources under a version prefix with typed request/response schemas and error codes.
- Map current state to the target: in-memory `ConversationStore`, local `account.json`/vehicle/history
  JSON on iOS, and optional SpacetimeDB telemetry. Use expand/contract steps, each independently
  deployable and reversible, with a shadow development environment first.
- Every step lists: tests written first (restart durability, negative tenant access, idempotency,
  source-revision validity), rollback, and what remains untouched (voice pipeline, retrieval/verification).

## 7. Deliverables and decision records

Produce, in this order, the contract §11 list: ER diagram and field dictionary; database/auth options
with a single-store recommendation; migration and compatibility map; versioned API contracts;
feature→screen→entity→endpoint→test traceability matrix; threat model (tenant spoofing, IDOR, webhook
replay, unauthorized ingestion, source-rights leakage, privacy retention); phased plan with separate
acceptance gates.

Write each decision as `docs/decisions/NNNN-<kebab-title>.md` from `docs/decisions/0000-template.md`
with status `proposed`. Only the repository owner accepts a record. Design documents belong under
`docs/`, never in `AGENTS.md` or `CLAUDE.md`.

## 8. Guardrails

No secrets, customer data, manuals, or transcripts in documents. Do not access bondingAI material.
State which findings were verified in code, which were taken from the historical audit, and which are
assumptions. Do not commit or push without approval.
