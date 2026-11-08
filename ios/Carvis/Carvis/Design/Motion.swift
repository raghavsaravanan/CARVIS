import SwiftUI

// All of Carvis's motion lives here so every screen moves the same way.
// Rules we follow:
// - Things enter with springs that settle quickly, with no bounce (calm, premium).
// - Nothing appears from nothing: entrances start slightly smaller and faded, not at zero.
// - Presses respond instantly with a small squeeze.
// - Reduce Motion swaps movement for simple fades.

enum Motion {
    /// Cards and content entering the screen.
    static let enter = Animation.spring(duration: 0.5, bounce: 0)
    /// Something on screen changing, like the gauge filling or a step updating.
    static let change = Animation.spring(duration: 0.6, bounce: 0)
    /// The one celebratory moment: finishing a job.
    static let celebrate = Animation.spring(duration: 0.6, bounce: 0.3)
    /// Delay between cards in a staggered entrance.
    static let stagger: Double = 0.06
}

/// A pressable card: squeezes to 97% while pressed and springs back on release.
struct PressableCardStyle: ButtonStyle {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .opacity(configuration.isPressed && reduceMotion ? 0.85 : 1)
            .animation(.spring(duration: 0.2, bounce: 0), value: configuration.isPressed)
    }
}

/// Fades and lifts a view into place the first time it appears.
/// `index` staggers a group so cards arrive one after another.
private struct AppearModifier: ViewModifier {
    let index: Int
    @State private var isVisible = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .opacity(isVisible ? 1 : 0)
            .offset(y: isVisible || reduceMotion ? 0 : 14)
            .scaleEffect(isVisible || reduceMotion ? 1 : 0.98)
            .onAppear {
                guard !isVisible else { return }
                withAnimation(Motion.enter.delay(Double(index) * Motion.stagger)) {
                    isVisible = true
                }
            }
    }
}

extension View {
    /// Animate in on first appearance. Use increasing `index` values to stagger.
    func appearAnimation(index: Int = 0) -> some View {
        modifier(AppearModifier(index: index))
    }

    /// Marks this view as where the zoom transition starts (iOS 18+).
    @ViewBuilder
    func zoomSource(id: String, in namespace: Namespace.ID, isEnabled: Bool = true) -> some View {
        if #available(iOS 18, *), isEnabled {
            matchedTransitionSource(id: id, in: namespace)
        } else {
            self
        }
    }

    /// Opens this screen by zooming out of the matching source (iOS 18+).
    /// Older iOS uses the normal slide.
    @ViewBuilder
    func zoomDestination(id: String, in namespace: Namespace.ID) -> some View {
        if #available(iOS 18, *) {
            navigationTransition(.zoom(sourceID: id, in: namespace))
        } else {
            self
        }
    }
}

// MARK: - Dashboard motion

extension View {
    /// Cards ease up into place as they scroll into view (once a quarter of them shows).
    func scrollReveal() -> some View {
        modifier(ScrollRevealModifier())
    }
}

private struct ScrollRevealModifier: ViewModifier {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        let moves = !reduceMotion  // read here: the transition closure runs off the main actor
        return content.scrollTransition(.animated(.spring(duration: 0.55, bounce: 0)).threshold(.visible(0.25))) { view, phase in
            let entering = phase == .bottomTrailing && moves
            return view
                .opacity(entering ? 0.35 : 1)
                .scaleEffect(entering ? 0.96 : 1)
                .offset(y: entering ? 18 : 0)
        }
    }
}

/// A number that rolls up from zero the first time it appears, then rolls between values.
struct RollingNumber: View {
    let value: Int
    var delay: Double = 0.25
    @State private var shown: Int?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Text((shown ?? 0).formatted())
            .monospacedDigit()
            .contentTransition(.numericText(value: Double(shown ?? 0)))
            .onAppear {
                guard shown == nil else { return }
                if reduceMotion {
                    shown = value
                } else {
                    shown = 0
                    withAnimation(.smooth(duration: 0.9).delay(delay)) { shown = value }
                }
            }
            .onChange(of: value) { _, new in
                withAnimation(.smooth(duration: 0.5)) { shown = new }
            }
            .accessibilityLabel(value.formatted())
    }
}

/// Fills from empty to `fraction` the first time it appears.
struct FillOnAppear: ViewModifier {
    let delay: Double
    @Binding var filled: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content.onAppear {
            guard !filled else { return }
            if reduceMotion { filled = true; return }
            withAnimation(.spring(duration: 1.0, bounce: 0).delay(delay)) { filled = true }
        }
    }
}
