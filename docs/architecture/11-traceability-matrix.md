# 11 — P0 traceability matrix

Requirement IDs are from [`../PRD.md`](../PRD.md); screens P01–P14 from the
[V1 contract §4](../product/v1-product-experience-contract.md). M2 PR references are in
[12-m2-roadmap.md](12-m2-roadmap.md).

| Requirement | Screen | Entities | Endpoint | Test | PR |
| --- | --- | --- | --- | --- | --- |
| CAR-001 secure sign-in | P01 | users | identity provider; `GET /v1/me` | JWT validity matrix; Keychain persistence (device) | B2 |
| CAR-002 profile, preferences | P12 | users | `/v1/me` | profile CRUD, tenant tests | B2 |
| CAR-003 workspace | P12 | workspaces, memberships | `/v1/workspaces` | one personal workspace per user | B2 |
| CAR-004 authorization | all | memberships, RLS | all | IDOR matrix, RLS-only test | B2 |
| CAR-005 deletion | P12 | users and cascade | `DELETE /v1/me`, `/v1/me/export` | purge and export tests | B8 |
| CAR-010/011/012 VIN, decode, manual | P05 | vehicles | `/v1/vehicles`, `/decode` | VIN check-digit vectors, decode fake | B3 |
| CAR-013/016 confirm, unresolved details | P06 | vehicle_snapshots | `/confirm` | snapshot immutability | B3 |
| CAR-014/015 Garage, safe switching | P04 | vehicles, conversations | `/v1/vehicles`, new conversation on switch | switch invalidates conversation memory | B3, B4 |
| CAR-020–026 voice | P07 | calls | `/calls`, bind, end, Vapi | `test_conversation.py` plus physical-device checks | B4, B5 |
| CAR-027 persistence | P07, P10 | conversations, calls, turns | `/v1/conversations` | restart-durability integration test | B4 |
| CAR-030–036 retrieval, verification, refusal | P08, P09 | evidence_* | webhook tool | `test_specs_v2.py`, `test_ride_height.py` unchanged | B7 |
| CAR-033/037 evidence display | P08 | evidence_references | `GET /v1/turns/{id}` | revision-validity test | B6 |
| CAR-038 coverage | P02 | coverage_* | `/v1/coverage` | manifest vs Qdrant consistency | B7 |
| CAR-050–052 history | P10, P11 | conversations, turns | list and detail | cursor and scope tests | B6 |
| CAR-053/054 feedback | P13 | feedback | `/feedback` | tenant and idempotency tests | B6 |
| CAR-060/061 vision, glasses preserved | none | none | `/v1/vision/query` | existing vision tests | B9 |

Security blockers from the historical audit map to: sessions and tokens (B2, B4, B5), unauthenticated
endpoints (A2, A3, B9), fail-open webhook (A1), transactional store and local JSON authority (B2–B4),
retention (B8), monitoring (B10), SpacetimeDB (B9), source rights (M3 gate G11).
