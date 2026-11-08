import MWDATCamera
import MWDATCore
import Observation
import UIKit

/// Everything Carvis does with the Meta glasses, in one place:
/// connecting them through the Meta AI app, showing live video from their
/// camera, and taking a photo.
///
/// The steps and SDK calls follow Meta's official CameraAccess sample
/// (Wearables Device Access Toolkit 1.0.1). Photos are kept in memory only
/// and are never saved to disk.
@Observable
@MainActor
final class GlassesController {
    /// Where we are in getting video from the glasses, in plain words.
    enum Status: Equatable {
        case notConnected      // Carvis hasn't been allowed to use the glasses yet
        case connecting        // waiting for the Meta AI app to come back
        case lookingForGlasses // allowed, but no glasses are on and nearby
        case ready             // glasses found, camera off
        case startingCamera
        case live              // video is coming in
        case paused            // someone tapped the glasses; tap again to resume
        case needsCameraAccess // waiting for camera approval in the Meta AI app
    }

    private(set) var registrationState: RegistrationState
    private(set) var hasActiveDevice = false
    private(set) var sessionState: DeviceSessionState = .idle
    private(set) var streamState: StreamState = .stopped
    let wakeListener = CarvisWakeListener()
    /// The name the Meta SDK reports for the connected glasses.
    private(set) var activeDeviceName: String?

    /// The newest video frame from the glasses.
    private(set) var frame: UIImage?

    /// The exact message from Meta's SDK when something fails. Shown as-is.
    var errorMessage: String?

    /// True while we wait for camera approval in the Meta AI app.
    private(set) var isAskingForCameraAccess = false

    /// The SDK's own session and camera states, for the small status line.
    var detail: String {
        "Session \(sessionState.description) · camera \(streamStateText)"
    }

    private var streamStateText: String {
        switch streamState {
        case .streaming: "streaming"
        case .starting: "starting"
        case .waitingForDevice: "waiting for glasses"
        case .stopping: "stopping"
        case .stopped: "off"
        case .paused: "paused"
        }
    }

    var status: Status {
        if registrationState == .registering { return .connecting }
        guard registrationState == .registered else { return .notConnected }
        switch streamState {
        case .streaming: return .live
        case .paused: return .paused
        case .starting, .waitingForDevice: return .startingCamera
        case .stopping, .stopped: break
        }
        if isAskingForCameraAccess { return .needsCameraAccess }
        if sessionState == .paused { return .paused }
        if sessionState == .starting || (wantsPreview && sessionState == .started) { return .startingCamera }
        return hasActiveDevice ? .ready : .lookingForGlasses
    }

    var isConnected: Bool { registrationState == .registered }
    var isLive: Bool { streamState == .streaming }

    @ObservationIgnored private let wearables: any WearablesInterface
    @ObservationIgnored private let deviceSelector: AutoDeviceSelector
    @ObservationIgnored private var session: DeviceSession?
    @ObservationIgnored private var camera: MWDATCamera.Camera?
    @ObservationIgnored private var cameraStartSession: DeviceSession?
    @ObservationIgnored private let sessionTokens = ListenerTokenBag()
    @ObservationIgnored private let streamTokens = ListenerTokenBag()
    @ObservationIgnored private var tasks: [Task<Void, Never>] = []
    private var wantsPreview = false
    @ObservationIgnored private var restartAfterStop = false
    @ObservationIgnored private var photoContinuation: CheckedContinuation<Data, any Error>?

