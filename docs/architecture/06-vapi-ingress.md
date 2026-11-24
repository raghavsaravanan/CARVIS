# 06 — Vapi webhook authentication and call binding

## Principle

Client-supplied call metadata (`vapi_call_id`, `metadata`, `variableValues`, anything the app sends
or an LLM echoes) is **correlation data only**. It can name a call; it can never authorize binding or
tool execution. Authority is the conjunction of server-held state the caller does not control.

## What vendor documentation says [W]

From Vapi's "Server authentication", "Server events" and "Enhanced authentication" documentation:

- Server endpoints are authenticated with Custom Credentials referenced by `credentialId`: Bearer
  Token (configurable header name and optional `Bearer` prefix; header `X-Vapi-Secret` without prefix
  reproduces the legacy behavior), HMAC (secret key, algorithm and signature header configurable),
  OAuth2 (documented as enterprise). Inline `secret`/`headers` are labeled legacy.
- `tool-calls` messages carry the `call` object and `toolCallList` (id, name, arguments); the call ID
  is also sent in an `X-Call-Id` header; responses are `{results:[{toolCallId, result|error}]}` with
  HTTP 200.

## Implementation gates (provider-dependent; **[?] until validated**)

M2 PR B5 cannot merge until each gate is validated with one owner-approved call against a **staging**
assistant and the captured payloads are committed as test fixtures. Track A does not depend on them.

| Gate | Must be demonstrated |
| --- | --- |
| G-V1 | Credential type attached to tools (Bearer or HMAC), exact header/signature canonicalization, whether a timestamp is covered |
| G-V2 | `GET /call/{id}` returns assistant ID, status, and the metadata/overrides we set; otherwise adopt the G-V5 variant |
| G-V3 | `tool-calls` contains `call.id`; `X-Call-Id` present and equal; whether metadata is echoed (not relied on either way) |
| G-V4 | Behavior under chosen recording/transcript/Zero-Data-Retention settings; end-of-call report ordering vs tool calls |
| G-V5 | Whether the iOS Vapi SDK can join a call created by the server (preferred design) |
| G-V6 | Retry/duplicate delivery and timeout semantics for tool calls |

## Design

1. **Ingress authentication.** Vapi Custom Credential (HMAC if G-V1 confirms canonicalization,
   otherwise Bearer in `X-Vapi-Secret`). Constant-time comparison (`hmac.compare_digest`). The app
   refuses to boot in staging or production without the credential. Two active secrets support
   rotation. Staging and production use separate assistants and credentials.
2. **Binding is authorized by three independent factors:**
   - **F1 — row ownership:** the caller's verified JWT owns the server-created `calls` row
     (`status=created`, generation current, created within 60 s).
   - **F2 — provider-confirmed linkage:** the server fetches the call from Vapi with its private key
     (3 s timeout) and requires, in **Vapi's own record**, our environment's assistant ID, a call that
     has not ended and is recent, and the one-time `bind_nonce` (256-bit, stored hashed, single use,
     60 s TTL) minted for this row. The nonce is checked against Vapi's response, never against the
     webhook payload or LLM output. An attacker submitting another user's `vapi_call_id` fails because
     that call carries the other row's nonce and is normally already bound.
   - **F3 — unbound and unique:** an atomic `UPDATE … WHERE status='created' AND vapi_call_id IS NULL`
     with a UNIQUE constraint; conflict returns 409 and writes an audit event; the nonce is consumed in
     the same transaction.
   Preferred stronger variant if G-V5 passes: the **server creates the Vapi call** and learns
   `vapi_call_id` first-hand, so no client assertion exists.
3. **Fail closed.** Vapi unreachable, metadata not retrievable (for example Zero Data Retention), or
   any factor failing rejects the bind (`bind_unverified`, retryable). The server never falls back to
   trusting the client claim, the webhook payload, or an LLM-echoed value.
4. **Webhook resolution.** `call.id` (cross-checked with `X-Call-Id`) → `resolve_call` (see
   [04-identity-tenancy-rls.md](04-identity-tenancy-rls.md)) → tenant, user, vehicle and snapshot from
   the row. `carvis_*` fields in the payload, `shop_id`, vehicle, year, make, model in tool arguments
   are ignored for authorization; a model-supplied vehicle that differs from the confirmed snapshot
   yields `vehicle_conflict` as today.
5. **Webhook-before-bind race** (pinned by `test_webhook_can_arrive_before_the_phone_binds_the_call`):
   an unbound `call.id` waits up to about 3 s for the bind to land, then returns the structured
   retryable error `call_not_ready`. There is no payload-trusting auto-bind (this removes today's
   on-the-fly bind in `session_for_webhook`).
6. **Replay and idempotency.** `webhook_events (vapi_call_id, tool_call_id)` UNIQUE returns the stored
   response for duplicates; ended and stale-generation calls are rejected; a timestamp tolerance is
   added only if G-V1 confirms signed timestamps. A replay needs the credential and writes nothing. It
   returns the stored response only while its call is still the conversation's active, current generation;
   a replay for an ended or superseded call (for example after a vehicle switch ended the conversation)
   returns no technical content.
7. **Tool scope.** Tools may invoke `lookup_spec`, `set_work_context`, `look_at_part`. No tool accepts
   tenant fields, and no tool creates or changes confirmed vehicle context: the legacy `confirm_vehicle`
   ("confirmed aloud") has no authority in v2 and is removed from the V1 tool set or returns a nonconfirming
   result. Only if roadmap D-19 includes CAR-019 does a proposal tool exist; it returns an unconfirmed
   candidate that the technician confirms in the app (`POST /v1/vehicles/{id}/confirm`). `lookup_spec` is
   evaluated against the bound call's conversation snapshot and generation, and its answer is released only
   if that call is still current ([03-data-model.md](03-data-model.md), "Vehicle context rules"). The
   sessionless legacy lookup path is removed in Track B after iOS migrates.
8. **Logging.** Request ID and call ID only; no transcripts or answers; Vapi recording and transcript
   storage disabled unless the retention decision (ADR-0009) says otherwise.

Accepted residual risk: an attacker holding both the victim's JWT and the live nonce within its 60 s
window is the victim; JWT theft is outside the binding design.

## Adversarial tests (must pass, with real provider response shapes pinned by G-V1…G-V6)

- Missing, empty or wrong credential ⇒ 401; app refuses to boot without a credential.
- Valid-JWT attacker submits a victim's live `vapi_call_id` with their own nonce ⇒ rejected; with no
  nonce ⇒ rejected; replays a captured bind ⇒ rejected; binds after TTL ⇒ rejected; binds a call whose
  assistant is not ours ⇒ rejected; two users race for one `vapi_call_id` ⇒ exactly one wins (409).
- Vapi API down or metadata unavailable ⇒ bind fails closed.
- Webhook with attacker-chosen `carvis_*` metadata or session ID for an unbound or other call ⇒ ignored.
- Tool arguments naming another tenant's `shop_id` or vehicle ⇒ ignored or `vehicle_conflict`.
- Replayed `toolCallId` on the current call ⇒ identical response, one `turns` row; `X-Call-Id` ≠ `call.id` ⇒ 400.
- Vehicle switch between a tool call and its response, or a replay after the switch ⇒ no technical content
  released for the old vehicle; the old call is ended.
- A tool claiming the technician confirmed a vehicle aloud ⇒ no snapshot created, context unchanged.
