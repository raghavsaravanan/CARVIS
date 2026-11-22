---
name: carvis-regression
description: Run and extend CARVIS regression checks — Python backend tests, pure Swift checks, SpacetimeDB TypeScript, voice-pipeline preservation, deterministic verified answers and refusals, tenant-isolation and authorization tests — and report mocked versus physical-device and live-provider validation honestly. Use before and after backend, iOS, or contract changes, and whenever asked whether something still works.
allowed-tools: Read Grep Glob Bash(scripts/verify.sh) Bash(scripts/bootstrap-worktree.sh *) Bash(scripts/tests/review-scope-test.sh) Bash(.venv/bin/python -m pytest *) Bash(.venv/bin/python -m compileall *) Bash(python3 -m pytest *) Bash(python3 -m compileall *) Bash(git status *) Bash(git diff *)
---

# CARVIS regression workflow

Default tests use mocks and local stores. They must never contact Vapi, Qdrant cloud, NVIDIA,
LlamaParse, or any paid/live provider, and never read real manuals or customer data.

## 1. Choose the narrowest check first

| Changed area | Run first |
| --- | --- |
| Conversation/session/tool logic (`backend/conversation.py`) | `pytest backend/tests/test_conversation.py` |
| Retrieval, schema, extraction, Qdrant v2 (`backend/spec_*.py`, `qdrant_v2.py`, `migrate_v2.py`, `ingest.py`) | `pytest backend/tests/test_specs_v2.py backend/tests/test_ride_height.py` |
| Vapi assistant config/prompt (`backend/vapi_assistant.py`, `backend/vapi/assistant_prompt.md`) | `pytest backend/tests/test_vapi_assistant.py` |
| Routes, voice formatting, vision (`backend/main.py`) | `pytest backend/tests/test_main.py backend/tests/test_vision_speed.py` |
| Swift state machines/policies | the matching `swiftc` command in `scripts/verify.sh` (see section 2) |
| `backend/spacetimedb/module/src/index.ts` | TypeScript compile (section 2) |

Python: use `.venv/bin/python` when it exists, otherwise `python3` (`scripts/verify.sh` does the same).
`.venv/` is gitignored. In a fresh checkout or worktree run `scripts/bootstrap-worktree.sh`, which
creates `.venv` from `backend/requirements-dev.txt` and installs the SpacetimeDB module's
`node_modules` (the runtime lockfile `backend/requirements.txt` has no pytest);
`scripts/bootstrap-worktree.sh --check` validates an existing setup without installing.
Run `-m pytest backend/tests -q` then `-m compileall -q backend` for the full backend baseline.

## 2. Full baseline and Swift/TypeScript commands

`scripts/verify.sh` is the complete local baseline: backend tests, compileall, four Swift pure
checks, SpacetimeDB `tsc`, `plutil -lint`, the iOS Simulator build (skipped without full Xcode),
repository-structure checks, the review-packet tests, and the documentation-link check (which
also covers `CLAUDE.md` and the skills). It requires `scripts/bootstrap-worktree.sh` (or at least
`npm ci --prefix backend/spacetimedb/module`) first. CI runs the same families as jobs
`Backend and hygiene`, `Swift pure checks`, and `SpacetimeDB typecheck`
(`.github/workflows/ci.yml`); those are the required status checks.

Pure Swift checks (source plus test compiled together, then executed):

| Check | Source | Test |
| --- | --- | --- |
| Conversation state machine | `ios/Carvis/Carvis/Assistant/ConversationMachine.swift` | `ios/Tests/ConversationMachineTests.swift` |
| Voice session controller | `ios/Carvis/Carvis/Assistant/VoiceSessionController.swift` | `ios/Tests/VoiceSessionControllerTests.swift` |
| Phone audio route policy | `ios/Carvis/Carvis/Speech/PhoneAudioRoutePolicy.swift` | `ios/Tests/PhoneAudioRoutePolicyTests.swift` |
| Wake phrase matcher | `ios/Carvis/Carvis/Glasses/WakePhraseMatcher.swift` | `ios/Tests/WakePhraseMatcherTests.swift` |

TypeScript: `backend/spacetimedb/module/node_modules/.bin/tsc --project backend/spacetimedb/module/tsconfig.json --noEmit`.
This is a typecheck only; no authorization test suite or `spacetime` CLI build runs here.

