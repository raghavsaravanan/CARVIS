import SwiftUI

/// The job screen. Carvis comes first: what your glasses see, what Carvis hears, and its
/// latest answer, because in practice you're under the car talking to it. The step cards
/// below are the visual guide.
struct JobProgressView: View {
    let session: RepairSession
    let response: StepResponse

    private var percentDone: Int {
        Int((Double(response.stepNumber - 1) / Double(max(response.totalSteps, 1))) * 100)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 8) {
                        LiveDot()
                        Text(session.jobName)
                            .font(.headline)
                        Spacer()
                        Text("\(percentDone)%")
                            .font(.headline)
                            .monospacedDigit()
                            .foregroundStyle(Theme.accent)
                            .contentTransition(.numericText(value: Double(response.stepNumber)))
                    }
                    SegmentedProgress(step: response.stepNumber, total: response.totalSteps)
                }

                AssistantPanel()
                    .appearAnimation(index: 0)

                Text("Step guide")
                    .font(.title3.weight(.semibold))
                    .padding(.top, 4)
                    .accessibilityAddTraits(.isHeader)

                StepDeck(response: response,
                         onNext: { Task { await session.next() } },
                         onBack: { session.goBack() })
                    .appearAnimation(index: 1)

                StepTimeline(total: response.totalSteps,
                             currentStep: response.stepNumber,
                             seenSteps: session.seenSteps)
                    .appearAnimation(index: 2)
            }
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 24)
            .animation(.spring(duration: 0.4, bounce: 0.1), value: response.stepNumber)
        }
        .scrollIndicators(.hidden)
        .background { CarvisBackground() }
        .toolbarBackground(.hidden, for: .navigationBar)
        // A light tick each time the job moves forward.
        .sensoryFeedback(.increase, trigger: response.stepNumber)
    }
}

/// Carvis during a job: the live view from your glasses, what it's hearing, and its
/// latest answer. Dark, like an instrument panel, so it's the first thing you see.
private struct AssistantPanel: View {
    @Environment(CarvisConversationCoordinator.self) private var assistant
    @Environment(GlassesController.self) private var glasses

    private var shown: UIImage? { assistant.photo ?? (assistant.isWorking ? nil : glasses.frame) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 10) {
                Circle()
                    .fill(Theme.lime)
                    .frame(width: 9, height: 9)
                    .phaseAnimator([false, true]) { dot, on in dot.opacity(on ? 1 : 0.35) } animation: { _ in .easeInOut(duration: 0.9) }
                Text("Carvis")
                    .font(.headline)
                Spacer()
                let isOn = assistant.voiceDisplay.isOn
                if assistant.isInConversation {
                    Button(action: assistant.endConversation) {
                        Label("End", systemImage: "phone.down.fill")
                            .font(.subheadline.weight(.semibold))
                            .padding(.horizontal, 14)
                            .frame(minHeight: 44)
                            .background(Theme.safetyRed.opacity(0.85), in: Capsule())
                    }
                    .buttonStyle(PressableCardStyle())
                    .accessibilityLabel("End conversation")
                    .transition(.blurReplace)
                }
                Button(action: assistant.toggleVoice) {
                    Label(isOn ? "Mute" : (assistant.voiceOn ? "Try again" : "Unmute"),
                          systemImage: isOn ? "mic.fill" : (assistant.voiceOn ? "arrow.clockwise" : "mic.slash.fill"))
                        .font(.subheadline.weight(.semibold))
                        .padding(.horizontal, 14)
                        .frame(minHeight: 44)
                        .background(.white.opacity(0.12), in: Capsule())
                        .contentTransition(.opacity)
                }
                .buttonStyle(PressableCardStyle())
                .accessibilityLabel(isOn ? "Mute Hey Carvis" : "Turn on Hey Carvis")
            }
            .foregroundStyle(.white)

            camera

            voiceLine

