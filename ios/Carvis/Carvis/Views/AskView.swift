import SwiftUI

/// Look at a part through your glasses, ask about it, and hear the answer.
/// The answer comes only from the car's service manual; if the manual
/// doesn't have it, Carvis says so instead of guessing.
struct AskView: View {
    @Environment(GlassesController.self) private var glasses
    @Environment(AccountStore.self) private var accounts
    @Environment(ChatHistory.self) private var chats
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    let vehicle: Vehicle
    let client: (any VisionClient)?
    let speech: any SpeechOutput

    @State private var question = ""
    @State private var phase: Phase = .idle
    @State private var photo: UIImage?
    @State private var spokenThrough: String?
    @State private var sessionID = UUID().uuidString
    @State private var listener = VoiceListener()
    /// Vapi conversation, when Config/VapiConfig.plist has keys. Otherwise Carvis's built-in voice.
    @State private var agent: VapiAgent? = VapiConfig.load().map(VapiAgent.init)
    @State private var isOnScreen = false

    // Voice: the glasses' own speech recognition (Meta Speech) listens for "Hey Carvis".
    // If glasses speech isn't available, phone speech takes over and the row says so.
    @AppStorage("carvis.voiceOn") private var voiceOn = true
    @State private var voiceSource: VoiceSource = .glasses
    /// After a bare "Hey Carvis", the next sentence is the question, until this time.
    @State private var awaitingQuestionUntil: Date?
    @State private var isSpeaking = false

    enum VoiceSource { case glasses, phone }

    private var wake: CarvisWakeListener { glasses.wakeListener }
    /// Don't react to voice while Carvis is working, talking, or in a Vapi conversation.
    private var isBusyForVoice: Bool { isWorking || isSpeaking || agent?.isInCall == true }
    @FocusState private var isQuestionFocused: Bool

    enum Phase: Equatable {
        case idle
        case capturing
        case asking
        case result(VisionResult)
        case failed(String)
    }