## 3. Voice pipeline preservation

The chain is iPhone → Vapi → FastAPI (`/conversation/sessions…`, `/vapi-tool`) → Qdrant →
deterministic answer or refusal → speech. Treat these as invariants; a change that needs to alter one
requires a scoped migration approved by the owner:

- Swift: `ConversationMachine` and `VoiceSessionController` stay independent of Meta; phone calls
  work without glasses; microphone stays muted until the route is verified; one active call generation.
- Backend: `test_conversation.py` covers session tokens, webhook secret, vehicle-confirmation gate,
  verbatim grounded answers, refusals with no scripted speech, stale/duplicate tool calls, call
  generation cleanup, camera correlation, and vehicle-change invalidation. `test_vapi_assistant.py`
  proves the prompt contains no specifications and every tool is an authenticated server tool.
- Existing status codes and response shapes for `/vapi-tool`, `/upload`, `/vision-query` and the
  conversation/camera endpoints are unchanged unless versioned.

## 4. Deterministic verified answers and refusals

`test_specs_v2.py` and `test_ride_height.py` define the safety contract: exact vehicle/variant
filters before semantic ranking; no cross-vehicle or cross-shop fallback; pending, tampered,
conflicting, or incomplete-procedure evidence refuses; missing variants ask for confirmation even if
values match; spoken text with an invented number is detected (`ungrounded_numbers` in
`backend/spec_retrieval.py`). When adding behavior, add both a positive case and an adversarial
refusal case. Never weaken an assertion to make a change pass; stop and report instead.

## 5. Tenant isolation and authorization testing

Existing coverage is session- and secret-level (`test_session_requires_its_own_token`,
`test_webhook_requires_the_vapi_secret`, `test_no_cross_vehicle_or_shop_fallback`). Re-verify whether a
user principal exists before claiming more. New authorization work needs, at minimum:

1. Two distinct test principals (A and B) with separate workspaces.
2. Unauthenticated, expired, and wrong-audience credentials rejected on every protected route.
3. Manipulated `user_id`, `shop_id`, vehicle, session, call, and feedback identifiers cannot read or
   mutate the other principal's data; responses do not reveal that the object exists.
4. Webhook replay and stale callbacks rejected; idempotent retries return the same result.
5. Restart durability and vehicle-switch invalidation across the persistence boundary.
6. Qdrant retrieval filtered by the server-derived tenant, never by a caller field.

Use fakes for identity, the store, and Qdrant. SpacetimeDB reducers currently have only typechecking;
say so rather than implying authorization tests ran.

## 6. Risk tiers, mutation checks, and read-only runs

The task's risk tier (`docs/development-workflow.md`, "Risk tiers") adds to everything above and
never removes a check. In short: T2 adds success and failure tests for new behavior; T3 adds
section 5's isolation and authorization negatives, migration up and down on a scratch store, and
`scripts/check-runtime-lock.sh` for dependency changes; T4 adds section 3's pipeline preservation
and section 4's adversarial refusals.

Mutation check: disable the guard (comment it out or force its condition), run the narrowest
suite, confirm it fails for the guard's reason, restore it, and confirm `git diff` shows no trace.
T2 does this for each new guard; T3 for every touched authentication, tenant, secret and limit
check; T4 also for every touched applicability, evidence and refusal condition. Record each
mutation and its failing test in the PR.

A reviewer whose sandbox forbids writes to the checkout can still run the Python suite without
writing to it: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider
backend/tests -q` (tested in the isolated Codex profile: 446 passed). Label the result
**mocked/unit**, and say it ran read-only.

## 7. Report honestly

Label every result as exactly one of: **mocked/unit**, **local**, **simulator**, **physical device**,
**live provider**, **production**. Say what you ran, the counts and failures, and what you could not run
(for example full Xcode absent, `node_modules` missing, no `.venv`, provider keys absent). Never present
mocks or the simulator as device or live evidence. Not physically validated as of the 2026-11-15 audit
(re-check before repeating): permission-denial recovery, incoming-call/Siri interruptions, wired and
Bluetooth route matrix, network handoff and provider outages, backgrounding, fresh Meta glasses
regression, repeated multi-day use. Report failures with output; do not retry until green or skip tests.