    init(wearables: any WearablesInterface = Wearables.shared) {
        self.wearables = wearables
        self.deviceSelector = AutoDeviceSelector(wearables: wearables)
        self.registrationState = wearables.registrationState

        tasks.append(Task { [weak self] in
            for await state in wearables.registrationStateStream() {
                guard let self else { return }
                self.registrationState = state
                if state == .registered {
                    self.startSessionIfNeeded()
                } else {
                    self.tearDown()
                }
            }
        })
        tasks.append(Task { [weak self, deviceSelector] in
            for await device in deviceSelector.activeDeviceStream() {
                guard let self else { return }
                self.hasActiveDevice = device != nil
                self.activeDeviceName = device.flatMap { wearables.deviceForIdentifier($0)?.nameOrId() }
                // Glasses came back (put on, unfolded): resume video if a screen wants it.
                if device != nil {
                    self.startSessionIfNeeded()
                } else {
                    self.tearDown()
                }
            }
        })
        tasks.append(Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(named: UIApplication.didEnterBackgroundNotification) {
                // Foreground-only wake experiment. Lock/background never leaves a
                // stale "listening" indicator or silently switches to the phone mic.
                self?.tearDown()
            }
        })
        tasks.append(Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(named: UIApplication.didBecomeActiveNotification) {
                self?.startSessionIfNeeded()
            }
        })
    }

    isolated deinit {
        tasks.forEach { $0.cancel() }
        wakeListener.disarm()
        session?.stop()
    }

    // MARK: - Connecting

    /// Opens the Meta AI app so you can let Carvis use your glasses.
    func connect() {
        guard registrationState != .registering else { return }
        Task {
            do {
                try await wearables.startRegistration()
            } catch let error as RegistrationError {
                errorMessage = error.description
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    /// The Meta AI app sends you back to Carvis with a link. Hand it to the SDK.
    func handle(url: URL) {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              components.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true
        else { return }
        Task {
            do {
                _ = try await wearables.handleUrl(url)
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    // MARK: - Live video

    /// Explicit user action: only this path may prompt for glasses mic access.
    func armWakeListener() {
        guard isConnected else {
            errorMessage = "Connect the glasses in Meta AI before arming wake detection."
            return
        }
        errorMessage = nil
        Task {
            guard await wakeListener.arm(using: wearables) else { return }
            if session?.state == .paused {
                tearDown(restartForWake: true)
            } else {
                startSessionIfNeeded()
            }
        }
    }

    func disarmWakeListener() {
        wakeListener.disarm()
        if !wantsPreview { tearDown() }
    }

    /// Lets go of glasses speech so a conversation can use the audio. The session and camera
    /// keep running, and this returns only once Speech is fully stopped.
    func releaseWakeListener() async {
        if wakeListener.isArmed { wakeListener.disarm() }
        await wakeListener.finishCleanup()
    }

    /// Call when a screen that shows the camera appears.
    func startPreview() {
        log("start preview (registered: \(isConnected), glasses found: \(hasActiveDevice), session: \(sessionState.description))")
        wantsPreview = true
        guard isConnected else { return }
        startSessionIfNeeded()
    }

    /// Call when that screen goes away. Ends the session so the glasses rest.
    func stopPreview() {
        wantsPreview = false
        // Keep the existing camera's terminal teardown semantics, then create a
        // fresh speech-only session if still armed. No competing SDK sessions.
        tearDown(restartForWake: wakeListener.isArmed)
    }

    private func startSessionIfNeeded() {
        guard UIApplication.shared.applicationState == .active, isConnected, hasActiveDevice,
              wantsPreview || (wakeListener.isArmed && wakeListener.hasMicrophonePermission) else { return }
        if let session {
            if session.state == .started {
                startCapabilities(on: session)
                return
            }
            if session.state == .stopping {
                restartAfterStop = true
                return
            }
            if session.state == .stopped {
                clearSession()
            } else {
                return
            }
        }
        guard session == nil else {
            log("session exists in state \(session?.state.description ?? "?"), waiting")
            return
        }
        do throws(DeviceSessionError) {
            let newSession = try wearables.createSession(deviceSelector: deviceSelector)
            session = newSession
            observe(newSession)
            sessionState = .starting
            try newSession.start()
        } catch {
            log("session error: \(error)")
            errorMessage = error.localizedDescription
            sessionState = .idle
            clearSession()
        }
    }

    private func startCapabilities(on session: DeviceSession) {
        guard self.session === session, session.state == .started, isConnected,
              hasActiveDevice, UIApplication.shared.applicationState == .active else { return }
        Task { await startCameraIfAllowed() }
        Task { await wakeListener.attach(to: session, using: wearables) }
    }

    private func startCameraIfAllowed() async {
        guard UIApplication.shared.applicationState == .active,
              isConnected, hasActiveDevice, wantsPreview, camera == nil,
              let session, session.state == .started, cameraStartSession !== session else { return }
        cameraStartSession = session
        defer {
            if cameraStartSession === session { cameraStartSession = nil }
        }
        do {
            var permission = try await wearables.checkPermissionStatus(.camera)
            log("camera permission: \(permission)")
            if permission != .granted {
                // Opens the Meta AI app to ask, then comes back.
                isAskingForCameraAccess = true
                defer { isAskingForCameraAccess = false }
                permission = try await wearables.requestPermission(.camera)
                log("camera permission after asking: \(permission)")
            }
            guard permission == .granted else {
                errorMessage = "Camera access was turned down in the Meta AI app."
                return
            }
        } catch {
            log("permission error: \(error)")
            errorMessage = error.localizedDescription
            return
        }
        guard UIApplication.shared.applicationState == .active,
              isConnected, hasActiveDevice, wantsPreview, camera == nil,
              self.session === session, session.state == .started else { return }

        do {
            // Raw frames turn straight into images. Low resolution keeps Bluetooth smooth;
            // photos are taken separately at full quality.
            let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 24)
            guard let newCamera = try session.addCamera(config: config) else {
                errorMessage = "Couldn't start the glasses camera. Try again."
                return
            }
            log("camera added, starting stream")
            camera = newCamera
            observe(newCamera.stream)
            streamState = .starting
            newCamera.stream.start()
        } catch {
            camera = nil
            errorMessage = error.localizedDescription
        }
    }

    private func log(_ message: String) {
        print("[Glasses] \(message)")
    }

    private func tearDown(restartForWake: Bool = false) {
        restartAfterStop = restartForWake && UIApplication.shared.applicationState == .active
        wakeListener.suspend("Paused: foreground and connected glasses are required. Locked-screen wake is not supported in this build.")
        failPendingPhoto(with: GlassesError.stopped)
        session?.stop()
    }

    // MARK: - Photos

    /// Takes a JPEG photo with the glasses camera. Needs live video first.
    func capturePhoto(timeout: Duration = .seconds(15)) async throws -> Data {
        guard isLive, let stream = camera?.stream else { throw GlassesError.notLive }
        guard photoContinuation == nil else { throw GlassesError.busy }
        // A photo that never arrives must fail rather than wait forever.
        let watchdog = Task { [weak self] in
            try? await Task.sleep(for: timeout)
            guard !Task.isCancelled else { return }
            self?.failPendingPhoto(with: GlassesError.captureFailed)
        }
        defer { watchdog.cancel() }
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                photoContinuation = continuation
                if Task.isCancelled || !stream.capturePhoto(format: .jpeg) {
                    photoContinuation = nil
                    continuation.resume(throwing: GlassesError.captureFailed)
                }
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.failPendingPhoto(with: GlassesError.captureFailed) }
        }
    }

    private func failPendingPhoto(with error: any Error) {
        photoContinuation?.resume(throwing: error)
        photoContinuation = nil
    }

    // MARK: - Listening to the SDK

    private func observe(_ session: DeviceSession) {
        session.statePublisher.listen { [weak self] state in
            guard let self else { return }
            Task { @MainActor in self.sessionChanged(to: state, for: session) }
        }.store(in: sessionTokens)
        session.errorPublisher.listen { [weak self] error in
            guard let self else { return }
            Task { @MainActor in
                self.log("session error: \(error)")
                self.errorMessage = error.localizedDescription
            }
        }.store(in: sessionTokens)
    }

    private func sessionChanged(to state: DeviceSessionState, for changed: DeviceSession) {
        guard changed === session else { return }
        log("session -> \(state.description)")
        sessionState = state
        switch state {
        case .started:
            startCapabilities(on: changed)
        case .paused:
            wakeListener.sessionPaused()
        case .stopped:
            let shouldRestart = restartAfterStop
            restartAfterStop = false
            clearSession()
            if shouldRestart { startSessionIfNeeded() }
        default:
            break
        }
    }

    private func observe(_ stream: MWDATCamera.Stream) {
        stream.statePublisher.listen { [weak self] state in
            guard let self else { return }
            Task { @MainActor in
                guard self.camera?.stream === stream else { return }
                self.streamChanged(to: state)
            }
        }.store(in: streamTokens)

        stream.videoFramePublisher.listen { [weak self] videoFrame in
            guard let self else { return }
            // Turn the frame into an image here, off the main thread.
            let image = videoFrame.makeUIImage()
            Task { @MainActor in
                guard self.camera?.stream === stream, let image,
                      UIApplication.shared.applicationState != .background else { return }
                self.frame = image
            }
        }.store(in: streamTokens)

        stream.photoDataPublisher.listen { [weak self] photo in
            guard let self else { return }
            Task { @MainActor in
                guard self.camera?.stream === stream else { return }
                self.photoContinuation?.resume(returning: photo.data)
                self.photoContinuation = nil
            }
        }.store(in: streamTokens)

        stream.errorPublisher.listen { [weak self] error in
            guard let self else { return }
            Task { @MainActor in
                guard self.camera?.stream === stream else { return }
                if error == .photoCaptureFailed {
                    self.failPendingPhoto(with: GlassesError.captureFailed)
                } else {
                    self.log("camera error: \(error)")
                    self.errorMessage = error.localizedDescription
                }
            }
        }.store(in: streamTokens)
    }

    private func streamChanged(to state: StreamState) {
        streamState = state
        log("camera -> \(streamStateText)")
        if state == .stopped { clearStream() }
    }

    private func clearStream() {
        streamTokens.clear()
        camera?.stop()
        camera = nil
        streamState = .stopped
        frame = nil
        failPendingPhoto(with: GlassesError.stopped)
    }

    private func clearSession() {
        wakeListener.sessionEnded()
        clearStream()
        sessionTokens.clear()
        session = nil
        sessionState = .idle
    }
}

enum GlassesError: LocalizedError {
    case notLive, busy, captureFailed, stopped

    var errorDescription: String? {
        switch self {
        case .notLive: "Wait for live video from your glasses, then try again."
        case .busy: "Still taking the last photo."
        case .captureFailed: "Couldn't take a photo. Try again in a moment."
        case .stopped: "The glasses camera stopped."
        }
    }
}
