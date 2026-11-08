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
    }

    private(set) var registrationState: RegistrationState
    private(set) var hasActiveDevice = false
    private(set) var sessionState: DeviceSessionState = .idle
    private(set) var streamState: StreamState = .stopped

    /// The newest video frame from the glasses.
    private(set) var frame: UIImage?

    /// The exact message from Meta's SDK when something fails. Shown as-is.
    var errorMessage: String?

    var status: Status {
        if registrationState == .registering { return .connecting }
        guard registrationState == .registered else { return .notConnected }
        switch streamState {
        case .streaming: return .live
        case .paused: return .paused
        case .starting, .waitingForDevice: return .startingCamera
        case .stopping, .stopped: break
        }
        if sessionState == .starting { return .startingCamera }
        return hasActiveDevice ? .ready : .lookingForGlasses
    }

    var isConnected: Bool { registrationState == .registered }
    var isLive: Bool { streamState == .streaming }

    @ObservationIgnored private let wearables: any WearablesInterface
    @ObservationIgnored private let deviceSelector: AutoDeviceSelector
    @ObservationIgnored private var session: DeviceSession?
    @ObservationIgnored private var camera: MWDATCamera.Camera?
    @ObservationIgnored private let sessionTokens = ListenerTokenBag()
    @ObservationIgnored private let streamTokens = ListenerTokenBag()
    @ObservationIgnored private var tasks: [Task<Void, Never>] = []
    @ObservationIgnored private var wantsPreview = false
    @ObservationIgnored private var photoContinuation: CheckedContinuation<Data, any Error>?

    init(wearables: any WearablesInterface = Wearables.shared) {
        self.wearables = wearables
        self.deviceSelector = AutoDeviceSelector(wearables: wearables)
        self.registrationState = wearables.registrationState

        tasks.append(Task { [weak self] in
            for await state in wearables.registrationStateStream() {
                self?.registrationState = state
            }
        })
        tasks.append(Task { [weak self, deviceSelector] in
            for await device in deviceSelector.activeDeviceStream() {
                guard let self else { return }
                self.hasActiveDevice = device != nil
                // Glasses came back (put on, unfolded): resume video if a screen wants it.
                if device != nil, self.wantsPreview { self.startSessionIfNeeded() }
            }
        })
        tasks.append(Task { [weak self] in
            for await _ in NotificationCenter.default.notifications(named: UIApplication.didEnterBackgroundNotification) {
                // Like the sample: stop the camera in the background to save the glasses' battery.
                self?.tearDown()
            }
        })
    }

    isolated deinit {
        tasks.forEach { $0.cancel() }
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

    /// Call when a screen that shows the camera appears.
    func startPreview() {
        wantsPreview = true
        guard isConnected else { return }
        startSessionIfNeeded()
    }

    /// Call when that screen goes away. Ends the session so the glasses rest.
    func stopPreview() {
        wantsPreview = false
        tearDown()
    }

    private func startSessionIfNeeded() {
        if let session, session.state == .started {
            Task { await startCameraIfAllowed() }
            return
        }
        guard session == nil else { return } // already starting
        do throws(DeviceSessionError) {
            let newSession = try wearables.createSession(deviceSelector: deviceSelector)
            session = newSession
            observe(newSession)
            sessionState = .starting
            try newSession.start()
        } catch {
            errorMessage = error.localizedDescription
            sessionState = .idle
            clearSession()
        }
    }

    private func startCameraIfAllowed() async {
        guard wantsPreview, camera == nil, let session, session.state == .started else { return }
        do {
            var permission = try await wearables.checkPermissionStatus(.camera)
            if permission != .granted {
                // Opens the Meta AI app to ask, then comes back.
                permission = try await wearables.requestPermission(.camera)
            }
            guard permission == .granted else {
                errorMessage = "Camera access was turned down in the Meta AI app."
                return
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        guard wantsPreview, camera == nil, self.session === session, session.state == .started else { return }

        do {
            // Raw frames turn straight into images. Low resolution keeps Bluetooth smooth;
            // photos are taken separately at full quality.
            let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 24)
            guard let newCamera = try session.addCamera(config: config) else {
                errorMessage = "Couldn't start the glasses camera. Try again."
                return
            }
            camera = newCamera
            observe(newCamera.stream)
            streamState = .starting
            newCamera.stream.start()
        } catch {
            camera = nil
            errorMessage = error.localizedDescription
        }
    }

    private func tearDown() {
        failPendingPhoto(with: GlassesError.stopped)
        session?.stop()
    }

    // MARK: - Photos

    /// Takes a JPEG photo with the glasses camera. Needs live video first.
    func capturePhoto() async throws -> Data {
        guard isLive, let stream = camera?.stream else { throw GlassesError.notLive }
        guard photoContinuation == nil else { throw GlassesError.busy }
        return try await withCheckedThrowingContinuation { continuation in
            photoContinuation = continuation
            if !stream.capturePhoto(format: .jpeg) {
                photoContinuation = nil
                continuation.resume(throwing: GlassesError.captureFailed)
            }
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
            Task { @MainActor in self.errorMessage = error.localizedDescription }
        }.store(in: sessionTokens)
    }

    private func sessionChanged(to state: DeviceSessionState, for changed: DeviceSession) {
        guard changed === session else { return }
        sessionState = state
        switch state {
        case .started:
            Task { await startCameraIfAllowed() }
        case .stopped:
            clearSession()
        default:
            break
        }
    }

    private func observe(_ stream: MWDATCamera.Stream) {
        stream.statePublisher.listen { [weak self] state in
            guard let self else { return }
            Task { @MainActor in self.streamChanged(to: state) }
        }.store(in: streamTokens)

        stream.videoFramePublisher.listen { [weak self] videoFrame in
            guard let self else { return }
            // Turn the frame into an image here, off the main thread.
            let image = videoFrame.makeUIImage()
            Task { @MainActor in
                guard let image,
                      UIApplication.shared.applicationState != .background else { return }
                self.frame = image
            }
        }.store(in: streamTokens)

        stream.photoDataPublisher.listen { [weak self] photo in
            guard let self else { return }
            Task { @MainActor in
                self.photoContinuation?.resume(returning: photo.data)
                self.photoContinuation = nil
            }
        }.store(in: streamTokens)

        stream.errorPublisher.listen { [weak self] error in
            guard let self else { return }
            Task { @MainActor in
                if error == .photoCaptureFailed {
                    self.failPendingPhoto(with: GlassesError.captureFailed)
                } else {
                    self.errorMessage = error.localizedDescription
                }
            }
        }.store(in: streamTokens)
    }

    private func streamChanged(to state: StreamState) {
        streamState = state
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
