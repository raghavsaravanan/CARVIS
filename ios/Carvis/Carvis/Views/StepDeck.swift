import SwiftUI

/// How each demo step looks on its card: an icon, a short title, the action the mechanic
/// completes, and what they'd say to the glasses when it's done. Demo content only; it has
/// no specs or numbers, which come from the manual.
struct StepVisual {
    let symbol: String
    let title: String
    let action: String
    let says: String
    var tools: [String] = []

    static func forStep(_ number: Int) -> StepVisual {
        let all: [StepVisual] = [
            StepVisual(symbol: "parkingsign.circle.fill", title: "Park the car",
                       action: "Parked, engine off, brake set", says: "Parked."),
            StepVisual(symbol: "arrow.up.circle.fill", title: "Lift onto jack stands",
                       action: "Car resting on two jack stands", says: "It's on the stands."),
            StepVisual(symbol: "wrench.and.screwdriver.fill", title: "Get your tools",
                       action: "Everything within reach", says: "Got everything.",
                       tools: ["Drain plug wrench", "Filter wrench", "Drain pan", "New filter", "New gasket", "Oil"]),
            StepVisual(symbol: "tray.fill", title: "Position the drain pan",
                       action: "Pan under the drain plug", says: "Pan's in place."),
            StepVisual(symbol: "arrow.counterclockwise.circle.fill", title: "Remove the drain plug",
                       action: "Plug out, oil draining", says: "It's draining."),
            StepVisual(symbol: "camera.viewfinder", title: "Let it drain",
                       action: "Glasses camera checked the opening", says: "Here's the opening."),
            StepVisual(symbol: "wrench.adjustable.fill", title: "Reinstall the drain plug",
                       action: "New gasket on, plug tightened", says: "Plug's back in."),
            StepVisual(symbol: "arrow.counterclockwise", title: "Remove the old filter",
                       action: "Old filter off", says: "Old filter's off."),
            StepVisual(symbol: "arrow.clockwise", title: "Install the new filter",
                       action: "New filter on, hand-tight plus three-quarters", says: "New filter's on."),
            StepVisual(symbol: "arrow.down.circle.fill", title: "Lower the car",
                       action: "Car back on its wheels", says: "It's down."),
            StepVisual(symbol: "drop.fill", title: "Add new oil",
                       action: "Oil in, cap back on", says: "Oil's in."),
            StepVisual(symbol: "gauge.with.dots.needle.67percent", title: "Check for leaks and level",
                       action: "No leaks, dipstick at full", says: "Reads full."),
        ]
        return all[min(max(number, 1), all.count) - 1]
    }
}

/// The swipeable stack of step cards. Swipe left to complete a step, right to go back.
struct StepDeck: View {
    let response: StepResponse
    let onNext: () -> Void
    let onBack: () -> Void

    @State private var drag: CGSize = .zero
    @State private var completing = false
    @State private var flyingAway: CGFloat = 0
    @State private var cardHeight: CGFloat = 300
    /// nil until a drag shows its direction; only sideways drags move the card.
    @State private var isSideways: Bool?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var step: Int { response.stepNumber }
    private var total: Int { response.totalSteps }
    private let swipeDistance: CGFloat = 110

    var body: some View {
        VStack(spacing: 18) {
            ZStack {
                // Upcoming steps peek out behind, smaller and lower.
                ForEach((1...2).reversed(), id: \.self) { depth in
                    if step + depth <= total {
                        PeekCard(number: step + depth, total: total)
                            .frame(height: cardHeight)
                            .scaleEffect(1 - CGFloat(depth) * 0.06 + peekLift(depth))
                            .offset(y: CGFloat(depth) * 30 - peekLift(depth) * 300)
                            .opacity(depth == 1 ? 0.9 : 0.6)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }
                }

                StepCard(response: response, visual: .forStep(step), completing: completing)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { cardHeight = $0 }
                    .id(step)
                    .offset(x: drag.width + flyingAway, y: drag.height * 0.15)
                    .rotationEffect(.degrees(reduceMotion ? 0 : Double(drag.width + flyingAway) / 22),
                                    anchor: .bottom)
                    .simultaneousGesture(swipe)
                    .transition(.asymmetric(
                        insertion: .scale(scale: 0.95).combined(with: .opacity),
                        removal: .opacity
                    ))
                    .accessibilityAction(named: "Next step") { complete() }
                    .accessibilityAction(named: "Previous step") { onBack() }
            }
            .padding(.bottom, 56)  // room for the peeking cards

            controls
        }
        .sensoryFeedback(.success, trigger: completing) { _, new in new }
        // The new step arrived: reset instantly so the next card starts centered.
        .onChange(of: step) {
            withTransaction(Transaction(animation: nil)) {
                drag = .zero
                flyingAway = 0
                completing = false
                isSideways = nil
            }
        }
    }

