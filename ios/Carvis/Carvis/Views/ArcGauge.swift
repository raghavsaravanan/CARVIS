import SwiftUI

/// A round gauge, like a car's fuel gauge, split into one segment per step.
/// The amber part sweeps up to the current step with a glowing tip, and the
/// big number rolls when the step changes.
struct ArcGauge: View {
    let step: Int
    let total: Int

    private let size: CGFloat = 220
    private let lineWidth: CGFloat = 18
    private let sweep: CGFloat = 0.75   // the arc covers 3/4 of a circle, open at the bottom

    /// What's drawn right now. It animates toward `fraction`, starting from 0 so the
    /// gauge sweeps up when the screen opens.
    @State private var shownFraction: CGFloat = 0
    @ScaledMetric(relativeTo: .largeTitle) private var numberSize: CGFloat = 72
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var fraction: CGFloat {
        total > 0 ? min(CGFloat(step) / CGFloat(total), 1) : 0
    }

    private var strokeStyle: StrokeStyle {
        StrokeStyle(lineWidth: lineWidth, lineCap: .round)
    }

    var body: some View {
        ZStack {
            // Track for the whole job.
            arc(to: sweep)
                .stroke(Theme.ink.opacity(0.07), style: strokeStyle)

            // Amber fill for how far you've come, with a soft glow.
            arc(to: sweep * shownFraction)
                .stroke(Theme.amber, style: strokeStyle)
                .shadow(color: Theme.amber.opacity(0.35), radius: 8)

            // Thin white notches split the arc into steps.
            ForEach(1..<max(total, 1), id: \.self) { index in
                notch(at: CGFloat(index) / CGFloat(total))
            }

            // A small white knob riding on the end of the fill.
            if shownFraction > 0 {
                Circle()
                    .fill(Color.white)
                    .frame(width: lineWidth - 8, height: lineWidth - 8)
                    .shadow(color: Theme.amber.opacity(0.6), radius: 4)
                    .offset(y: -size / 2)
                    .rotationEffect(.degrees(225 + 270 * shownFraction))
            }

            VStack(spacing: 0) {
                Text("\(step)")
                    .font(.system(size: numberSize, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .contentTransition(.numericText(value: Double(step)))   // digits roll up
                    .minimumScaleFactor(0.5)
                    .lineLimit(1)
                Text("of \(total) steps")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            }
            .padding(.horizontal, 40)
        }
        .frame(width: size, height: size)
        .padding(lineWidth / 2)
        .onAppear {
            if reduceMotion {
                shownFraction = fraction
            } else {
                // Wait for the screen's zoom to settle, then sweep up.
                withAnimation(Motion.change.delay(0.25)) { shownFraction = fraction }
            }
        }
        .onChange(of: fraction) { _, newValue in
            withAnimation(reduceMotion ? nil : Motion.change) { shownFraction = newValue }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Step \(step) of \(total)")
    }

    /// Part of the circle, turned so the opening faces down.
    private func arc(to end: CGFloat) -> some Shape {
        Circle()
            .trim(from: 0, to: end)
            .rotation(.degrees(135))
    }

    /// A small white line across the arc at position t (0 = start, 1 = end).
    private func notch(at t: CGFloat) -> some View {
        Capsule()
            .fill(Color.white)
            .frame(width: 3, height: lineWidth + 2)
            .offset(y: -size / 2)
            .rotationEffect(.degrees(225 + 270 * t))
    }
}

#Preview {
    ArcGauge(step: 6, total: 12)
}
