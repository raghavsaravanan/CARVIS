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

    /// The gauge plus what's happening right now.
    private var heroCard: some View {
        VStack(spacing: 20) {
            HStack(spacing: 8) {
                LiveDot()
                Text(session.jobName)
                    .font(.headline)
                    .foregroundStyle(Theme.inkSecondary)
            }

            ArcGauge(step: response.stepNumber, total: response.totalSteps)
                // DEMO ONLY: until the glasses are connected, tapping the gauge moves to the next step.
                .onTapGesture {
                    Task { await session.next() }
                }

            if response.safetyGate {
                SafetyBanner(text: response.displayText)
                    .transition(.blurReplace)
            }

            // The text cross-fades with a slight blur, so the old and new steps
            // read as one smooth change instead of two overlapping blocks.
            ZStack(alignment: .topLeading) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Now")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.inkSecondary)
                    // On safety steps the banner holds display_text, so show the full spoken instruction here.
                    Text(response.safetyGate ? response.spokenText : response.displayText)
                        .font(.title.weight(.semibold))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .id(response.stepNumber)
                .transition(.blurReplace)
            }
            .accessibilityElement(children: .combine)

            if response.checkpoint.type == .vision {
                CameraCheckPlaceholder(prompt: response.checkpoint.prompt)
                    .transition(.blurReplace)
            }
        }
        .padding(24)
        .carvisGlass(.hero, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
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
                    .foregroundStyle(Theme.amber)
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
                    .fill(state == .done ? Theme.amber : Theme.ink.opacity(0.1))
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
                .fill(Theme.amber)
                .overlay {
                    Image(systemName: "checkmark")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(Theme.ink)
                }
                .transition(.scale(scale: 0.7).combined(with: .opacity))
        case .current:
            Circle()
                .fill(Theme.amber.opacity(0.2))
                .overlay(Circle().strokeBorder(Theme.amber, lineWidth: 3))
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
