# Carvis v2 implementation validation

Validated on 2026-11-07 (America/Chicago). No production alias or deployed service
configuration was changed. No cloud points or collections were deleted.

## Passed

- Backend regression suite: 59 tests, including the original 10 tests. Coverage
  includes WRX oil/filter capacities, transmission separation and clarification,
  wheel/camber isolation, wrong vehicles/shops, missing/conflicting evidence,
  ordered procedures, source review, duplicate/renamed source ingestion, content
  hash cache invalidation, parse/embedding/partial-write failures, alias cutover
  validation, Nemotron client reuse and compatible HTTP response contracts.
- Live re-ingestion of the same curated document preserved the 18-point staging
  count and all four existing source-review decisions.
- React frontend: TypeScript and Vite production build.
- Live Qdrant Cloud staging configuration: 384-dimensional Cosine collection,
  14 requested keyword indexes, schema-version integer index, search-text index.
- Live LlamaParse ingestion of the supplied WRX capacity PDF. OCR split the header
  and lost merged-cell applicability, so its initial records remained unverified.
  Explicit source transcription was used for the oil-change rows instead.
- Four curated oil-change records were compared directly with the rendered
  original PDF: 6MT/CVT × oil plus filter/oil only. The reviewer identity explicitly
  records **Codex agent: rendered original PDF comparison**; this is agent source
  review, not a claim of independent human signoff.
- Live acceptance suite: all 12 cases in
  `backend/tests/fixtures/wrx-acceptance.json` passed against Qdrant Cloud and the
  real FastEmbed model. Its expected values and source rows are bound to the
  original supplied PDF's SHA-256.
- In-process ASGI HTTP smoke checks with the real cloud database/model:
  `/vapi-tool` returned the cited 6MT oil/filter answer; `/vision-query` returned
  the cited CVT oil-only answer; wheel torque returned a 404 refusal.
  The vision request used a synthetic JPEG-signature fixture with an explicit
  question, so image inference was intentionally skipped. This does not test
  camera capture, image decoding by NVIDIA or physical audio output.
- Observed warm backend request times in that smoke run were about 107 ms for
  Vapi lookup and 93 ms for the explicit vision request. These exclude NVIDIA
  inference, speech recognition/synthesis, glasses transport and cold startup.

## Cloud state

- Original `george_specs`: **142 points**, green, unchanged; a full local vector/
  payload backup was exported to `.carvis_migration/legacy-backup.json`.
- `carvis_specs_v2`: **18 points**, green; **4 reviewed** oil-change records and
  **14 pending** OCR/earlier extraction records. Pending records cannot authorize
  answers. Superseded extractions were preserved rather than deleted.
- No alias has been created or switched. Production still uses its original
  deployment. `carvis_specs_active` cutover tooling is implemented and tested.
- Local acceptance report: `.carvis_migration/wrx-validation.json`. Review,
  transcription, cache and backup files are ignored by Git.

## Remaining deployment/source gates

- The correct original wheel-installation manual page is still needed for a
  positive wheel-fastener torque demo. The supplied wheel-height PDF contains
  suspension-height/camber material; it is not wheel-torque evidence. The
  disambiguation regression tests use clearly labeled synthetic fastener values.
- The remaining legacy corpus has not been source-reviewed/migrated. The verified
  staging scope is intentionally the four WRX oil-change variants. Choose and
  validate the intended production scope before switching the application.
- NVIDIA live image inference was not exercised in this validation; adapter parsing
  and reusable-client behavior were tested with mocked provider responses.
- Xcode build could not run: this host selects `/Library/Developer/CommandLineTools`
  and `xcodebuild` reports that full Xcode is required. Physical iPhone/Meta capture
  and audio routing therefore were not tested here. Native SDK code was unchanged.

For a local backend demonstration against the validated staging scope without
changing production, run:

```bash
cd backend
CARVIS_QDRANT_COLLECTION=carvis_specs_v2 ../.venv/bin/uvicorn main:app \
  --host 0.0.0.0 --port 8000
```

Use explicit year/make/model and transmission; say whether the filter is replaced.
The default legacy collection path deliberately returns `migration_pending` in
the new code. Follow [the migration runbook](../qdrant-v2-migration.md) for review,
production activation and rollback, rather than deploying this code with unchanged
legacy retrieval configuration.
