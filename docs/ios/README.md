# Carvis native iOS app

`ios/Carvis` is the only user-facing Carvis application. The dashboard starts a native iPhone
Vapi conversation without Meta setup. Meta glasses remain an optional wake and camera path.

The **Ask Carvis** screen takes a photo with the glasses camera, sends it to Carvis's
`POST /vision-query` with the question and the explicit vehicle (2022 / subaru / wrx), and
shows and speaks the manual-grounded answer or refusal.

The glasses code follows Meta's official CameraAccess sample and the Wearables Device Access
Toolkit (`MWDATCore`, `MWDATCamera`) 1.0.1 interfaces. No SDK calls are invented.

Official sources:

- <https://github.com/facebook/meta-wearables-dat-ios>
- <https://github.com/facebook/meta-wearables-dat-ios/tree/main/samples/CameraAccess>
- <https://wearables.developer.meta.com/docs/develop/>

## Hardware checkpoint (tested 2026-11-07)

| Item | Result |
| --- | --- |
| Xcode / iOS SDK | Xcode 27.0 (27A266a), iOS SDK 27.0 |
| iPhone | iPhone 14 Pro, iOS 27.0.1 |
| Glasses | Ray-Ban Meta Wayfarer Gen 2, Developer Mode on in the Meta AI app |
| Apple signing | **Free (personal) Apple Developer team** — no paid account |
| CameraAccess registration | Succeeded |
| CameraAccess session | Started |
| CameraAccess live preview | **Works**, after the Bluetooth Classic fix below |
| Carvis on device | Builds, installs, launches |
| Carvis registration, preview, capture, `/vision-query` | **Works** |
| Hey Carvis, Vapi conversation, camera during a call | Built; **not yet tested on glasses**. See [the hands-free test](handsfree.md) |

### Two fixes needed with a free Apple team

1. **Remove the Wi-Fi entitlements.** CameraAccess ships with
   `com.apple.developer.networking.HotspotConfiguration` and `...wifi-info`. Personal teams
   can't sign those ("Personal development teams ... do not support the Access Wi-Fi
   Information and Hotspot capabilities"). Meta's BirdSpotter sample captures photos and
   streams without them.
2. **Declare Bluetooth Classic.** Without the entitlements, CameraAccess's preview failed with
   `Device is not connected: <id>`. Meta's guide says camera streaming uses Bluetooth Classic,
   which needs the `external-accessory` background mode and
   `UISupportedExternalAccessoryProtocols = [com.meta.ar.wearable]`. CameraAccess doesn't
   declare them (BirdSpotter does). After adding both, preview streamed.

Carvis's `Carvis-Info.plist` and `Carvis.entitlements` already include both fixes.

Free-team limits: the build expires after 7 days (reinstall from Xcode before judging), and a
phone can hold only 3 free-team apps at once.

## Run it

For the new foreground **Hi Carvis / Hey Carvis** glasses-speech experiment, follow
[the wake-listener hardware test](wake-listener.md). It adds a dedicated diagnostic
screen and emits wake events; it does not integrate Vapi. Physical detection and
camera concurrency are not yet verified. Locked-screen listening is intentionally
paused in this build.

1. Open `ios/Carvis/Carvis.xcodeproj` in Xcode. Swift Package Manager fetches the pinned
   dependencies.
2. Select the Carvis target, choose your team, and keep or change the bundle ID.
3. In `Carvis-Info.plist`, set `CarvisBaseURL` to the backend. It defaults to a Mac on the same
   Wi-Fi (`http://<mac-name>.local:8000`); for that, run Carvis with
   `uvicorn main:app --host 0.0.0.0 --port 8000` from `backend/`. Use the HTTPS Render URL once
   deployed.
