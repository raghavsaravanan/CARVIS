import AVFoundation
import Combine
import Foundation
import Observation
import SwiftUI
import UIKit

/// Presents the current glasses entry path and camera state to SwiftUI.
/// One instance, above the views.
///
/// VoiceSessionController owns the provider, server call, and injected audio route;
/// ConversationMachine defines the transitions. Meta supplies wake and camera events here.
@Observable
@MainActor
final class CarvisConversationCoordinator {
    /// A typed question on the Ask screen (Snap and ask).
    enum Phase: Equatable {
        case idle
        case capturing
        case asking
        case result(VisionResult)
        case failed(String)
    }

    enum Reason: Hashable { case job, askScreen }
    enum WakeSource { case glassesSpeech, glassesBluetooth }
    enum CameraWork { case idle, capturing, identifying }
    enum VoiceMode { case glasses, phone }
    enum PhoneCallState: Equatable {
        case idle, connecting, listening, speaking, reconnecting(String), ending, ended, failed(String)

        var title: String {
            switch self {
            case .idle: "Ready to talk"
            case .connecting: "Connecting"
            case .listening: "Listening"
            case .speaking: "Carvis is speaking"
            case .reconnecting: "Checking audio route"
            case .ending: "Ending call"
            case .ended: "Call ended"
            case .failed: "Call failed"
            }
        }

        var detail: String {
            switch self {
            case .idle: "Use your iPhone or a connected headset."
            case .connecting: "Starting Vapi and checking the microphone and speaker."
            case .listening: "Ask your question."
            case .speaking: "You can speak to interrupt."
            case .reconnecting(let reason), .failed(let reason): reason
            case .ending: "Releasing the call audio."
            case .ended: "Tap to start another conversation."
            }
        }
    }

    // MARK: State the screens show

    var question = ""
    private(set) var phase: Phase = .idle
    /// The photo behind the latest answer. Cleared back to live video after a while.
    var photo: UIImage?
    private(set) var askedQuestion: String?
    private(set) var spokenThrough: String?
    private(set) var machine = ConversationMachine()
    private(set) var wakeSource: WakeSource = .glassesSpeech
    private(set) var cameraWork: CameraWork = .idle
    private(set) var voiceMode: VoiceMode = .glasses
    private(set) var phoneOutcome: PhoneCallState = .idle
    /// What the server currently holds as true, refreshed during a call.
    private(set) var serverState: ConversationState?
    private(set) var reasons: Set<Reason> = []
    /// Why the last conversation failed, shown until the next "Hey Carvis".
    private(set) var lastFailure: String?

    var voiceOn: Bool {
        didSet { UserDefaults.standard.set(voiceOn, forKey: Self.voiceKey) }
    }

    let listener = VoiceListener()
    let agent: VapiAgent?
    let glasses: GlassesController

    var conversationPhase: ConversationPhase { machine.phase }
    var isInConversation: Bool { machine.isInCallPhase }
    var client: CarvisVisionClient? { accounts.visionClient }
    var vehicle: Vehicle? { garage.profile.vehicle }
    var isActive: Bool { !reasons.isEmpty }
    var isWorking: Bool { phase == .capturing || phase == .asking || cameraWork != .idle }
    var wake: CarvisWakeListener { glasses.wakeListener }
    var isPhoneCallVisible: Bool { voiceMode == .phone }
    var phoneCallState: PhoneCallState {
        guard voiceMode == .phone else { return phoneOutcome }
        switch conversationPhase {
        case .releasingWake, .startingCall, .verifyingRoute: return .connecting
        case .inCall:
            switch agent?.state {
            case .speaking: return .speaking
            case .listening: return .listening
            case .failed(let reason): return .failed(reason)
            default: return .connecting
            }
        case .routeLost(let reason): return .reconnecting(reason)
        case .endingCall, .shuttingDown: return .ending
        default: return phoneOutcome
        }
    }

    // MARK: Private

