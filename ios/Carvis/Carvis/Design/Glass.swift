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
    case dark               // the dark stat tile
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
        if case .dark = kind {
            // Solid, like the instrument panel it imitates. Glass would wash it out.
            content
                .background(shape.fill(Theme.tile))
                .shadow(color: Theme.ink.opacity(0.18), radius: 18, y: 10)
        } else if #available(iOS 26, *) {
            content
                .background(shape.fill(nativeFill))   // mostly white, so cards read as solid bento tiles
                .glassEffect(nativeGlass, in: shape)
                .shadow(color: Theme.ink.opacity(0.05), radius: 14, y: 6)
        } else {
            content
                .background(shape.fill(fallbackFill))
                .background(.ultraThinMaterial, in: shape)
                .overlay(shape.stroke(Color.white.opacity(0.9), lineWidth: 1))
                .shadow(color: Theme.ink.opacity(0.06), radius: 16, y: 6)
        }
    }

    @available(iOS 26, *)
    private var nativeGlass: Glass {
        switch kind {
        case .hero, .card, .dark: .regular
        case .tinted(let color): .regular.tint(color.opacity(0.25))
        case .prominent(let color): .regular.tint(color)
        }
    }

    private var nativeFill: Color {
        switch kind {
        case .hero: Color.white.opacity(0.92)
        case .card: Color.white.opacity(0.8)
        case .tinted, .prominent, .dark: Color.clear
        }
    }

    private var fallbackFill: Color {
        switch kind {
        case .hero: Color.white.opacity(0.95)
        case .card: Color.white.opacity(0.85)
        case .tinted(let color): color.opacity(0.16)
        case .prominent(let color): color.opacity(0.95)
        case .dark: Theme.tile
        }
    }
}

struct CarvisButtonModifier: ViewModifier {
    let prominent: Bool

    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            // Apple's glass button styles include their own press animation.
            if prominent {
                // White label: the app-wide ink text color would otherwise make it black on black.
                content.buttonStyle(.glassProminent).tint(Theme.ink).foregroundStyle(.white)
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
            .foregroundStyle(prominent ? Color.white : Theme.ink)
            .carvisGlass(prominent ? .prominent(Theme.ink) : .card, in: Capsule())
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

/// The cool grey "garage floor" behind everything, with a faint blue glow
/// near the top where the car sits.
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
                        [0, 0.45], [0.55, 0.35], [1, 0.4],
                        [0, 1], [0.5, 1], [1, 1]
                    ],
                    colors: [
                        Theme.sky, Theme.sky, Theme.accent.opacity(0.10),
                        Theme.pearl, Theme.sky, Theme.accent.opacity(0.06),
                        Theme.pearl, Theme.pearl, Theme.pearl
                    ]
                )
            } else {
                LinearGradient(
                    colors: [Theme.sky, Theme.pearl],
                    startPoint: .top,
                    endPoint: .bottom
                )
            }
        }
        .ignoresSafeArea()
    }
}

extension View {
    /// The floating main button (New job, Get started): dark frosted glass with a light edge,
    /// so the content scrolling behind it shows through.
    func floatingGlassButton() -> some View {
        buttonStyle(FloatingGlassButtonStyle())
    }
}

struct FloatingGlassButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(.white)
            .padding(.horizontal, 24)
            // A soft sheen across the top half, like light on glass.
            .background {
                Capsule().fill(LinearGradient(colors: [.white.opacity(0.18), .white.opacity(0)],
                                              startPoint: .top, endPoint: .center))
            }
            .modifier(DarkGlassBackground())
            .overlay {
                Capsule().strokeBorder(
                    LinearGradient(colors: [.white.opacity(0.45), .white.opacity(0.06)],
                                   startPoint: .top, endPoint: .bottom),
                    lineWidth: 1
                )
            }
            .shadow(color: Theme.ink.opacity(0.22), radius: 18, y: 10)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .opacity(isEnabled ? 1 : 0.45)
            .animation(.spring(duration: 0.2, bounce: 0), value: configuration.isPressed)
    }
}

private struct DarkGlassBackground: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 26, *) {
            content.glassEffect(.regular.tint(Theme.ink.opacity(0.82)).interactive(), in: Capsule())
        } else {
            content
                .background(Capsule().fill(Theme.ink.opacity(0.8)))
                .background(.ultraThinMaterial, in: Capsule())
        }
    }
}

/// A labelled group on the dashboard: a heading, then its cards on a soft frosted panel.
struct DashboardSection<Content: View>: View {
    var title: String?
    var subtitle: String?
    var tint: Color = .white
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let title {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.title2.weight(.semibold))
                        .tracking(-0.3)
                        .accessibilityAddTraits(.isHeader)
                    if let subtitle {
                        Text(subtitle)
                            .font(.subheadline)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }
                .padding(.horizontal, 6)
            }

            VStack(alignment: .leading, spacing: 12) {
                content
            }
            .padding(12)
            .background {
                RoundedRectangle(cornerRadius: 34, style: .continuous)
                    .fill(LinearGradient(colors: [tint.opacity(0.5), .white.opacity(0.25)],
                                         startPoint: .top, endPoint: .bottom))
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 34, style: .continuous))
                    .overlay(
                        RoundedRectangle(cornerRadius: 34, style: .continuous)
                            .strokeBorder(.white.opacity(0.7), lineWidth: 1)
                    )
            }
        }
    }
}
