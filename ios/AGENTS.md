# iOS engineering rules

These rules extend the repository `AGENTS.md` for `ios/`.

- SwiftUI views present state; long-lived dependencies and application state need explicit,
  stable ownership across view updates.
- Explicitly initiated native iPhone audio is v1 priority. Meta Wearables remains an optional
  adapter using the official SDK lifecycle; glasses must not become a P0 prerequisite.
- Keep server secrets out of the app. Store credentials/tokens in Keychain and treat local files
  as caches, not authorization or server truth.
- Network clients use typed contracts, timeouts/cancellation, safe retry rules, and visible
  refusal/error states. Never replace backend evidence text with a guessed value.
- Handle audio permissions, interruptions, route changes, backgrounding, and provider failures.
  Audio ownership changes require pure-state and physical-device tests.
- Preserve VoiceOver, readable text, reduced motion, clear audio-state labels, and workshop-sized
  controls. Require a simulator build with full Xcode and report signing/device checks separately.
- Run the pure checks and project lint with `scripts/verify.sh`.
