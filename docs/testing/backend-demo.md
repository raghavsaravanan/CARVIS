# Carvis demo verification

Complete [the v2 migration checklist](../qdrant-v2-migration.md) before expecting numeric answers. Pending records cannot answer questions.

## WRX oil-change demo

Confirm 2022 / Subaru / WRX and the actual transmission. Ask one exact operation:

- “Engine oil capacity with filter, 6MT.”
- “Engine oil capacity without filter, 6MT.”
- Repeat with CVT only when that is the confirmed configuration.

The supplied capacity PDF shows 4.5 L with a filter change and 4.3 L for oil only. Both engine-oil cells span the 6MT/CVT columns. These values require source review in Qdrant before the app can speak them. Overhaul fill is a separate operation.

Demonstrate safe clarification by omitting transmission or filter context. Demonstrate refusal by asking for an unavailable vehicle or wheel-fastener torque without a reviewed installation source.

## Wheel demo limitation

The supplied wheel-height PDF contains suspension height and camber setup, not wheel-fastener torque. Do not use it as evidence for a wheel-bolt answer. Obtain the original tire/wheel installation page, confirm vehicle applicability, and review the exact wheel-fastener record. Old Qdrant text alone is insufficient for verification.

## Vapi and app checks

Use explicit year/make/model, shop and transmission. The Vapi request may include these as JSON fields. The browser has a transmission selector; the existing iOS app can include the transmission and operation in the spoken question.

Validate HTTP 200 grounded answers with real sources, 404 vision refusals, Vapi-shaped refusal results, provider/network error states, and actual audio output. A visual hypothesis must never select another vehicle or an unconfirmed fastener. Confirm glasses routing on the physical phone using [iOS instructions](../../ios/README.md).

Use credentials from server environment only. No user photos, manual exports or credentials belong in Git.
