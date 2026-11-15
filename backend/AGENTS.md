# Backend engineering rules

These rules extend the repository `AGENTS.md` for `backend/`.

- Keep `main.py` as the compatible FastAPI entry point. Routes validate typed inputs and delegate
  domain/provider work instead of adding new global state.
- Preserve existing status codes and shapes for `/vapi-tool`, `/upload`, `/vision-query`, and
  conversation/camera endpoints unless a versioned migration is approved.
- Authentication establishes the principal; authorize every protected read/write server-side.
  Caller-provided tenant fields are untrusted input.
- Qdrant ranking occurs only after exact applicability filters. Python verification enforces
  reviewed evidence, conflicts, digests, variants, and complete procedures.
- Conversation/provider adapters never manufacture technical facts. Give Vapi, Nemotron,
  LlamaParse, and future providers bounded contracts, timeouts, and explicit failures.
- Default tests use mocks/local stores and never contact paid providers or cloud databases. Live
  checks are explicit opt-in and labeled.
- Run `.venv/bin/python -m pytest backend/tests -q` and
  `.venv/bin/python -m compileall -q backend` (or the configured equivalent). Follow
  `docs/backend/qdrant-v2-migration.md` for review, collections, aliases, activation, and rollback.
