# Carvis

Carvis is an automotive technician copilot: Meta glasses capture context, NVIDIA Nemotron proposes visible components, and FastAPI retrieves reviewed specifications from vehicle manuals in Qdrant. The companion app displays and speaks grounded answers.

## Repository

| Directory | Purpose |
| --- | --- |
| `backend/` | FastAPI, LlamaParse ingestion, structured specifications, Qdrant tooling, tests |
| `frontend/` | React/Vite JPEG question console with speech output |
| `ios/` | Native Meta glasses companion and device setup |
| `docs/` | Architecture, migration, deployment, and safety documentation |

## Specification retrieval v2

Each record holds one value or an ordered procedure step, exact vehicle applicability, component/operation/specification type, original cell/row evidence, PDF content hash, and review status. Decimal values stay exact strings. Source conversions are preserved, with no computed unit substitution.

Queries filter exact vehicle and operation metadata before semantic ranking. Python verifies every matching candidate, detects conflicting manuals/revisions, requests missing variants, and formats numbers with actual citations. Unsupported requests refuse. Visual identification never establishes vehicle identity or authorizes a repair fact.

**Deployment gate:** the existing production collection is preserved. This backend returns `migration_pending` while reading the legacy collection; deploy the new retrieval code together with a validated v2 alias configuration. Do not deploy expecting legacy semantic answers to continue. Source review and acceptance validation must precede activation.

See [migration and Qdrant configuration](docs/qdrant-v2-migration.md) for the exact commands, review workflow, activation, and rollback. [Architecture](docs/architecture.md) explains the API contracts and latency boundaries.

## Local development

Create a virtual environment and install `backend/requirements.txt`. Copy `backend/.env.example` to `backend/.env` and set server-side Qdrant, LlamaParse, NVIDIA and Vapi credentials. Existing credentials need no changes. Never put these keys in frontend environment variables.

From the repository root:

```bash
.venv/bin/python -m pytest backend/tests -q
.venv/bin/python backend/qdrant_v2.py
```

Ingestion requires explicit source paths and vehicle metadata, or a JSON manifest:

```bash
.venv/bin/python backend/ingest.py /absolute/path/manual.pdf \
  --year 2022 --make subaru --model wrx --shop-id shop_demo \
  --export-dir .carvis_review
```

New records are **pending review** and cannot answer questions until reviewed and validated. Parse caches use PDF content hashes plus parser configuration; changed files are reparsed even under unchanged filenames. Set a supported pinned `CARVIS_PARSER_VERSION` for reproducible production parsing.

After completing the migration:

```bash
cd backend
../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

In a second terminal, run `npm ci --prefix frontend` then `npm run dev --prefix frontend`. The development proxy forwards `/api` to FastAPI. Select explicit vehicle/transmission context and ask whether the oil filter is being replaced.

## API compatibility

- `GET /health`: liveness.
- `POST /vision-query`: multipart JPEG, question, year, make, model, session ID; optional shop and variant fields. Returns compatible answer/component/vehicle fields plus source citations and timings. A refusal is HTTP 404 with an error and status.
- `POST /vapi-tool`: existing flat/nested Vapi payloads and secret header; confirmed per-call vehicle context remains supported. Include transmission and exact operation in the question or structured fields.
- `POST /upload`: explicit vehicle metadata and PDF; HTTP 202 queues pending-review staging ingestion, not immediate availability.

Nemotron is the default visual provider. Its API client is reused. Explicit, complete specification questions can skip image inference; ambiguous visual questions request mechanic confirmation. Provider failures never trigger generated repair advice. The named component, matching manual, and required configuration must be confirmed.

## Deployment and hardware

`render.yaml` retains the backend build/start and health route. Configure `CARVIS_QDRANT_COLLECTION=carvis_specs_active` only after validation and alias activation. Use a separate, unaliased `CARVIS_INGEST_COLLECTION` for future generations.

Follow [iOS setup](ios/README.md) for Meta registration, device permissions, physical-glasses camera capture, and audio routing. Hardware operation and NVIDIA live inference require independent device/provider validation; backend tests do not prove them.

Qdrant is the current database. SpacetimeDB is deferred. Local PDFs, images, credentials, parse caches, source-review exports, and database files stay outside Git.