    @ObservationIgnored private let accounts: AccountStore
    @ObservationIgnored private let chats: ChatHistory
    @ObservationIgnored private let garage: CarProfileStore
    @ObservationIgnored private let speech: SystemSpeechOutput
    @ObservationIgnored private var voiceSession: VoiceSessionController?
    @ObservationIgnored private var metaAudioRoute: MetaGlassesAudioRoute?
    @ObservationIgnored private var phoneAudioRoute: PhoneAudioRoute?
    @ObservationIgnored private let cue = ThinkingCue()
    @ObservationIgnored private var sessionID = UUID().uuidString
    @ObservationIgnored private var cancellables = Set<AnyCancellable>()
    @ObservationIgnored private var cameraTask: Task<Void, Never>?
    @ObservationIgnored private var stateTask: Task<Void, Never>?
    @ObservationIgnored private var backToLiveTask: Task<Void, Never>?
    /// Set once Meta's Speech has failed in this session, so it isn't retried on every wake.
    @ObservationIgnored private var glassesSpeechFailed = false
    /// Starts a bare "Hey Carvis" without waiting for the glasses to finish the sentence.
    @ObservationIgnored private var earlyWake: Task<Void, Never>?
    @ObservationIgnored private var wakeTime: ContinuousClock.Instant?
    private static let voiceKey = "carvis.voiceOn"

    private var api: ConversationClient? { client.map { ConversationClient(baseURL: $0.baseURL) } }

