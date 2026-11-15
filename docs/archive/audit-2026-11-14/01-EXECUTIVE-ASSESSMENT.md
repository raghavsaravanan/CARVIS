# Carvis executive assessment

**Audit date:** 2026-11-14
**Scope:** repository state at `39b9a7f` on `main`; no production services contacted
**Constraint:** `docs/PRD.md` is absent from both the working tree and `HEAD`. The product outcomes in the audit brief are therefore used as a provisional P0 baseline. This is not a substitute for an approved PRD.

## Executive conclusion

Carvis is a strong hackathon prototype with an unusually careful service-manual verification core, but it is not ready for a real mechanic or TestFlight pilot. The repository contains three partially connected products: a Meta-glasses-first native app, a source-reviewed FastAPI/Qdrant knowledge backend, and a SpacetimeDB/React shop workspace. The immediate product direction instead requires a phone-first, authenticated, durable audio application. That end-to-end product does not yet exist.

The most reusable foundation is the v2 knowledge-safety pipeline: explicit vehicle applicability, pending-review ingestion, evidence digests, exact filters, conflict detection, complete procedure-stage checks, deterministic spoken formatting, and refusal when evidence is insufficient. This behavior is implemented across [`spec_schema.py`](../../../backend/spec_schema.py), [`spec_retrieval.py`](../../../backend/spec_retrieval.py), [`ingest.py`](../../../backend/ingest.py), and [`qdrant_v2.py`](../../../backend/qdrant_v2.py), with broad mocked/local coverage in [`test_specs_v2.py`](../../../backend/tests/test_specs_v2.py). It should be preserved behind clearer interfaces rather than rewritten.

The main launch blockers are product and operational foundations, not model sophistication:

1. There is no server-backed user account, authorization boundary, or iOS identity integration. The iOS “account” is a local JSON file ([`AppStores.swift`](../../../ios/Carvis/Carvis/Models/AppStores.swift#L4-L84)).
2. The voice flow explicitly requires Meta glasses and a glasses Bluetooth route ([`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L219-L239), [`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L353-L386)); it is not an iPhone audio-first experience.
3. Conversation truth is process memory with a four-hour TTL and a 256-session cap ([`conversation.py`](../../../backend/conversation.py#L29-L34), [`conversation.py`](../../../backend/conversation.py#L307-L340)). Restarts and horizontal scaling lose sessions, history, and call bindings.
4. The knowledge corpus is not production-ready. Repository evidence documents only four reviewed WRX oil-change records and no approved ALLDATA access ([`qdrant-v2.md`](../validation-qdrant-v2.md)).
5. The public API boundary is unsafe for a pilot: `/vision-query`, `/upload`, and session creation have no user authentication; CORS is wildcard; Vapi authentication is optional if a secret is missing ([`main.py`](../../../backend/main.py#L1148-L1154), [`main.py`](../../../backend/main.py#L1502-L1573), [`main.py`](../../../backend/main.py#L1801-L1814)).

## Provisional P0 estimate

Because the required PRD is missing, the only defensible denominator is the eight launch outcomes in the audit brief. Each outcome was scored `1.0` only for implementation with suitable repository validation, `0.5` for a meaningful partial implementation, `0.25` for a prototype/local-only implementation, and `0` if absent. The scores are:

| Outcome | Score | Rationale |
| --- | ---: | --- |
| Account and onboarding | 0.25 | Polished local onboarding; no real account/authentication. |
| Identify and confirm vehicle | 0.50 | Local profile plus spoken confirmation state; no authoritative vehicle/VIN workflow or durable ownership. |
| Natural voice conversation on iPhone | 0.00 | Current path requires Meta glasses and Vapi configuration. |
| Vehicle-specific questions | 0.50 | Strong backend path, but narrow controlled vocabulary/corpus and no phone-first E2E validation. |
| Sourced/verified answers and safe refusal | 0.75 | Strong deterministic implementation/tests; production corpus and real integration remain unvalidated. |
| Correct continuing context | 0.50 | Tested within one in-memory session; not durable across restart/device/session boundaries. |
| History and saved vehicles | 0.25 | Local chat/job history and one local profile; no multi-vehicle or server history. |
| Basic settings | 0.25 | Scattered local controls; no coherent pilot settings/privacy/account management. |
| **Total** | **3.0 / 8 = 37.5%** | Provisional implementation estimate, not a PRD compliance score. |

Round this to **about 35–40% implemented**, with **high uncertainty (±15 percentage points)** until `docs/PRD.md` is supplied and the real P0 requirement weights and acceptance criteria are known. Only the deterministic backend safety slice is meaningfully validated; the complete pilot journey is 0% end-to-end validated.

## Readiness

| Dimension | Assessment |
| --- | --- |
| Source-grounded numeric safety | Promising prototype; preserve and harden. |
| Native iOS product | Visually substantial, but aimed at a glasses demo rather than phone-first pilot. |
| Identity and multi-tenancy | Not production-ready. |
| Conversation durability | Not production-ready. |
| Automotive data coverage/licensing | External blocker. ALLDATA access must not be assumed. |
| Test automation | Useful local suites, no CI, no XCTest target, current clean-host suite has two dependency-related failures. |
| Deployment/operations | Demo deployment only; no migration automation, release environments, monitoring, backup/restore proof, or incident controls. |
| TestFlight | Not ready: no phone-only audio path, real auth, privacy/retention package, release configuration, or full Xcode/device validation. |

## Recommended direction

Use a **modular monolith**, not microservices: one FastAPI deployment with explicit identity, vehicle, conversation, knowledge, ingestion/admin, and provider-adapter modules; one durable transactional store for users/vehicles/conversations; Qdrant only for reviewed evidence retrieval; and Vapi behind a replaceable voice-provider boundary. Keep Meta and vision as optional adapters that cannot block phone audio. Defer the SpacetimeDB shop workspace until the pilot proves a concrete multi-user need or adopt it deliberately as the primary durable store after a focused evaluation.

The first approved implementation milestone should establish a secure vertical slice: authenticated iOS onboarding, one durable confirmed vehicle, a phone-microphone Vapi conversation, one source-grounded lookup/refusal, durable conversation history, and CI around that slice. No cleanup should begin before the missing PRD and the decisions in [`09-OPEN-DECISIONS.md`](09-OPEN-DECISIONS.md) are resolved.
