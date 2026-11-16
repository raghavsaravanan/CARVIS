# 0005. Vapi webhook authentication and call binding

- **Status:** proposed (provider-dependent parts marked pending validation)
- **Date:** 2026-11-15
- **Resolves:** PRD CAR-020–027; contract §7.2
- **Supersedes:** none

## Context

`/vapi-tool` fails open without `VAPI_WEBHOOK_SECRET`; `bind_call` can overwrite another session's
mapping; the webhook path trusts a payload-supplied session ID and caller-supplied `shop_id`
([`../architecture/01-current-state.md`](../architecture/01-current-state.md)).

## Options considered

| Option | Assessment |
| --- | --- |
| LLM- or client-echoed call token as authority | **Rejected**: both are attacker-influenced |
| Trust the client-supplied `vapi_call_id` after JWT check | Rejected: a caller can name another user's call |
| JWT-owned row ∧ provider-confirmed nonce ∧ unique unbound mapping | Chosen |
| Server creates the Vapi call and learns the ID first-hand | Preferred if the iOS SDK can join it (gate G-V5) |

## Decision

Client call metadata is correlation data only. Webhook credential: Vapi Custom Credential (HMAC if
validated, otherwise Bearer in `X-Vapi-Secret`), constant-time comparison, boot refusal without it,
two secrets for rotation. Binding requires F1 row ownership, F2 confirmation from Vapi's own record
including a single-use 60 s nonce, and F3 atomic unique bind; failure is closed (`bind_unverified`).
Webhook resolution uses the minimal `resolve_call` function and ignores payload/tool-argument
tenancy. Dedupe in `webhook_events`. Details and tests:
[`../architecture/06-vapi-ingress.md`](../architecture/06-vapi-ingress.md).

**Pending validation (implementation gates G-V1…G-V6):** credential/HMAC canonicalization and
timestamps, `GET /call/{id}` contents, `X-Call-Id`, Zero-Data-Retention behavior, SDK join of a
server-created call, retry semantics. This record stays provisional on those points until a real
staging call validates them (decision D-9).

## Consequences

One extra provider call at bind time (3 s timeout); bind failures are retryable. Rollback: the
Track A hardening (fail-closed secret, no rebind) remains independent of this record.

## Verification

Adversarial binding tests, replay/idempotency tests, fixtures captured from the staging call, gate G15.
