# Carvis Qdrant v2 configuration and migration

## Deployment gate

Keep the existing `george_specs` collection intact. That name is a legacy external
identifier retained for compatibility. The new code refuses numeric answers from
that collection with `migration_pending`; it does not silently run unsafe legacy
retrieval. **Do not deploy the changed backend independently of a validated v2
configuration.** Leave the currently deployed application running during staging.

No collection deletion, reset, payload deletion, or automatic alias activation is
part of ingestion. `purge_db.py` is disabled. Source review is an operator task:
the review flag records an explicit original-document comparison; it cannot prove
that an operator actually performed that comparison.

## Qdrant Cloud checklist

- Retain the original collection and its points; export an offline backup.
- Create an unaliased `carvis_specs_v2` collection, or a new generation such as
  `carvis_specs_v2_next` when updating a previously activated collection.
- Dense unnamed vectors: **384**, **Cosine**, embedding model
  **BAAI/bge-small-en-v1.5**. Do not mix other embeddings in this collection.
- Keyword indexes: `shop_id`, `year`, `make`, `model`, `document_ref`, `component`,
  `spec_type`, `operation`, `transmission`, `record_kind`, `verification_status`,
  `engine_code`, `trim`, `market`.
- Integer index: `schema_version`.
- Full-text index: `search_text`. For a server without text-index support, use
  `--no-full-text`. Retrieval does not depend on full-text matching.
- Keep year as a four-digit **string** consistently in the payload and filters.
- Keep source rows, full raw values, warnings, provenance and review metadata in
  payloads without indexing every evidence field.
- Verify collection health, vector configuration, index types and point counts.
- Test answers and refusals against reviewed original-source acceptance cases.
- Activate `carvis_specs_active` only after validation; keep the former collection
  for rollback. Future ingestion must target a new unaliased generation.

