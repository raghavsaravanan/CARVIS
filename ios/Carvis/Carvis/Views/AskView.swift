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
                questionCard
                    .appearAnimation(index: 1)
                resultSection
            }
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 24)
            .animation(reduceMotion ? .easeOut(duration: 0.2) : Motion.enter, value: phase)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.interactively)
        .background { CarvisBackground() }
        .navigationTitle("Ask Carvis")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .onAppear { glasses.startPreview() }
        .onDisappear {
            glasses.stopPreview()
            speech.stop()
        }
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
                CameraStatusMessage(status: glasses.status, onConnect: glasses.connect)
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
                tint: Theme.amber,
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
        guard canAsk, let client else { return }
        isQuestionFocused = false
        speech.stop()
        let asked = trimmedQuestion
        phase = .capturing
        Task {
            do {
                let jpeg = try await glasses.capturePhoto()
                photo = UIImage(data: jpeg)
                phase = .asking
                let result = try await client.ask(photo: jpeg, question: asked, vehicle: vehicle, sessionID: sessionID)
                switch result {
                case .answer(let text, _, _):
                    speak(text)
                case .notInManual(let message, _):
                    speak(message)
                }
                phase = .result(result)
            } catch {
                phase = .failed(error.localizedDescription)
            }
        }
    }

    private func speak(_ text: String) {
        speech.speak(text)
        if let name = AudioRoute.bluetoothOutputName {
            spokenThrough = "Spoken through \(name)"
        } else {
            spokenThrough = "Spoken on your phone speaker. Your glasses aren't the audio output right now."
        }
    }
}

private func percent(_ value: Double) -> String {
    value.formatted(.percent.precision(.fractionLength(0)))
}

// MARK: - Pieces

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
    let onConnect: () -> Void

    var body: some View {
        VStack(spacing: 14) {
            if status == .startingCamera || status == .connecting {
                ProgressView()
                    .controlSize(.large)
                    .tint(.white)
            } else {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 40, weight: .medium))
                    .foregroundStyle(Theme.amber)
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
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var text: String {
        switch status {
        case .notConnected: "Connect your glasses to see what they see"
        case .connecting: "Finish in the Meta AI app"
        case .lookingForGlasses: "Put on your glasses and open the arms"
        case .ready, .startingCamera: "Starting the glasses camera"
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
