# Repository consolidation report

**Date:** 2026-11-14
**Branch:** `chore/repository-consolidation`
**Starting commit:** `39b9a7f` (`main`)
**Scope:** cleanup and consolidation only; no new product features or production changes

## Result

Carvis now has one user-facing application: the native SwiftUI app. The obsolete React/Vite
application and its browser-only generated bindings are removed. FastAPI, Qdrant verification and
migration protections, Vapi, Nemotron, Meta Wearables work, and the future-facing SpacetimeDB
module remain in place.

No production service, Qdrant collection, alias, Vapi assistant, or SpacetimeDB database was
contacted or modified.

## Final directory tree

```text
.
├── AGENTS.md
├── Procfile
├── README.md
├── backend/
│   ├── main.py, conversation.py
│   ├── spec_schema.py, spec_extract.py, spec_retrieval.py
│   ├── ingest.py, qdrant_v2.py, migrate_v2.py, purge_db.py
│   ├── vapi_assistant.py, vapi/
│   ├── schemas/
│   ├── tests/
│   └── spacetimedb/
│       ├── AGENTS.md, CLAUDE.md
│       ├── spacetime.json, spacetime.local.json
│       └── module/
│           ├── src/index.ts
│           ├── package.json, package-lock.json
│           └── tsconfig.json
├── docs/
│   ├── PRD.md
│   ├── REPOSITORY-CONSOLIDATION.md
│   ├── audit/
│   ├── backend/
│   └── ios/
├── ios/
│   ├── Carvis/
│   └── Tests/
├── render.yaml
├── requirements.txt
└── runtime.txt
```

The removed `frontend/` directory is intentionally absent.

## Removed files and directories

### Obsolete React/Vite frontend

The entire `frontend/` directory was removed. Its exact tracked files were:

