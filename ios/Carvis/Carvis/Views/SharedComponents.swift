import SwiftUI

// Small pieces used on more than one screen.

/// "Step 3 of 12" with an amber fill showing how far along you are.
struct ProgressCapsule: View {
    let step: Int
    let total: Int

    private var fraction: CGFloat {
        total > 0 ? CGFloat(step) / CGFloat(total) : 0
    }

    var body: some View {
        Text("Step \(step) of \(total)")
            .font(.subheadline.weight(.semibold))
            .monospacedDigit()
            .padding(.horizontal, 20)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .background(alignment: .leading) {
                GeometryReader { geometry in
                    Capsule()
                        .fill(Theme.accent.opacity(0.6))
                        .frame(width: geometry.size.width * fraction)
                }
            }
            .clipShape(Capsule())
            .carvisGlass(.card, in: Capsule())
    }
}

/// A small amber dot with a soft ring that keeps pulsing outward: "this is live".
/// With Reduce Motion on, it's just the dot.
struct LiveDot: View {
    var size: CGFloat = 8
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Circle()
            .fill(Theme.accent)
            .frame(width: size, height: size)
            .background {
                if !reduceMotion {
                    Circle()
                        .fill(Theme.accent)
                        .phaseAnimator([false, true]) { ring, expanded in
                            ring
                                .scaleEffect(expanded ? 2.8 : 1)
                                .opacity(expanded ? 0 : 0.45)
                        } animation: { expanded in
                            expanded ? .easeOut(duration: 1.6) : nil
                        }
                }
            }
            .accessibilityHidden(true)
    }
}

/// Soft red banner shown when a step has safety_gate = true.
struct SafetyBanner: View {
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.headline)
                .foregroundStyle(Theme.safetyRed)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("Safety check")
                    .font(.headline)
                Text(text)
                    .font(.body)
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .carvisGlass(.tinted(Theme.safetyRed), in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// Stand-in for the camera check that arrives with the glasses.
struct CameraCheckPlaceholder: View {
    let prompt: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "camera.viewfinder")
                .font(.title3)
                .foregroundStyle(Theme.inkSecondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("Camera check coming soon")
                    .font(.subheadline.weight(.semibold))
                Text(prompt)
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            }
            Spacer(minLength: 0)
        }
        .padding(16)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}
