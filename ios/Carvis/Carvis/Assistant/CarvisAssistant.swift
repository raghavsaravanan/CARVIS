import Combine
import Foundation
import Observation
import SwiftUI
import UIKit

/// Carvis, the hands-free mechanic. One instance for the whole app.
///
/// While it's active (during a job, or on the Ask screen) it keeps the glasses camera live
/// and listens for "Hey Carvis" through the glasses' own speech recognition (Meta Speech),
/// with phone speech as a labelled backup. A spoken question takes a photo of what you're
/// looking at, asks the service manual through /vision-query, and speaks the answer.
/// With Vapi keys, the question starts a Vapi conversation instead.
@Observable
@MainActor
final class CarvisAssistant {
    enum Phase: Equatable {
        case idle
        case capturing
        case asking
        case result(VisionResult)
        case failed(String)
    }

    enum VoiceSource { case glasses, phone }

    /// Why Carvis is on. It stays on while any reason remains.
    enum Reason: Hashable { case job, askScreen }

    // MARK: State the screens show

    var question = ""
    private(set) var phase: Phase = .idle
    /// The photo behind the latest answer. Cleared back to live video after a while.
    var photo: UIImage?
    /// The question behind the latest answer.
    private(set) var askedQuestion: String?
    private(set) var spokenThrough: String?
    private(set) var voiceSource: VoiceSource = .glasses
    /// After a bare "Hey Carvis", the next sentence is the question, until this time.
    private(set) var awaitingQuestionUntil: Date?
    private(set) var isSpeaking = false
    private(set) var reasons: Set<Reason> = []

    var voiceOn: Bool {
        didSet { UserDefaults.standard.set(voiceOn, forKey: Self.voiceKey) }
    }

    let listener = VoiceListener()
    /// Vapi conversation, when Config/VapiConfig.plist has keys.
    let agent: VapiAgent?
    let glasses: GlassesController
    let vehicle = Vehicle.demo

    var client: CarvisVisionClient? { accounts.visionClient }
    var isActive: Bool { !reasons.isEmpty }
    var isWorking: Bool { phase == .capturing || phase == .asking }
    var wake: CarvisWakeListener { glasses.wakeListener }

    // MARK: Private

    @ObservationIgnored private let accounts: AccountStore
    @ObservationIgnored private let chats: ChatHistory
    @ObservationIgnored private let speech: SystemSpeechOutput
    @ObservationIgnored private var sessionID = UUID().uuidString
    @ObservationIgnored private var cancellables = Set<AnyCancellable>()
    @ObservationIgnored private var backToLiveTask: Task<Void, Never>?
    private static let voiceKey = "carvis.voiceOn"

    /// Don't react to voice while Carvis is working, talking, or in a Vapi conversation.
    private var isBusyForVoice: Bool { isWorking || isSpeaking || agent?.isInCall == true }

    init(glasses: GlassesController, accounts: AccountStore, chats: ChatHistory, speech: SystemSpeechOutput) {
        self.glasses = glasses
        self.accounts = accounts
        self.chats = chats
        self.speech = speech
        UserDefaults.standard.register(defaults: [Self.voiceKey: true])
        self.voiceOn = UserDefaults.standard.bool(forKey: Self.voiceKey)
        self.agent = VapiConfig.load().map(VapiAgent.init)

        let wake = glasses.wakeListener
        wake.wakeDetected
            .sink { [weak self] _ in self?.heardWakeOnGlasses() }
            .store(in: &cancellables)
        wake.transcripts
            .sink { [weak self] heard in self?.heardOnGlasses(heard) }
            .store(in: &cancellables)
        wake.stateUpdates
            .sink { [weak self] state in
                // Glasses speech couldn't start (not enabled, permission, firmware): use the phone.
                guard let self, state == .failed, self.isActive, self.voiceOn, self.voiceSource == .glasses else { return }
                self.useBackupVoice()
            }
            .store(in: &cancellables)
        listener.onHeard = { [weak self] text in
            guard let self, self.voiceSource == .phone else { return }
            self.handleSpoken(text)
        }
        watchGlassesConnection()
    }

    // MARK: - On and off

    func activate(_ reason: Reason) {
        let wasActive = isActive
        reasons.insert(reason)
        guard !wasActive else { return }
        sessionID = UUID().uuidString
        glasses.startPreview()   // the camera stays live so Carvis can see what you see
        startVoice()
    }

    func deactivate(_ reason: Reason) {
        reasons.remove(reason)
        guard !isActive else { return }
        agent?.end()
        stopVoice()
        glasses.stopPreview()
        speech.stop()
        backToLiveTask?.cancel()
        photo = nil
        phase = .idle
    }

