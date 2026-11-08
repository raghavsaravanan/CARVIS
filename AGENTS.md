# Carvis engineering notes

- `backend/` is the working FastAPI + Qdrant/FastEmbed + LlamaParse backend. Preserve `/vapi-tool`, `/upload`, ingestion behavior, and the existing tests.
- Keep service-manual answers source-grounded. Never invent torque values, safety guidance, part numbers, or vehicle identity from an image.
- The native glasses client must follow Meta's official `CameraAccess` sample and current Meta Wearables Device Access Toolkit docs. Do not guess SDK names or lifecycle calls.
- Keep secrets, credentials, captured images, local Qdrant data, and parse caches out of commits.
- Make changes incrementally and run the narrowest relevant tests/build after each phase.
- Use Carvis in new code, documentation, UI, and logs; retain legacy external identifiers only for compatibility.
- Ingestion writes pending-review v2 records to staging. Never auto-verify OCR or mutate an aliased collection.
- Numeric answers require exact applicability, reviewed source evidence, complete procedure stages, and deterministic validation. Never use similarity as proof or fall back across vehicles.
- Keep the legacy cloud collection intact. Follow `docs/qdrant-v2-migration.md` before deployment or alias changes.