    /// As you drag, the next card rises a little to take the front card's place.
    private func peekLift(_ depth: Int) -> CGFloat {
        guard depth == 1 else { return 0 }
        return min(abs(drag.width) / 1600, 0.05)
    }

    private var controls: some View {
        HStack(spacing: 16) {
            Button(action: onBack) {
                Image(systemName: "chevron.left")
                    .font(.title3.weight(.semibold))
                    .frame(width: Theme.buttonHeight, height: Theme.buttonHeight)
            }
            .buttonStyle(PressableCardStyle())
            .carvisGlass(.card, in: Circle())
            .disabled(step <= 1)
            .opacity(step <= 1 ? 0.4 : 1)
            .accessibilityLabel("Previous step")

            VStack(spacing: 4) {
                Text(step >= total ? "Swipe to finish" : "Swipe to complete")
                    .font(.subheadline.weight(.semibold))
                Text("or say \u{201C}next\u{201D} to your glasses")
                    .font(.footnote)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .frame(maxWidth: .infinity)

            Button(action: complete) {
                Image(systemName: step >= total ? "checkmark" : "chevron.right")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: Theme.buttonHeight, height: Theme.buttonHeight)
                    .background(Theme.ink, in: Circle())
                    .overlay(Circle().strokeBorder(.white.opacity(0.18), lineWidth: 1))
                    .shadow(color: Theme.ink.opacity(0.25), radius: 14, y: 8)
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(PressableCardStyle())
            .accessibilityLabel(step >= total ? "Finish job" : "Next step")
        }
    }

    private var swipe: some Gesture {
        DragGesture(minimumDistance: 12)
            .onChanged { value in
                guard !completing else { return }
                if isSideways == nil {
                    isSideways = abs(value.translation.width) > abs(value.translation.height)
                }
                guard isSideways == true else { return }
                drag = value.translation
            }
            .onEnded { value in
                defer { isSideways = nil }
                guard !completing, isSideways == true else { return }
                let travel = value.predictedEndTranslation.width
                if value.translation.width < -swipeDistance || travel < -swipeDistance * 2.5 {
                    complete()
                } else if (value.translation.width > swipeDistance || travel > swipeDistance * 2.5), step > 1 {
                    withAnimation(.spring(duration: 0.45, bounce: 0.1)) { onBack() }
                } else {
                    withAnimation(.spring(duration: 0.4, bounce: 0.25)) { drag = .zero }
                }
            }
    }

    /// Check it off, show what the mechanic said, fly the card away, then move on.
    private func complete() {
        guard !completing else { return }
        withAnimation(.spring(duration: 0.3, bounce: 0.3)) { completing = true }
        Task {
            try? await Task.sleep(for: .milliseconds(reduceMotion ? 250 : 650))
            withAnimation(.spring(duration: 0.4, bounce: 0)) {
                flyingAway = reduceMotion ? 0 : -520
            }
            try? await Task.sleep(for: .milliseconds(reduceMotion ? 50 : 220))
            onNext()  // the card stays off screen until the next step arrives (see onChange)
        }
    }
}

/// The front card: what to do now, shown as something you complete.
private struct StepCard: View {
    let response: StepResponse
    let visual: StepVisual
    let completing: Bool

