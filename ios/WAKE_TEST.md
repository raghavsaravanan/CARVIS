# Carvis glasses wake-listener hardware test

This is an armed, foreground-only transcript wake detector. It recognizes **Hi
Carvis** and **Hey Carvis** from Meta glasses speech recognition, then emits
`CarvisWakeListener.wakeDetected` (Combine publisher). It does not start Vapi,
speak a reply, invoke Meta AI, send HTTP, or record the iPhone microphone.

## Implementation and validation status

- Implemented against the **Meta DAT 1.0.1** interfaces; the package version is
  pinned exactly and the Carvis target now links `MWDATSpeech`.
- `GlassesController` owns the sole `DeviceSession`; camera and Speech attach to
  that session. Speech teardown does not stop an active camera. Turning preview
  off intentionally restarts the session in speech-only mode if still armed.
- Only the explicit Arm/Retry action requests DAT `.microphone` permission.
  Resume/reconnect checks permission silently. No phone-microphone fallback exists.
- Tokens are retained before `Speech.start()`. SDK token cancellation is async;
  cleanup finishes before a replacement Speech capability attaches. Old queued
  callbacks are rejected after disarm, background, errors or session replacement.
- Final transcripts only; case/punctuation normalization; the phrase must start
  the transcript; two-second cooldown. Confidence `-1` (unavailable) is accepted.
- Transcript text is ephemeral UI state, cleared on disarm, never logged/saved.
  Xcode logs contain state/event counts, not conversation text.
- Local Swift matcher checks: **17 passed**. Swift syntax parsing and project/
  plist lint passed. These checks do not validate recognition or SDK runtime behavior.
- Full Xcode/iOS build and physical microphone/camera tests: **not executed** on
  this host, which has Command Line Tools selected rather than full Xcode.

## 1. Prepare the real devices and app

1. Use the iPhone already paired with the Ray-Ban Meta Gen 2 glasses. Charge the
   glasses, update their firmware/Meta AI app, unfold and wear them, and confirm
   they are connected in Meta AI.
2. In Wearables Developer Center, enable the app's experimental **Speech**
   capability and microphone access as available for your app/account. Meta says
   this feature supports development/beta testing, not production publication.
   Developer Mode camera success alone does not prove Speech is enabled.
3. Use your existing Meta registration setup. The checked-in plist has placeholder
   `MetaAppID`/`ClientToken`; if a Developer Center-backed registration is needed,
   supply the real values locally through your team's configuration workflow and
   do not commit them. Feature access cannot be fabricated by the listener.
4. Open `ios/Carvis/Carvis.xcodeproj` in **full Xcode**. Resolve packages and verify
   Meta DAT **1.0.1**, with `MWDATCore`, `MWDATCamera`, **MWDATSpeech** linked to the
   Carvis target. Select your signing team and physical iPhone destination.
5. Enable iPhone Developer Mode/trust the computer if Xcode requests it. Build and
   run Carvis. This test does **not** need FastAPI, Qdrant, NVIDIA credentials, or
   a backend network connection.

On a Mac with Xcode installed, a simulator build check can also be attempted with:

