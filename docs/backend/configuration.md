# Backend configuration reference

How the FastAPI backend is configured and how it behaves at startup, at its request boundary and
against PostgreSQL. Installation, the local run command and dependency locking are in the
[root README](../../README.md#development-setup); design and rationale are in
[`architecture.md`](architecture.md).

## Local environment file

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

## Environment and startup guards

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

## Operator upload endpoint

`/upload` is an operator-only endpoint. It rejects every request (401) that does not carry exactly one
`X-Carvis-Operator-Token` header exactly matching `CARVIS_OPERATOR_TOKEN` (surrounding whitespace in the variable is
ignored); when the variable is unset or blank every upload is rejected, though the API still starts.
Accepted files must begin with the `%PDF-` magic and be at most 50 MiB (larger bodies get 413 and stop
streaming at the cap). These checks run before ingestion is scheduled, so a rejected request never
reaches LlamaParse.

## Request limits and error messages

Every other route caps its request body while it streams, and answers 413 `{"detail": …}` with
`Connection: close` above the cap:

| Route | Body cap |
| --- | --- |
| `/vision-query` and camera photos | 8 MiB image plus 64 KiB of form fields |
| `/vapi-tool` | 4 MiB |
| Every other route | 64 KiB |

Unexpected failures return a fixed message, such as `Specification lookup is temporarily
unavailable.`, never exception text; the reason is logged on the server.

## Logging

Carvis's own logs are JSON lines by default; set `CARVIS_LOG_FORMAT=text` for the human-readable
format. Structured log fields pass an explicit allowlist (`FIELD_POLICY` in `backend/log_config.py`),
so request paths log codes, counts, type names, known vocabularies and salted fingerprints of
caller-supplied IDs, never the mechanic's questions, transcripts, answers, images, model output,
phone-supplied reasons, caller-chosen IDs or exception messages. Uvicorn's own access and error lines
(and the httpx and openai libraries' loggers) stay outside that policy; B1 did not change them. Limits are listed in
[`architecture.md`](architecture.md#api-contracts).

## PostgreSQL foundation, health and request IDs (M2 B1)

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

## Runtime roles, runtime login and JWT verification (M2 B2a)

- Migration `0003_runtime_roles` adds `carvis_bootstrap` and `carvis_provisioner` (`NOLOGIN`), revokes
  `EXECUTE` on new functions from `PUBLIC` for `carvis_owner` and `carvis_provisioner` (global default
  privileges), and revokes everything on the CARVIS schemas and their objects (tables, sequences,
  routines and types) from `PUBLIC` and, where they exist, from `anon`, `authenticated` and
  `service_role`. CARVIS schemas must not define range types: PostgreSQL makes their constructor
  functions owned by the bootstrap superuser with `PUBLIC` `EXECUTE`, which the migration cannot
  revoke, so it refuses to proceed. It first rechecks the B1 roles and refuses to continue
  (changing nothing) if any has gained an attribute, membership, setting, owned object or privilege
  that 0002 did not give it. A non-superuser `CREATEROLE` migration login keeps PostgreSQL 16's
  automatic ADMIN-only membership in the roles it creates; that is migration-administrator authority,
  never a runtime privilege (doc 04, "Function ownership and migration membership").
- The deployment's runtime login holds no privileges of its own: it is a member of `carvis_app` and
  `carvis_bootstrap` with `INHERIT FALSE, SET TRUE` and of nothing else. The owner grants this once per
  database, at provisioning, with the migration login (never on deploy):

  ```bash
  CARVIS_MIGRATION_DATABASE_URL=postgresql://… ../.venv/bin/python -m db.runtime_login grant <login>
  CARVIS_MIGRATION_DATABASE_URL=postgresql://… ../.venv/bin/python -m db.runtime_login check <login>
  ```

  Both refuse an unsafe login (superuser, `BYPASSRLS`, `CREATEROLE`, `CREATEDB`, replication, owning
  any object or the database, holding any ACL or default ACL, role settings, other memberships or
  members) and name the failed conditions only. The login's credential is created by the deployment
  and never enters the repository.
- `/readyz` now reads the version table as `carvis_app` (`SET LOCAL ROLE`). Outside `local` it also
  runs the same runtime-login check on the connected login, so a superuser, `BYPASSRLS` or otherwise
  unsafe login, or one that may not switch to `carvis_app`, reports `database_misconfigured`. Runtime
  roles that do not exist yet report `migrations_pending`. The response shape and reason set are
  unchanged.
- `CARVIS_DATABASE_URL` must describe the connection explicitly: libpq service files (`service`,
  `servicefile`, `PGSERVICE`, `PGSERVICEFILE`) are refused, and the effective host, `hostaddr` and port
  counts (from the URL, else `PGHOST`/`PGHOSTADDR`/`PGPORT`) must follow libpq's rule: hosts and
  addresses match when both are given, and there is one port or one per target. A URL
  that breaks either rule is invalid: boot refused outside `local`, `database_misconfigured` in
  `local`.
- Issuer settings for JWT verification (ADR-0002), optional and transitional: `CARVIS_AUTH_ISSUER`,
  `CARVIS_AUTH_AUDIENCE`, `CARVIS_AUTH_JWKS_URL`. All unset means authentication is unconfigured; a
  partial set, or a JWKS URL that is not `https://`, refuses boot outside `local`. The verifier
  (`backend/auth/`) accepts only ES256/RS256 tokens of at most 1 hour with 30 s leeway and the
  Supabase `authenticated` role; B2c wires it to the `/v1` routes (below). Supabase
  compatibility (issuer URL, audience, JWKS path, claims) is untested; tests use a fake JWKS.
- The request-path async engine (`db.engine.create_async_app_engine`) bounds each new connection,
  name resolution included, by one 2-second deadline, and resolves names on its own small thread pool
  shared by concurrent pool fills. Nothing uses it yet (B2b).

## Identity tables and provisioning (M2 B2b-1)

- Migration `0004_identity` adds `carvis.users`, `carvis.workspaces` and `carvis.memberships`, each
  with row-level security enabled and forced. `carvis_app` and `carvis_worker` may only read them,
  and only the rows their transaction context (`app.user_id`, `app.workspace_ids`) allows; with no
  context they see nothing.
- `carvis.ensure_principal(issuer, subject, email)` is the only runtime path that creates identity
  rows. It is a `SECURITY DEFINER` function owned by `carvis_provisioner` and executable only by
  `carvis_bootstrap`. It finds or creates the user, their personal workspace and their owner
  membership, and returns `(user_id, status)`. It requires `READ COMMITTED`. The provisioner's policies
  confine each read and insert to the principal the `app.bootstrap_*` settings name at that
  statement. The function body sets those settings from its arguments and clears them on return, so
  confinement of a whole call to one principal rests on that (reviewed and tested) body, not on the
  policies alone.
- `db.catalog.violations()` is the reusable catalog check: forced RLS, role attributes, no `PUBLIC`
  or issuer grants, allow-listed definer routines, exact table privileges without grant options, and
  for the CARVIS runtime roles no ownership of any object (database and schemas included), no
  `CREATE` on the database or the CARVIS schemas and no grant options. The migration runs it
  as a post-condition, and later packages extend it.
- Downgrading `0004` refuses while any identity table has rows.
- `/v1` reads them from B2c, through the B2b-2 session context.

## Request session context (M2 B2b-2)

- `db.context` runs each request as two transactions on the runtime login. `provision()` runs a bootstrap
  transaction as `carvis_bootstrap` in READ COMMITTED and returns `(user_id, status)` from
  `ensure_principal`. `tenant_session()` then runs the unit of work as `carvis_app`, with `app.user_id` set and
  `app.workspace_ids` derived from the caller's memberships under row-level security before the first query; the
  workspace set is also on the session for the caller.
- An `after_begin` listener on the request session class installs the context and refuses any transaction that
  has none, before sending anything. A non-active user is refused before a tenant transaction starts. Savepoints
  keep the outer context. Only transaction-scoped settings are used, so nothing survives commit, rollback,
  cancellation or the connection's return to the pool.
- The listener sends only a fixed list of statements, with every type, function and table schema-qualified, so a
  connection's `search_path` cannot redirect them; tests compare the SQL the driver receives with that list.
- The `/v1` routes use it from B2c.

## Versioned API `/v1` (M2 B2c)

Contract: [`05-api-v1.md`](../architecture/05-api-v1.md); it is proposed until B2c merges with the iOS
side's agreement recorded by the owner. Implemented: `GET /v1/me`, `GET /v1/workspaces`.

- **Configuration.** `/v1` answers 503 `service_unavailable` until both the issuer settings
  (`CARVIS_AUTH_ISSUER`, `CARVIS_AUTH_AUDIENCE`, `CARVIS_AUTH_JWKS_URL`) and `CARVIS_DATABASE_URL` are set
  (ADR-0002 transitional rule); legacy routes are unaffected. Nothing connects at boot. Outside `local`,
  the first `/v1` request runs the runtime-login check (`python -m db.runtime_login check`'s conditions) and
  `/v1` stays at 503 while the login is unsafe or the runtime roles are missing.
- **Authentication.** Exactly one `Authorization: Bearer <JWT>` header. No bearer credential ⇒ 401 with
  `WWW-Authenticate: Bearer`; any unacceptable credential or a non-active user ⇒ 401 with
  `WWW-Authenticate: Bearer error="invalid_token"`. No usable issuer keys ⇒ 503 (a token naming a key
  the issuer does not publish is 401 while cached keys are usable).
- **Database.** Each request is one bootstrap transaction and one tenant transaction (B2b-2). From the
  login check on, a request has 5 s; a timeout, lock wait or any database error is 503.
- **Errors.** Every application-produced `/v1` error is `{"error": {"code", "message", "request_id",
  "retryable"}}`, with `request_id` equal to `X-Request-ID`; messages are fixed per code. Every `/v1`
  response carries `Cache-Control: no-store`, and `Connection: close` when it is sent before an announced
  request body was read to the end (A6). A response the ASGI server generates before the app runs
  (Uvicorn's plain-text 400) cannot carry the envelope or these headers. Legacy routes keep their shapes.
- **Logs.** Refusals are logged as `v1_request_refused` with a code and a reason code; unexpected errors as
  `v1_unhandled_error` with the exception type name. Tokens, emails, messages and input are never logged.
- **Contract snapshot.** `backend/tests/fixtures/openapi-v1.json` is the `/v1` OpenAPI contract; the test
  fails on any difference. After an intended, additive change, regenerate it with
  `CARVIS_UPDATE_OPENAPI_SNAPSHOT=1 .venv/bin/python -m pytest backend/tests/test_b2c_v1_api.py -k snapshot`.
