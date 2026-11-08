import SwiftUI

/// Look at a part through your glasses, ask about it, and hear the answer.
/// The answer comes only from the car's service manual; if the manual
/// doesn't have it, Carvis says so instead of guessing.
/// All the listening and asking lives in `CarvisAssistant`; this screen shows it.
struct AskView: View {
    @Environment(CarvisAssistant.self) private var assistant
    @Environment(GlassesController.self) private var glasses
    @Environment(AccountStore.self) private var accounts
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @FocusState private var isQuestionFocused: Bool

    private var phase: CarvisAssistant.Phase { assistant.phase }
    private var isWorking: Bool { assistant.isWorking }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                cameraCard
                    .appearAnimation(index: 0)
                if let agent = assistant.agent, agent.isInCall || agent.state != .idle {
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
            .animation(reduceMotion ? .easeOut(duration: 0.2) : Motion.enter, value: assistant.agent?.state)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.interactively)
        .background { CarvisBackground() }
        .navigationTitle("Ask Carvis")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        // Carvis listens and the camera stays live while this screen is open.
        .onAppear { assistant.activate(.askScreen) }
        .onDisappear { assistant.deactivate(.askScreen) }
        .sensoryFeedback(.start, trigger: assistant.awaitingQuestionUntil != nil || assistant.listener.state == .hearingQuestion) { _, hearing in hearing }
        .sensoryFeedback(.success, trigger: phase) { _, new in
            if case .result(.answer) = new { return true }
            return false
        }
    }

    // MARK: - Camera

    private var cameraCard: some View {
        ZStack {
            Rectangle().fill(Theme.ink.opacity(0.9))

            if let shown = assistant.photo ?? (isWorking ? nil : glasses.frame) {
                Image(uiImage: shown)
                    .resizable()
                    .scaledToFill()
                    .transition(.opacity)
                    .accessibilityLabel(assistant.photo == nil ? "Live view from your glasses" : "Photo from your glasses")
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
            CameraBadge(isPhoto: assistant.photo != nil, status: glasses.status)
                .padding(16)
        }
        .overlay(alignment: .topTrailing) {
            if assistant.photo != nil, !isWorking {
                Button("Back to live view", systemImage: "arrow.uturn.backward") {
                    withAnimation(Motion.enter) { assistant.backToLive() }
                }
                .labelStyle(.iconOnly)
                .font(.title3.weight(.semibold))
                .frame(width: 52, height: 52)
                .carvisGlass(.card, in: Circle())
                .padding(12)
                .transition(.blurReplace)
            }
        }
        .animation(.easeOut(duration: 0.2), value: assistant.photo == nil)
    }

    // MARK: - Question

    private var questionCard: some View {
        @Bindable var assistant = assistant
        return VStack(alignment: .leading, spacing: 14) {
            Label(assistant.vehicle.displayName, systemImage: "car.side.fill")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.inkSecondary)

            VoiceRow(display: assistant.voiceDisplay, action: assistant.toggleVoice)

            TextField("What's the torque for this?", text: $assistant.question)
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
            .disabled(!assistant.canAsk)

            if let reason = assistant.disabledReason {
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

    private func ask() {
        isQuestionFocused = false
        assistant.askTyped()
    }

    // MARK: - Result

    @ViewBuilder
    private var resultSection: some View {
        if assistant.client == nil {
            NoticeCard(
                title: "Server address missing",
                message: "Add CarvisBaseURL to Carvis-Info.plist so Carvis knows where to send questions.",
                systemImage: "exclamationmark.triangle.fill",
                tint: Theme.safetyRed
            )
        }
        switch phase {
        case .result(.answer(let text, let component, let answerVehicle)):
            AnswerCard(answer: text, component: component, vehicle: answerVehicle, spokenThrough: assistant.spokenThrough)
                .transition(.blurReplace)
        case .result(.notInManual(let message, let component)):
            NoticeCard(
                title: "Not in the manual",
                message: message + (component.map { "\nCarvis thinks it sees: \($0.component) (\(percent($0.confidence)))." } ?? ""),
                systemImage: "book.closed.fill",
                tint: Theme.accent,
                footnote: assistant.spokenThrough
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
}

func percent(_ value: Double) -> String {
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
