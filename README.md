# CARVIS

CARVIS is a native iOS automotive intelligence platform for delivering vehicle-specific,
source-grounded repair information through conversational voice and optional visual context.

The system is designed for professional technicians: it preserves explicit vehicle context,
validates technical evidence deterministically, and refuses unsupported specifications rather than
guessing.

## Architecture

```mermaid
flowchart LR
    I[Native iOS app] <--> V[Vapi voice]
    I <--> A[FastAPI backend]
    V <--> A
    A <--> Q[Qdrant verified knowledge]
    A -. visual context .-> N[NVIDIA Nemotron]
    I -. optional wearable adapter .-> M[Meta Wearables]
    A -. shop intelligence .-> S[SpacetimeDB]
```

- `ios/` — SwiftUI application, voice experience, device integrations, and native tests.
- `backend/` — FastAPI APIs, conversation orchestration, ingestion, retrieval, verification, and
  provider adapters.
- `backend/spacetimedb/` — server-side shop/workspace schema, views, reducers, and authorization.
- `docs/` — product requirements, active architecture, operational runbooks, and archived records.

The iOS application is the only user-facing client. Carvis has no web frontend.

## Knowledge safety

CARVIS treats retrieval and verification as separate responsibilities. A technical answer must:

1. use an explicit, confirmed vehicle and relevant configuration;
2. match reviewed evidence with exact applicability and provenance;
3. preserve units, conditions, warnings, and ordered procedure stages; and
4. refuse pending, incomplete, conflicting, stale, or cross-vehicle evidence.

Semantic similarity may rank already-applicable evidence; it never proves correctness. Images and
vision models cannot establish vehicle identity or authorize repair specifications. New ingestion
is staged as pending review, and Qdrant migration or alias work must follow the
[migration runbook](docs/backend/qdrant-v2-migration.md).

## Development setup

### Backend

Requirements: Python 3.12 and a safely configured local or cloud Qdrant collection.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r backend/requirements-dev.txt
cd backend
CARVIS_ENV=local ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

