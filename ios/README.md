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
| Carvis registration, preview, capture, `/vision-query` | **Works** (e.g. wheel nuts → 120 N·m) |
| Hey Carvis (Apple speech) | Microphone works after the fixes below |
| Vapi conversation | Built; not yet tested (needs the dashboard setup below) |

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

1. **Wake word: glasses first (Meta Speech).** Opening Ask Carvis arms `CarvisWakeListener`,
   which uses the glasses' own speech recognition (`MWDATSpeech`). "Hey Carvis, <question>"
   (or a bare "Hey Carvis", then the question within 8 seconds) fills the question, takes a
   glasses photo, asks `/vision-query`, and speaks the answer. Matching is start-of-sentence
   only and accepts common misses ("Hey Jarvis", "OK Carver", "Hey car vis"); see
   `ios/Tests/WakePhraseMatcherTests.swift` (22 checks). Meta marks Speech as experimental;
   it may need enabling in the Wearables Developer Center. Not yet verified on hardware.
   - **Backup: phone speech.** If glasses speech fails (or the glasses aren't connected),
     Apple speech recognition takes over and the row says so. It uses CameraAccess's audio
     setup (`.playAndRecord`, `.videoRecording`, `[.allowBluetoothHFP, .mixWithOthers]`).
     Error `561017449` (`!pri`) means another app holds the mic, usually a call. End it.
   - Meta's toolkit doesn't allow custom wake words outside the app ("Hey Meta" is
     system-owned), so this only works with Carvis open on the Ask screen.
2. **Conversation (Vapi).** If `Carvis/Config/VapiConfig.plist` has a public key and assistant
   ID, "Hey Carvis, …" stops the wake-word listener (it frees the mic) and starts a Vapi call
   with the [Vapi iOS SDK](https://github.com/VapiAI/client-sdk-ios), pinned to commit
   `5fdb73d` because it has no release tags. The question said with the wake word is sent as
   the first user message. When the call ends, the wake-word listener starts again.
   Without the file, Carvis answers one question at a time with its built-in voice.

### Vapi setup (team dashboard)

Copy `Carvis/Config/VapiConfig.example.plist` to `VapiConfig.plist` and fill in the **public**
key and assistant ID. `VapiConfig.plist` is git-ignored. The app sends the vehicle as
`variableValues` and `metadata`: `year`, `make`, `model`, `vehicle`, `session_id`.

The assistant needs (verify these in the Vapi dashboard; they're not testable from this repo):

- **`lookup_spec`**, the existing server tool pointing at `/vapi-tool` with the
  `X-Vapi-Secret` header, for spoken spec questions.
- **`look_at_part`**, a function tool with **no server URL**, so Vapi sends the call to the
  app. Parameter: `question` (string). The app takes a glasses photo, asks `/vision-query`,
  and adds the result to the conversation as a system message. Mark it async, so the call
  doesn't wait for a server reply.
- Client messages that include `transcript`, `speech-update` and `tool-calls`.
- A system prompt along these lines:

  > You are Carvis, a hands-free assistant for a mechanic working on a {{vehicle}}. Never
  > guess the vehicle. For any torque value, fluid amount, part number, procedure or safety
  > step, call `lookup_spec`, or `look_at_part` when the mechanic refers to something they're
  > looking at ("this", "that bolt"). Say tool results exactly; never add, round or invent a
  > number. If a tool says it's not in the manual, say so plainly. Keep answers to one or two
  > sentences.

Open questions to check on hardware: whether Vapi's audio (Daily WebRTC) routes to the glasses
when they're connected, and whether `add-message` triggers a spoken reply right away.

## Safety rules the app keeps

- No backend API keys in the app; the Carvis backend holds them. The only Vapi value in the
  app is the client-side public key, kept out of git.
- Captured photos stay in memory and are never saved or committed.
- The vehicle is always sent explicitly; the photo never decides which car it is.
- The answer text is shown exactly as Carvis returns it. Refusals ("not in the manual") and
  errors (`{error, component}` and `{detail}`) are shown verbatim, never replaced with a guess.
- The mock oil-change walkthrough contains no torque values, oil amounts, or intervals;
  the WRX oil section isn't loaded, so it points to the service manual instead.
- Spoken answers are labelled with where they played: the glasses' Bluetooth name, or the
  phone speaker as a labelled fallback. There's no separate DAT audio-output API; the glasses
  act as a Bluetooth audio device.
