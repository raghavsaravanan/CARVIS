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

/// The swipeable stack of step cards: a visual guide, secondary to talking with Carvis.
/// Swipe left to complete a step, right to go back. The card checks itself off as soon as
/// you've dragged far enough, then flies straight into the next one.
struct StepDeck: View {
    let response: StepResponse
    let onNext: () -> Void
    let onBack: () -> Void

    @State private var drag: CGSize = .zero
    @State private var flyingAway: CGFloat = 0
    @State private var isLeaving = false
    @State private var cardHeight: CGFloat = 260
    /// nil until a drag shows its direction; only sideways drags move the card.
    @State private var isSideways: Bool?
    @State private var hasHinted = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var step: Int { response.stepNumber }
    private var total: Int { response.totalSteps }
    private let swipeDistance: CGFloat = 100

    /// Dragged far enough to complete: the card shows it's checked off.
    private var isPastThreshold: Bool { drag.width < -swipeDistance }
    private var showsComplete: Bool { isPastThreshold || isLeaving }

    var body: some View {
        VStack(spacing: 14) {
            ZStack {
                // Upcoming steps wait behind, and the next one rises as you swipe.
                ForEach((1...2).reversed(), id: \.self) { depth in
                    if step + depth <= total {
                        PeekCard(number: step + depth, total: total)
                            .frame(height: cardHeight)
                            .scaleEffect(1 - CGFloat(depth) * 0.06 + lift(depth))
                            .offset(y: CGFloat(depth) * 28 - lift(depth) * 270)
                            .opacity(depth == 1 ? 0.95 : 0.6)
                            .allowsHitTesting(false)
                            .accessibilityHidden(true)
                    }
                }

                StepCard(response: response, visual: .forStep(step), completing: showsComplete)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { cardHeight = $0 }
                    .id(step)
                    .offset(x: drag.width + flyingAway, y: drag.height * 0.1)
                    .rotationEffect(.degrees(reduceMotion ? 0 : Double(drag.width + flyingAway) / 24), anchor: .bottom)
                    .simultaneousGesture(swipe)
                    // The next card takes the place of the one that rose behind it.
                    .transition(.asymmetric(insertion: .opacity.combined(with: .offset(y: 10)), removal: .identity))
                    .accessibilityAction(named: "Complete step") { leave() }
                    .accessibilityAction(named: "Previous step") { onBack() }
            }
            .padding(.bottom, 52)  // room for the waiting cards

            HStack(spacing: 8) {
                Image(systemName: "hand.draw.fill")
                    .foregroundStyle(Theme.accent)
                Text(step >= total ? "Swipe left to finish" : "Swipe left to complete")
                    .font(.subheadline.weight(.semibold))
                if step > 1 {
                    Text("· right to go back")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
            .frame(maxWidth: .infinity)
            .accessibilityHidden(true)
        }
        .sensoryFeedback(.impact(weight: .medium), trigger: isPastThreshold) { old, new in new && !old }
        // The new step arrived: reset instantly so the next card starts in place.
        .onChange(of: step) {
            withTransaction(Transaction(animation: nil)) {
                drag = .zero
                flyingAway = 0
                isLeaving = false
                isSideways = nil
            }
        }
        // On the first card, a half swipe shows that swiping is how you move on.
        .task(id: step) {
            guard step == 1, !hasHinted, !reduceMotion else { return }
            try? await Task.sleep(for: .milliseconds(900))
            guard !Task.isCancelled, drag == .zero, !isLeaving else { return }
            hasHinted = true
            withAnimation(.spring(duration: 0.55, bounce: 0)) { drag = CGSize(width: -swipeDistance * 0.7, height: 0) }
            try? await Task.sleep(for: .milliseconds(600))
            withAnimation(.spring(duration: 0.55, bounce: 0.3)) { drag = .zero }
        }
    }

    /// How far the next card has risen toward the front, 0 to 0.06.
    private func lift(_ depth: Int) -> CGFloat {
        guard depth == 1 else { return 0 }
        return min((abs(drag.width) + abs(flyingAway)) / 1600, 0.06)
    }

    private var swipe: some Gesture {
        DragGesture(minimumDistance: 10)
            .onChanged { value in
                guard !isLeaving else { return }
                if isSideways == nil {
                    isSideways = abs(value.translation.width) > abs(value.translation.height)
                }
                guard isSideways == true else { return }
                // Can't swipe back past the first step.
                let width = step <= 1 ? min(value.translation.width, value.translation.width / 4) : value.translation.width
                drag = CGSize(width: width, height: value.translation.height)
            }
            .onEnded { value in
                defer { isSideways = nil }
                guard isSideways == true, !isLeaving else { return }
                let flick = value.predictedEndTranslation.width
                if value.translation.width < -swipeDistance || flick < -swipeDistance * 2.5 {
                    leave()
                } else if (value.translation.width > swipeDistance || flick > swipeDistance * 2.5), step > 1 {
                    withAnimation(.spring(duration: 0.35, bounce: 0)) { drag = .zero }
                    onBack()
                } else {
                    withAnimation(.spring(duration: 0.4, bounce: 0.25)) { drag = .zero }
                }
            }
    }

    /// Fly the card off and move on as soon as it's out of sight. No pause.
    private func leave() {
        guard !isLeaving else { return }
        isLeaving = true
        withAnimation(.spring(duration: reduceMotion ? 0.2 : 0.3, bounce: 0)) {
            flyingAway = -700
            drag.height = 0
        }
        Task {
            try? await Task.sleep(for: .milliseconds(reduceMotion ? 120 : 240))
            onNext()
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
        VStack(alignment: .leading, spacing: 14) {
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
                        .font(.system(size: 27, weight: .semibold))
                        .foregroundStyle(.white)
                        .symbolEffect(.bounce, value: response.stepNumber)
                        .symbolEffect(.bounce, value: completing)
                }
                .frame(width: 60, height: 60)
                .accessibilityHidden(true)

                Text(visual.title)
                    .font(.system(size: 22, weight: .semibold))
                    .tracking(-0.4)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Text(response.safetyGate ? response.spokenText : response.displayText)
                .font(.body)
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
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous)
                .strokeBorder(response.safetyGate ? Theme.safetyRed.opacity(0.35) : Theme.ink.opacity(0.05), lineWidth: response.safetyGate ? 2 : 1)
        )
        .shadow(color: Theme.ink.opacity(0.12), radius: 24, y: 14)
        .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
        .animation(.spring(duration: 0.28, bounce: 0.3), value: completing)
        .accessibilityElement(children: .combine)
    }
}

/// A card waiting behind the front one. Just its edge shows, so it stays plain.
private struct PeekCard: View {
    let number: Int
    let total: Int

    var body: some View {
        RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous)
            .fill(Theme.card)
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous)
                    .strokeBorder(Theme.ink.opacity(0.05), lineWidth: 1)
            )
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