- `frontend/.env.example`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tsconfig.json`
- `frontend/tsconfig.app.json`
- `frontend/vite.config.ts`
- `frontend/src/App.tsx`
- `frontend/src/main.tsx`
- `frontend/src/spacetimeClient.ts`
- `frontend/src/styles.css`
- `frontend/src/vite-env.d.ts`
- `frontend/src/module_bindings/index.ts`
- `frontend/src/module_bindings/types.ts`
- `frontend/src/module_bindings/types/procedures.ts`
- `frontend/src/module_bindings/types/reducers.ts`
- `frontend/src/module_bindings/accept_invite_reducer.ts`
- `frontend/src/module_bindings/decline_invite_reducer.ts`
- `frontend/src/module_bindings/invite_worker_reducer.ts`
- `frontend/src/module_bindings/join_shop_by_code_reducer.ts`
- `frontend/src/module_bindings/record_shop_query_result_reducer.ts`
- `frontend/src/module_bindings/register_or_update_profile_reducer.ts`
- `frontend/src/module_bindings/remove_shop_worker_reducer.ts`
- `frontend/src/module_bindings/revoke_invite_reducer.ts`
- `frontend/src/module_bindings/start_shop_query_reducer.ts`
- `frontend/src/module_bindings/my_profile_table.ts`
- `frontend/src/module_bindings/my_shop_table.ts`
- `frontend/src/module_bindings/shop_call_results_table.ts`
- `frontend/src/module_bindings/shop_calls_table.ts`
- `frontend/src/module_bindings/shop_members_table.ts`
- `frontend/src/module_bindings/visible_invites_table.ts`

These generated bindings had no consumer outside the deleted browser application. The canonical
SpacetimeDB schema and reducers remain under `backend/spacetimedb/module/`.

### Duplicate configuration and browser-only backend support

- `backend/Procfile` — duplicated the root Procfile for a deployment layout not used by
  `render.yaml`.
- `backend/runtime.txt` — byte-identical duplicate of root `runtime.txt`.
- FastAPI wildcard `CORSMiddleware` configuration — existed for browser access and is not needed
  by native iOS, Vapi webhooks, or server integrations.
- Frontend-specific ignore patterns in `.gitignore`.

The pre-existing working-tree deletion of `backend/.env.example` was preserved. It was not
deleted by this cleanup.

### Duplicated agent reference material

Removed generic duplicated Cursor rules:

- former SpacetimeDB component Cursor rules: `cli.mdc`, `concepts.mdc`, and
  `typescript-server.mdc`

They were replaced with the scoped `carvis-spacetime.mdc` pointer. The 713-line copies in
`backend/spacetimedb/AGENTS.md`, `CLAUDE.md`, `.windsurfrules`, and Copilot instructions were replaced
with one concise canonical module guide plus small tool-specific pointers.

## Reorganized and updated files

The retained SpacetimeDB runtime was grouped under `backend/spacetimedb/`, while its independent
TypeScript module remains in `backend/spacetimedb/module/`. The native SwiftUI application remains
in `ios/`; there is no web frontend. This preserves Swift project, Python import, deployment, and
SpacetimeDB runtime boundaries without conflating server code with UI.

- `README.md` is now the primary repository entry point and describes the native-iOS-only
  architecture, safety model, setup, tests, limitations, and documentation map.
- `docs/backend/architecture.md` distinguishes current glasses-first implementation from the approved
  phone-first target and records the retained SpacetimeDB boundary.
- `docs/ios/README.md` identifies iOS as the only user-facing application and accurately labels the
  current glasses-first prototype.
- `docs/backend/testing-demo.md` no longer references browser controls.
- `docs/backend/validation-qdrant-v2.md` retains the old web build only as dated historical evidence.
- `docs/audit/README.md` marks the detailed audit as a pre-consolidation historical snapshot and
  points to the PRD/current architecture.
- `AGENTS.md` and `backend/spacetimedb/AGENTS.md` now carry the canonical repository and component rules.
- `render.yaml` no longer describes a backend/frontend split.

## Dependencies

Removed with `frontend/package.json` and its lockfile:

- React and React DOM
- Vite and the React Vite plugin
- browser-side TypeScript/type packages
- the browser SpacetimeDB client dependency and generated bindings

The SpacetimeDB server module retains its independent pinned `spacetimedb` and TypeScript
dependencies.

`httpx>=0.27.0` was added as an explicit backend dependency because retained FastAPI-to-
SpacetimeDB telemetry imports it directly. It had previously been available only transitively.

## Preserved functionality and protections

- FastAPI routes including `/vapi-tool`, `/upload`, `/vision-query`, and conversation/camera
  endpoints.
- Vapi assistant configuration and exact grounded tool responses.
- Nemotron visual adapter and its prohibition on vehicle/specification authority.
- Meta Wearables camera, speech, wake, and audio-route work.
- Camera command correlation, deadlines, duplicate handling, and stale-result rejection.
- Qdrant v2 schema, exact applicability filters, conflict detection, review digests, deterministic
  numeric formatting, staging-only writes, migration validation, alias activation/rollback code,
  and the legacy collection boundary.
- PDF parsing/extraction and pending-review ingestion behavior.
- Existing backend and pure Swift tests.
- Simulated/guided native components whose PRD disposition is not safe to decide during cleanup.

Legacy internal backend helpers with no current in-repository caller were retained because their
external compatibility status is uncertain and tests still characterize related behavior. They
should be revisited only with a route/consumer deprecation decision, not deleted speculatively.

## SpacetimeDB status

`backend/spacetimedb/module/src/index.ts`, its package/lock/TypeScript configuration, shop/user/
invitation/query schemas, sender-derived authorization, views, and reducers are intact. No browser
bindings remain. Native iOS integration was not implemented.

`npm ci` installed the pinned local dependencies, and `./node_modules/.bin/tsc --noEmit` passed.
`npm run build` could not execute because the separate `spacetime` CLI is not installed. No publish
or database command ran.

## Validation results

| Check | Before cleanup | After cleanup |
| --- | --- | --- |
| Backend suite in ambient Python | 112 passed, 2 failed (`openai` missing) | Same result before dependency installation; no cleanup regression |
| Backend suite in clean Python 3.12 `.venv` | Not available | **114 passed**, 1 local-Qdrant warning |
| Conversation state machine | 66 checks passed | **66 checks passed** |
| Wake phrase matcher | 29 checks passed | **29 checks passed** |
| Python compilation | Passed | **Passed** |
| plist/entitlement/project lint | Passed | **Passed** |
| SpacetimeDB TypeScript | Not run | **`tsc --noEmit` passed** |
| SpacetimeDB CLI build | Not run | Blocked: `spacetime` CLI not installed |
| React frontend build | Blocked: dependencies absent | Removed by approved product decision |
| Xcode build | Blocked | Blocked: Command Line Tools selected; full Xcode unavailable |
| Python dependency consistency | Not run | **`pip check` passed** in Python 3.12 `.venv` |
| Local Markdown links | Not run | **Passed** after removing historical links to deleted frontend files |
| Structural checks | N/A | Frontend absent; root deploy files, iOS, SpacetimeDB, Qdrant migration files present |

The local Qdrant warning states that payload indexes have limited effect in embedded Qdrant; it
does not indicate a failed test. No hardware, live provider, cloud database, or TestFlight claim
is made.

## Remaining warnings and blockers

1. `docs/PRD.md` is version 1.0 **Draft for Review**; approval and open technical/business
   decisions remain necessary.
2. Production identity, tenant authorization, durable conversation state, phone-first audio,
   history, and TestFlight release work are intentionally not implemented by this cleanup.
3. Authorized automotive data rights and pilot coverage remain critical external dependencies.
4. Full Xcode, simulator/app build, archive, signing, and physical iPhone validation remain
   unavailable in this environment.
5. The SpacetimeDB CLI/module build and authorization integration tests remain to be established.
6. Python dependencies use broad lower bounds rather than a committed reproducible lock.
7. `backend/.env.example` remains deleted as pre-existing user work; README documents required
   variable names without restoring it.
8. Historical audit files describe the pre-consolidation repository and are explicitly labeled.

## Recommended next milestone

Proceed only after PRD approval and the identity, durable store, data-rights, and Vapi privacy
decisions are made. The next implementation milestone should be the PRD's first secure vertical
slice: authenticated native onboarding, one durable confirmed vehicle, explicitly initiated
iPhone audio, one source-grounded lookup/clarification/refusal, durable history, and CI—while
preserving the existing verification engine and keeping glasses/vision optional.

## Final organization milestone

The subsequent organization pass established exactly four engineering instruction scopes:
`AGENTS.md`, `backend/AGENTS.md`, `backend/spacetimedb/AGENTS.md`, and `ios/AGENTS.md`. Unsupported
Claude, Cursor, Windsurf, and Copilot compatibility files were removed. Historical audits, this
consolidation record, the architecture inventory, and dated Qdrant validation were moved under
`docs/archive/`; active PRD, backend runbooks, and iOS procedures remain outside the archive.
`scripts/verify.sh` is the canonical local baseline. No application behavior or production resource
was changed by that final pass.
