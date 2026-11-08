import AVFoundation
import Combine
import Foundation
import Observation
import SwiftUI
import UIKit

/// Owns a hands-free conversation from "Hey Carvis" until it has completely ended.
/// One instance, above the views.
///
/// Meta's toolkit supplies the wake transcripts and camera images. Vapi and Daily handle the
/// conversation's audio through iOS Bluetooth. The rules for what happens when are in
/// `ConversationMachine`; this class carries them out. The server holds the memory.
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

    // MARK: Private

    private struct ActiveCall {
        let handle: ConversationHandle
        let generation: Int
    }

    @ObservationIgnored private let accounts: AccountStore
    @ObservationIgnored private let chats: ChatHistory
    @ObservationIgnored private let garage: CarProfileStore
    @ObservationIgnored private let speech: SystemSpeechOutput
    @ObservationIgnored private let cue = ThinkingCue()
    @ObservationIgnored private var sessionID = UUID().uuidString
    @ObservationIgnored private var handle: ConversationHandle?
    @ObservationIgnored private var handleVehicle: Vehicle?
    @ObservationIgnored private var activeCall: ActiveCall?
    @ObservationIgnored private var cancellables = Set<AnyCancellable>()
    @ObservationIgnored private var routeObservation: AnyCancellable?
    @ObservationIgnored private var routeTask: Task<Void, Never>?
    @ObservationIgnored private var cameraTask: Task<Void, Never>?
    @ObservationIgnored private var stateTask: Task<Void, Never>?
    @ObservationIgnored private var backToLiveTask: Task<Void, Never>?
    /// Set once Meta's Speech has failed in this session, so it isn't retried on every wake.
    @ObservationIgnored private var glassesSpeechFailed = false
    /// Starts a bare "Hey Carvis" without waiting for the glasses to finish the sentence.
    @ObservationIgnored private var earlyWake: Task<Void, Never>?
    /// Creates the server session ahead of time, so "Hey Carvis" doesn't wait for it.
    @ObservationIgnored private var sessionWarmup: Task<Void, Never>?
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

        agent?.onConnected = { [weak self] in
            self?.mark("assistant connected")
            self?.send(.callConnected)
        }
        agent?.onEnded = { [weak self] error in self?.send(.callEnded(error: error)) }

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
        watch({ [weak self] in self?.glasses.isConnected }) { [weak self] _ in self?.retryWakeIfWaiting() }
        watch({ [weak self] in self?.garage.profile.vehicle }) { [weak self] _ in self?.retryWakeIfWaiting() }
    }

    // MARK: - On and off

    func activate(_ reason: Reason) {
        let wasActive = isActive
        reasons.insert(reason)
        guard !wasActive else { return }
        sessionID = UUID().uuidString
        handle = nil
        handleVehicle = nil
        serverState = nil
        glassesSpeechFailed = false
        sessionWarmup = Task { [weak self] in _ = try? await self?.createOrUpdateSession() }
        glasses.startPreview()   // the camera stays live so Carvis can see what you see
        send(.activate)
    }

    func deactivate(_ reason: Reason) {
        reasons.remove(reason)
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
        send(.userEnded)
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
        case .callStartFailed(let reason): lastFailure = reason
        case .callEnded(.some(let reason)): lastFailure = reason
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
        case .startCall(let question): startCall(openingQuestion: question)
        case .verifyRoute: verifyRoute()
        case .setMicMuted(let muted): Task { await agent?.setMicrophoneMuted(muted) }
        case .deliverQuestion(let question): agent?.deliver(question: question)
        case .endCall: agent?.end()
        case .shutdownCall: shutdownCall()
        }
    }

    // MARK: - Wake word

    private func startWake() {
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
        guard isActive, wakeSource == .glassesSpeech else { return }
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
        guard isActive, wakeSource == .glassesBluetooth else { return }
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

    private func ensureSession() async throws -> ConversationHandle {
        await sessionWarmup?.value
        return try await createOrUpdateSession()
    }

    private func createOrUpdateSession() async throws -> ConversationHandle {
        guard let api, let vehicle else {
            throw ConversationSetupError.message("Carvis needs a server address and your car's details first.")
        }
        if let handle {
            if handleVehicle != vehicle {
                try await api.updateVehicle(handle, vehicle: vehicle)
                handleVehicle = vehicle
            }
            return handle
        }
        let created = try await api.createSession(ownerName: accounts.account?.name ?? "", vehicle: vehicle)
        handle = created
        handleVehicle = vehicle
        return created
    }

    /// Selects the glasses' Bluetooth microphone before the call can open a microphone at all.
    private func prepareGlassesAudio() async throws {
        let glassesName = glasses.activeDeviceName
        try await AudioSessionQueue.run {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetoothHFP])
            try session.setActive(true)
            let inputs = session.availableInputs ?? []
            print("[Conversation] available inputs: \(inputs.map { "\($0.portName) (\($0.portType.rawValue))" })")
            guard let mic = inputs.first(where: { $0.portType == .bluetoothHFP && GlassesRouteCheck.matches($0.portName, glassesName) }) else {
                throw ConversationSetupError.message("Your glasses' microphone isn't connected to this iPhone. Check Bluetooth in Settings.")
            }
            try session.setPreferredInput(mic)
        }
    }

    private func startCall(openingQuestion: String?) {
        Task {
            do {
                guard let agent, let api else {
                    throw ConversationSetupError.message("Vapi isn't configured.")
                }
                let handle = try await ensureSession()
                try stillStarting()
                // Done side by side, because each one otherwise waits on the other.
                async let serverCall = api.startCall(handle, openingQuestion: openingQuestion)
                try await prepareGlassesAudio()
                let call = try await serverCall
                activeCall = ActiveCall(handle: handle, generation: call.generation)
                try stillStarting()
                var overrides: [String: Any] = ["variableValues": call.variableValues]
                // With a question, its delivery is the first turn. Otherwise Carvis greets.
                if openingQuestion != nil { overrides["firstMessageMode"] = "assistant-waits-for-user" }
                let callID = try await agent.start(metadata: ["carvis_session_id": handle.sessionID], overrides: overrides)
                mark("call requested")
                // Ended while connecting: the agent is already hanging up, so start nothing else.
                guard isCallRunning else { return }
                try? await api.bindCall(handle, generation: call.generation, vapiCallID: callID)
                guard isCallRunning else { return }
                observeRoute()
                startCameraLoop(handle: handle, generation: call.generation)
                startStatePolling(handle: handle)
            } catch is ConversationCancelled {
                print("[Conversation] ended before the call started")
                send(.callEnded(error: nil))
            } catch {
                print("[Conversation] couldn't start: \(error)")
                // The server restarted and forgot this session: make a new one next time.
                if let api = error as? ConversationAPIError, api.status == 401 || api.status == 404 { handle = nil }
                send(.callStartFailed(error.localizedDescription))
            }
        }
    }

    private func stillStarting() throws {
        guard conversationPhase == .startingCall else { throw ConversationCancelled() }
    }

    private var isCallRunning: Bool {
        switch conversationPhase {
        case .startingCall, .verifyingRoute, .inCall, .routeLost: true
        default: false
        }
    }

    // MARK: - Audio route

    private func routeStatus() -> GlassesRouteStatus {
        let ports = AudioRoute.currentPorts()
        return GlassesRouteCheck.evaluate(inputs: ports.inputs, outputs: ports.outputs, glassesName: glasses.activeDeviceName)
    }

    private func describe(_ status: GlassesRouteStatus) -> String {
        switch status {
        case .ready(let name): "Using \(name)"
        case .noMicrophone: "Your glasses' microphone isn't connected."
        case .noSpeaker: "Your glasses' speakers aren't connected."
        case .otherDevice(let name): "Audio is going to \(name), not your glasses."
        }
    }

    /// Keeps asking for Bluetooth and checking until the glasses are truly the route.
    /// The microphone stays muted the whole time.
    private func verifyRoute() {
        routeTask?.cancel()
        routeTask = Task { [weak self] in
            var attempts = 0
            while !Task.isCancelled {
                guard let self else { return }
                switch self.conversationPhase {
                case .verifyingRoute, .routeLost:
                    if attempts % 10 == 0 { await self.agent?.preferBluetooth() }
                default:
                    return
                }
                guard !Task.isCancelled else { return }
                let status = self.routeStatus()
                if case .ready = status {
                    print("[Conversation] route check: \(status)")
                    self.mark("route verified")
                    self.send(.routeVerified)
                    return
                }
                if attempts % 10 == 0 { print("[Conversation] route check: \(status)") }
                attempts += 1
                if attempts == 40, self.conversationPhase == .verifyingRoute {   // four seconds
                    self.send(.routeLost(self.describe(status)))
                }
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
    }

    private func observeRoute() {
        routeObservation = NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.routeChanged() }
    }

    private func routeChanged() {
        let status = routeStatus()
        print("[Conversation] route changed: \(status)")
        switch conversationPhase {
        case .inCall:
            if case .ready = status { return }
            send(.routeLost(describe(status)))
        case .routeLost:
            if case .ready = status {
                send(.routeVerified)
            } else {
                send(.routeLost(describe(status)))
            }
        default:
            break
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
        cue.start()
        cameraWork = .capturing
        defer {
            cue.stop()
            cameraWork = .idle
        }
        do {
            let jpeg = try await glasses.capturePhoto(timeout: .seconds(min(max(command.secondsRemaining - 8, 3), 15)))
            print("[Conversation] captured \(jpeg.count) bytes")
            photo = UIImage(data: jpeg)
            cameraWork = .identifying
            try await api.uploadPhoto(handle, requestID: command.requestID, jpeg: jpeg, timeout: command.secondsRemaining)
            print("[Conversation] photo identified")
            scheduleBackToLive()
        } catch let error as ConversationAPIError where error.isStale {
            print("[Conversation] photo no longer wanted")
        } catch {
            print("[Conversation] camera failed: \(error.localizedDescription)")
            try? await api.reportCameraFailure(handle, requestID: command.requestID, reason: error.localizedDescription)
        }
    }

    private func startStatePolling(handle: ConversationHandle) {
        guard let api else { return }
        stateTask = Task { [weak self] in
            while !Task.isCancelled {
                if let state = try? await api.state(handle) { self?.serverState = state }
                try? await Task.sleep(for: .seconds(1.5))
            }
        }
    }

    // MARK: - Shutdown

    /// Everything from the call stops before Carvis can listen again.
    private func shutdownCall() {
        routeTask?.cancel()
        routeObservation = nil
        let camera = cameraTask
        cameraTask = nil
        camera?.cancel()
        stateTask?.cancel()
        stateTask = nil
        cue.stop()
        cameraWork = .idle
        let finished = activeCall
        activeCall = nil
        Task {
            await camera?.value
            if let finished, let api {
                try? await api.endCall(finished.handle, generation: finished.generation, reason: "app")
                if let state = try? await api.state(finished.handle) { serverState = state }
            }
            _ = try? await AudioSessionQueue.run {
                try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
            }
            AudioOwnership.conversationOwnsAudio = false
            SystemSpeechOutput.usePlaybackSession()
            print("[Conversation] shutdown complete")
            send(.shutdownComplete)
            if !isActive { finishDeactivating() }
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

/// The conversation was ended before its call got started.
private struct ConversationCancelled: Error {}

enum ConversationSetupError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case .message(let text): text
        }
    }
}
