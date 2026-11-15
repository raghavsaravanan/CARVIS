# Technical debt, reliability and security audit

Severity reflects risk to a real mechanic pilot, not code style.

## Critical findings

### TD-01 — No application identity or enforceable tenant boundary

**Evidence.** iOS stores a local `Account` in Documents and explicitly says “there's no account server yet” ([`AppStores.swift`](../../../ios/Carvis/Carvis/Models/AppStores.swift#L4-L45)). `POST /conversation/sessions` creates a session for any supplied owner/vehicle. `/vision-query` and `/upload` accept caller-controlled `shop_id`; neither requires an end-user credential ([`main.py`](../../../backend/main.py#L1313-L1345), [`main.py`](../../../backend/main.py#L1502-L1527)).

**Impact.** Anyone who can reach the API can submit documents, consume paid inference, choose another tenant identifier, or query whatever exact records match that identifier. Per-session tokens do not authenticate a person or shop.

**Remedy.** Introduce one verified user principal at the API edge; derive shop/tenant membership server-side; protect ingestion with a reviewer/admin role; store mobile credentials in Keychain; add negative cross-tenant tests. Do not deploy public pilot routes until this is complete.

### TD-02 — Conversation state is ephemeral and single-process

**Evidence.** `ConversationStore` is a module-global dictionary with a four-hour TTL and 256-session cap; Vapi-call bindings, tool idempotency, trace, confirmed vehicle, and grounded answer all live in memory ([`conversation.py`](../../../backend/conversation.py#L29-L38), [`conversation.py`](../../../backend/conversation.py#L92-L119), [`conversation.py`](../../../backend/conversation.py#L307-L373)). README instructs one worker.

**Impact.** Deploy/restart loses active calls and history. Multiple workers race or reject valid requests. There is no recovery, audit trail, or cross-device continuity.

**Remedy.** Persist users, vehicles, conversations, calls, messages, confirmed context, and tool executions in a transactional store. Use generation/version columns and idempotency keys. Keep only short-lived camera futures in process, with durable command state and expiry.

### TD-03 — No authorized production automotive data source

**Evidence.** Prior validation reports four reviewed WRX oil records, 14 pending records, and no production alias cutover ([`qdrant-v2.md`](../validation-qdrant-v2.md)). ALLDATA permission is explicitly unresolved.

**Impact.** The pilot cannot safely answer a useful range of real shop questions. Technical quality cannot solve missing rights, coverage, revision, or applicability.

**Remedy.** Make data authorization a launch gate. Define a licensed provider/manual ingestion agreement, supported vehicle/question scope, source-revision and revocation handling, named reviewer roles, and coverage reporting. Never use ALLDATA content absent written authorization.

### TD-04 — Current audio architecture contradicts phone-first product direction

**Evidence.** Voice activation requires connected glasses; audio setup rejects non-glasses microphones and the coordinator stops when glasses are unavailable ([`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L219-L239), [`CarvisConversationCoordinator.swift`](../../../ios/Carvis/Carvis/Assistant/CarvisConversationCoordinator.swift#L353-L366)).

**Impact.** The P0 mechanic journey cannot start on a standard iPhone. Meta Speech also has documented beta/publication constraints.

**Remedy.** Define `AudioInput`, `VoiceSession`, and optional `WearableInput` boundaries. Make iPhone microphone/speaker the default v1 route with normal permission, interruptions, Bluetooth/headset, background, and call lifecycle handling. Preserve glasses route policy as an optional mode.

### TD-05 — Upload/ingestion is an unauthenticated, unbounded in-process job

**Evidence.** `/upload` only checks metadata and filename suffix, streams without an explicit size cap, writes a temp file, and starts a FastAPI background task ([`main.py`](../../../backend/main.py#L1502-L1560)).

**Impact.** Resource exhaustion, paid parse/embedding abuse, orphaned partial work, lost jobs on restart, and no operator-visible status. A `.pdf` extension is not file validation.

**Remedy.** Admin/reviewer authorization; strict byte/page/type quotas; content sniffing and malware policy; durable job record/queue; idempotency key; explicit status/error; cost controls; retention cleanup; staging-only invariant tests.

## High findings

### TD-06 — Provider behavior can bypass the deterministic answer boundary

The backend controls exact speech for successful `lookup_spec`, but README acknowledges free-form turns are prompt-governed. Refusal tool results do not use exact scripted speech. A conversational model can still volunteer unsupported repair advice outside the numeric formatter.

**Remedy.** Define allowed response classes and tool-first policy. For technical claims, make the server return the final speakable response for answer, clarification, and refusal. Add transcript-level evaluations for unsolicited numbers, procedures, safety claims, and cross-vehicle leakage.

### TD-07 — Monolithic backend module and parallel legacy paths

`backend/main.py` is 1,936 lines and owns configuration, provider clients, legacy text formatting/search, FastAPI routes, telemetry, session APIs, vision, and ingestion. It contains both legacy sessionless lookup helpers and the newer v2 conversation tools. The global `_CALL_SESSIONS` path and `ConversationStore` are separate conversation memories.

**Impact.** Changes have a wide blast radius; it is easy to fix one path but not the other. Import-time globals impede testing.

**Remedy.** Incrementally extract route modules and application services behind stable contracts: `identity`, `vehicles`, `conversations`, `knowledge`, `ingestion`, `providers`, `observability`. First characterize current route behavior; do not rewrite retrieval.

### TD-08 — SpacetimeDB integration has split identity/ownership

FastAPI uses one configured token for best-effort reducer calls ([`main.py`](../../../backend/main.py#L58-L83)); reducers derive caller and shop from `ctx.sender`. React separately logs under its browser identity. iOS does neither. The same logical query can be absent, duplicated, or attributed to the wrong principal.

**Remedy.** Choose one authoritative application store and identity flow. If SpacetimeDB remains, authenticate iOS and propagate a verifiable user principal via a supported server pattern; otherwise isolate this module as a future shop experiment. Never pass arbitrary user tokens through logs or client-controlled identity fields.

### TD-09 — Weak deployment security defaults

- Wildcard origins plus credentials are configured ([`main.py`](../../../backend/main.py#L1148-L1154)).
- Vapi authentication is enforced only if `VAPI_WEBHOOK_SECRET` exists.
- `/health` is liveness only, while Render may start without the active v2 collection or vision key.
- The checked-in iOS base URL is a developer laptop hostname and HTTP.
- Info.plist microphone text claims phone-microphone use even though the current hands-free code refuses it.

**Remedy.** Fail closed on required secrets; separate liveness/readiness; environment-specific HTTPS configuration; restricted origins or no CORS for native-only routes; rate limiting and request quotas; correct permission copy; release configuration validation.

### TD-10 — Local sensitive data lacks a defined protection/retention model

Names, vehicle/VIN fields, history, server overrides, and chat replies are plain JSON in the app Documents directory. Browser identity tokens are stored in `localStorage`. There is no deletion/export workflow, retention schedule, provider transcript/audio decision, or privacy manifest/policy evidence.

**Remedy.** Inventory every data field and processor. Store auth secrets in Keychain, apply iOS file protection, minimize stored transcripts, define retention/deletion/export, and document Vapi/NVIDIA/Qdrant data handling before pilot consent.

### TD-11 — Build and dependency reproducibility is incomplete

Python requirements use broad lower bounds; parser version defaults to `latest`. Frontend dependencies include several `latest` declarations despite a lockfile. There is no CI. This host collected 114 backend tests but two failed because the declared `openai` package was not installed in the active Python environment.

**Remedy.** Produce a reviewed Python lock/constraints file, pin parser/model contracts, use lockfile installs, add CI for backend, pure Swift checks, Xcode build/tests, frontend and Spacetime builds, secret scanning and dependency review.

### TD-12 — No iOS test target or release boundary

The two Swift suites are standalone executables, not XCTest. Coordinator, persistence, API decoding, navigation, permission states, interruption recovery, accessibility and release configuration are untested. The Xcode project appears to contain only the app target.

**Remedy.** Add unit/UI test targets; make clients injectable; add URLProtocol-backed API tests; persistence/migration tests; state restoration; audio lifecycle tests on device; archive and TestFlight smoke checklist.

## Medium findings

### TD-13 — UI contains non-authoritative mock repair procedures

`ShopStore` defines static oil, brake, rotation and filter procedures, and `MockBackendClient` drives guided work. Even without torque values, steps like lifting or caliper work are safety-relevant and are not tied to reviewed evidence.

**Remedy.** Hide the guided walkthrough from the v1 pilot or convert procedure steps to the same reviewed evidence model. Clearly label demo-only data in development builds.

### TD-14 — Errors and storage failures are often swallowed

Several iOS saves use `try?`; Spacetime telemetry is best effort; state polling ignores failures. This is acceptable for a demo but makes data loss and degraded behavior invisible.

**Remedy.** Classify retryable/fatal/user-actionable errors, expose safe user recovery, record metrics, and test offline/reconnect/disk-full/provider-timeout paths.

### TD-15 — Observability is not production-shaped

There are useful timings and state logs, but no stable request/correlation ID across iOS → Vapi → FastAPI → Qdrant, no metrics/SLOs, no alerting, no redaction policy, and some legacy logs include question text.

**Remedy.** Structured logs with IDs and outcome codes; never log images/tokens/full transcripts; latency/error/refusal/coverage metrics; readiness and provider circuit status; audit events for source review and administrative changes.

### TD-16 — API contracts are ad hoc

Multipart and JSON types are hand-coded separately in Swift and Python, versions are absent, refusals sometimes use HTTP 404 and sometimes Vapi-shaped HTTP 200, and `source`/`sources` contracts are not shared.

**Remedy.** Define versioned Pydantic request/response schemas and generated/verified OpenAPI client types; standard error envelope; stable source citation and clarification types; compatibility tests for retained legacy routes.

## Positive engineering to retain

- Staging-only ingestion and explicit ban on mutating aliased/legacy collections.
- Review digest bound to the entire evidence payload.
- Exact applicability before semantic ranking.
- Full-scope conflict detection and complete procedure-stage validation.
- Request-correlated camera workflow with deadlines and stale-result rejection.
- Pure conversation state machine separated from SDK side effects.
- Explicit vision prompt boundary and measurement scrubbing.
