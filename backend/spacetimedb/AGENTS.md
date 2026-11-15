# SpacetimeDB engineering rules

These rules extend `../../AGENTS.md` and `../AGENTS.md` for `backend/spacetimedb/`.

- Tables, views, hooks, and reducers remain deterministic and transactional. Use `ctx.sender`,
  `ctx.timestamp`, and `ctx.random`; never trust caller-supplied identity, role, membership,
  tenant, time, or randomness.
- Enforce shop membership and role authorization inside every protected read and write. Views and
  subscriptions must not expose another user or shop's private records.
- Export only registered runtime values; keep ordinary helpers private. Do not log sensitive
  identity, query, answer, vehicle, or membership payloads.
- From `backend/spacetimedb/module/`, run `npm ci` when dependencies are absent and
  `./node_modules/.bin/tsc --noEmit`. Report the CLI build unavailable when a compatible
  `spacetime` executable is not installed.
- Generate client bindings only with a documented, pinned schema/CLI command; never hand-edit
  them. No iOS bindings are approved yet.
- Never publish, clear, rename, or migrate a database or schema without explicit approval,
  authorization regression tests, and a rollback plan.
