# HackUTD 2026 engineering notes

- `backend/` is the working FastAPI + Qdrant/FastEmbed + LlamaParse backend. Preserve `/vapi-tool`, `/upload`, ingestion behavior, and the existing tests.
- Keep service-manual answers source-grounded. Never invent torque values, safety guidance, part numbers, or vehicle identity from an image.
- The native glasses client must follow Meta's official `CameraAccess` sample and current Meta Wearables Device Access Toolkit docs. Do not guess SDK names or lifecycle calls.
- Keep secrets, credentials, captured images, local Qdrant data, and parse caches out of commits.
- Make changes incrementally and run the narrowest relevant tests/build after each phase.

