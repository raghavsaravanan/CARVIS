# Backend expansion plan

This plan broadens George after the Subaru WRX baseline is tested. The current retrieval and safety behavior stays intact while each capability is added behind focused tests.

## Baseline to protect

- Preserve `/vapi-tool`, `/upload`, `/health`, and `/vision-query`.
- Keep Qdrant as the manual retrieval source of truth.
- Keep Nemotron limited to visual component context.
- Never infer vehicle identity from an image.
- Never generate a torque value, warning, part number, or procedure without retrieved manual evidence.
- Refuse when the matching manual or variant is unavailable.
- Keep images temporary and secrets server-only.

## Phase B1 — Subaru ingestion and evidence baseline

Goal: establish a repeatable test set using the 2022 Subaru WRX manual.

Tasks:

1. Ingest the permitted PDF as `2022 / subaru / wrx`.
2. Confirm collection creation, point count, and payload metadata.
3. Build a small golden-question set from the manual: torque, fluid, clearance, warning, and unsupported questions.
4. Record the expected section and answer for each question.
5. Test exact vehicle match, wrong vehicle, missing manual, and ambiguous request behavior.
6. Measure retrieval latency and answer latency.

Acceptance: every supported answer cites the correct manual evidence, and unsupported questions refuse safely.

## Phase B2 — Page-aware and hierarchical ingestion

Goal: make answers auditable and improve retrieval on a large factory manual.

Add metadata to every chunk:

```text
document_ref
page_number
section_path
subsection
table_title
figure_id
source_excerpt
```

Tasks:

1. Preserve page boundaries during LlamaParse extraction.
2. Preserve heading hierarchy instead of flattening the manual into one string.
3. Keep table rows atomic while attaching the surrounding heading and page.
4. Attach warnings and notes to the exact related table or procedure.
5. Return source location metadata in `/vision-query` and `/vapi-tool` responses.

Acceptance: the UI and voice response can identify the manual section and page used as evidence.

## Phase B3 — Vehicle variant identity

Goal: prevent valid facts from the wrong Subaru configuration.

Extend metadata and request fields where available:

```text
engine
transmission
trim
market
production_range
```

Tasks:

1. Detect variant information during ingestion or require it from the uploader.
2. Store variant fields as indexed Qdrant payload values.
3. Require confirmation when multiple variants match.
4. Never silently choose a variant from visual appearance.
5. Return a clarification request when the manual evidence is variant-dependent.

Acceptance: identical component questions from different variants cannot cross-contaminate.

## Phase B4 — Retrieval quality

Goal: improve exact part/spec lookup without weakening refusal thresholds.

Tasks:

1. Normalize automotive aliases, abbreviations, units, and part numbers.
2. Add lexical matching for exact part numbers and section terms.
3. Combine dense vector retrieval with lexical candidates.
4. Retrieve a small top-k set and rerank using vehicle, section, and query-term matches.
5. Keep strict metadata filters before semantic fallback.
6. Add retrieval evaluation metrics: recall@k, wrong-vehicle rate, refusal precision, and latency.

Acceptance: exact part-number and torque-table questions improve without increasing wrong-manual answers.

## Phase B5 — Answer modes

Goal: stop treating every request as a one-row specification lookup.

Implement explicit modes:

### Specification mode

Returns one or two sentences from the best matching table or fact.

### Procedure mode

Returns a short ordered checklist from contiguous manual steps, including prerequisites and relevant warnings. It must never invent missing steps.

### Diagnostic mode

Returns the next manual-supported test or decision branch from symptoms, diagnostic codes, and mechanic-provided measurements. It must distinguish a manual instruction from an inference.

### Identification mode

Uses the image to propose a component and asks for confirmation when confidence is low. It does not answer repair questions by itself.

Acceptance: each mode has separate retrieval, formatting, refusal, and test cases.

## Phase B6 — Diagrams and visual evidence

Goal: support questions that depend on diagrams, connector layouts, and exploded views.

Tasks:

1. Render selected manual pages during ingestion.
2. Store page-image references and searchable captions/labels.
3. Retrieve diagram pages alongside text chunks.
4. Use Nemotron only to describe the visible component or compare it with retrieved manual imagery.
5. Return “diagram evidence unavailable” instead of guessing when the required figure is missing.

Acceptance: diagram-dependent questions either return linked manual evidence or refuse safely.

## Phase B7 — Safety and regression hardening

Tasks:

1. Add adversarial tests for wrong-year, wrong-make, wrong-model, and wrong-variant requests.
2. Add tests for conflicting manual chunks.
3. Add tests for OCR errors in units and part numbers.
4. Ensure warnings are not dropped for safety-critical procedures.
5. Add response provenance and confidence fields.
6. Keep backend tests, ingestion tests, and frontend build green.
7. Run a full Subaru manual regression suite before changing the demo vehicle.

Acceptance: unsupported or ambiguous requests fail closed, with no fabricated automotive content.

## Implementation order

```text
Subaru baseline
  → page/section evidence
  → variant metadata
  → hybrid retrieval
  → specification/procedure/diagnostic modes
  → diagrams
  → safety and regression hardening
```

Do not implement later phases until the preceding phase has a repeatable test set and passes the existing safety rules.