These index and alias operations follow the [Qdrant index documentation](https://qdrant.tech/documentation/manage-data/indexing/)
and [atomic collection alias documentation](https://qdrant.tech/documentation/manage-data/collections/).

## 1. Prepare and back up

Commands below run from the repository root with existing server credentials in
`backend/.env`. No credential values belong in commands, logs or committed files.

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python backend/migrate_v2.py export-legacy \
  --output .carvis_migration/legacy-backup.json
.venv/bin/python backend/qdrant_v2.py --collection carvis_specs_v2
```

The export includes vectors and payloads and does not modify the legacy source.
Backup and review directories are ignored by Git.

## 2. Ingest original PDFs with explicit applicability

Use the original manuals, not a legacy-chunk promotion: those chunks lack enough
provenance and atomic applicability to become verified records safely.

```bash
.venv/bin/python backend/ingest.py /absolute/path/manual.pdf \
  --year 2022 --make subaru --model wrx --shop-id shop_demo \
  --collection carvis_specs_v2 --export-dir .carvis_review
```

Optional flags: `--transmission`, `--engine-code`, `--trim`, `--market`,
`--force-parse`, `--premium`. Do not specify a variant unless the document really
applies to it. Source transmission columns become separate records. An uploader
restriction never relabels another source variant.

For batch ingestion, create a local JSON manifest:

```json
{
  "documents": [
    {
      "path": "manual-a.pdf",
      "shop_id": "shop_demo",
      "year": "2022",
      "make": "subaru",
      "model": "wrx",
      "document_ref": "wrx-capacity"
    },
    {
      "path": "manual-b.pdf",
      "shop_id": "shop_demo",
      "year": "2023",
      "make": "subaru",
      "model": "wrx",
      "transmission": "6mt"
    }
  ]
}
```

```bash
.venv/bin/python backend/ingest.py --manifest /absolute/path/manifest.json \
  --collection carvis_specs_v2 --export-dir .carvis_review
```

Paths resolve relative to the manifest; all paths and vehicle metadata are checked
before paid parsing starts. Optional missing source values stay null. Required
vehicle fields have no production defaults. Parser cache keys include PDF bytes,
SDK/parser versions, prompt, tier and options. Pin `CARVIS_PARSER_VERSION` to a
supported release in production; `latest` can change remotely, so refresh parsing
when intentionally upgrading it. New extraction versions produce new records.

Embedding/parse failures never delete old data. A failed batch can leave additional
pending points if a network error occurs after some upserts; rerunning is safe.
Identical content/extraction/applicability produces deterministic point IDs, with
existing review decisions and original stored provenance preserved.

## 3. Repair OCR through an explicit source transcription

Never copy a populated 6MT cell into an empty CVT cell solely because OCR left it
blank. Inspect the original PDF: a blank, a dash and a merged cell are different.

For difficult scans, provide local page evidence:

```json
{
  "pdf_sha256": "REPLACE_WITH_ORIGINAL_PDF_SHA256",
  "transcribed_by": "identified source transcriber",
  "pages": [{
    "page": 1,
    "table_row_offsets": {"1": 2},
    "markdown": "SOURCE-FAITHFUL MARKDOWN TRANSCRIPTION"
  }]
}
```

`table_row_offsets` is optional. If table 1 omits two preceding original data rows,
offset 2 preserves the actual original row numbers in citations. Include headings,
units, variant headers, warnings and footnotes that apply to the extracted rows.
Use complete table transcription wherever practical. Repeated values are permitted
only when the original source explicitly spans those variants.

```bash
.venv/bin/python backend/ingest.py /absolute/path/manual.pdf \
  --year 2022 --make subaru --model wrx --shop-id shop_demo \
  --page-evidence /absolute/path/page-evidence.json \
  --export-dir .carvis_review/curated
```

The supplied PDF hash is checked. A manifest entry may also specify a
`page_evidence` path. This fallback is explicitly identified in parser metadata and
still creates **pending-review** records. It never bypasses review.

## 4. Review original evidence

```bash
.venv/bin/python backend/migrate_v2.py export-review \
  --collection carvis_specs_v2 --output .carvis_review/all-records.json
```

Create a local JSON array selecting only records checked against the original PDF.
Check vehicle applicability, original page/section/table/row, exact variant column,
operation, quantity/unit, conditions/warnings, and complete ordered procedure steps.
Unknown components and missing cells are not approvable. Records from superseded
extractions should remain pending/rejected; do not approve conflicting revisions.

```bash
.venv/bin/python backend/migrate_v2.py review \
  --collection carvis_specs_v2 --records .carvis_review/selected-records.json \
  --source /absolute/path/manual.pdf --reviewer source-reviewer-name \
  --confirm-source-reviewed
```

Review checks the original PDF hash/filename, existing exact evidence, numeric cell,
unit, variant-column alignment and required source locations before updating review
status. It binds approval to the full evidence digest. It does not trust a manually
set status alone. Editing an exported record requires re-staging exact corrected
evidence (for example, by correcting the transcription and re-ingesting) before approval.

## 5. Validate acceptance cases

Create a local suite with positive cases for **every verified applicability and
operation scope**, plus unsupported/conflicting/ambiguous cases. A successful
case must include the actual source hash, location, quantity/unit and applicability:

```json
[
  {
    "name": "WRX 6MT oil plus filter",
    "vehicle": {"shop_id":"shop_demo","year":"2022","make":"subaru","model":"wrx"},
    "query": "engine oil capacity with filter 6MT",
    "expected": {
      "component":"engine_oil","operation":"oil_and_filter",
      "spec_type":"fluid_capacity","transmission":"6mt",
      "numeric_value":"4.5","unit":"L","source_file":"wrxOilAmount.pdf",
      "source_page":1,"source_document_hash":"REPLACE_WITH_ORIGINAL_PDF_SHA256"
    }
  },
  {
    "name":"Missing transmission",
    "vehicle":{"shop_id":"shop_demo","year":"2022","make":"subaru","model":"wrx"},
    "query":"engine oil capacity with filter",
    "refusal":"clarification"
  }
]
```

Add oil-only and CVT cases, incorrect year/model, missing operation, and unavailable
wheel-fastener torque. When wheel installation evidence becomes available, add
its positive case and a camber-only negative case. For procedures, `expected` is an
ordered array of per-stage expected objects, including `step_order`/`step_count`.

The supplied oil PDF already has a source-bound 12-case suite at
`backend/tests/fixtures/wrx-acceptance.json`. It is ready for use once those four
records have been reviewed. Its source hash must match the actual PDF; update the
suite through source review if the source changes. It intentionally expects a
wheel-torque refusal until that installation source has been supplied and reviewed.

```bash
.venv/bin/python backend/migrate_v2.py validate --collection carvis_specs_v2 \
  --suite .carvis_review/acceptance.json --output .carvis_migration/validation.json
```

Validation fails for no reviewed data, bad vector/index configurations, invalid
evidence/IDs, conflicts, incomplete procedures, unsupported answers or uncovered
verified scopes. The report binds the current collection inventory and suite.

## 6. Activate and deploy

Pause staging writers during validation/cutover. Tooling refuses writes to aliased
collections, but Qdrant does not provide an alias compare-and-swap lock against
external operators; coordinate deployment and limit direct write access.

```bash
.venv/bin/python backend/migrate_v2.py activate --collection carvis_specs_v2 \
  --suite .carvis_review/acceptance.json --output .carvis_migration/activation.json
```

Activation reruns acceptance validation immediately, checks the inventory again,
and atomically updates the stable alias. For a subsequent migration, pass
`--expected-previous carvis_specs_v2` with the currently inspected alias target.

Only then set `CARVIS_QDRANT_COLLECTION=carvis_specs_active` in the backend
deployment and restart/deploy the changed application. Set
`CARVIS_INGEST_COLLECTION=carvis_specs_v2_next` for future uploads/ingestion. Never
point uploads at the activated collection. Retain the existing cloud credentials.

Smoke-test Vapi with explicit metadata/variants and the configured secret header;
test `/vision-query` success/refusal contracts and actual app speech. Source evidence
must remain visible, and refusals must not become numeric answers downstream.

## Rollback

Keep the activation report, previous validated v2 collection and its acceptance
suite. Roll back by running the same `activate` command against that previous
collection with `--expected-previous` set to the current target. It validates the
rollback target and performs another atomic alias switch. No points are deleted.

Before the first v2 activation, rollback means leaving production unchanged. The
old deployed application remains available for operational recovery; reverting an
application deployment does not make its legacy retrieval safe. The new backend
will deliberately refuse when pointed at legacy unverified chunks.
