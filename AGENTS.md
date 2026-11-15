# Carvis engineering policy

Carvis is an iOS-only automotive intelligence product. The native SwiftUI application lives in
`ios/`; do not add a web product UI. `docs/PRD.md` is the product source of truth. FastAPI owns
trusted API/orchestration behavior, Qdrant holds reviewed knowledge evidence, and
`backend/spacetimedb/` is the retained server-side realtime module.

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
- Use automotive content only with documented rights. Do not access bondingAI repositories,
  credentials, schemas, confidential employer resources, or implementation details.

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

`backend/AGENTS.md`, `backend/spacetimedb/AGENTS.md`, and `ios/AGENTS.md` extend this policy.
