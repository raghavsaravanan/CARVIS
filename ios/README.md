# Phase 1 — Meta CameraAccess bootstrap

This directory intentionally contains the handoff/runbook until Xcode is available. The app must be based on Meta's official sample, not an independently invented SDK wrapper.

Official sources:

- <https://github.com/meta/meta-wearables-dat-ios>
- <https://github.com/meta/meta-wearables-dat-ios/tree/main/samples/CameraAccess>
- <https://wearables.developer.meta.com/docs/develop/>

## Local prerequisite status

The current development host reports no active Xcode developer tools (`xcode-select` cannot locate Xcode), so the project cannot be built or signed from this workspace yet. The official sample currently documents iOS 17.2+, Xcode 26.4+, and Swift 6.3+.

## Continue in Xcode

1. Install the current Xcode release meeting the sample prerequisite and select it with `xcode-select`.
2. Clone/download the official repository and open `samples/CameraAccess/CameraAccess.xcodeproj`.
3. Select the CameraAccess app target, choose the team's Apple development team, and use a unique bundle identifier.
4. Build with `Cmd+B` for an iPhone simulator first. Resolve only signing/dependency/toolchain issues; do not replace Meta SDK calls.
5. For a physical run, enable Developer Mode in the Meta AI app and pair the Ray-Ban Meta Gen 2 glasses.
6. Run on the iPhone. Complete the sample's registration/connect flow. If the release-channel configuration requires it, use the Meta Wearables Developer Center values for `META_APP_ID` and `CLIENT_TOKEN`; never commit them.
7. Tap **Start Session**, then **Preview**. Confirm that the live camera stream is visible.
8. Tap **Capture** and verify that a JPEG is produced and can be previewed/shared by the sample.
9. Background the app while previewing, return to it, and verify the sample returns to a clean idle state before starting again.
10. If prompted, complete the official firmware or app-on-glasses update flow, then repeat steps 7–8.

## Hardware checkpoint

Stop and report these results before adding George networking:

- Xcode version and iOS SDK version;
- iPhone model/iOS version;
- glasses firmware/app status;
- whether registration succeeded;
- whether preview streamed from the glasses;
- whether capture produced a JPEG and its approximate byte size;
- any exact error text or required update.

Do not upload or commit the captured image. The next implementation step is a small George-specific adapter around the sample's already-working capture output.

