import SwiftUI

// The one place that decides how glass looks.
// On iOS 26 and later it uses Apple's Liquid Glass.
// On older iOS it uses a frosted material with a thin white edge and a soft shadow.

/// The kinds of glass used in the app, from most to least opaque.
enum GlassKind {
    case hero               // the step instruction panel: thickest, most opaque
    case card               // secondary cards and buttons
    case tinted(Color)      // a lightly colored card, like the safety banner
    case prominent(Color)   // the main button
}

extension View {
    /// Put this view on glass, e.g. `.carvisGlass(.card, in: Capsule())`.
    func carvisGlass(_ kind: GlassKind, in shape: some Shape) -> some View {
        modifier(CarvisGlassModifier(kind: kind, shape: shape))
    }

    /// Style a button as a Carvis glass button.
    func carvisButton(prominent: Bool = false) -> some View {
        modifier(CarvisButtonModifier(prominent: prominent))
    }
}

struct CarvisGlassModifier<S: Shape>: ViewModifier {
    let kind: GlassKind
    let shape: S

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content
                .background(shape.fill(nativeFill))   // extra white makes the hero panel more opaque
                .glassEffect(nativeGlass, in: shape)
        } else {
            content
                .background(shape.fill(fallbackFill))
                .background(.ultraThinMaterial, in: shape)
                .overlay(shape.stroke(Color.white.opacity(0.7), lineWidth: 1))
                .shadow(color: Theme.ink.opacity(0.08), radius: 16, y: 6)
        }
    }

    @available(iOS 26, *)
    private var nativeGlass: Glass {
        switch kind {
        case .hero, .card: .regular
        case .tinted(let color): .regular.tint(color.opacity(0.25))
        case .prominent(let color): .regular.tint(color)
        }
    }

    private var nativeFill: Color {
        switch kind {
        case .hero: Color.white.opacity(0.55)
        case .card: Color.white.opacity(0.15)
        case .tinted, .prominent: Color.clear
        }
    }

    private var fallbackFill: Color {
        switch kind {
        case .hero: Color.white.opacity(0.6)
        case .card: Color.white.opacity(0.25)
        case .tinted(let color): color.opacity(0.16)
        case .prominent(let color): color.opacity(0.85)
        }
    }
}

struct CarvisButtonModifier: ViewModifier {
    let prominent: Bool

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            // Apple's glass button styles include their own press animation.
            if prominent {
                content.buttonStyle(.glassProminent).tint(Theme.amber)
            } else {
                content.buttonStyle(.glass)
            }
        } else {
            content.buttonStyle(FallbackGlassButtonStyle(prominent: prominent))
        }
    }
}

/// Button style for iOS 17 and 18: glass capsule plus a small spring when pressed.
struct FallbackGlassButtonStyle: ButtonStyle {
    let prominent: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .padding(.horizontal, 20)
            .carvisGlass(prominent ? .prominent(Theme.amber) : .card, in: Capsule())
            .scaleEffect(configuration.isPressed ? 0.96 : 1)
            .animation(reduceMotion ? nil : .spring(response: 0.3, dampingFraction: 0.6),
                       value: configuration.isPressed)
    }
}

/// Groups glass elements so Liquid Glass can blend them together (iOS 26+).
/// On older iOS it just shows the content.
struct CarvisGlassGroup<Content: View>: View {
    var spacing: CGFloat = 16
    @ViewBuilder var content: Content

    var body: some View {
        if #available(iOS 26, *) {
            GlassEffectContainer(spacing: spacing) { content }
        } else {
            content
        }
    }
}

/// The soft, light background the glass sits on.
/// The amber glow is at the bottom, behind the main buttons.
struct CarvisBackground: View {
    var body: some View {
        ZStack {
            Theme.pearl
            if #available(iOS 18, *) {
                MeshGradient(
                    width: 3,
                    height: 3,
                    points: [
                        [0, 0], [0.5, 0], [1, 0],
                        [0, 0.5], [0.6, 0.45], [1, 0.5],
                        [0, 1], [0.5, 1], [1, 1]
                    ],
                    colors: [
                        Theme.sky, Theme.pearl, Theme.sky,
                        Theme.pearl, Theme.pearl, Theme.sky.opacity(0.8),
                        Theme.sky.opacity(0.7), Theme.amber.opacity(0.22), Theme.amber.opacity(0.3)
                    ]
                )
            } else {
                LinearGradient(
                    colors: [Theme.sky, Theme.pearl, Theme.amber.opacity(0.22)],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
        }
        .ignoresSafeArea()
    }
}
