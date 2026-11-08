# Carvis iOS app (Meta glasses + Carvis)

`ios/Carvis` is the iPhone app. The phone is the dashboard; the Meta glasses provide live
video. The **Ask Carvis** screen takes a photo with the glasses camera, sends it to Carvis's
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
| Hey Carvis, Vapi conversation, camera during a call | Built; **not yet tested on glasses**. See [the hands-free test](HANDSFREE_TEST.md) |

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
[the wake-listener hardware test](WAKE_TEST.md). It adds a dedicated diagnostic
screen and emits wake events; it does not integrate Vapi. Physical detection and
camera concurrency are not yet verified. Locked-screen listening is intentionally
paused in this build.

1. Open `ios/Carvis/Carvis.xcodeproj` in Xcode. Swift Package Manager fetches
   `meta-wearables-dat-ios`.
2. Select the Carvis target, choose your team, and keep or change the bundle ID.
3. In `Carvis-Info.plist`, set `CarvisBaseURL` to the backend. It defaults to a Mac on the same
   Wi-Fi (`http://<mac-name>.local:8000`); for that, run Carvis with
   `uvicorn main:app --host 0.0.0.0 --port 8000` from `backend/`. Use the HTTPS Render URL once
   deployed.
4. Run on the iPhone. On the dashboard, tap **Connect glasses** and approve in the Meta AI app
   (`carvis://` brings you back). Then **Ask about a part**, type a question, and tap
   **Snap and ask**.

## Dashboard

The car hero, an oil change countdown, odometer, next-due item, maintenance list, and your own
specs. Everything is edited on the phone and saved locally (`car-profile.json`). The pre-filled
intervals and mileage are demo placeholders; set them from the owner's manual.

## Shop (mechanic / team accounts)

Host a shop to watch every mechanic's job live: who, bay, vehicle, job, current step,
progress, safety and camera checks, and an activity feed. Mechanics on the same model are
grouped together. Your own job on this phone shows as "You".

Frontend only for now: the other mechanics are a simulated crew. To connect the SpacetimeDB
backend, replace `seedCrew` and `tick` in `Carvis/Models/ShopStore.swift` with a subscription
that fills `crew`, `events`, and `finishedToday`. Per mechanic the screens need: name, bay,
vehicle, job name, step number, total steps, step title, safety/camera flags, step start time,
and job finish time. The views in `ShopViews.swift` only read the store.

## Voice: Hey Carvis and Vapi

One object owns a hands-free conversation: `CarvisConversationCoordinator`. Its rules are in
`ConversationMachine`, which has no audio or SDK in it, so they're tested on their own
(`ios/Tests/ConversationMachineTests.swift`).

1. **Listening.** Starting a job arms `CarvisWakeListener`, which uses the glasses' own speech
   recognition (`MWDATSpeech`). If Meta Speech fails, Apple recognition takes over, but only
   on the glasses' Bluetooth microphone. The phone's microphone is never used; without the
   glasses, the app pauses and says why.
2. **Handing over the audio.** On "Hey Carvis", Meta Speech and Apple recognition are released
   and awaited, while the camera keeps running. `AudioOwnership` then stops anything else
   from changing the audio setup until the call has completely ended.
3. **The call.** Vapi and Daily carry the conversation's audio over iOS Bluetooth. The
   microphone stays muted until both the microphone and speaker are confirmed to be the
   glasses. If that route is lost, the microphone is muted again until it comes back. A
   question said with the wake phrase is delivered once.
4. **Memory.** One session is shared by the app, Vapi, and the backend
   (`backend/conversation.py`). It holds the confirmed vehicle, component, operation, pending
   question, and grounded answer. A spoken correction clears whatever depended on it.
5. **Seeing.** `look_at_part` is a server tool. The backend holds the tool call open and sends
   the phone a command tied to this session and call. The phone takes a new photo and uploads
   it, Nemotron identifies the part, and the original tool call gets the result. Commands
   have deadlines and are deduplicated; late or repeated photos are rejected.
6. **Specifications.** `lookup_spec` answers come from reviewed records in Qdrant, and the
   backend gives Vapi the exact sentence to say. The model isn't asked to word it.

**Known limit:** free-form turns between tool calls are held back only by the system prompt.
The backend controls what's said for grounded answers, not every word the model says.

### Setup

Follow [the hands-free test](HANDSFREE_TEST.md). `VapiConfig.plist` is git-ignored and holds
only the **public** key and assistant ID. The system prompt is in
`backend/vapi/assistant_prompt.md`, and `backend/vapi_assistant.py` configures the assistant.

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
  or the phone speaker. Hands-free conversations never use the phone's microphone or speaker
  on purpose. There's no separate DAT audio-output API; the glasses act as a Bluetooth audio
  device.
- The backend must run with `CARVIS_QDRANT_COLLECTION=carvis_specs_v2`. Otherwise it refuses
  specification questions on purpose.
