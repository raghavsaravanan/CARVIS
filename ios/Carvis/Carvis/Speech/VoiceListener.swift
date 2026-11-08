import AVFoundation
import Observation
import Speech

/// Listens for "Hey Carvis" followed by a question, using Apple's speech
/// recognition (on the phone, on-device when supported). The microphone is the
/// glasses' Bluetooth mic, set up the same way as Meta's CameraAccess sample.
/// If that mic isn't available it stops and says so; it never uses the phone's mic.
///
/// It only listens while it's turned on and Carvis is open. Nothing is recorded
/// or saved: audio goes straight to the recognizer.
@Observable
@MainActor
final class VoiceListener {
    enum State: Equatable {
        case off
        case starting
        case listening        // waiting for "Hey Carvis"
        case hearingQuestion  // heard the wake phrase, taking down the question
        case paused           // answering; not listening so it won't hear itself
        case unavailable(String)
    }

    /// A question heard after "Hey Carvis". A new value each time, even for the same words.
    struct Heard: Equatable {
        let id = UUID()
        let text: String
    }

    private(set) var state: State = .off {
        didSet { if oldValue != state { onStateChange?(state) } }
    }
    @ObservationIgnored var onStateChange: ((State) -> Void)?
    /// What it's hearing right now: the question so far, after the wake phrase.
    private(set) var transcript = ""
    private(set) var heard: Heard?
    /// The Bluetooth mic in use (your glasses), or nil for the phone's mic.
    private(set) var microphoneName: String?

    var isOn: Bool {
        switch state {
        case .off, .unavailable: false
        default: true
        }
    }

    @ObservationIgnored private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    @ObservationIgnored private let engine = AVAudioEngine()
    @ObservationIgnored private let requestBox = RequestBox()
    @ObservationIgnored private var task: SFSpeechRecognitionTask?
    @ObservationIgnored private var taskID = 0
    @ObservationIgnored private var silenceTimer: Task<Void, Never>?
    @ObservationIgnored private var restartTimer: Task<Void, Never>?
    @ObservationIgnored private var routeObserver: (any NSObjectProtocol)?
    @ObservationIgnored private var attempts = 0
    /// Called with each question heard after "Hey Carvis".
    @ObservationIgnored var onHeard: ((String) -> Void)?

    // MARK: - Turning it on and off

    func start() async {
        guard !isOn else { return }
        attempts += 1
        state = .starting

        guard await Self.requestSpeechPermission() == .authorized else {
            state = .unavailable("Allow speech recognition for Carvis in Settings.")
            return
        }
        guard await AVAudioApplication.requestRecordPermission() else {
            state = .unavailable("Allow microphone access for Carvis in Settings.")
            return
        }
        guard let recognizer, recognizer.isAvailable else {
            state = .unavailable("Speech recognition isn't available right now.")
            return
        }
        do {
            try await useGlassesMicrophone()
            guard state == .starting else { return }  // turned off while starting
            try startEngine()
        } catch {
            print("[Voice] mic start failed: \(error)")
            stopEngine()
            // Audio can be briefly busy right after the camera starts. Try once more.
            if attempts < 2 {
                state = .off
                try? await Task.sleep(for: .seconds(1))
                await start()
                return
            }
            attempts = 0  // so tapping the switch gets a fresh try
            state = .unavailable(error is VoiceError ? error.localizedDescription : "Couldn't start the microphone: \(error.localizedDescription)")
            return
        }
        observeRouteChanges()
        attempts = 0
        print("[Voice] listening, mic: \(microphoneName ?? "none"), on-device: \(recognizer.supportsOnDeviceRecognition)")
        state = .listening
        beginRecognition()
    }

    func stop() {
        stopRecognition()
        guard !AudioOwnership.conversationOwnsAudio else { return }
        AudioSessionQueue.runDetached {
            let session = AVAudioSession.sharedInstance()
            try? session.setActive(false, options: .notifyOthersOnDeactivation)
            try? session.setCategory(.playback, mode: .spokenAudio)
        }
    }

