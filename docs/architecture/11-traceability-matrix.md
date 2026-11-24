# 11 — P0 traceability matrix

Requirement IDs are from [`../PRD.md`](../PRD.md); screens P01–P14 from the
[V1 contract §4](../product/v1-product-experience-contract.md). M2 PR references are in
[12-m2-roadmap.md](12-m2-roadmap.md).

Status reflects merged `main` as of 2026-11-24: Track B packages B1, B2a, B2b-1, B2b-2 and B2c are
merged (PRs #17, #19, #22, #24, #25). Rows are updated only
where merged tests cover part of the requirement. "Prototype" means today's legacy path behaves this
way with existing tests, not that the V1 design exists.

| Requirement | Screen | Entities | Endpoint | Test | PR | Status |
| --- | --- | --- | --- | --- | --- | --- |
| CAR-001 secure sign-in | P01 | users | identity provider; `GET /v1/me` | JWT validity matrix; Keychain persistence (device) | B2a, B2c | Partial: JWT verifier and matrix merged (B2a, `test_b2a_jwt.py`); `GET /v1/me` merged (B2c, `test_b2c_v1_api.py`, `test_b2c_v1_postgres.py`); Keychain is device-only, not started |
| CAR-002 profile, preferences | P12 | users | `/v1/me` | profile CRUD, tenant tests | B2 (package unassigned) | Not started |
| CAR-003 workspace | P12 | workspaces, memberships | `/v1/workspaces` | one personal workspace per user | B2b-1, B2c | Partial: tables and `ensure_principal` provisioning merged (B2b-1, `test_b2b1_identity.py`); `/v1/workspaces` merged (B2c, `test_b2c_v1_postgres.py`); iOS side not started |
| CAR-004 authorization | all | memberships, RLS | all | IDOR matrix, RLS-only test | B2b-1, B2b-2, B2c | Partial: forced RLS and session-context isolation merged (`test_b2b1_identity.py`, `test_b2b2_context.py`); B2c route tests cover cross-user isolation and ignored caller-supplied IDs on `/v1/me` and `/v1/workspaces` (`test_b2c_v1_postgres.py`); later routes' IDOR tests come with their packages |
| CAR-005 deletion | P12 | users and cascade | `DELETE /v1/me`, `/v1/me/export` | purge and export tests | B8 | Not started |
| CAR-010/011/012 VIN, decode, manual | P05 | vehicles | `/v1/vehicles`, `/decode` | VIN check-digit vectors, decode fake | B3 | Not started |
| CAR-013/016 confirm, unresolved details | P06 | vehicle_snapshots | `/confirm` | snapshot immutability | B3 | Not started |
| CAR-014/015 Garage, safe switching | P04 | vehicles, conversations | `/v1/vehicles`, new conversation on switch | switch invalidates conversation memory | B3, B4 | Not started |
| CAR-019 conversational vehicle identification (conditional V1 enhancement) | P04, P07 | vehicles (candidate only) | proposal tool; `/confirm` | proposal never creates a snapshot; model-claimed confirmation changes nothing | B5 if included (D-19) | Not started; conditional |
| CAR-020–026 voice | P07 | calls | `/calls`, bind, end, Vapi | `test_conversation.py` plus physical-device checks | B4, B5 | Not started |
| CAR-027 persistence | P07, P10 | conversations, calls, turns | `/v1/conversations` | restart-durability integration test | B4 | Not started |
| CAR-030–036 retrieval, verification, refusal | P08, P09 | evidence_* | webhook tool | `test_specs_v2.py`, `test_ride_height.py` unchanged | B7d, B7e | Prototype (legacy Qdrant path, tests exist) |
| CAR-033/037 evidence display | P08 | evidence_references | `GET /v1/turns/{id}` | revision-validity test | B6 | Not started |
| CAR-038 coverage | P02 | coverage_* | `/v1/coverage` | manifest vs Qdrant consistency | B7e | Not started |
| CAR-050–052 history | P10, P11 | conversations, turns | list and detail | cursor and scope tests | B6 | Not started |
| CAR-053/054 feedback | P13 | feedback | `/feedback` | tenant and idempotency tests | B6 | Not started |
| CAR-041 spoken output preserves approved facts, units, qualifications, refusals | P07, P08 | answers, evidence_references | webhook tool, controlled delivery path or blocked technical voice | staging real-speech checks (D-9, live call needs approval), physical-device checks | B5, B7e, M5 | Not started (release gate D-14) |
| CAR-043 selected complete reviewed procedures | P08 | procedures, steps | webhook tool | 07 serve-time requirements 1 and 3 (complete procedures), acceptance requirements; incomplete refusal tests | B7a–e | Prototype (procedure completeness in legacy path) |
| CAR-042 known-issue, TSB and recall discovery (conditional V1 enhancement) | P08 | manufacturer communications | webhook tool | rights-cleared or labeled synthetic cases (R3) | B7a–e if included (D-18) | Not started; conditional |
| Brain lifecycle (rights, review, projection, withdrawal, restore) | none | evidence_*, review decisions, control collection | internal CLI/API | 07 cases 1–12, serve-time acceptance requirements and F1–F3 (protocol cases per D-13) | B7a–c, B7f | Not started |
| CAR-060/061 vision, glasses preserved | none | none | `/v1/vision/query` | existing vision tests | B9 | Prototype (preserved) |

Security blockers from the historical audit map to: sessions and tokens (B2, B4, B5), unauthenticated
endpoints (A2, A3, B9), fail-open webhook (A1), transactional store and local JSON authority (B2–B4),
retention (B8), monitoring (B10), SpacetimeDB (B9), source rights (M3 gate G11).