    init(glasses: GlassesController, accounts: AccountStore, chats: ChatHistory,
         garage: CarProfileStore, speech: SystemSpeechOutput) {
        self.glasses = glasses
        self.accounts = accounts
        self.chats = chats
        self.garage = garage
        self.speech = speech
        UserDefaults.standard.register(defaults: [Self.voiceKey: true])
        self.voiceOn = UserDefaults.standard.bool(forKey: Self.voiceKey)
        self.agent = VapiConfig.load().map(VapiAgent.init)
        if !voiceOn { _ = machine.handle(.mute) }

        if let agent {
            let glassesRoute = MetaGlassesAudioRoute(glasses: glasses, provider: agent)
            metaAudioRoute = glassesRoute
            phoneAudioRoute = PhoneAudioRoute(provider: agent)
            let session = VoiceSessionController(provider: agent, route: glassesRoute)
            session.onEvent = { [weak self] event in
                guard let self else { return }
                switch event {
                case .connected: self.mark("assistant connected"); self.send(.callConnected)
                case .ended(let error): self.send(.callEnded(error: error))
                case .startFailed(let reason): self.send(.callStartFailed(reason))
                case .routeReady: self.mark("route verified"); self.send(.routeVerified)
                case .routeLost(let reason): self.send(.routeLost(reason))
                case .shutdownComplete:
                    if self.voiceMode == .phone {
                        self.send(.deactivate)
                        self.voiceMode = .glasses
                        if let glassesRoute = self.metaAudioRoute { _ = self.voiceSession?.selectRoute(glassesRoute) }
                        self.send(.shutdownComplete)
                        if self.isActive {
                            self.voiceSession?.activate(backend: self.api,
                                                        ownerName: self.accounts.account?.name ?? "",
                                                        vehicle: self.vehicle)
                            self.glasses.startPreview()
                            self.send(.activate)
                        } else {
                            self.finishDeactivating()
                        }
                    } else {
                        self.send(.shutdownComplete)
                        if !self.isActive { self.finishDeactivating() }
                    }
                }
            }
            session.onCallStarted = { [weak self] handle, generation in
                self?.startCameraLoop(handle: handle, generation: generation)
                self?.startStatePolling(handle: handle)
            }
            session.onState = { [weak self] state in self?.serverState = state }
            voiceSession = session
        }

        let wake = glasses.wakeListener
        wake.wakeDetected
            .sink { [weak self] _ in self?.heardWakeOnGlasses() }
            .store(in: &cancellables)
        wake.stateUpdates
            .sink { [weak self] state in self?.glassesSpeechChanged(state) }
            .store(in: &cancellables)
        wake.transcripts
            .sink { [weak self] heard in self?.glassesTranscript(heard) }
            .store(in: &cancellables)
        listener.onHeard = { [weak self] text in
            guard let self, self.wakeSource == .glassesBluetooth else { return }
            self.wakeHeard(question: text)
        }
        listener.onStateChange = { [weak self] state in self?.bluetoothRecognitionChanged(state) }
        watch({ [weak self] in self?.glasses.isConnected }) { [weak self] _ in
            self?.retryWakeIfWaiting()
            self?.voiceSession?.refreshRoute()
        }
        watch({ [weak self] in self?.garage.profile.vehicle }) { [weak self] _ in self?.retryWakeIfWaiting() }
        NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)
            .sink { [weak self] _ in
                guard let self, self.isPhoneCallVisible else { return }
                self.endConversation()
            }
            .store(in: &cancellables)
    }

    // MARK: - On and off

    func activate(_ reason: Reason) {
        let wasActive = isActive
        reasons.insert(reason)
        guard voiceMode == .glasses else { return }
        guard !wasActive else { return }
        sessionID = UUID().uuidString
        serverState = nil
        glassesSpeechFailed = false
        voiceSession?.activate(backend: api, ownerName: accounts.account?.name ?? "", vehicle: vehicle)
        glasses.startPreview()   // the camera stays live so Carvis can see what you see
        send(.activate)
    }

    func deactivate(_ reason: Reason) {
        reasons.remove(reason)
        if voiceMode == .phone {
            if !isActive { glasses.stopPreview() }
            return
        }
        guard !isActive else { return }
        send(.deactivate)
        if !isInConversation, conversationPhase != .shuttingDown { finishDeactivating() }
    }

    private func finishDeactivating() {
        glasses.stopPreview()
        speech.stop()
        backToLiveTask?.cancel()
        photo = nil
        phase = .idle
    }

    /// Mute or unmute "Hey Carvis". If it couldn't start, tapping tries again.
    func toggleVoice() {
        guard voiceMode == .glasses else { return }
        print("[Conversation] touch: voice control")
        if case .waiting = conversationPhase {
            startWake()
            return
        }
        voiceOn.toggle()
        send(voiceOn ? .unmute : .mute)
    }

    func endConversation() {
        print("[Conversation] touch: end conversation")
        if voiceMode == .phone { phoneOutcome = .ended }
        send(.userEnded)
    }

    /// A tap starts a Vapi call without arming Meta or requiring a wake phrase.
    func startPhoneConversation() {
        guard !isPhoneCallVisible else { return }
        guard conversationPhase != .shuttingDown else { return }
        guard !machine.isInCallPhase, conversationPhase != .releasingWake else {
            phoneOutcome = .failed("Finish the current conversation first.")
            return
        }
        guard let voiceSession, let phoneAudioRoute, agent != nil else {
            phoneOutcome = .failed("Add your Vapi public key and assistant ID to start voice calls.")
            return
        }
        guard vehicle != nil else {
            phoneOutcome = .failed("Add your car's year, make, and model first.")
            return
        }
        guard api != nil else {
            phoneOutcome = .failed("Set a Carvis server address first.")
            return
        }
        guard voiceSession.selectRoute(phoneAudioRoute) else {
            phoneOutcome = .failed("Finish the current conversation first.")
            return
        }
        earlyWake?.cancel()
        earlyWake = nil
        speech.stop()
        phoneOutcome = .idle
        voiceMode = .phone
        if !isActive {
            voiceSession.activate(backend: api, ownerName: accounts.account?.name ?? "", vehicle: vehicle)
        }
        send(.startDirectCall)
    }

    /// Show live video again instead of the last photo.
    func backToLive() {
        backToLiveTask?.cancel()
        photo = nil
        if !isWorking { phase = .idle }
        speech.stop()
    }

    // MARK: - State machine

    private func send(_ event: ConversationEvent) {
        switch event {
        case .wake: lastFailure = nil
        case .callStartFailed(let reason):
            lastFailure = reason
            if voiceMode == .phone { phoneOutcome = .failed(reason) }
        case .callEnded(let error):
            if let error { lastFailure = error }
            if voiceMode == .phone { phoneOutcome = error.map(PhoneCallState.failed) ?? .ended }
        default: break
        }
        let before = machine.phase
        let effects = machine.handle(event)
        if machine.phase != before { print("[Conversation] \(before) -> \(machine.phase)") }
        effects.forEach(run)
    }

    private func run(_ effect: ConversationEffect) {
        switch effect {
        case .startWake: startWake()
        case .stopWake: stopWake()
        case .releaseWake: releaseWake()
        case .startCall(let question):
            voiceSession?.start(backend: api, ownerName: accounts.account?.name ?? "",
                                vehicle: vehicle, openingQuestion: question)
        case .verifyRoute: voiceSession?.verifyRoute()
        case .setMicMuted(let muted): voiceSession?.setMicrophoneMuted(muted)
        case .deliverQuestion(let question): voiceSession?.deliver(question: question)
        case .endCall: voiceSession?.end()
        case .shutdownCall: shutdownCall()
        }
    }

    // MARK: - Wake word

    private func startWake() {
        guard voiceMode == .glasses else { return }
        guard agent != nil else {
            send(.wakeUnavailable("Add your Vapi keys to start conversations."))
            return
        }
        guard vehicle != nil else {
            send(.wakeUnavailable("Add your car's year, make, and model first."))
            return
        }
        guard glasses.isConnected else {
            send(.wakeUnavailable("Connect your glasses."))
            return
        }
        if glassesSpeechFailed {
            wakeSource = .glassesBluetooth
            Task { await listener.start() }
            return
        }
        wakeSource = .glassesSpeech
        glasses.armWakeListener()
    }

    private func stopWake() {
        glasses.disarmWakeListener()
        listener.stop()
    }

    private func retryWakeIfWaiting() {
        guard isActive, voiceOn, case .waiting = conversationPhase else { return }
        startWake()
    }

    private func glassesSpeechChanged(_ state: CarvisWakeListener.State) {
        guard isActive, voiceMode == .glasses, wakeSource == .glassesSpeech else { return }
        switch state {
        case .listening:
            print("[Conversation] listening through glasses speech")
            send(.wakeReady)
        case .failed:
            // Meta's Speech isn't available here. The glasses' Bluetooth mic can still hear
            // the wake phrase through Apple recognition. Never the phone's mic.
            print("[Conversation] glasses speech failed: \(wake.errorMessage ?? "unknown"); using the glasses' Bluetooth mic")
            guard conversationPhase == .arming || conversationPhase == .listening else { return }
            glassesSpeechFailed = true
            wakeSource = .glassesBluetooth
            glasses.disarmWakeListener()
            Task { await listener.start() }
        case .paused:
            send(.wakeUnavailable("Put your glasses on and keep Carvis open."))
        case .disarmed, .requestingPermission, .waitingForSession, .starting, .stopping:
            break
        }
    }

    private func bluetoothRecognitionChanged(_ state: VoiceListener.State) {
        guard isActive, voiceMode == .glasses, wakeSource == .glassesBluetooth else { return }
        switch state {
        case .listening:
            print("[Conversation] listening through the glasses' Bluetooth mic, \(listener.microphoneName ?? "?")")
            send(.wakeReady)
        case .unavailable(let reason):
            send(.wakeUnavailable(reason))
        default:
            break
        }
    }

    /// The glasses take a moment to finish a sentence. If they've heard only "Hey Carvis" and
    /// nothing more follows shortly, start now. Any further words cancel this and wait for
    /// the finished sentence, so a question said in one breath is kept.
    private func glassesTranscript(_ heard: CarvisWakeListener.Heard) {
        earlyWake?.cancel()
        earlyWake = nil
        guard !heard.isFinal, conversationPhase == .listening, wakeSource == .glassesSpeech,
              WakePhraseMatcher.question(after: heard.text) == "" else { return }
        earlyWake = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(450))
            guard let self, !Task.isCancelled else { return }
            self.earlyWake = nil
            self.wakeHeard(question: "")
        }
    }

    /// The glasses report the wake on a finished sentence, so the transcript already holds
    /// anything said after "Hey Carvis".
    private func heardWakeOnGlasses() {
        wakeHeard(question: WakePhraseMatcher.question(after: wake.lastTranscript) ?? "")
    }

    /// A bare "Hey Carvis" starts the call straight away. Anything said after it travels
    /// with the call and is delivered once.
    private func wakeHeard(question: String) {
        guard voiceMode == .glasses else { return }
        print("[Conversation] wake heard, question: \(!question.isEmpty)")
        wakeTime = .now
        send(.wake(question: question.isEmpty ? nil : question))
    }

    // MARK: - Handing over the audio

    private func releaseWake() {
        // From here until the call is fully over, nothing else may change the audio setup.
        AudioOwnership.conversationOwnsAudio = true
        speech.stop()
        Task {
            await glasses.releaseWakeListener()   // the camera keeps running
            await listener.stopAndRelease()
            print("[Conversation] wake listeners released")
            mark("wake released")
            send(.wakeReleased)
        }
    }

    // MARK: - Camera commands from the server

    private func startCameraLoop(handle: ConversationHandle, generation: Int) {
        guard let api else { return }
        cameraTask = Task { [weak self] in
            var seen = Set<String>()
            while !Task.isCancelled {
                do {
                    guard let command = try await api.nextCameraCommand(handle) else { continue }
                    guard !Task.isCancelled, command.generation == generation, seen.insert(command.requestID).inserted else { continue }
                    await self?.fulfill(command, handle: handle, api: api)
                } catch {
                    if Task.isCancelled { return }
                    print("[Conversation] camera channel: \(error)")
                    try? await Task.sleep(for: .seconds(1))
                }
            }
        }
    }

    /// Takes a new photo for this command. The cue plays only while this work is happening.
    private func fulfill(_ command: CameraCommand, handle: ConversationHandle, api: ConversationClient) async {
        print("[Conversation] camera command \(command.requestID.prefix(8)), \(Int(command.secondsRemaining))s left")
        if voiceMode == .phone && !glasses.isConnected {
            try? await api.reportCameraFailure(handle, requestID: command.requestID,
                                               reason: "Glasses camera unavailable for this phone call.")
            return
        }
        cue.start()
        cameraWork = .capturing
        defer {
            cue.stop()
            cameraWork = .idle
        }
        do {
            let jpeg = try await glasses.capturePhoto(timeout: .seconds(min(max(command.secondsRemaining - 8, 3), 15)))
            try Task.checkCancellation()
            print("[Conversation] captured \(jpeg.count) bytes")
            photo = UIImage(data: jpeg)
            cameraWork = .identifying
            try await api.uploadPhoto(handle, requestID: command.requestID, jpeg: jpeg, timeout: command.secondsRemaining)
            try Task.checkCancellation()
            print("[Conversation] photo identified")
            scheduleBackToLive()
        } catch is CancellationError {
            // A stopped call must not publish a photo or report a new camera failure.
        } catch let error as ConversationAPIError where error.isStale {
            print("[Conversation] photo no longer wanted")
        } catch {
            guard !Task.isCancelled else { return }
            print("[Conversation] camera failed: \(error.localizedDescription)")
            try? await api.reportCameraFailure(handle, requestID: command.requestID, reason: error.localizedDescription)
        }
    }

    private func startStatePolling(handle: ConversationHandle) {
        guard let api else { return }
        stateTask = Task { [weak self] in
            while !Task.isCancelled {
                if let state = try? await api.state(handle), !Task.isCancelled { self?.serverState = state }
                try? await Task.sleep(for: .seconds(1.5))
            }
        }
    }

    // MARK: - Shutdown

    /// Camera work is cancelled before the route and server generation are released.
    private func shutdownCall() {
        let camera = cameraTask
        cameraTask = nil
        camera?.cancel()
        stateTask?.cancel()
        stateTask = nil
        cue.stop()
        cameraWork = .idle
        Task {
            await camera?.value
            voiceSession?.shutdown()
        }
    }

    // MARK: - Typed questions (Snap and ask)

    /// Says why a question can't be asked right now, so the screen never looks broken.
    var disabledReason: String? {
        if isWorking { return nil }
        if isInConversation { return "You're in a conversation with Carvis." }
        if vehicle == nil { return "Add your car's year, make, and model first." }
        if client == nil { return "The server address is missing." }
        if !glasses.isConnected { return "Connect your glasses so Carvis can see." }
        if !glasses.isLive { return "Waiting for live video from your glasses." }
        if question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Type a question first." }
        return nil
    }

    var canAsk: Bool { disabledReason == nil && !isWorking }

    func askTyped() {
        guard canAsk, let client, let vehicle else { return }
        speech.stop()
        backToLiveTask?.cancel()
        let asked = question.trimmingCharacters(in: .whitespacesAndNewlines)
        askedQuestion = asked
        phase = .capturing
        Task {
            do {
                let jpeg = try await glasses.capturePhoto()
                photo = UIImage(data: jpeg)
                phase = .asking
                let result = try await client.ask(photo: jpeg, question: asked, vehicle: vehicle, sessionID: sessionID)
                phase = .result(result)
                record(asked, result)
                switch result {
                case .answer(let text, _, _): await speakAndWait(text)
                case .notInManual(let message, _): await speakAndWait(message)
                }
            } catch {
                phase = .failed(error.localizedDescription)
            }
            scheduleBackToLive()
        }
    }

    private func scheduleBackToLive() {
        backToLiveTask?.cancel()
        backToLiveTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(12))
            guard let self, !Task.isCancelled, !self.isWorking else { return }
            withAnimation(.easeOut(duration: 0.3)) { self.photo = nil }
        }
    }

    private func record(_ asked: String, _ result: VisionResult) {
        switch result {
        case .answer(let text, _, _): chats.add(question: asked, reply: text, fromManual: true)
        case .notInManual(let message, _): chats.add(question: asked, reply: message, fromManual: false)
        }
    }

    private func speakAndWait(_ text: String) async {
        if let name = AudioRoute.bluetoothOutputName {
            spokenThrough = "Spoken through \(name)"
        } else {
            spokenThrough = "Spoken on your phone speaker. Your glasses aren't the audio output right now."
        }
        await speech.speakAndWait(text)
    }

    // MARK: - What the voice row says

    var voiceDisplay: VoiceDisplay {
        if voiceMode == .phone {
            let state = phoneCallState
            return VoiceDisplay(title: state.title, subtitle: state.detail,
                                isOn: true, isLive: state == .listening)
        }
        switch conversationPhase {
        case .off, .muted:
            return VoiceDisplay(title: "Hey Carvis is muted", subtitle: "Unmute to talk to Carvis hands-free", isOn: false, isLive: false)
        case .waiting(let reason):
            return VoiceDisplay(title: "Hey Carvis isn't listening", subtitle: reason, isOn: false, isLive: false)
        case .arming:
            if wakeSource == .glassesSpeech, wake.state == .requestingPermission {
                return VoiceDisplay(title: "Allow the glasses microphone", subtitle: "Approve it in the Meta AI app", isOn: true, isLive: false)
            }
            return VoiceDisplay(title: "Starting to listen", subtitle: "One moment", isOn: true, isLive: false)
        case .listening:
            let source = wakeSource == .glassesSpeech ? "Listening through your glasses" : "Listening through your glasses' Bluetooth microphone"
            return VoiceDisplay(title: "Say \u{201C}Hey Carvis\u{201D} when you need help",
                                subtitle: lastFailure.map { "That didn\u{2019}t connect. \($0)" } ?? source, isOn: true, isLive: true)
        case .releasingWake, .startingCall:
            return VoiceDisplay(title: "Connecting", subtitle: "One moment", isOn: true, isLive: false)
        case .verifyingRoute:
            return VoiceDisplay(title: "Checking your glasses audio", subtitle: "One moment", isOn: true, isLive: false)
        case .inCall:
            if cameraWork == .capturing {
                return VoiceDisplay(title: "Looking", subtitle: "Taking a photo through your glasses", isOn: true, isLive: false)
            }
            if cameraWork == .identifying {
                return VoiceDisplay(title: "Looking", subtitle: "Identifying what you're looking at", isOn: true, isLive: false)
            }
            if let partial = agent?.partial, !partial.isEmpty {
                return VoiceDisplay(title: "Listening", subtitle: "\u{201C}\(partial)\u{201D}", isOn: true, isLive: true)
            }
            if agent?.state == .speaking {
                return VoiceDisplay(title: "Carvis is talking", subtitle: "Just talk to interrupt", isOn: true, isLive: false)
            }
            return VoiceDisplay(title: "Talking with Carvis", subtitle: "Go ahead", isOn: true, isLive: true)
        case .routeLost(let reason):
            return VoiceDisplay(title: "Paused until your glasses reconnect", subtitle: reason, isOn: true, isLive: false)
        case .endingCall, .shuttingDown:
            return VoiceDisplay(title: "Finishing up", subtitle: "One moment", isOn: true, isLive: false)
        }
    }

    // MARK: - Helpers

    /// How long after the wake phrase each stage happened. Goes to the log only.
    private func mark(_ stage: String) {
        guard let wakeTime else { return }
        let elapsed = wakeTime.duration(to: .now).components
        print("[Timing] \(stage): \(elapsed.seconds * 1000 + elapsed.attoseconds / 1_000_000_000_000_000) ms after wake")
    }

    /// Runs `action` whenever `value` changes, using the Observation framework.
    private func watch<T: Equatable>(_ value: @escaping () -> T?, action: @escaping (T?) -> Void) {
        var last = value()
        func track() {
            withObservationTracking {
                _ = value()
            } onChange: { [weak self] in
                guard self != nil else { return }
                Task { @MainActor in
                    let current = value()
                    if current != last {
                        last = current
                        action(current)
                    }
                    track()
                }
            }
        }
        track()
    }
}
