# Carvis architecture

## Request flow

Meta glasses → native iPhone companion → JPEG/question + explicit vehicle → FastAPI → NVIDIA Nemotron visual context when needed → exact structured Qdrant filters → Python evidence/conflict validation → cited specification → app speech output.

The React console uses the same HTTP contract with a phone/browser JPEG fallback. The iOS capture lifecycle and audio routing remain in the existing Meta integration.

## Backend modules

- `ingest.py`: validates explicit CLI/manifest metadata, caches numbered LlamaParse pages by PDF SHA-256 and parser configuration, extracts pending records, embeds and stages.
- `spec_schema.py`: strict schema version 2, Decimal strings, source-cell/unit/variant validation and review digests.
- `schemas/specification-v2.json`: generated JSON Schema matching the Pydantic payload.
- `spec_extract.py`: conservative atomic row/variant extraction, warnings, split variant headers and ordered torque stages. Empty merged cells stay unavailable.
- `qdrant_v2.py`: staging collection/vector/index configuration and deterministic idempotent upserts. All embeddings are validated before writes. Existing source review decisions survive re-ingestion.
- `spec_retrieval.py`: request normalization, exact filters, complete scoped candidate evaluation, ranking, and deterministic speech formatting.
- `migrate_v2.py`: legacy backup, review exports, original-PDF-bound approval, acceptance validation, atomic alias activation and rollback.
- `main.py`: compatible FastAPI routes, Nemotron adapter, short-lived confirmed vehicle sessions and timings.
- `purge_db.py`: retired compatibility entry point; no deletion is performed.

## Data and provenance

Records include shop/year/make/model and optional trim/engine/transmission/market; component aliases, operation and specification type; numeric value or range, unit and raw cell; conditions/warnings/notes; PDF hash, filename, page, section, table, row, header, excerpt and parser/extraction metadata.

Unavailable values remain null. Both searchable text and original row evidence are retained; full parsed pages remain in the local content-hash cache. A transcription fallback must identify its transcriber and match the original PDF hash. It creates pending records, never verified answers.

OCR, including a visually plausible number, is pending review. An identified source reviewer compares applicability, values, units, warnings, source location, table spans and complete procedure stages against the original. Approval binds the entire evidence payload digest. Changes after review invalidate approval. This digest detects changes; it is not a cryptographic reviewer identity or proof that OCR is correct. Access to review tooling must be limited to trusted operators.

## Retrieval safety

1. Require explicit vehicle identity, or reuse a previously confirmed complete identity in the same shop/call. A partial vehicle change cannot inherit unrelated session fields.
2. Normalize supported component aliases and operation/specification/transmission intent. Conflicting explicit context requests clarification.
3. Exact-filter shop, year, make, model, component, operation, spec type, supplied variants, schema version and verified status.
4. Enumerate the complete matching scope up to 256 points. Overflows refuse for clarification. This prevents a conflicting record outside semantic top-k from being hidden.
5. Revalidate applicability, source cell and unit, review digest, source revisions and candidate conflicts in Python. Missing relevant variants ask for confirmation even when the documented values are equal.
6. Rank up to 16 exact-filtered candidates using the existing BAAI/bge-small-en-v1.5 embeddings (384 dimensions, Cosine). Similarity only chooses among previously validated evidence.
7. Format exact values in Python with actual citations. Ordered steps and warnings are preserved without voice-length truncation.

There is no cross-vehicle fallback, inferred vehicle identity, model-generated numerical answer or unit conversion. Unknown components/operations refuse or require explicit canonical context. The controlled vocabulary is intentionally limited; extending it requires evidence-backed records and tests.

## API contracts

`/vision-query` retains file/question/year/make/model/session_id. Optional form fields are shop_id, transmission, engine_code, trim, market, component, operation, spec_type. Success retains answer, vehicle, component and source, and adds sources/status/source_grounded/timings_ms. Refusals retain HTTP 404 with error/component and add a machine-readable status.

`/vapi-tool` accepts flat JSON, nested parameters, and existing Vapi tool-call shapes. Variants may be in structured fields or the question. It preserves results/toolCallId/result and adds source evidence. It never passes numeric answers through the legacy free-text torque formatter.

`/upload` stages pending records and returns HTTP 202. It no longer deletes a document before replacement. Background failures leave existing data intact. Large batch writes are not transactional: a network failure may leave additional pending points, but no old points are removed. Rerunning the same ingestion is safe.

## Nemotron and latency

A reused NVIDIA-compatible AsyncOpenAI client provides visual recognition with bounded timeouts and no repair-fact authority. Complete explicit requests skip unnecessary inference. Ambiguous requests can return a visual hypothesis for mechanic confirmation; hypotheses never become unconfirmed exact component filters.

Responses track inference, embedding, retrieval, verification and total milliseconds. An exact candidate scan adds a network round trip so hidden conflicts cannot be missed. Cold model startup, NVIDIA inference, and network latency are not covered by a sub-second guarantee.

## Deployment boundary

The legacy collection remains intact. New ingestion targets `carvis_specs_v2`; `carvis_specs_active` is the future stable alias. Mutating an aliased collection is forbidden by tooling. Build a new staging generation for updates.

The v2 application refuses legacy numeric answers until migration is complete. Do not deploy the changed backend alone while leaving production pointed at the legacy collection. Follow [the migration runbook](qdrant-v2-migration.md), validate original sources and acceptance cases, activate the alias, then configure/deploy the new backend. Keep the prior deployed application available for operational rollback. V2 rollback should use a previously validated v2 generation, never an unsafe fallback.

Secrets and images remain server-side/ephemeral. This change does not add SpacetimeDB or modify Meta SDK lifecycle calls.

