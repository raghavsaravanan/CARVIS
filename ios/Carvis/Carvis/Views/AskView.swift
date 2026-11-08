import SwiftUI

/// Look at a part through your glasses, ask about it, and hear the answer.
/// The answer comes only from the car's service manual; if the manual
/// doesn't have it, Carvis says so instead of guessing.
struct AskView: View {
    @Environment(GlassesController.self) private var glasses
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
        .task { await listener.start() }
        .onDisappear {
            isOnScreen = false
            agent?.end()
            glasses.stopPreview()
            listener.stop()
            speech.stop()
        }
        // "Hey Carvis, ..." was heard.
        .onChange(of: listener.heard) { _, heard in
            guard let heard else { return }
            question = heard.text
            if agent != nil {
                startConversation(opening: heard.text)  // talk it through with Vapi
            } else {
                askByVoice()                             // one question, one answer
            }
        }
        .sensoryFeedback(.start, trigger: listener.state == .hearingQuestion) { _, hearing in hearing }
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
                                    detail: glasses.detail,
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

            VoiceToggle(listener: listener, usesVapi: agent != nil)

            TextField("What's the torque for this?", text: $question, axis: .vertical)
                .font(.title3)
                .lineLimit(1...3)
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
            guard isOnScreen else { return }
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

    private func speakAndWait(_ text: String) async {
        if let name = AudioRoute.bluetoothOutputName {
            spokenThrough = "Spoken through \(name)"
        } else {
            spokenThrough = "Spoken on your phone speaker. Your glasses aren't the audio output right now."
        }
        await speech.speakAndWait(text)
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

/// The "Hey Carvis" switch. When it's on, it shows what Carvis is hearing.
private struct VoiceToggle: View {
    let listener: VoiceListener
    let usesVapi: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button {
            if listener.isOn {
                listener.stop()
            } else {
                Task { await listener.start() }
            }
        } label: {
            HStack(spacing: 14) {
                ZStack {
                    if listener.isOn && listener.state != .paused {
                        LiveDot(size: 10)
                    } else {
                        Image(systemName: listener.isOn ? "mic.fill" : "mic.slash.fill")
                            .font(.headline)
                    }
                }
                .frame(width: 28)
                .foregroundStyle(listener.isOn ? Theme.accent : Theme.inkSecondary)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.headline)
                    Text(subtitle)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                }
                .contentTransition(.opacity)
                Spacer(minLength: 8)
                Text(listener.isOn ? "On" : "Off")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(listener.isOn ? Theme.accent : Theme.inkSecondary)
            }
            .padding(.horizontal, 18)
            .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight, alignment: .leading)
            .background(
                (listener.isOn ? Theme.accent.opacity(0.14) : Theme.ink.opacity(0.06)),
                in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
        }
        .buttonStyle(PressableCardStyle())
        .animation(reduceMotion ? nil : .easeOut(duration: 0.2), value: listener.state)
        .accessibilityValue(listener.isOn ? "On" : "Off")
    }

    private var title: String {
        switch listener.state {
        case .off: "Hey Carvis"
        case .starting: "Starting the microphone"
        case .listening: "Say \u{201C}Hey Carvis\u{201D} and your question"
        case .hearingQuestion: "Listening"
        case .paused: "Answering"
        case .unavailable: "Hey Carvis is off"
        }
    }

    private var subtitle: String {
        switch listener.state {
        case .off: usesVapi ? "Talk with Carvis hands-free" : "Ask hands-free through your glasses"
        case .starting: "One moment"
        case .listening: listener.microphoneName.map { "Using \($0)" } ?? "Using your phone\u{2019}s mic"
        case .hearingQuestion: listener.transcript.isEmpty ? "Go ahead" : "\u{201C}\(listener.transcript)\u{201D}"
        case .paused: usesVapi ? "In a conversation" : "I\u{2019}ll listen again when I\u{2019}m done"
        case .unavailable(let reason): reason
        }
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
    let detail: String
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
            if status != .notConnected {
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
