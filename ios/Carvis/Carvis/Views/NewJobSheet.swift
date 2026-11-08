import SwiftUI

/// Pops up from the dashboard. First you name the job,
/// then Carvis asks you to put on your glasses and start.
struct NewJobSheet: View {
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
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .sensoryFeedback(.selection, trigger: isAskingForGlasses)
    }

    private var nameStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Name this job")
                .font(.title2.weight(.semibold))

            TextField("Job name", text: $name)
                .font(.title3)
                .submitLabel(.next)
                .focused($isNameFieldFocused)
                .onSubmit(goToGlassesStep)
                .padding(.horizontal, 20)
                .frame(minHeight: 56)
                .background(Theme.ink.opacity(0.06), in: Capsule())

            Label("\(Vehicle.demo.displayName) · Oil change", systemImage: "car.side.fill")
                .font(.subheadline)
                .foregroundStyle(Theme.inkSecondary)

            Spacer(minLength: 0)

            Button(action: goToGlassesStep) {
                Text("Next")
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
            }
            .carvisButton(prominent: true)
            .disabled(trimmedName.isEmpty)
        }
        .onAppear { isNameFieldFocused = true }
    }

    private var glassesStep: some View {
        VStack(spacing: 16) {
            Image(systemName: "eyeglasses")
                .font(.system(size: 52, weight: .medium))
                .foregroundStyle(Theme.amber)
                .frame(width: 104, height: 104)
                .background(Theme.amber.opacity(0.12), in: Circle())
                .symbolEffect(.bounce, value: isAskingForGlasses)
                .accessibilityHidden(true)

            Text("Put on your glasses")
                .font(.title2.weight(.semibold))

            Text("Carvis will talk you through \(trimmedName) on your Meta glasses. Your phone shows your progress.")
                .font(.body)
                .foregroundStyle(Theme.inkSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)

            if !glasses.isConnected {
                Button(action: glasses.connect) {
                    Label(glasses.status == .connecting ? "Finish in the Meta AI app" : "Connect glasses",
                          systemImage: "eyeglasses")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()
                .disabled(glasses.status == .connecting)
                .transition(.blurReplace)
            } else {
                Label("Glasses connected", systemImage: "checkmark.circle.fill")
                    .font(.headline)
                    .foregroundStyle(Theme.amber)
                    .transition(.blurReplace)
            }

            Spacer(minLength: 0)

            HStack(spacing: 16) {
                Button {
                    withAnimation(stepAnimation) { isAskingForGlasses = false }
                } label: {
                    Text("Back")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()

                Button {
                    onStart(trimmedName)
                } label: {
                    Text("Start")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton(prominent: true)
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