4. For a phone call, add a car and follow [Voice setup](#setup), then tap **Talk to Carvis**.
   For camera questions, connect Meta glasses in the app and use **Snap and ask**.

## Dashboard

The car hero, an oil change countdown, odometer, next-due item, maintenance list, and your own
specs. Everything is edited on the phone and saved locally (`car-profile.json`). The pre-filled
intervals and mileage are demo placeholders; set them from the owner's manual.

## Shop (mechanic / team accounts)

Host a shop to watch every mechanic's job live: who, bay, vehicle, job, current step,
progress, safety and camera checks, and an activity feed. Mechanics on the same model are
grouped together. Your own job on this phone shows as "You".

Native prototype only for now: the other mechanics are a simulated crew. To connect the retained SpacetimeDB
backend, replace `seedCrew` and `tick` in `Carvis/Models/ShopStore.swift` with a subscription
that fills `crew`, `events`, and `finishedToday`. Per mechanic the screens need: name, bay,
vehicle, job name, step number, total steps, step title, safety/camera flags, step start time,
and job finish time. The views in `ShopViews.swift` only read the store.

## Voice: iPhone calls and optional glasses

The dashboard's **Talk to Carvis** button starts an explicit Vapi call using the iPhone
microphone and speaker, or a connected headset. It does not arm a wake listener or require
Meta setup. The call status and persistent End Call control follow real provider and route
events. Physical iPhone audio and a live Vapi call still require device validation.

`CarvisConversationCoordinator` presents the phone and glasses entry paths and camera state.
`ConversationMachine` defines the transitions. `VoiceSessionController` now owns the Vapi
call, backend session/generation, route verification, and audio release through injected
provider, backend, and audio-route interfaces. `PhoneAudioRoute` configures the iOS call
category before Vapi joins, then lets Vapi/Daily select speakerphone, wired, or Bluetooth
audio. `MetaGlassesAudioRoute` retains the glasses-only Bluetooth policy. The voice controller
has no Meta, wake, camera, or SwiftUI dependency;
its mocked checks run alongside the pure machine checks in `scripts/verify.sh`.
The Meta SDK is configured once before its singleton is accessed. If local Meta credentials
are absent, an unavailable adapter leaves glasses actions disabled while the app still launches.

1. **Phone entry.** Tapping Talk to Carvis releases any wake listener, creates or reuses a
   vehicle-scoped backend session, starts one call generation, requests microphone permission,
   and starts Vapi. The microphone remains muted until the selected route is usable.
2. **Optional glasses listening.** Starting a job arms `CarvisWakeListener`, which uses the glasses' own speech
   recognition (`MWDATSpeech`). If Meta Speech fails, Apple recognition takes over, but only
   on the glasses' Bluetooth microphone. This wake path never falls back to the phone mic.
3. **Handing over the audio.** On "Hey Carvis", Meta Speech and Apple recognition are released
   and awaited, while the camera keeps running. `AudioOwnership` then stops anything else
   from changing the audio setup until the call has completely ended.
4. **Glasses call.** The Meta route adapter prepares the Bluetooth microphone. Vapi and Daily carry the conversation's audio over iOS Bluetooth. The
   microphone stays muted until both the microphone and speaker are confirmed to be the
   glasses. If that route is lost, the microphone is muted again until it comes back. A
   question said with the wake phrase is delivered once.
5. **Memory.** One session is shared by the app, Vapi, and the backend
   (`backend/conversation.py`). It holds the confirmed vehicle, component, operation, pending
   question, and grounded answer. A spoken correction clears whatever depended on it.
6. **Seeing.** `look_at_part` is a server tool. The backend holds the tool call open and sends
   the phone a command tied to this session and call. The phone takes a new photo and uploads
   it, Nemotron identifies the part, and the original tool call gets the result. Commands
   have deadlines and are deduplicated; late or repeated photos are rejected. A phone-only call
   reports camera unavailable for the correlated request rather than waiting for glasses.
7. **Specifications.** `lookup_spec` answers come from reviewed records in Qdrant, and the
   backend gives Vapi the exact sentence to say. The model isn't asked to word it.

**Known limit:** free-form turns between tool calls are held back only by the system prompt.
The backend controls what's said for grounded answers, not every word the model says.
The current glasses wake and camera screens still require Meta hardware. Phone calls have not
been verified with a live Vapi provider or physical iPhone audio in this repository.

### Setup

Follow [the hands-free test](handsfree.md). `VapiConfig.plist` is git-ignored and holds
only the **public** key and assistant ID. The system prompt is in
`backend/vapi/assistant_prompt.md`, and `backend/vapi_assistant.py` configures the assistant.
For a phone-only test, install the app on an iPhone, set a reachable `CarvisBaseURL` and the
Vapi public key/assistant ID, add a vehicle, leave Meta glasses disconnected, then tap
**Talk to Carvis** on the dashboard. Grant microphone permission, verify two-way audio and
the status transitions, tap **End call**, and repeat. Test wired/Bluetooth headsets and an
interruption separately; the simulator does not validate physical audio routing.

## Safety rules the app keeps

- No backend API keys in the app; the Carvis backend holds them. The only Vapi value in the
  app is the client-side public key, kept out of git.
- Captured photos stay in memory and are never saved or committed.
- The vehicle is always sent explicitly; the photo never decides which car it is.
- The answer text is shown exactly as Carvis returns it. Refusals ("not in the manual") and
  errors (`{error, component}` and `{detail}`) are shown verbatim, never replaced with a guess.
- The mock oil-change walkthrough contains no torque values, oil amounts, or intervals;
  the WRX oil section isn't loaded, so it points to the service manual instead.
- Typed Snap-and-ask answers are labelled with where they played: the glasses' Bluetooth name
  or the phone speaker. Explicit phone calls use the iPhone microphone and speaker or a
  connected headset. The optional glasses wake path remains restricted to glasses audio.
- The backend must run with `CARVIS_QDRANT_COLLECTION=carvis_specs_v2`. Otherwise it refuses
  specification questions on purpose.
