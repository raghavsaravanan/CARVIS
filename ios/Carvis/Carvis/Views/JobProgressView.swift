import SwiftUI

/// The live progress screen. View only: the glasses guide the repair,
/// and this screen shows where you are for you (on a break) or anyone watching.
struct JobProgressView: View {
    let session: RepairSession
    let response: StepResponse

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                heroCard
                StepTimeline(total: response.totalSteps,
                             currentStep: response.stepNumber,
                             seenSteps: session.seenSteps)
                    .appearAnimation(index: 2)
            }
            .padding(.horizontal, 20)
            .padding(.top, 4)
            .padding(.bottom, 24)
            .animation(Motion.change, value: response.stepNumber)
        }
        .scrollIndicators(.hidden)
        .background { CarvisBackground() }
        .toolbarBackground(.hidden, for: .navigationBar)
        // A light tick each time the job moves forward.
        .sensoryFeedback(.increase, trigger: response.stepNumber)
    }

    /// The job name, progress, and the swipeable stack of step cards.
    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 8) {
                LiveDot()
                Text(session.jobName)
                    .font(.headline)
                Spacer()
                Text("\(Int((Double(response.stepNumber - 1) / Double(max(response.totalSteps, 1))) * 100))%")
                    .font(.headline)
                    .monospacedDigit()
                    .foregroundStyle(Theme.accent)
                    .contentTransition(.numericText(value: Double(response.stepNumber)))
            }
            SegmentedProgress(step: response.stepNumber, total: response.totalSteps)

            StepDeck(response: response,
                     onNext: { Task { await session.next() } },
                     onBack: { session.goBack() })
                .padding(.top, 6)
        }
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
