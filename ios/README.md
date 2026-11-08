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
| Carvis registration / preview / capture / `/vision-query` / glasses audio | Not yet verified on hardware |

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

## Safety rules the app keeps

- No API keys in the app; Carvis holds them.
- Captured photos stay in memory and are never saved or committed.
- The vehicle is always sent explicitly; the photo never decides which car it is.
- The answer text is shown exactly as Carvis returns it. Refusals ("not in the manual") and
  errors (`{error, component}` and `{detail}`) are shown verbatim, never replaced with a guess.
- The mock oil-change walkthrough contains no torque values, oil amounts, or intervals;
  the WRX oil section isn't loaded, so it points to the service manual instead.
- Spoken answers are labelled with where they played: the glasses' Bluetooth name, or the
  phone speaker as a labelled fallback. There's no separate DAT audio-output API; the glasses
  act as a Bluetooth audio device.