    /// Mute or unmute. If voice is on but couldn't start (for example a permission is off),
    /// tapping tries again instead of muting.
    func toggleVoice() {
        if voiceOn, voiceDisplay.isOn {
            voiceOn = false
            stopVoice()
        } else {
            voiceOn = true
            if isActive {
                stopVoice()
                startVoice()
            }
        }
    }

    /// Show live video again instead of the last photo.
    func backToLive() {
        backToLiveTask?.cancel()
        photo = nil
        if !isWorking { phase = .idle }
        speech.stop()
    }

    // MARK: - Asking

    /// Says why a question can't be asked right now, so the screen never looks broken.
    var disabledReason: String? {
        if isWorking { return nil }
        if client == nil { return "The server address is missing." }
        if !glasses.isConnected { return "Connect your glasses so Carvis can see." }
        if !glasses.isLive { return "Waiting for live video from your glasses." }
        if question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Type a question first." }
        return nil
    }

    var canAsk: Bool { disabledReason == nil && !isWorking }

    /// The typed question (Snap and ask).
    func askTyped() {
        guard canAsk else { return }
        run(byVoice: false)
    }

    /// Same as Snap and ask, but every outcome is also spoken, because you may not be
    /// looking at the phone.
    private func askByVoice() {
        if canAsk {
            run(byVoice: true)
            return
        }
        let reason = disabledReason ?? "I'm still working on the last question."
        Task {
            await speakAndWait(reason)
            listener.resume()
        }
    }