    private var tint: Color { response.safetyGate ? Theme.safetyRed : Theme.accent }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text("Step \(response.stepNumber) of \(response.totalSteps)")
                    .font(.subheadline.weight(.semibold))
                    .monospacedDigit()
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Theme.pearl, in: Capsule())
                Spacer()
                if response.safetyGate {
                    Label("Safety check", systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.safetyRed)
                } else if response.checkpoint.type == .vision {
                    Label("Camera check", systemImage: "eyeglasses")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.accent)
                }
            }

            HStack(alignment: .center, spacing: 16) {
                ZStack {
                    Circle()
                        .fill(LinearGradient(colors: [tint, tint.opacity(0.75)], startPoint: .top, endPoint: .bottom))
                        .shadow(color: tint.opacity(0.4), radius: 14, y: 8)
                    Image(systemName: visual.symbol)
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(.white)
                        .symbolEffect(.bounce, value: response.stepNumber)
                        .symbolEffect(.bounce, value: completing)
                }
                .frame(width: 76, height: 76)
                .accessibilityHidden(true)

                Text(visual.title)
                    .font(.system(size: 26, weight: .semibold))
                    .tracking(-0.4)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text(response.safetyGate ? response.spokenText : response.displayText)
                .font(.title3)
                .foregroundStyle(Theme.ink.opacity(0.85))
                .fixedSize(horizontal: false, vertical: true)

            if !visual.tools.isEmpty {
                FlowChips(items: visual.tools)
            }

            // The action, checked off as you complete it.
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .strokeBorder(completing ? Theme.accent : Theme.ink.opacity(0.2), lineWidth: 2)
                    if completing {
                        Circle().fill(Theme.accent)
                        Image(systemName: "checkmark")
                            .font(.subheadline.weight(.bold))
                            .foregroundStyle(.white)
                            .transition(.scale(scale: 0.4).combined(with: .opacity))
                    }
                }
                .frame(width: 30, height: 30)
                Text(visual.action)
                    .font(.body.weight(.semibold))
                    .strikethrough(completing, color: Theme.ink.opacity(0.4))
                    .foregroundStyle(completing ? Theme.inkSecondary : Theme.ink)
                Spacer(minLength: 0)
            }
            .padding(14)
            .background(completing ? Theme.accent.opacity(0.1) : Theme.pearl,
                        in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))

            // What the mechanic says to the glasses when they're done.
            if completing {
                HStack(spacing: 8) {
                    Spacer(minLength: 40)
                    Image(systemName: "waveform")
                        .font(.footnote.weight(.semibold))
                    Text("\u{201C}\(visual.says) Next.\u{201D}")
                        .font(.body.weight(.medium))
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Theme.ink, in: Capsule())
                .frame(maxWidth: .infinity, alignment: .trailing)
                .transition(.scale(scale: 0.8, anchor: .bottomTrailing).combined(with: .opacity))
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous)
                .strokeBorder(response.safetyGate ? Theme.safetyRed.opacity(0.35) : Theme.ink.opacity(0.05), lineWidth: response.safetyGate ? 2 : 1)
        )
        .shadow(color: Theme.ink.opacity(0.12), radius: 24, y: 14)
        .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// A card waiting behind the front one: just enough to show what's coming.
private struct PeekCard: View {
    let number: Int
    let total: Int

    var body: some View {
        let visual = StepVisual.forStep(number)
        HStack(spacing: 14) {
            Image(systemName: visual.symbol)
                .font(.title3.weight(.semibold))
                .foregroundStyle(Theme.inkSecondary)
                .frame(width: 48, height: 48)
                .background(Theme.pearl, in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text("Step \(number) of \(total)")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.inkTertiary)
                Text(visual.title)
                    .font(.headline)
                    .foregroundStyle(Theme.inkSecondary)
            }
            Spacer()
        }
        .padding(22)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .shadow(color: Theme.ink.opacity(0.08), radius: 16, y: 8)
    }
}

/// Small chips that wrap onto new lines.
private struct FlowChips: View {
    let items: [String]

    var body: some View {
        FlowLayout(spacing: 8) {
            ForEach(items, id: \.self) { item in
                Text(item)
                    .font(.footnote.weight(.semibold))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(Theme.accent.opacity(0.1), in: Capsule())
                    .foregroundStyle(Theme.accent)
            }
        }
    }
}

private struct FlowLayout: Layout {
    var spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, widest: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                y += rowHeight + spacing
                x = 0
                rowHeight = 0
            }
            x += size.width + spacing
            widest = max(widest, x - spacing)
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: min(widest, width), height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.maxX {
                y += rowHeight + spacing
                x = bounds.minX
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