Dependencies are pinned with hashes. `backend/requirements.in` lists the direct runtime
dependencies and compiles to `backend/requirements.txt`, which is what Render installs.
`backend/requirements-dev.in` adds test tooling such as pytest and compiles to
`backend/requirements-dev.txt`, which is used for local development and CI. Edit only the `.in`
files, then regenerate both lockfiles with [uv](https://docs.astral.sh/uv/):

```bash
cd backend
uv pip compile requirements.in --universal --python-version 3.12 --generate-hashes --no-header -o requirements.txt
uv pip compile requirements-dev.in --universal --python-version 3.12 --generate-hashes --no-header -o requirements-dev.txt
```

Add `--upgrade` (or `--upgrade-package <name>`) to move pins forward deliberately.
`backend/tests/test_dependency_lock.py` fails in any of these cases:

- a lockfile entry is unpinned or unhashed;
- an input is missing from its lockfile, or is pinned outside its `.in` bound;
- test tooling reaches the runtime lockfile.

`scripts/check-runtime-lock.sh [python]` runs in CI and needs PyPI access. It:

- installs only `backend/requirements.txt` into a temporary virtual environment, as Render does;
- confirms that pytest is absent;
- imports every top-level `backend/*.py` module with `.env` loading disabled, and fails if any
  environment variable appears;
- fails on any Python-level network event (DNS lookup, connect, send, urllib request) or process
  launch during import, even one whose error a module catches;
- fails if import leaves extra threads running.

Native code that bypasses Python's `socket` module is not covered.

`backend/setup.sh` loads `backend/.env` with python-dotenv's `load_dotenv(override=False)`, as the
API does, and never sources the file as shell. As a result:

- a variable present in the environment takes precedence even when it is empty;
- `${VAR}` references resolve the same way;
- `PYTHON_DOTENV_DISABLED` is honoured.

Surrounding whitespace is trimmed; internal whitespace is kept. The script uses `.venv/bin/python`
(or `CARVIS_SETUP_PYTHON`). It exits with status 2 if it cannot read `.env` safely, for example when
python-dotenv is not installed or a value spans several lines.

Keep provider credentials in the local `backend/.env`; never commit secrets, source manuals,
captured images, parse caches, Qdrant data, or review exports.

`CARVIS_ENV` is `local`, `staging` or `production`; when unset the API assumes `production`, and any
other value, or `local` on Render, refuses to start. Outside `local` the API also refuses to start
without `VAPI_WEBHOOK_SECRET`. `/vapi-tool` rejects every request whose `X-Vapi-Secret` header does not
exactly match the configured secret (surrounding whitespace in the variable is ignored), so set it
(any value, matching the assistant's tool headers) to exercise the webhook locally, or set
`CARVIS_ENV=local` to run the rest of the API without one.

Outside `local` the API also refuses to start unless `CARVIS_DEFAULT_SHOP_ID` (the shop used when a
request omits `shop_id`, as the iOS app always does) and `CARVIS_QDRANT_COLLECTION` are set, and, when
both `SPACETIMEDB_URI` and `SPACETIMEDB_TOKEN` are set (telemetry on), `SPACETIMEDB_DB_NAME`. The old fallbacks `shop_demo`,
`george_specs` and `hackutd` apply only with `CARVIS_ENV=local`. To keep a deployment's current
behavior, set these variables to the values it was implicitly using.

`/upload` is an operator-only endpoint. It rejects every request (401) that does not carry exactly one
`X-Carvis-Operator-Token` header exactly matching `CARVIS_OPERATOR_TOKEN` (surrounding whitespace in the variable is
ignored); when the variable is unset or blank every upload is rejected, though the API still starts.
Accepted files must begin with the `%PDF-` magic and be at most 50 MiB (larger bodies get 413 and stop
streaming at the cap). These checks run before ingestion is scheduled, so a rejected request never
reaches LlamaParse.

Every other route caps its request body while it streams, and answers 413 `{"detail": …}` with
`Connection: close` above the cap:

| Route | Body cap |
| --- | --- |
| `/vision-query` and camera photos | 8 MiB image plus 64 KiB of form fields |
| `/vapi-tool` | 4 MiB |
| Every other route | 64 KiB |

Unexpected failures return a fixed message, such as `Specification lookup is temporarily
unavailable.`, never exception text; the reason is logged on the server.

Carvis's own logs are JSON lines by default; set `CARVIS_LOG_FORMAT=text` for the human-readable
format. Structured log fields pass an explicit allowlist (`FIELD_POLICY` in `backend/log_config.py`),
so request paths log codes, counts, type names, known vocabularies and salted fingerprints of
caller-supplied IDs, never the mechanic's questions, transcripts, answers, images, model output,
phone-supplied reasons, caller-chosen IDs or exception messages. Uvicorn's own access and error lines
(and the httpx and openai libraries' loggers) stay outside that policy; B1 did not change them. Limits are listed in
[`docs/backend/architecture.md`](docs/backend/architecture.md#api-contracts).

#### PostgreSQL foundation, health and request IDs (M2 B1)

- `GET /healthz` answers 200 `{"status": "ok"}` and consults nothing. `GET /health` is unchanged.
- `GET /readyz` answers 200 `{"status": "ready"}` only when PostgreSQL is reachable and the recorded
  Alembic revision is this build's head; otherwise 503 `{"status": "not_ready", "reason": …}` with
  `starting`, `database_unconfigured`, `database_misconfigured`, `database_unreachable` or
  `migrations_pending`. The probe has a hard 2-second deadline, opens one connection at a time, resolves host names on one
  dedicated thread (never more than one lookup outstanding), tries hosts in order and every address
  of each, resolving a host only after the earlier ones have failed, all within that deadline, and
  concurrent requests share it. A first host name whose lookup stalls makes the probe report
  `database_unreachable` even if a later host is healthy (accepted B1 limit).
- `CARVIS_DATABASE_URL` (optional in B1, transitional): the API's PostgreSQL URL. `postgresql://`,
  `postgres://` and `postgresql+psycopg://` are accepted and use the psycopg 3 driver; anything else
  refuses boot outside `local` (in `local` it boots and `/readyz` reports `database_misconfigured`).
  Unset means `/readyz` reports `database_unconfigured`. The value is never logged.
- `CARVIS_MIGRATION_DATABASE_URL`: the privileged login that runs migrations (separate from the API's
  URL; there is no fallback). PostgreSQL 16 or later. From `backend/`:

  ```bash
  CARVIS_MIGRATION_DATABASE_URL=postgresql://… ../.venv/bin/python -m alembic -c migrations/alembic.ini upgrade head
  ../.venv/bin/python -m db.history   # fails unless the chain is linear with one head
  ```

  The login needs `CREATE` on the database and `CREATEROLE` (or superuser). Nothing runs migrations
  automatically on deploy.
- Every response carries exactly one `X-Request-ID`: a caller's value if it is a single UUID
  (normalized to 32 lowercase hex), otherwise a new one.
- Real-PostgreSQL tests (`backend/tests/test_b1_migrations.py`) need a throwaway PostgreSQL 16+ server's
  superuser URL in `CARVIS_TEST_POSTGRES_URL`; they create and drop databases and cluster-wide roles,
  so never point it at a real server. Without it they skip (CI sets `CARVIS_REQUIRE_POSTGRES=1`, which
  makes them fail instead). For example:
  `docker run -d --rm -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=scratch postgres:16` and
  `CARVIS_TEST_POSTGRES_URL=postgresql://postgres:scratch@127.0.0.1:55432/postgres`.

### iOS

Open [`ios/Carvis/Carvis.xcodeproj`](ios/Carvis/Carvis.xcodeproj) in Xcode, configure signing and
`CarvisBaseURL`, then run on an iPhone or simulator. Meta Wearables support is optional and requires
the official Device Access Toolkit configuration described in the [iOS guide](docs/ios/README.md).

## Verification

Install Python and SpacetimeDB package dependencies, then run:

```bash
./scripts/verify.sh
```

The verifier runs backend regression tests, Python compilation, pure Swift conversation and wake
checks, SpacetimeDB type-checking, Apple configuration lint, repository structure checks,
documentation-link validation, and an iOS simulator build when full Xcode is available.

## Documentation

- [Documentation map and precedence](docs/README.md)
- [Product requirements](docs/PRD.md)
- [V1 Product Experience Contract](docs/product/v1-product-experience-contract.md)
- [P0 Readiness Audit, 2026-11-15 (historical snapshot)](docs/audits/2026-11-15-p0-readiness-audit.md)
- [Development workflow](docs/development-workflow.md)
- [Architecture decision records](docs/decisions/README.md)
- [Backend architecture](docs/backend/architecture.md)
- [Qdrant review and migration](docs/backend/qdrant-v2-migration.md)
- [Native iOS setup and testing](docs/ios/README.md)
- [Historical architecture and validation records](docs/archive/)

Engineering policy is defined in [`AGENTS.md`](AGENTS.md), with scoped extensions under `backend/`
and `ios/`.