    private func run(byVoice: Bool) {
        guard let client else { return }
        speech.stop()
        listener.pause()  // don't let it hear its own answer
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
                if byVoice {
                    await speakAndWait("Sorry, that didn't work. The details are on your phone.")
                }
            }
            listener.resume()
            scheduleBackToLive()
        }
    }

    /// After an answer, go back to live video once you've had time to read it.
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
        isSpeaking = true
        await speech.speakAndWait(text)
        isSpeaking = false
    }

    // MARK: - Vapi conversation

    private func startConversation(opening: String) {
        guard let agent, !agent.isInCall else { return }
        // Vapi needs the microphone, so the phone listener lets go of it first.
        listener.stop()
        speech.stop()
        agent.lookAtPart = { [weak self] question in
            await self?.lookAtPartForVapi(question) ?? "Carvis isn't available."
        }
        agent.onEnded = { [weak self] in
            // Back to listening for "Hey Carvis" once the conversation is over.
            guard let self, self.isActive, self.voiceOn, self.voiceSource == .phone else { return }
            Task { await self.listener.start() }
        }
        Task { await agent.start(vehicle: vehicle, sessionID: sessionID, openingQuestion: opening) }
    }

    /// Vapi asked to see the part: take a glasses photo and ask the manual. Returns the text
    /// Vapi should say.
    private func lookAtPartForVapi(_ asked: String) async -> String {
        guard let client else { return "The Carvis server address is missing, so I can't check the manual." }
        guard glasses.isLive else { return "The glasses camera isn't live, so I can't see the part." }
        question = asked
        askedQuestion = asked
        phase = .capturing
        do {
            let jpeg = try await glasses.capturePhoto()
            photo = UIImage(data: jpeg)
            phase = .asking
            let result = try await client.ask(photo: jpeg, question: asked, vehicle: vehicle, sessionID: sessionID)
            phase = .result(result)
            record(asked, result)
            spokenThrough = "Spoken by Carvis on Vapi"
            scheduleBackToLive()
            switch result {
            case .answer(let text, _, _): return text
            case .notInManual(let message, _): return "Not in the manual: \(message)"
            }
        } catch {
            phase = .failed(error.localizedDescription)
            return "The lookup failed, so I don't have an answer. \(error.localizedDescription)"
        }
    }

    // MARK: - Voice

    private func startVoice() {
        guard voiceOn, isActive else { return }
        if glasses.isConnected {
            voiceSource = .glasses
            listener.stop()
            glasses.armWakeListener()
        } else {
            useBackupVoice()
        }
    }

    private func useBackupVoice() {
        voiceSource = .phone
        if wake.isArmed { glasses.disarmWakeListener() }
        Task { await listener.start() }
    }

    private func stopVoice() {
        awaitingQuestionUntil = nil
        if wake.isArmed { glasses.disarmWakeListener() }
        listener.stop()
    }

    /// Glasses connected while Carvis is on: move from phone speech to glasses speech.
    private func watchGlassesConnection() {
        withObservationTracking {
            _ = glasses.isConnected
        } onChange: { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                if self.glasses.isConnected, self.isActive, self.voiceOn, self.voiceSource == .phone {
                    self.startVoice()
                }
                self.watchGlassesConnection()
            }
        }
    }

    /// "Hey Carvis, what's the torque for this?" asks right away. A bare "Hey Carvis"
    /// gets a short "Yes?" and the next sentence becomes the question.
    private func heardWakeOnGlasses() {
        guard isActive, voiceOn, voiceSource == .glasses, !isBusyForVoice else { return }
        let rest = VoiceListener.question(afterWakePhraseIn: wake.lastTranscript) ?? ""
        if rest.split(separator: " ").count >= 2 {
            handleSpoken(rest)
        } else {
            awaitingQuestionUntil = .now + 8
            Task { await speakAndWait("Yes?") }
        }
    }

    private func heardOnGlasses(_ heard: CarvisWakeListener.Heard) {
        guard isActive, voiceSource == .glasses, heard.isFinal, !isBusyForVoice,
              let until = awaitingQuestionUntil else { return }
        guard until > .now else {
            awaitingQuestionUntil = nil
            return
        }
        let text = heard.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.split(separator: " ").count >= 2 else { return }
        awaitingQuestionUntil = nil
        handleSpoken(text)
    }

    /// A spoken question, from either microphone.
    private func handleSpoken(_ text: String) {
        question = text
        if agent != nil {
            startConversation(opening: text)
        } else {
            askByVoice()
        }
    }

    // MARK: - What the voice row says

    var voiceDisplay: VoiceDisplay {
        guard voiceOn else {
            return VoiceDisplay(title: "Hey Carvis is muted", subtitle: "Unmute to talk to Carvis hands-free", isOn: false, isLive: false)
        }
        if agent?.isInCall == true {
            return VoiceDisplay(title: "In a conversation", subtitle: "Carvis is talking with you", isOn: true, isLive: false)
        }
        switch phase {
        case .capturing: return VoiceDisplay(title: "Looking", subtitle: "Taking a photo through your glasses", isOn: true, isLive: false)
        case .asking: return VoiceDisplay(title: "Checking the manual", subtitle: "One moment", isOn: true, isLive: false)
        default: break
        }
        if isSpeaking {
            return VoiceDisplay(title: "Answering", subtitle: "I\u{2019}ll listen again when I\u{2019}m done", isOn: true, isLive: false)
        }
        switch voiceSource {
        case .glasses:
            if awaitingQuestionUntil != nil {
                let heard = VoiceListener.question(afterWakePhraseIn: wake.lastTranscript) == nil ? wake.lastTranscript : ""
                return VoiceDisplay(title: "Listening", subtitle: heard.isEmpty ? "Go ahead" : "\u{201C}\(heard)\u{201D}", isOn: true, isLive: true)
            }
            switch wake.state {
            case .listening:
                return VoiceDisplay(title: "Say \u{201C}Hey Carvis\u{201D} when you need help",
                                    subtitle: "Listening through your glasses", isOn: true, isLive: true)
            case .requestingPermission:
                return VoiceDisplay(title: "Allow the glasses microphone", subtitle: "Approve it in the Meta AI app", isOn: true, isLive: false)
            case .paused:
                return VoiceDisplay(title: "Paused", subtitle: "Put your glasses on and keep Carvis open", isOn: true, isLive: false)
            case .failed:
                return VoiceDisplay(title: "Switching to phone speech", subtitle: "One moment", isOn: true, isLive: false)
            case .disarmed, .waitingForSession, .starting, .stopping:
                return VoiceDisplay(title: "Starting glasses speech", subtitle: "One moment", isOn: true, isLive: false)
            }
        case .phone:
            let source = glasses.isConnected ? "Phone speech, glasses speech isn\u{2019}t available"
                : listener.microphoneName.map { "Listening through \($0)" } ?? "Listening through your phone"
            switch listener.state {
            case .off, .starting:
                return VoiceDisplay(title: "Starting the microphone", subtitle: "One moment", isOn: true, isLive: false)
            case .listening:
                return VoiceDisplay(title: "Say \u{201C}Hey Carvis\u{201D} when you need help", subtitle: source, isOn: true, isLive: true)
            case .hearingQuestion:
                return VoiceDisplay(title: "Listening",
                                    subtitle: listener.transcript.isEmpty ? "Go ahead" : "\u{201C}\(listener.transcript)\u{201D}",
                                    isOn: true, isLive: true)
            case .paused:
                return VoiceDisplay(title: "Answering", subtitle: "I\u{2019}ll listen again when I\u{2019}m done", isOn: true, isLive: false)
            case .unavailable(let reason):
                return VoiceDisplay(title: "Hey Carvis is off", subtitle: reason, isOn: false, isLive: false)
            }
        }
    }
}