```bash
xcodebuild -project ios/Carvis/Carvis.xcodeproj -scheme Carvis \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

Simulator compilation is not a glasses microphone test.

## 2. Verify actual foreground wake events

1. On Carvis's dashboard, open **Glasses wake test**. Tap **Connect glasses** if
   needed, approve registration in Meta AI, and return to Carvis.
2. Keep **Camera preview off** for the initial speech-only test.
3. Tap **Arm wake listener**. Approve the **glasses microphone** permission in Meta
   AI if asked, then return to Carvis. The UI must show permission **granted** and
   state **listening**, with **Listening through the glasses microphone**. Merely
   showing `starting`, `waitingForSession` or `paused` is not a pass.
4. Keep the app visible and stop touching the phone. Say **Hi Carvis**, then pause
   for the SDK to finalize the transcript. The screen must show a final glasses
   transcript, **Detected: Hi Carvis**, and an incremented **wakeDetected events
   received** counter. Xcode's console records `wakeDetected from glasses speech`.
5. Wait at least **two seconds**, then say **Hey Carvis**. Verify a second event.
   Repeat each phrase five times, allowing recognition/finalization between turns.
6. Say unrelated speech, **Hi Carvison**, and **Say Hey Carvis**. None should emit a
   wake event. Only a transcript that starts with the exact two-word wake phrase
   is accepted; approximate spellings are intentionally not guessed.
7. Tap **Disarm**; both phrases must stop producing events. Re-arm and verify they
   work again. Counters are diagnostic and are not reset by disarming.

Recognition is on the glasses via `MWDATSpeech`, not an iOS phone recorder. The
diagnostic screen subscribes to the real publisher; its received-event counter is
separate from the listener's total. There is no simulated transcript injection or
fake success button in the app. For a separate observer's verification, leave the
phone on a stand away from the wearer and watch the event counter while the wearer
speaks normally into the glasses.

There is deliberately **no spoken acknowledgment** in this experiment: TTS could
be transcribed and retrigger the listener. A second person can watch the screen or
Xcode logs while the wearer keeps their hands free.

## 3. Verify camera remains functional while listening

1. While state is **listening**, turn **Camera preview** on. If camera permission
   opens Meta AI, approve and return. Wait for both listening and live preview.
2. Say each wake phrase and verify events while the preview continues updating.
3. Tap **Capture test JPEG**. It must report a nonzero byte count from the actual
   photo callback. No JPEG is stored or uploaded. Wait for completion; repeat five
   times, alternating captures and wake phrases.
4. Turn preview off. Expect a brief shared-session restart, then speech-only
   **listening** again. Verify another wake event. Turn preview back on and repeat.
5. Disarm while preview is on. Confirm the camera continues streaming/capturing
   and wake events stop. Finally return to the dashboard and confirm the existing
   **Ask about a part** camera screen still works.

Record the exact SDK error if Speech or camera refuses concurrent use. A nil
Speech capability, `unavailable`, `startFailed`, stopped session, or missing photo
callback is a failure to investigate, not permission to use the phone microphone.
The SDK can report `photoCaptureFailed` after its own timeout; the UI reports the
failure rather than claiming a capture succeeded merely because it was requested.

## 4. Locked-screen/background result

**Locked-screen wake is not supported by this build.** The controller preserves
its camera background teardown policy and explicitly pauses/detaches Speech when
the app backgrounds. Queued/background transcripts cannot emit a wake event.
The app does not run an always-on service and cannot detect phrases after it has
been terminated. This is an implementation boundary, not a claim that all future
Meta/iOS background designs are impossible.

Verify the boundary on hardware:

1. Arm and confirm one foreground wake event; note the counter.
2. Lock the iPhone and say each phrase. Unlock it without speaking another phrase.
   There must be no newly received events from that locked interval. The listener
   resumes only after Carvis is active again and the glasses session is available.
3. Say a fresh phrase after the state returns to **listening**; it should emit.
4. Repeat by switching to another app, then returning. Leaving the diagnostic
   screen itself disarms it rather than leaving invisible listening active.

Physical locked-screen behavior has **not** been observed by this implementation
session. Report the observed result separately from this intentional policy.

## 5. Disconnect and permission/error checks

- While armed, fold/remove/disconnect the glasses. Confirm listening stops and no
  event can be emitted. Reconnect/unfold with Carvis foreground; verify automatic
  session reattachment, or record the error and use **Retry listening**.
- Deny microphone permission, then Arm. The UI must report failure; it must not
  report listening or substitute phone input. Restore permission and retry.
- If partial transcripts appear but never finalize, or the locale/spelling differs,
  record the visible transcript and locale without publishing private conversation.
  Check Speech/account/firmware support. A final transcript is required for this test.
- If there is no Speech feature in your Developer Center or the SDK reports it
  unavailable, that is an external feature-access blocker, not a successful wake test.

Record iPhone/iOS, glasses firmware, Meta AI version, SDK version, registration
mode, permission result, final transcript, event count, camera result, disconnect
result, and lock/background result before marking the hardware test passed.

## Local deterministic checks

From the repository root:

```bash
swiftc -module-cache-path /tmp/carvis-wake-swift-cache \
  ios/Carvis/Carvis/Glasses/WakePhraseMatcher.swift \
  ios/Tests/WakePhraseMatcherTests.swift -o /tmp/carvis-wake-matcher-tests
/tmp/carvis-wake-matcher-tests
plutil -lint ios/Carvis/Carvis-Info.plist ios/Carvis/Carvis.xcodeproj/project.pbxproj
```

These run the real matching algorithm only. They are not a substitute for the
physical SDK listener, permission, microphone, concurrency or background tests.

## Official API references checked

- [SDK 1.0.1 Speech interfaces](https://github.com/meta/meta-wearables-dat-ios/blob/1.0.1/MWDATSpeech.xcframework/ios-arm64/MWDATSpeech.framework/Modules/MWDATSpeech.swiftmodule/arm64-apple-ios.swiftinterface)
- [SDK 1.0.1 Core interfaces, including async token cancellation and microphone permission](https://github.com/meta/meta-wearables-dat-ios/blob/1.0.1/MWDATCore.xcframework/ios-arm64/MWDATCore.framework/Modules/MWDATCore.swiftmodule/arm64-apple-ios.swiftinterface)
- [Meta Speech guide](https://github.com/meta/meta-wearables-dat-ios/blob/main/plugins/mwdat-ios/skills/speech/SKILL.md)
