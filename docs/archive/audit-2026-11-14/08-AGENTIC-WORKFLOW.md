# Codex-oriented engineering workflow

## Current setup assessment

- Root `AGENTS.md` is concise and contains the most important safety invariants. Keep it.
- `.cursor/rules/project-context.mdc` largely duplicates root guidance. Duplication risks drift.
- `backend/spacetimedb/AGENTS.md` and `CLAUDE.md` formerly contained very large, nearly duplicated generic SpacetimeDB reference material rather than project-specific engineering instructions.
- `backend/spacetimedb/.cursor/rules/*`, `.windsurfrules`, and `.github/copilot-instructions.md` add more tool-specific instruction surfaces.
- There are no repository-local reusable Codex skills, planning templates, PR template, CODEOWNERS, CI workflows, or automated hooks visible.

The minimal professional setup should use a small hierarchy of project-specific `AGENTS.md` files plus ordinary scripts/CI. Do not install MCP servers or build autonomous orchestration for this project.

## Recommended instruction hierarchy

### Root `AGENTS.md`

Retain the current safety constraints and add only:

- Source of truth: approved `docs/PRD.md`, architecture decisions under `docs/adr/`, and API compatibility policy.
- Commands for clean install, backend tests, iOS pure checks/Xcode build, frontend build and Spacetime module build.
- Definition of done: tests actually run, validation class reported, no secret/source data committed.
- Change discipline: one vertical slice per PR; no feature plus broad cleanup; preserve dirty worktree.
- Security: authenticated tenant derived server-side; no proprietary source data in fixtures/logs; no production service/database mutation without explicit approval.

### `backend/AGENTS.md`

- Exact retrieval and reviewed-evidence invariants.
- Route compatibility for `/vapi-tool`, `/upload`, `/vision-query`.
- Unit/integration commands and fixture rules.
- Provider adapters must be faked in default tests; live/paid tests opt-in and labeled.
- Database migration/review/alias changes require runbook and approval.

### `ios/AGENTS.md`

- Phone-first v1; glasses are optional adapter.
- Official Meta sample/docs only for SDK calls.
- Main-actor/audio ownership rules and physical-device validation requirements.
- No secrets; Keychain for credentials; file protection for cache.
- Required unit/UI/device test classes and accessibility expectations.

### `backend/spacetimedb/AGENTS.md`

Replace generic copied manuals with short Carvis-specific rules: sender-derived identity, tenant-scoped views, deterministic reducers, generated binding command, local build/test command, and production publish prohibition without approval. Link to official docs rather than embedding hundreds of generic lines. Remove duplicate `CLAUDE.md` only after confirming no active tool requires it; otherwise make it a one-line pointer to `AGENTS.md`.

### `frontend/AGENTS.md`

State that the workspace is deferred, generated bindings policy, lockfile install/build command, token/security constraints, and no assumption it owns P0 identity/history.

## Reusable skills/workflows to add only when implementation begins

These should be small repository-local skills or scripts with deterministic inputs and no credentials:

1. **`carvis-backend-check`** — compile, targeted pytest, then full pytest; labels mocked versus live.
2. **`carvis-ios-check`** — pure Swift checks, plist lint, simulator build/test when Xcode exists, and a printed physical-test checklist.
3. **`carvis-source-review`** — validates source hash, evidence digest, reviewer identity and pending/verified transitions; never auto-approves.
4. **`carvis-qdrant-migration-check`** — read-only inventory/acceptance preview by default; alias mutation requires explicit human approval.
5. **`carvis-pr-review`** — diff-scoped security, regression, privacy and grounding checklist.

Do not create an “all-purpose Carvis agent” or remote automation with production credentials.

## Planning procedure

For any nontrivial change:

1. Cite PRD requirement IDs and acceptance criteria.
2. Identify affected trust boundaries, compatibility routes and data migrations.
3. List existing code/tests to retain and the narrowest new vertical behavior.
4. State validation layers: unit, contract, integration, device, live-provider, production.
5. Identify any paid/live/destructive step and wait for explicit approval.
6. Record a short ADR for identity/store/provider/schema choices that are hard to reverse.

Plans should fit in an issue or `docs/plans/<id>.md`; they should not become speculative architecture documents disconnected from a PR.

## Implementation procedure

1. Start from a cleanly identified branch; preserve unrelated local changes.
2. Add or tighten characterization tests before moving compatibility behavior.
3. Implement one vertical slice in small commits.
4. Run the narrowest test after each phase, then the component suite.
5. Never weaken a test, refusal, exact filter or review requirement to obtain green status.
6. Report commands and exact results; distinguish mock/local/device/live checks.
7. Update relevant docs/API schemas in the same PR.

## Independent review

Every P0 PR should receive two separate review passes, whether performed by people or bounded agents:

- **Security/privacy review:** authentication, authorization, tenant isolation, secret/token handling, logging, retention, upload abuse, provider data flow.
- **Grounding/regression review:** vehicle applicability, source/revision, numeric formatting, conflicts, procedures, compatibility routes, Qdrant staging/alias safety.

The implementer should not mark their own live/device/production validation as complete without captured evidence. Reviewers must use the diff and tests, not README claims.

## Testing expectations

| Layer | Default in PR | Notes |
| --- | --- | --- |
| Pure unit/state/schema | Required | Fast and deterministic. |
| API/contract with fakes/local store | Required for affected routes | No network or paid services. |
| Database migration/integration | Required for schema changes | Ephemeral local DB; test forward and rollback where supported. |
| iOS simulator/XCTest | Required for app changes | CI on macOS; does not prove audio/hardware. |
| Physical iPhone | Required for audio/release changes | Record device/OS/build and observed outcome. |
| Meta glasses | Required only for glasses changes | Follow official sample/current docs. |
| Live provider/Qdrant | Explicit opt-in | Approved credentials/cost/environment; never production mutation by default. |
| Source acceptance/evaluation | Required for knowledge scope | Reviewed, licensed evidence only. |

CI should use locked dependencies and include secret scanning, dependency review, backend suite, Swift pure checks, Xcode build/tests, frontend build, and Spacetime module build when those components change. Path filters may reduce cost but must not skip shared contract tests.

## Git and pull requests

- Branches: `feature/<issue>-<slug>`, `fix/<issue>-<slug>`, `docs/<issue>-<slug>`.
- Commits: imperative, scoped, no generated/cache/secret/source artifacts.
- PRs: one product slice; link requirement and issue; list risk, migrations, flags, rollback, tests with results, screenshots/device evidence where applicable.
- Require review for auth, schemas/migrations, knowledge safety, provider configuration, deployment and dependency changes.
- Never rewrite shared history or force-push a reviewed release branch without coordination.
- Releases: immutable tag, environment promotion, migration gate and documented rollback.

## Safe bounded delegation

Parallel work is appropriate only when files and decisions do not overlap. A lead must define for each delegate:

- exact objective and allowed paths;
- read-only versus edit authority;
- requirements and invariants;
- expected output/test command;
- prohibited live/production/destructive actions.

Good parallel tasks: read-only inventory, isolated test additions, independent security review, documentation validation. Bad parallel tasks: multiple agents editing `backend/main.py`, choosing architecture independently, changing shared schemas, alias operations, dependency upgrades, or resolving the same failing tests. The lead integrates, runs the complete relevant suite, and owns conflict resolution.

Access remains limited to this repository and explicitly authorized resources. Third-party proprietary or confidential materials are out of scope.
