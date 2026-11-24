# Carvis engineering policy

Carvis is an iOS-only automotive intelligence product. The native SwiftUI application lives in
`ios/`; do not add a web product UI. `docs/PRD.md` is the product source of truth. FastAPI owns
trusted API/orchestration behavior, PostgreSQL is the designated single transactional store
(`docs/decisions/0001-single-store-postgresql.md`), Qdrant holds reviewed knowledge evidence, and
`backend/spacetimedb/` currently receives only best-effort telemetry (its retirement is proposed in
`docs/decisions/0007-retire-spacetimedb.md`).

## Documentation authority

Start at `docs/README.md`. `docs/PRD.md` defines product requirements;
`docs/product/v1-product-experience-contract.md` defines the approved V1 pilot scope (its open
decisions, such as D-12, stay unresolved until a record in `docs/decisions/` resolves
them); `docs/audits/` holds dated historical snapshots, so verify current behavior against code and
tests. Terminology: V1 is the pilot technician's field-test release; M1–M5 are the engineering milestones
leading to it, not product versions; P0 is mandatory in V1 and P1–P3 are post-V1 priorities with no
assigned version (definitions in `docs/README.md`). Link to these documents; do not restate them here.

## Safety and trust

- Technical answers require a confirmed vehicle, exact applicability, reviewed source evidence,
  provenance, units, conditions, and complete procedure stages. Similarity, model confidence, OCR,
  or an image is never proof.
- Never invent unsupported numerical specifications, part numbers, warnings, procedures, or
  vehicle identity. Refuse or clarify when evidence is insufficient or conflicting.
- Derive user and tenant authority from an authenticated principal. Never authorize with a
  caller-supplied user, shop, vehicle, or session identifier.
- Keep secrets, credentials, raw audio, transcripts, captured images, personal/shop/vehicle data,
  local Qdrant data, manuals, caches, and review exports out of commits and logs.
- Use automotive content only with documented rights. Do not access, copy, transfer, or
  reuse third-party proprietary source code, data, schemas, credentials, or other confidential
  information without explicit written authorization from its owner.

## Protected boundaries

- Preserve `/vapi-tool`, `/upload`, `/vision-query`, conversation/camera contracts, ingestion,
  Vapi, Nemotron, and Meta Wearables behavior unless a scoped change explicitly migrates them.
- Ingestion writes pending-review v2 records only to unaliased staging. Never auto-verify OCR,
  mutate an alias, weaken evidence checks, fall back across vehicles, or change the legacy
  collection outside `docs/backend/qdrant-v2-migration.md`.
- Meta work follows the official CameraAccess sample and current Device Access Toolkit docs.
  Nemotron provides optional visual context, never vehicle or repair-fact authority.
- Do not publish SpacetimeDB, contact paid/live providers, alter cloud resources, or mutate
  production services/databases without explicit approval.

## Engineering discipline and definition of done

- Preserve intentional working-tree changes. Make small, reviewable changes and run the narrowest
  relevant tests first. Separate mocked, local, simulator, physical-device, live, and production
  validation in reports.
- Use Carvis in new code, UI, docs, and logs; retain legacy external identifiers only for
  compatibility. Do not combine broad cleanup with feature work.
- Do not commit, push, rewrite history, or perform destructive Git operations without approval.
- A change is done only when behavior and failures are tested, contracts/docs are updated,
  safety/privacy/tenant boundaries remain intact, checks actually ran, unavailable validation is
  stated, and no secret or generated local data is included. Use `scripts/verify.sh` for the full
  repository baseline when warranted.

## Agent workflow

Coordinated agent work follows `docs/development-workflow.md` ("Agent workflow"): roles, task
contracts, risk tiers, the review protocol, and tested worker launch profiles. For every agent and
model:

- Dispatch is not authorization. Commit, push, and pull-request creation need the owner's approval,
  recorded in the task contract or given by invoking `/carvis-continue`.
- Review only committed candidates, through `scripts/review-scope.sh`. Any change to the candidate
  makes earlier reviews stale, except a clean update from `origin/main` that the script shows
  touches no task file and brings in no T3+ file.
- Risk tiers only add requirements; only the owner lowers a tier.
- Autonomous review is budgeted by tier (`docs/development-workflow.md`, "Review budget, findings and stopping").
  Only blocking findings are corrected within a task. On an exhausted budget or any stopping
  condition, stop and escalate to the owner. A budget never waives a mandatory gate.
- Workers never dispatch other workers, create branches or worktrees the coordinator owns, answer
  another agent's permission prompts, or edit outside their assigned worktree.
- A Git worktree, an agent's plan mode, and written instructions are not security boundaries; only
  operating-system sandboxes and GitHub protections enforce anything.

`backend/AGENTS.md`, `backend/spacetimedb/AGENTS.md`, and `ios/AGENTS.md` extend this policy.
