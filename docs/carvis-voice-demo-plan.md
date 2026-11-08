# Carvis — finish the hands-free demo

Implement on the Mac with Xcode, the iPhone, paired Ray-Ban Meta Gen 2 glasses, and developer accounts. Inspect the latest checkout and reuse its working code.

Goal: after setup/arming, “Hey Carvis” starts a natural conversation, confirms the vehicle, performs real visual inspection, retrieves ride-height tolerance, and supports follow-ups without phone interaction.

No scripted dialogue, hardcoded vehicles/specifications, fake tools, or silent phone-microphone fallback. The system prompt controls how the assistant talks; code controls routing, state, tools and evidence validation.

1. Reuse what exists.
Inspect VapiAgent, AskView, CarvisWakeListener, VoiceListener, SpeechOutput, GlassesController, profiles, FastAPI and retrieval. Vapi is already integrated in code; finish and verify it rather than adding a parallel implementation.

2. Correct the routing.
Meta DAT provides wake transcripts and camera images. Vapi/Daily uses iOS Bluetooth audio for conversation. Add one CarvisConversationCoordinator and audio owner.
Await release of both wake/Apple recognizers before Vapi starts, preserving the camera session. Prevent playback-only audio changes from overriding Vapi. Verify actual Ray-Ban input AND output routes; pause on route loss. Re-arm only after complete call shutdown, including errors.

3. Preserve the conversation.
A bare wake starts Vapi immediately; wake plus question delivers the remaining question exactly once. Share one session across app, Vapi and backend. Pass the existing profile name and editable vehicle context instead of Vehicle.demo.
Persist confirmed vehicle/variants, component, operation, pending question and grounded answer for the session. Spoken corrections invalidate conflicting state. Local chat history alone is insufficient.

4. Complete camera tools.
Replace look_at_part’s uncorrelated system-message injection with a supported server-tool result workflow. Reuse existing capture code.
Send authenticated session/request-correlated commands to the iPhone, capture/upload a fresh JPEG, reuse Nemotron identification, and resolve the original waiting tool call. Add timeouts, cancellation, deduplication and stale-result rejection. Play the thinking cue during actual work. Separate visual proposals from authoritative specifications; preserve /vision-query compatibility.

5. Ground technical answers.
Reuse lookup_spec and /vapi-tool; handle actual webhook payloads and multiple tool calls. Review/ingest ride-height tolerance separately from nominal height, preserving signed offsets, units, applicability and citations.
Enforce approved technical text at the final speech boundary using supported Vapi mechanisms; a “repeat exactly” prompt alone is insufficient.

6. Configure one assistant system prompt.
It controls tone, profile-aware greeting, vehicle confirmation, clarification and tool use. Remove coded conversational replies and demo branches. Never place specification answers in the prompt or claim tools ran when they did not.

7. Build and demonstrate incrementally.
On physical glasses verify: wake → greeting → spoken confirmation → camera/Nemotron → Qdrant answer → follow-up → interruption → Bluetooth recovery.
Test camera capture during Vapi audio; investigate documented alternatives if needed, never phone input disguised as glasses input. Require five touch-free foreground runs after arming.
Keep backend tests passing. Report code-only, hardware-demonstrated and blocked capabilities separately. Test locked/background operation separately; do not claim support or terminated-app wake without proof. Protect credentials/images and use official SDK interfaces.
