import SwiftUI

/// Pops up from the dashboard in two steps:
/// 1. What you're working on: the job name and what to expect.
/// 2. Your glasses: whether they're connected, then Start.
struct NewJobSheet: View {
    /// The car this job is on.
    let vehicleName: String
    /// Called with the job name when you tap Start.
    let onStart: (String) -> Void

    @State private var name = "Oil change"
    @State private var isAskingForGlasses = false
    @FocusState private var isNameFieldFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(GlassesController.self) private var glasses

    private var trimmedName: String {
        name.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        ZStack {
            if isAskingForGlasses {
                glassesStep
                    .transition(.blurReplace)
            } else {
                nameStep
                    .transition(.blurReplace)
            }
        }
        .padding(24)
        .foregroundStyle(Theme.ink)
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .presentationBackground(Theme.pearl)
        .sensoryFeedback(.selection, trigger: isAskingForGlasses)
    }

    // MARK: - Step 1

    private var nameStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            StepHeader(number: 1, title: "New job", subtitle: vehicleName)

            VStack(alignment: .leading, spacing: 10) {
                Text("Name this job")
                    .font(.headline)
                TextField("Job name", text: $name)
                    .font(.title3)
                    .submitLabel(.next)
                    .focused($isNameFieldFocused)
                    .onSubmit(goToGlassesStep)
                    .padding(.horizontal, 20)
                    .frame(minHeight: 60)
                    .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
            }

            // What Carvis will walk you through.
            HStack(spacing: 14) {
                Image(systemName: "drop.fill")
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(Theme.accent, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                VStack(alignment: .leading, spacing: 4) {
                    Text("Oil change · 12 steps")
                        .font(.headline)
                    HStack(spacing: 3) {
                        ForEach(0..<12, id: \.self) { index in
                            Capsule()
                                .fill(index == 0 ? Theme.accent : Theme.ink.opacity(0.1))
                                .frame(height: 5)
                        }
                    }
                    Text("Includes 2 safety checks and a camera check")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(16)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))

            Spacer(minLength: 0)

            Button(action: goToGlassesStep) {
                Label("Next", systemImage: "arrow.right")
                    .labelStyle(TitleThenIcon())
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
            }
            .floatingGlassButton()
            .disabled(trimmedName.isEmpty)
        }
        .onAppear { isNameFieldFocused = true }
    }

    // MARK: - Step 2

    private var glassesStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            StepHeader(number: 2, title: "Put on your glasses", subtitle: trimmedName)

            // A small dark "showroom" panel with the glasses and their status.
            VStack(spacing: 16) {
                ZStack {
                    RadialGradient(colors: [Theme.accent.opacity(0.55), .clear], center: .center, startRadius: 4, endRadius: 110)
                    Image(systemName: "eyeglasses")
                        .font(.system(size: 64, weight: .medium))
                        .foregroundStyle(.white)
                        .symbolEffect(.bounce, value: glasses.isConnected)
                }
                .frame(height: 130)

                HStack(spacing: 8) {
                    Circle()
                        .fill(glasses.isConnected ? Theme.lime : .white.opacity(0.35))
                        .frame(width: 9, height: 9)
                    Text(glasses.isConnected ? "Glasses connected" : "Glasses not connected")
                        .font(.headline)
                        .foregroundStyle(.white)
                        .contentTransition(.opacity)
                }

                if !glasses.isConnected {
                    Button(action: glasses.connect) {
                        Text(glasses.status == .connecting ? "Finish in the Meta AI app" : "Connect glasses")
                            .font(.headline)
                            .foregroundStyle(Theme.ink)
                            .padding(.horizontal, 24)
                            .frame(minHeight: 52)
                            .background(Theme.lime, in: Capsule())
                    }
                    .buttonStyle(PressableCardStyle())
                    .disabled(glasses.status == .connecting)
                    .transition(.scale(scale: 0.9).combined(with: .opacity))
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity)
            .background(Theme.tile, in: RoundedRectangle(cornerRadius: Theme.Radius.hero, style: .continuous))
            .animation(.spring(duration: 0.4, bounce: 0), value: glasses.isConnected)

            VStack(alignment: .leading, spacing: 12) {
                Tip(symbol: "rectangle.stack.fill", text: "Each step shows as a card on your phone. Swipe it when you're done.")
                Tip(symbol: "speaker.wave.2.fill", text: "Carvis reads every step out loud.")
            }

            Spacer(minLength: 0)

            HStack(spacing: 12) {
                Button {
                    withAnimation(stepAnimation) { isAskingForGlasses = false }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.title3.weight(.semibold))
                        .frame(width: Theme.primaryButtonHeight, height: Theme.primaryButtonHeight)
                }
                .buttonStyle(PressableCardStyle())
                .background(Theme.card, in: Circle())
                .accessibilityLabel("Back")

                Button {
                    onStart(trimmedName)
                } label: {
                    Label("Start job", systemImage: "play.fill")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
                }
                .floatingGlassButton()
            }
        }
    }

    private var stepAnimation: Animation {
        reduceMotion ? .easeOut(duration: 0.2) : Motion.enter
    }

    private func goToGlassesStep() {
        guard !trimmedName.isEmpty else { return }
        isNameFieldFocused = false
        withAnimation(stepAnimation) { isAskingForGlasses = true }
    }
}

/// "1 of 2" over a big title, so the two steps feel like one flow.
private struct StepHeader: View {
    let number: Int
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                ForEach(1...2, id: \.self) { index in
                    Capsule()
                        .fill(index <= number ? Theme.accent : Theme.ink.opacity(0.12))
                        .frame(width: index == number ? 22 : 8, height: 6)
                }
            }
            .padding(.bottom, 6)
            .accessibilityLabel("Step \(number) of 2")
            Text(title)
                .font(.system(size: 30, weight: .semibold))
                .tracking(-0.6)
            Text(subtitle)
                .font(.title3)
                .foregroundStyle(Theme.inkSecondary)
                .lineLimit(1)
        }
    }
}

private struct Tip: View {
    let symbol: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.accent)
                .frame(width: 22)
            Text(text)
                .font(.subheadline)
                .foregroundStyle(Theme.inkSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// "Next →": text first, arrow after.
private struct TitleThenIcon: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 10) {
            configuration.title
            configuration.icon
        }
    }
}