    /// Hands the microphone over to a conversation. Returns once iOS has let go of it.
    func stopAndRelease() async {
        let wasOn = state != .off
        stopRecognition()
        guard wasOn else { return }
        _ = try? await AudioSessionQueue.run {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private func stopRecognition() {
        attempts = 0
        endRecognition()
        stopEngine()
        if let routeObserver { NotificationCenter.default.removeObserver(routeObserver) }
        routeObserver = nil
        state = .off
        transcript = ""
        microphoneName = nil
    }

    /// Stop listening while Carvis answers, so it doesn't hear itself.
    func pause() {
        guard isOn, state != .paused else { return }
        endRecognition()
        transcript = ""
        state = .paused
    }

    func resume() {
        guard state == .paused else { return }
        state = .listening
        beginRecognition()
    }

    // MARK: - Audio

    private func useGlassesMicrophone() async throws {
        microphoneName = try await AudioSessionQueue.run {
            let session = AVAudioSession.sharedInstance()
            // Meta's CameraAccess setup (AudioInputHandler.configureBluetooth).
            try session.setCategory(.playAndRecord, mode: .videoRecording, options: [.allowBluetoothHFP, .mixWithOthers])
            try session.setActive(true)
            // The glasses' Bluetooth microphone or nothing. The phone's mic is never used.
            guard let glasses = session.availableInputs?.first(where: { $0.portType == .bluetoothHFP }) else {
                throw VoiceError.noGlassesMicrophone
            }
            try session.setPreferredInput(glasses)
            print("[Voice] route: \(session.currentRoute.inputs.map(\.portName)) -> \(session.currentRoute.outputs.map(\.portName))")
            guard let active = session.currentRoute.inputs.first(where: { $0.portType == .bluetoothHFP }) else {
                throw VoiceError.noGlassesMicrophone
            }
            return active.portName
        }
    }

    private func startEngine() throws {
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else { throw VoiceError.noMicrophone }
        Self.installTap(on: input, format: format, box: requestBox)
        engine.prepare()
        try engine.start()
    }

    private func stopEngine() {
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
    }

    /// Glasses connected or disconnected: restart the mic on the new route.
    private func observeRouteChanges() {
        guard routeObserver == nil else { return }
        routeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main
        ) { [weak self] note in
            let reason = (note.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt)
                .flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
            guard let self, reason == .newDeviceAvailable || reason == .oldDeviceUnavailable else { return }
            Task { @MainActor in await self.restartMicrophone() }
        }
    }

    private func restartMicrophone() async {
        guard isOn else { return }
        stopEngine()
        do {
            try await useGlassesMicrophone()
            guard isOn else { return }
            try startEngine()
        } catch {
            endRecognition()
            state = .unavailable("The microphone stopped: \(error.localizedDescription)")
        }
    }

    // MARK: - Recognition

    private func beginRecognition() {
        guard let recognizer else { return }
        endRecognition()

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.contextualStrings = ["Carvis", "Hey Carvis"]
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        requestBox.set(request)

        taskID += 1
        let id = taskID
        task = Self.startTask(recognizer: recognizer, request: request) { [weak self] text, isFinal, failed in
            guard let self else { return }
            Task { @MainActor in self.handle(text: text, isFinal: isFinal, failed: failed, id: id) }
        }

        // Apple limits one recognition to about a minute, so start fresh while idle.
        restartTimer = Task { [weak self] in
            try? await Task.sleep(for: .seconds(45))
            guard let self, !Task.isCancelled, self.taskID == id, self.state == .listening else { return }
            self.beginRecognition()
        }
    }

    private func endRecognition() {
        silenceTimer?.cancel()
        restartTimer?.cancel()
        taskID += 1  // ignore anything the old task still sends
        requestBox.set(nil)?.endAudio()
        task?.cancel()
        task = nil
    }

    private func handle(text: String?, isFinal: Bool, failed: Bool, id: Int) {
        guard id == taskID, state == .listening || state == .hearingQuestion else { return }
        if let text { print("[Voice] heard: \(text)") }

        if let text, let question = Self.question(afterWakePhraseIn: text) {
            state = .hearingQuestion
            transcript = question
            waitForSilence(id: id)
        }

        if isFinal || failed {
            if state == .hearingQuestion {
                finishQuestion()
            } else {
                // Nothing said, or it timed out: start listening again after a breath.
                restartTimer?.cancel()
                restartTimer = Task { [weak self] in
                    try? await Task.sleep(for: .milliseconds(400))
                    guard let self, !Task.isCancelled, self.state == .listening else { return }
                    self.beginRecognition()
                }
            }
        }
    }

    /// The question is done when you stop talking. Just "Hey Carvis" waits longer for the rest.
    private func waitForSilence(id: Int) {
        silenceTimer?.cancel()
        // A bare "Hey Carvis" starts the conversation almost at once.
        let pause: Duration = transcript.isEmpty ? .milliseconds(1100) : .milliseconds(1500)
        silenceTimer = Task { [weak self] in
            try? await Task.sleep(for: pause)
            guard let self, !Task.isCancelled, self.taskID == id, self.state == .hearingQuestion else { return }
            self.finishQuestion()
        }
    }

    private func finishQuestion() {
        let question = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        endRecognition()
        transcript = ""
        state = .paused  // resumes only after the conversation has completely ended
        heard = Heard(text: question)
        onHeard?(question)
    }

    // MARK: - Wake phrase

    /// "Carvis" isn't a dictionary word, so the recognizer often hears a near miss.
    private static let wakePattern = try! NSRegularExpression(
        pattern: #"\b(?:hey|hi|hay|ok|okay)[\s,.!]+(?:car\s?vis|carvis|jarvis|carvas|carves|carvus|cervis|garvis|kervis|carbis|carver|car this)\b[\s,.!?]*"#,
        options: [.caseInsensitive]
    )

    /// The words after the last "Hey Carvis", or nil if it wasn't said.
    static func question(afterWakePhraseIn text: String) -> String? {
        let range = NSRange(text.startIndex..., in: text)
        guard let match = wakePattern.matches(in: text, range: range).last,
              let end = Range(match.range, in: text)?.upperBound
        else { return nil }
        return String(text[end...]).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - Off the main thread

    // These run on audio and speech threads, so they stay outside the main actor.

    private nonisolated static func installTap(on input: AVAudioInputNode, format: AVAudioFormat, box: RequestBox) {
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            box.append(buffer)
        }
    }

    private nonisolated static func startTask(
        recognizer: SFSpeechRecognizer,
        request: SFSpeechAudioBufferRecognitionRequest,
        onResult: @escaping @Sendable (String?, Bool, Bool) -> Void
    ) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            if let error { print("[Voice] recognition ended: \(error.localizedDescription)") }
            onResult(result?.bestTranscription.formattedString, result?.isFinal ?? false, error != nil)
        }
    }

    private nonisolated static func requestSpeechPermission() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
    }
}

/// Hands mic audio from the audio thread to whichever recognition request is current.
private final class RequestBox: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    @discardableResult
    func set(_ new: SFSpeechAudioBufferRecognitionRequest?) -> SFSpeechAudioBufferRecognitionRequest? {
        lock.withLock {
            let old = request
            request = new
            return old
        }
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.withLock { request }?.append(buffer)
    }
}

private enum VoiceError: LocalizedError {
    case noMicrophone
    case noGlassesMicrophone
    var errorDescription: String? {
        switch self {
        case .noMicrophone: "No microphone is available."
        case .noGlassesMicrophone: "Your glasses' microphone isn't connected to this iPhone."
        }
    }
}