            if let reply = reply {
                VStack(alignment: .leading, spacing: 6) {
                    if let asked = reply.asked {
                        Text("\u{201C}\(asked)\u{201D}")
                            .font(.subheadline)
                            .foregroundStyle(.white.opacity(0.55))
                            .lineLimit(2)
                    }
                    Text(reply.text)
                        .font(.title2.weight(.semibold))
                        .foregroundStyle(reply.fromManual ? .white : Theme.warning)
                        .fixedSize(horizontal: false, vertical: true)
                    if reply.fromManual {
                        Label("From the service manual", systemImage: "book.fill")
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(Theme.lime)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.white.opacity(0.07), in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
                .transition(.blurReplace)
                .accessibilityElement(children: .combine)
            }
        }
        .padding(18)
        .carvisGlass(.dark, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .animation(.spring(duration: 0.4, bounce: 0), value: assistant.phase)
    }

    private var reply: (asked: String?, text: String, fromManual: Bool)? {
        // A conversation's answer comes from the server's memory, so it's what was validated.
        if let grounded = assistant.serverState?.grounded_answer {
            return (grounded.query, grounded.text, true)
        }
        switch assistant.phase {
        case .result(.answer(let text, _, _)): return (assistant.askedQuestion, text, true)
        case .result(.notInManual(let message, _)): return (assistant.askedQuestion, "Not in the manual. \(message)", false)
        case .failed(let message): return (assistant.askedQuestion, "Couldn\u{2019}t get an answer. \(message)", false)
        default: return nil
        }
    }

    /// What the glasses see, live, or the photo Carvis just used.
    private var camera: some View {
        ZStack {
            Rectangle().fill(.black.opacity(0.5))
            if let shown {
                Image(uiImage: shown)
                    .resizable()
                    .scaledToFill()
                    .transition(.opacity)
                    .accessibilityLabel(assistant.photo == nil ? "Live view from your glasses" : "What Carvis looked at")
            } else if !glasses.isConnected {
                VStack(spacing: 12) {
                    Text("Connect your glasses so Carvis can see what you see")
                        .font(.headline)
                        .foregroundStyle(.white)
                        .multilineTextAlignment(.center)
                    Button(action: glasses.connect) {
                        Text(glasses.status == .connecting ? "Finish in the Meta AI app" : "Connect glasses")
                            .font(.headline)
                            .foregroundStyle(Theme.ink)
                            .padding(.horizontal, 22)
                            .frame(minHeight: 48)
                            .background(Theme.lime, in: Capsule())
                    }
                    .buttonStyle(PressableCardStyle())
                    .disabled(glasses.status == .connecting)
                }
                .padding(18)
            } else {
                VStack(spacing: 10) {
                    ProgressView().tint(.white)
                    Text(assistant.isWorking ? "Looking\u{2026}" : "Starting the glasses camera")
                        .font(.subheadline.weight(.medium))
                        .foregroundStyle(.white.opacity(0.75))
                }
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 200)
        .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .overlay(alignment: .topLeading) {
            if shown != nil {
                HStack(spacing: 6) {
                    if assistant.photo == nil {
                        Circle().fill(Theme.lime).frame(width: 7, height: 7)
                        Text("Live from your glasses")
                    } else {
                        Image(systemName: "camera.fill")
                        Text("What Carvis looked at")
                    }
                }
                .font(.caption.weight(.semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(.black.opacity(0.45), in: Capsule())
                .padding(10)
            }
        }
        .overlay(alignment: .topTrailing) {
            if assistant.photo != nil, !assistant.isWorking {
                Button("Back to live view", systemImage: "arrow.uturn.backward") {
                    withAnimation(.easeOut(duration: 0.25)) { assistant.backToLive() }
                }
                .labelStyle(.iconOnly)
                .font(.subheadline.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(.black.opacity(0.45), in: Circle())
                .padding(6)
            }
        }
        .animation(.easeOut(duration: 0.25), value: assistant.photo == nil)
    }

    /// What Carvis is doing right now: listening, hearing you, looking, answering.
    private var voiceLine: some View {
        let display = assistant.voiceDisplay
        return HStack(spacing: 12) {
            ZStack {
                if display.isLive {
                    Circle()
                        .fill(Theme.lime.opacity(0.18))
                        .frame(width: 40, height: 40)
                        .phaseAnimator([false, true]) { ring, big in ring.scaleEffect(big ? 1.15 : 0.9) } animation: { _ in .easeInOut(duration: 1.1) }
                    Image(systemName: "waveform")
                        .font(.headline)
                        .foregroundStyle(Theme.lime)
                        .symbolEffect(.variableColor.iterative, isActive: true)
                } else if assistant.isWorking {
                    ProgressView().tint(Theme.lime)
                } else {
                    Image(systemName: display.isOn ? "ellipsis" : "mic.slash.fill")
                        .font(.headline)
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
            .frame(width: 40, height: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(display.title)
                    .font(.headline)
                    .foregroundStyle(.white)
                Text(display.subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.white.opacity(0.6))
                    .lineLimit(2)
            }
            .contentTransition(.opacity)
            Spacer(minLength: 0)
        }
        .animation(.easeOut(duration: 0.2), value: display)
        .accessibilityElement(children: .combine)
    }
}

/// One small bar per step: done steps filled, the current one glowing.
private struct SegmentedProgress: View {
    let step: Int
    let total: Int

    var body: some View {
        HStack(spacing: 4) {
            ForEach(1...max(total, 1), id: \.self) { number in
                Capsule()
                    .fill(number < step ? Theme.accent : number == step ? Theme.accent.opacity(0.45) : Theme.ink.opacity(0.08))
                    .frame(height: 6)
                    .shadow(color: number == step ? Theme.accent.opacity(0.5) : .clear, radius: 5)
            }
        }
        .animation(.spring(duration: 0.5, bounce: 0), value: step)
        .accessibilityElement()
        .accessibilityLabel("Step \(step) of \(total)")
    }
}

/// Every step in the job as a vertical line of dots.
/// Done steps show what they said, the current step is highlighted,
/// and upcoming steps only show their number (the backend doesn't send them ahead of time).
private struct StepTimeline: View {
    let total: Int
    let currentStep: Int
    let seenSteps: [Int: StepResponse]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Label {
                Text("Steps")
            } icon: {
                Image(systemName: "list.bullet")
                    .foregroundStyle(Theme.accent)
            }
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(Theme.inkSecondary)
            .padding(.bottom, 16)
            .accessibilityAddTraits(.isHeader)

            ForEach(1..<total + 1, id: \.self) { number in
                TimelineRow(
                    number: number,
                    state: state(for: number),
                    text: seenSteps[number]?.displayText,
                    isSafety: seenSteps[number]?.safetyGate ?? false,
                    isLast: number == total
                )
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private func state(for number: Int) -> TimelineRow.StepState {
        if number < currentStep { return .done }
        if number == currentStep { return .current }
        return .upcoming
    }
}

private struct TimelineRow: View {
    enum StepState { case done, current, upcoming }

    let number: Int
    let state: StepState
    let text: String?
    let isSafety: Bool
    let isLast: Bool

    private let nodeSize: CGFloat = 28

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack { node }
                .frame(width: nodeSize, height: nodeSize)
            ZStack(alignment: .topLeading) { label }
                .padding(.top, 3)
                .padding(.bottom, isLast ? 0 : 18)
            Spacer(minLength: 0)
        }
        // The line connecting this dot to the next one. It turns amber once the step is done.
        .background(alignment: .leading) {
            if !isLast {
                Rectangle()
                    .fill(state == .done ? Theme.accent : Theme.ink.opacity(0.1))
                    .frame(width: 3)
                    .padding(.top, nodeSize + 2)
                    .padding(.leading, (nodeSize - 3) / 2)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityValue(accessibilityState)
    }

    /// Each state swaps in with a small scale + fade, so a step "pops" to done.
    @ViewBuilder
    private var node: some View {
        switch state {
        case .done:
            Circle()
                .fill(Theme.accent)
                .overlay {
                    Image(systemName: "checkmark")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(.white)
                }
                .transition(.scale(scale: 0.7).combined(with: .opacity))
        case .current:
            Circle()
                .fill(Theme.accent.opacity(0.2))
                .overlay(Circle().strokeBorder(Theme.accent, lineWidth: 3))
                .overlay(LiveDot(size: 10))
                .transition(.scale(scale: 0.7).combined(with: .opacity))
        case .upcoming:
            Circle()
                .strokeBorder(Theme.ink.opacity(0.15), lineWidth: 2)
                .overlay {
                    Text("\(number)")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Theme.ink.opacity(0.55))
                }
                .transition(.opacity)
        }
    }

    @ViewBuilder
    private var label: some View {
        switch state {
        case .done:
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                if isSafety { safetyIcon }
                Text(text ?? "Step \(number)")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .lineLimit(2)
            }
            .transition(.blurReplace)
        case .current:
            VStack(alignment: .leading, spacing: 2) {
                Text("Step \(number), now")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.inkSecondary)
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if isSafety { safetyIcon }
                    Text(text ?? "Step \(number)")
                        .font(.body.weight(.semibold))
                        .lineLimit(3)
                }
            }
            .transition(.blurReplace)
        case .upcoming:
            Text("Step \(number)")
                .font(.subheadline)
                .foregroundStyle(Theme.ink.opacity(0.55))
                .transition(.opacity)
        }
    }

    private var safetyIcon: some View {
        Image(systemName: "exclamationmark.triangle.fill")
            .font(.caption)
            .foregroundStyle(Theme.safetyRed)
            .accessibilityLabel("Safety step")
    }

    private var accessibilityState: String {
        switch state {
        case .done: "Done"
        case .current: "Current step"
        case .upcoming: "Not started"
        }
    }
}