    private var trimmedQuestion: String {
        question.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var isWorking: Bool { phase == .capturing || phase == .asking }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                cameraCard
                    .appearAnimation(index: 0)
                if let agent, agent.isInCall || agent.state != .idle {
                    ConversationCard(agent: agent)
                        .transition(.blurReplace)
                }
                questionCard
                    .appearAnimation(index: 1)
                resultSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 24)
            .animation(reduceMotion ? .easeOut(duration: 0.2) : Motion.enter, value: phase)
            .animation(reduceMotion ? .easeOut(duration: 0.2) : Motion.enter, value: agent?.state)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.interactively)
        .background { CarvisBackground() }
        .navigationTitle("Ask Carvis")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .onAppear {
            isOnScreen = true
            glasses.startPreview()
        }
        // Listen for "Hey Carvis" as soon as the screen opens. The switch turns it off.
        .task { startVoice() }
        .onDisappear {
            isOnScreen = false
            agent?.end()
            stopVoice()
            glasses.stopPreview()
            speech.stop()
        }
        // Glasses speech heard "Hey Carvis", and everything said while listening.
        .onReceive(glasses.wakeListener.wakeDetected) { _ in heardWakeOnGlasses() }
        .onReceive(glasses.wakeListener.transcripts) { heard in heardOnGlasses(heard) }
        .onChange(of: glasses.wakeListener.state) { _, state in
            // Glasses speech couldn't start (not enabled, permission, firmware): use the phone.
            if state == .failed, voiceOn, voiceSource == .glasses { useBackupVoice() }
        }
        .onChange(of: glasses.isConnected) { _, connected in
            if connected, voiceOn, voiceSource == .phone { startVoice() }
        }
        // Phone speech heard "Hey Carvis, ..." (backup path).
        .onChange(of: listener.heard) { _, heard in
            guard let heard, voiceSource == .phone else { return }
            handleSpoken(heard.text)
        }
        .sensoryFeedback(.start, trigger: awaitingQuestionUntil != nil || listener.state == .hearingQuestion) { _, hearing in hearing }
        .sensoryFeedback(.success, trigger: phase) { _, new in
            if case .result(.answer) = new { return true }
            return false
        }
    }

    // MARK: - Camera

    private var cameraCard: some View {
        ZStack {
            Rectangle().fill(Theme.ink.opacity(0.9))

            if let shown = photo ?? (isWorking ? nil : glasses.frame) {
                Image(uiImage: shown)
                    .resizable()
                    .scaledToFill()
                    .transition(.opacity)
                    .accessibilityLabel(photo == nil ? "Live view from your glasses" : "Photo from your glasses")
            } else {
                CameraStatusMessage(status: glasses.status,
                                    detail: accounts.isTeam ? glasses.detail : nil,
                                    onConnect: glasses.connect,
                                    onRetry: {
                                        glasses.stopPreview()
                                        glasses.startPreview()
                                    })
                    .padding(24)
            }
        }
        .frame(maxWidth: .infinity)
        .aspectRatio(3 / 4, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .overlay(alignment: .topLeading) {
            CameraBadge(isPhoto: photo != nil, status: glasses.status)
                .padding(16)
        }
        .overlay(alignment: .topTrailing) {
            if photo != nil, !isWorking {
                Button("Back to live view", systemImage: "arrow.uturn.backward") {
                    withAnimation(Motion.enter) {
                        photo = nil
                        phase = .idle
                    }
                    speech.stop()
                }
                .labelStyle(.iconOnly)
                .font(.title3.weight(.semibold))
                .frame(width: 52, height: 52)
                .carvisGlass(.card, in: Circle())
                .padding(12)
                .transition(.blurReplace)
            }
        }
        .animation(.easeOut(duration: 0.2), value: photo == nil)
    }

    // MARK: - Question

    private var questionCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label(vehicle.displayName, systemImage: "car.side.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.inkSecondary)

            VoiceRow(display: voiceDisplay, action: toggleVoice)

            TextField("What's the torque for this?", text: $question)
                .font(.title3)
                .submitLabel(.send)
                .focused($isQuestionFocused)
                .onSubmit(ask)
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
                .frame(minHeight: 56)
                .background(Theme.ink.opacity(0.06), in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))

            Button(action: ask) {
                HStack(spacing: 10) {
                    if isWorking {
                        ProgressView()
                            .tint(.white)
                    } else {
                        Image(systemName: "camera.aperture")
                    }
                    Text(buttonTitle)
                        .contentTransition(.opacity)
                }
                .font(Theme.buttonFont)
                .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
            }
            .carvisButton(prominent: true)
            .disabled(!canAsk)

            if let reason = disabledReason {
                Text(reason)
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .frame(maxWidth: .infinity)
                    .multilineTextAlignment(.center)
                    .contentTransition(.opacity)
            }
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private var buttonTitle: String {
        switch phase {
        case .capturing: "Taking photo"
        case .asking: "Checking the manual"
        default: "Snap and ask"
        }
    }

    /// Says why the button is off, so it never looks broken.
    private var disabledReason: String? {
        if isWorking { return nil }
        if client == nil { return "The server address is missing." }
        if !glasses.isLive { return "Waiting for live video from your glasses." }
        if trimmedQuestion.isEmpty { return "Type a question first." }
        return nil
    }

    private var canAsk: Bool {
        !trimmedQuestion.isEmpty && !isWorking && glasses.isLive && client != nil
    }

    // MARK: - Result

    @ViewBuilder
    private var resultSection: some View {
        if client == nil {
            NoticeCard(
                title: "Server address missing",
                message: "Add CarvisBaseURL to Carvis-Info.plist so Carvis knows where to send questions.",
                systemImage: "exclamationmark.triangle.fill",
                tint: Theme.safetyRed
            )
        }
        switch phase {
        case .result(.answer(let text, let component, let answerVehicle)):
            AnswerCard(answer: text, component: component, vehicle: answerVehicle, spokenThrough: spokenThrough)
                .transition(.blurReplace)
        case .result(.notInManual(let message, let component)):
            NoticeCard(
                title: "Not in the manual",
                message: message + (component.map { "\nCarvis thinks it sees: \($0.component) (\(percent($0.confidence)))." } ?? ""),
                systemImage: "book.closed.fill",
                tint: Theme.accent,
                footnote: spokenThrough
            )
            .transition(.blurReplace)
        case .failed(let message):
            NoticeCard(
                title: "Something went wrong",
                message: message,
                systemImage: "exclamationmark.triangle.fill",
                tint: Theme.safetyRed
            )
            .transition(.blurReplace)
        default:
            if let error = glasses.errorMessage {
                NoticeCard(
                    title: "Glasses",
                    message: error,
                    systemImage: "eyeglasses",
                    tint: Theme.safetyRed,
                    dismiss: { glasses.errorMessage = nil }
                )
                .transition(.blurReplace)
            }
        }
    }

    // MARK: - Actions

    private func ask() {
        guard canAsk else { return }
        run(byVoice: false)
    }

    /// Same as tapping Snap and ask, but every outcome is also spoken,
    /// because you may not be looking at the phone.
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
        isQuestionFocused = false
        speech.stop()
        listener.pause()  // don't let it hear its own answer
        let asked = trimmedQuestion
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
                case .answer(let text, _, _):
                    await speakAndWait(text)
                case .notInManual(let message, _):
                    await speakAndWait(message)
                }
            } catch {
                phase = .failed(error.localizedDescription)
                if byVoice {
                    await speakAndWait("Sorry, that didn't work. The details are on your phone.")
                }
            }
            listener.resume()
        }
    }

    // MARK: - Vapi conversation

    private func startConversation(opening: String) {
        guard let agent, !agent.isInCall else { return }
        // Vapi needs the microphone, so Carvis's own listener lets go of it first.
        listener.stop()
        speech.stop()
        agent.lookAtPart = { question in await lookAtPartForVapi(question) }
        agent.onEnded = {
            // Back to listening for "Hey Carvis" once the conversation is over.
            guard isOnScreen, voiceOn, voiceSource == .phone else { return }
            Task { await listener.start() }
        }
        Task { await agent.start(vehicle: vehicle, sessionID: sessionID, openingQuestion: opening) }
    }

    /// Vapi asked to see the part: take a glasses photo and ask the manual, exactly
    /// like Snap and ask. Returns the text Vapi should say.
    private func lookAtPartForVapi(_ asked: String) async -> String {
        guard let client else { return "The Carvis server address is missing, so I can't check the manual." }
        guard glasses.isLive else { return "The glasses camera isn't live, so I can't see the part." }
        question = asked
        phase = .capturing
        do {
            let jpeg = try await glasses.capturePhoto()
            photo = UIImage(data: jpeg)
            phase = .asking
            let result = try await client.ask(photo: jpeg, question: asked, vehicle: vehicle, sessionID: sessionID)
            phase = .result(result)
            record(asked, result)
            spokenThrough = "Spoken by Carvis on Vapi"
            switch result {
            case .answer(let text, _, _): return text
            case .notInManual(let message, _): return "Not in the manual: \(message)"
            }
        } catch {
            phase = .failed(error.localizedDescription)
            return "The lookup failed, so I don't have an answer. \(error.localizedDescription)"
        }
    }

    /// Saves the question and reply so the dashboard can show your latest chats.
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

    // MARK: - Voice

    private func startVoice() {
        guard voiceOn else { return }
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

    private func toggleVoice() {
        if voiceOn {
            voiceOn = false
            stopVoice()
        } else {
            voiceOn = true
            startVoice()
        }
    }

    /// "Hey Carvis, what's the torque for this?" asks right away. A bare "Hey Carvis"
    /// gets a short "Yes?" and the next sentence becomes the question.
    private func heardWakeOnGlasses() {
        guard voiceOn, voiceSource == .glasses, !isBusyForVoice else { return }
        let rest = VoiceListener.question(afterWakePhraseIn: wake.lastTranscript) ?? ""
        if rest.split(separator: " ").count >= 2 {
            handleSpoken(rest)
        } else {
            awaitingQuestionUntil = .now + 8
            Task { await speakAndWait("Yes?") }
        }
    }

    private func heardOnGlasses(_ heard: CarvisWakeListener.Heard) {
        guard voiceSource == .glasses, heard.isFinal, !isBusyForVoice,
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

    /// A spoken question, from either microphone: talk it through with Vapi if it's set up,
    /// otherwise one question and one answer from the manual.
    private func handleSpoken(_ text: String) {
        question = text
        if agent != nil {
            startConversation(opening: text)
        } else {
            askByVoice()
        }
    }

    /// What the voice row says right now.
    private var voiceDisplay: VoiceDisplay {
        guard voiceOn else {
            return VoiceDisplay(title: "Hey Carvis", subtitle: "Ask hands-free through your glasses", isOn: false, isLive: false)
        }
        if agent?.isInCall == true {
            return VoiceDisplay(title: "In a conversation", subtitle: "Carvis is talking with you", isOn: true, isLive: false)
        }
        if isSpeaking || isWorking {
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
                return VoiceDisplay(title: "Say \u{201C}Hey Carvis\u{201D} and your question",
                                    subtitle: "Using your glasses microphone", isOn: true, isLive: true)
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
                : listener.microphoneName.map { "Using \($0)" } ?? "Using your phone\u{2019}s microphone"
            switch listener.state {
            case .off, .starting:
                return VoiceDisplay(title: "Starting the microphone", subtitle: "One moment", isOn: true, isLive: false)
            case .listening:
                return VoiceDisplay(title: "Say \u{201C}Hey Carvis\u{201D} and your question", subtitle: source, isOn: true, isLive: true)
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

private func percent(_ value: Double) -> String {
    value.formatted(.percent.precision(.fractionLength(0)))
}

// MARK: - Pieces

/// The live conversation with Carvis on Vapi: who's talking, what was said, and a way out.
private struct ConversationCard: View {
    let agent: VapiAgent

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                if agent.isInCall { LiveDot() }
                Text("Talking with Carvis")
                    .font(.headline)
                Spacer()
                Text(status)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(statusColor)
                    .contentTransition(.opacity)
            }

            if case .failed(let message) = agent.state {
                Text(message)
                    .font(.body)
                    .foregroundStyle(Theme.safetyRed)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }

            VStack(alignment: .leading, spacing: 8) {
                ForEach(agent.lines.suffix(4)) { line in
                    Bubble(text: line.text, fromCarvis: line.fromCarvis)
                        .transition(.blurReplace)
                }
                if !agent.partial.isEmpty {
                    Bubble(text: agent.partial, fromCarvis: false)
                        .opacity(0.6)
                }
            }
            .animation(Motion.enter, value: agent.lines)

            if agent.isInCall {
                Button(role: .destructive) {
                    agent.end()
                } label: {
                    Label("End conversation", systemImage: "phone.down.fill")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()
            }
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .sensoryFeedback(.start, trigger: agent.state == .listening)
    }

    private var status: String {
        switch agent.state {
        case .idle: "Ended"
        case .connecting: "Connecting"
        case .listening: "Listening"
        case .speaking: "Speaking"
        case .lookingAtPart: "Looking at the part"
        case .failed: "Couldn\u{2019}t connect"
        }
    }

    private var statusColor: Color {
        switch agent.state {
        case .failed: Theme.safetyRed
        case .speaking, .lookingAtPart: Theme.accent
        default: Theme.inkSecondary
        }
    }
}

private struct Bubble: View {
    let text: String
    let fromCarvis: Bool

    var body: some View {
        Text(text)
            .font(.body)
            .foregroundStyle(fromCarvis ? Theme.ink : .white)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(fromCarvis ? Theme.pearl : Theme.ink,
                        in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
            .frame(maxWidth: .infinity, alignment: fromCarvis ? .leading : .trailing)
            .accessibilityLabel((fromCarvis ? "Carvis: " : "You: ") + text)
    }
}

/// What the voice row shows.
struct VoiceDisplay: Equatable {
    let title: String
    let subtitle: String
    /// The switch position.
    let isOn: Bool
    /// Actively listening right now (pulsing dot).
    let isLive: Bool
}

/// The "Hey Carvis" switch, showing what Carvis is hearing.
private struct VoiceRow: View {
    let display: VoiceDisplay
    let action: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            HStack(spacing: 14) {
                ZStack {
                    if display.isLive {
                        LiveDot(size: 10)
                    } else {
                        Image(systemName: display.isOn ? "waveform" : "mic.slash.fill")
                            .font(.headline)
                    }
                }
                .frame(width: 28)
                .foregroundStyle(display.isOn ? Theme.accent : Theme.inkSecondary)

                VStack(alignment: .leading, spacing: 2) {
                    Text(display.title)
                        .font(.headline)
                    Text(display.subtitle)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                .contentTransition(.opacity)
                Spacer(minLength: 8)
                Capsule()
                    .fill(display.isOn ? Theme.accent : Theme.ink.opacity(0.15))
                    .frame(width: 46, height: 28)
                    .overlay(alignment: display.isOn ? .trailing : .leading) {
                        Circle()
                            .fill(.white)
                            .padding(3)
                            .shadow(color: .black.opacity(0.15), radius: 2, y: 1)
                    }
                    .accessibilityHidden(true)
            }
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight, alignment: .leading)
            .background(
                (display.isOn ? Theme.accent.opacity(0.1) : Theme.ink.opacity(0.05)),
                in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
        }
        .buttonStyle(PressableCardStyle())
        .animation(reduceMotion ? nil : .spring(duration: 0.3, bounce: 0), value: display)
        .accessibilityLabel("Hey Carvis")
        .accessibilityValue(display.isOn ? "On, \(display.title)" : "Off")
    }
}

/// "Live" / "Photo" chip in the corner of the camera view.
private struct CameraBadge: View {
    let isPhoto: Bool
    let status: GlassesController.Status

    var body: some View {
        HStack(spacing: 8) {
            if isPhoto {
                Image(systemName: "camera.fill")
                    .font(.caption.weight(.semibold))
                Text("Photo")
            } else if status == .live {
                LiveDot()
                Text("Live from your glasses")
            } else {
                Image(systemName: "eyeglasses")
                    .font(.caption.weight(.semibold))
                Text("Glasses camera")
            }
        }
        .font(.subheadline.weight(.semibold))
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .carvisGlass(.card, in: Capsule())
        .contentTransition(.opacity)
        .animation(.easeOut(duration: 0.2), value: status)
    }
}

/// Shown inside the camera frame until video arrives.
private struct CameraStatusMessage: View {
    let status: GlassesController.Status
    let detail: String?
    let onConnect: () -> Void
    let onRetry: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            if status == .startingCamera || status == .connecting || status == .needsCameraAccess {
                ProgressView()
                    .controlSize(.large)
                    .tint(.white)
            } else {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 40, weight: .medium))
                    .foregroundStyle(Theme.accent)
            }
            Text(text)
                .font(.title3.weight(.semibold))
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
                .fixedSize(horizontal: false, vertical: true)
            if status == .notConnected {
                Button(action: onConnect) {
                    Text("Connect glasses")
                        .font(Theme.buttonFont)
                        .padding(.horizontal, 28)
                        .frame(minHeight: Theme.buttonHeight)
                }
                .carvisButton(prominent: true)
            } else if status == .ready || status == .startingCamera || status == .paused {
                Button(action: onRetry) {
                    Text("Restart camera")
                        .font(Theme.buttonFont)
                        .padding(.horizontal, 28)
                        .frame(minHeight: Theme.buttonHeight)
                }
                .carvisButton()
            }
            if status != .notConnected, let detail {
                Text(detail)
                    .font(.footnote)
                    .foregroundStyle(.white.opacity(0.7))
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var text: String {
        switch status {
        case .notConnected: "Connect your glasses to see what they see"
        case .connecting: "Finish in the Meta AI app"
        case .lookingForGlasses: "Put on your glasses and open the arms"
        case .ready: "Glasses found. Tap Restart camera."
        case .startingCamera: "Starting the glasses camera"
        case .needsCameraAccess: "Allow camera access in the Meta AI app, then come back"
        case .paused: "Paused. Tap the side of your glasses to resume."
        case .live: ""
        }
    }
}

/// The manual's answer, big and readable, with what the camera saw underneath.
private struct AnswerCard: View {
    let answer: String
    let component: VisionComponent
    let vehicle: Vehicle
    let spokenThrough: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("From the \(vehicle.displayName) service manual", systemImage: "book.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.inkSecondary)

            Text(answer)
                .font(Theme.instructionFont)
                .fixedSize(horizontal: false, vertical: true)

            Divider()

            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Carvis sees")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                    Text(component.component)
                        .font(.body.weight(.semibold))
                }
                Spacer(minLength: 12)
                Text(percent(component.confidence))
                    .font(.title3.weight(.semibold))
                    .monospacedDigit()
                    .accessibilityLabel("\(percent(component.confidence)) sure")
            }

            if let spokenThrough {
                Label(spokenThrough, systemImage: "speaker.wave.2.fill")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(24)
        .carvisGlass(.hero, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// A soft colored card for refusals and errors. Shows the message exactly as received.
private struct NoticeCard: View {
    let title: String
    let message: String
    let systemImage: String
    let tint: Color
    var footnote: String?
    var dismiss: (() -> Void)?

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: systemImage)
                .font(.headline)
                .foregroundStyle(tint)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.headline)
                Text(message)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if let footnote {
                    Text(footnote)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
            Spacer(minLength: 0)
            if let dismiss {
                Button("Dismiss", systemImage: "xmark", action: dismiss)
                    .labelStyle(.iconOnly)
                    .font(.headline)
                    .frame(width: 44, height: 44)
            }
        }
        .padding(20)
        .carvisGlass(.tinted(tint), in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}
