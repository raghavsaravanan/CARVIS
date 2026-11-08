import SwiftUI

/// First launch, in two steps on one "showroom":
/// 1. Welcome: the WRX on a dark stage, and what Carvis does.
/// 2. About you: your name and how you'll use Carvis. Saved on this phone only.
struct OnboardingView: View {
    let accounts: AccountStore

    private enum Step { case welcome, details }

    @State private var step: Step = .welcome
    @State private var name = ""
    @State private var mode: Account.Mode = .personal
    @FocusState private var isNameFocused: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var stepAnimation: Animation { reduceMotion ? .easeOut(duration: 0.2) : .spring(duration: 0.6, bounce: 0.08) }

    var body: some View {
        GeometryReader { geometry in
            let stageHeight = geometry.size.height * (step == .welcome ? 0.54 : 0.34)
            VStack(spacing: -36) {
                ShowroomStage(compact: step == .details,
                              title: step == .welcome ? "Your hands-free\nmechanic" : "Tell us about you")
                    .frame(height: stageHeight + geometry.safeAreaInsets.top)
                sheet
                    .frame(maxHeight: .infinity, alignment: .top)
            }
            .ignoresSafeArea(edges: .top)
        }
        .background(Theme.card.ignoresSafeArea())
        .statusBarHidden(true)
        .sensoryFeedback(.selection, trigger: mode)
        .sensoryFeedback(.impact(weight: .light), trigger: step)
    }

    // MARK: - The white sheet

    private var sheet: some View {
        ZStack {
            if step == .welcome {
                welcome.transition(.blurReplace)
            } else {
                details.transition(.blurReplace)
            }
        }
        .padding(.horizontal, 24)
        .padding(.top, 30)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(
            UnevenRoundedRectangle(topLeadingRadius: 36, topTrailingRadius: 36, style: .continuous)
                .fill(Theme.card)
                .shadow(color: .black.opacity(0.25), radius: 24, y: -6)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private var welcome: some View {
        VStack(alignment: .leading, spacing: 18) {
            FeatureRow(symbol: "eyeglasses", title: "Hands-free on Meta glasses",
                       detail: "Look at a part and ask. Carvis answers in your ear.", index: 0)
            FeatureRow(symbol: "book.closed.fill", title: "Straight from the manual",
                       detail: "Torque specs and steps come only from your service manual.", index: 1)
            FeatureRow(symbol: "gauge.with.dots.needle.67percent", title: "Your car at a glance",
                       detail: "Oil changes, maintenance, and history in one place.", index: 2)
            Spacer(minLength: 12)
            Button {
                withAnimation(stepAnimation) { step = .details }
            } label: {
                Label("Get started", systemImage: "arrow.right")
                    .labelStyle(TrailingIconLabelStyle())
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
            }
            .floatingGlassButton()
            .padding(.bottom, 8)
        }
    }

    private var details: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("Your name")
                        .font(.headline)
                    TextField("First and last name", text: $name)
                        .font(.title3)
                        .textContentType(.name)
                        .submitLabel(.go)
                        .focused($isNameFocused)
                        .onSubmit(finish)
                        .padding(.horizontal, 20)
                        .frame(minHeight: 60)
                        .background(Theme.pearl, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("How will you use Carvis?")
                        .font(.headline)
                    ForEach(Account.Mode.allCases) { option in
                        ModeOption(mode: option, isSelected: mode == option) {
                            withAnimation(.spring(duration: 0.3, bounce: 0)) { mode = option }
                        }
                    }
                    Text("You can change this any time.")
                        .font(.footnote)
                        .foregroundStyle(Theme.inkTertiary)
                }
            }
            .padding(.bottom, 24)
        }
        .scrollIndicators(.hidden)
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 12) {
                Button {
                    isNameFocused = false
                    withAnimation(stepAnimation) { step = .welcome }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.title3.weight(.semibold))
                        .frame(width: Theme.primaryButtonHeight, height: Theme.primaryButtonHeight)
                }
                .buttonStyle(PressableCardStyle())
                .background(Theme.pearl, in: Circle())
                .accessibilityLabel("Back")

                Button(action: finish) {
                    Text("Create account")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
                }
                .floatingGlassButton()
                .disabled(trimmedName.isEmpty)
            }
            .padding(.bottom, 8)
            .background(Theme.card)
        }
    }

    private func finish() {
        guard !trimmedName.isEmpty else { return }
        accounts.account = Account(name: trimmedName, mode: mode)
    }
}

/// "Get started →": text first, arrow after.
private struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: 10) {
            configuration.title
            configuration.icon
        }
    }
}

/// The dark showroom: a blue spotlight, the WRX on a glossy floor with its reflection,
/// and a single light sweep across the paint when it arrives.
private struct ShowroomStage: View {
    let compact: Bool
    let title: String

    @State private var arrived = false
    @State private var sweep = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack(alignment: .bottom) {
            // Stage and spotlight
            Theme.tile
            RadialGradient(colors: [Theme.accent.opacity(0.55), Theme.accent.opacity(0.12), .clear],
                           center: UnitPoint(x: 0.5, y: compact ? 0.62 : 0.66),
                           startRadius: 10, endRadius: compact ? 220 : 320)
            // Glossy floor
            LinearGradient(colors: [.clear, .white.opacity(0.06)], startPoint: .top, endPoint: .bottom)
                .frame(height: compact ? 70 : 120)

            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    Image(systemName: "car.side.fill")
                        .font(.footnote.weight(.bold))
                        .foregroundStyle(Theme.ink)
                        .frame(width: 26, height: 26)
                        .background(Theme.lime, in: Circle())
                    Text("Carvis")
                        .font(.system(.headline, design: .rounded, weight: .semibold))
                        .foregroundStyle(.white)
                }
                .padding(.bottom, compact ? 10 : 14)

                Text(title)
                    .font(.system(size: compact ? 30 : 38, weight: .semibold))
                    .tracking(-0.8)
                    .foregroundStyle(.white)
                    .fixedSize(horizontal: false, vertical: true)
                    .contentTransition(.opacity)
                    .accessibilityAddTraits(.isHeader)

                Spacer(minLength: 0)

                car
                    .frame(maxWidth: compact ? 250 : .infinity)
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, compact ? 44 : 56)
            }
            .padding(.horizontal, 24)
            .padding(.top, 64)
        }
        .clipped()
    }

    private var car: some View {
        VStack(spacing: 0) {
            Image("WRX")
                .resizable()
                .scaledToFit()
                // One soft light sweep across the paint, clipped to the car's shape.
                .overlay {
                    GeometryReader { geometry in
                        LinearGradient(colors: [.clear, .white.opacity(0.55), .clear],
                                       startPoint: .leading, endPoint: .trailing)
                            .frame(width: geometry.size.width * 0.35)
                            .rotationEffect(.degrees(18))
                            .offset(x: sweep ? geometry.size.width * 1.2 : -geometry.size.width * 0.5)
                            .blendMode(.plusLighter)
                    }
                    .mask(Image("WRX").resizable().scaledToFit())
                    .allowsHitTesting(false)
                }
                .background(alignment: .bottom) {
                    Ellipse()
                        .fill(.black.opacity(0.7))
                        .frame(height: 18)
                        .blur(radius: 10)
                        .padding(.horizontal, 24)
                        .offset(y: 6)
                }
                .accessibilityLabel("Blue 2022 Subaru WRX")

            // Faint reflection on the floor
            Image("WRX")
                .resizable()
                .scaledToFit()
                .scaleEffect(x: 1, y: -1)
                .opacity(0.16)
                .mask(LinearGradient(colors: [.white, .clear], startPoint: .top, endPoint: .center))
                .frame(height: 40, alignment: .top)
                .clipped()
                .accessibilityHidden(true)
        }
        .offset(x: arrived || reduceMotion ? 0 : 140)
        .opacity(arrived ? 1 : 0)
        .onAppear {
            guard !arrived else { return }
            if reduceMotion {
                arrived = true
                return
            }
            withAnimation(.spring(duration: 1.0, bounce: 0.1).delay(0.15)) { arrived = true }
            withAnimation(.easeInOut(duration: 1.1).delay(1.0)) { sweep = true }
        }
    }
}

/// A short reason to use Carvis, with an icon. Rows slide in one after another.
private struct FeatureRow: View {
    let symbol: String
    let title: String
    let detail: String
    let index: Int

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.headline)
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(Theme.ink, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)
                Text(detail)
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityElement(children: .combine)
        .appearAnimation(index: index + 2)
    }
}

/// A big selectable card for Personal or Mechanic / team.
private struct ModeOption: View {
    let mode: Account.Mode
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 16) {
                Image(systemName: mode.symbol)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(isSelected ? .white : Theme.ink)
                    .frame(width: 48, height: 48)
                    .background(isSelected ? Theme.accent : Theme.pearl, in: Circle())
                VStack(alignment: .leading, spacing: 3) {
                    Text(mode.title)
                        .font(.headline)
                    Text(mode.summary)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 8)
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.title2)
                    .foregroundStyle(isSelected ? Theme.accent : Theme.inkTertiary)
            }
            .padding(18)
            .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight, alignment: .leading)
            .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                    .stroke(isSelected ? Theme.accent : Theme.ink.opacity(0.06), lineWidth: isSelected ? 2 : 1)
            )
            .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        }
        .buttonStyle(PressableCardStyle())
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

/// Your profile: change your name or mode, or sign out.
struct AccountSheet: View {
    let accounts: AccountStore
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                if let account = accounts.account {
                    Section {
                        HStack(spacing: 14) {
                            Text(account.initials)
                                .font(.title3.weight(.semibold))
                                .foregroundStyle(.white)
                                .frame(width: 56, height: 56)
                                .background(Theme.ink, in: Circle())
                            VStack(alignment: .leading, spacing: 2) {
                                TextField("Name", text: Binding(
                                    get: { accounts.account?.name ?? "" },
                                    set: { accounts.account?.name = $0 }
                                ))
                                .font(.title3.weight(.semibold))
                                Text("\(account.mode.title) account · on this phone")
                                    .font(.subheadline)
                                    .foregroundStyle(Theme.inkSecondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }

                    Section {
                        Picker("Mode", selection: Binding(
                            get: { accounts.account?.mode ?? .personal },
                            set: { accounts.account?.mode = $0 }
                        )) {
                            ForEach(Account.Mode.allCases) { Text($0.title).tag($0) }
                        }
                        .pickerStyle(.segmented)
                    } header: {
                        Text("Mode")
                    } footer: {
                        Text(account.mode.summary)
                    }

                    Section {
                        Button("Sign out", role: .destructive) {
                            accounts.signOut()
                            dismiss()
                        }
                    } footer: {
                        Text("Your car and service history stay on this phone.")
                    }
                }
            }
            .navigationTitle("Account")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .fontWeight(.semibold)
                }
            }
        }
        .tint(Theme.accent)
        .presentationDetents([.medium, .large])
    }
}

/// The WRX with a drop shadow, so it sits on the ground instead of floating.
struct CarImage: View {
    var body: some View {
        Image("WRX")
            .resizable()
            .scaledToFit()
            // A soft shadow cast by the car's own shape.
            .shadow(color: Theme.ink.opacity(0.16), radius: 18, x: 0, y: 16)
            .background(alignment: .bottom) {
                ZStack {
                    // Wide, soft ambient shadow on the floor.
                    Ellipse()
                        .fill(Theme.ink.opacity(0.24))
                        .frame(height: 34)
                        .blur(radius: 18)
                        .padding(.horizontal, 10)
                    // Tight, darker contact shadow right under the tires.
                    Ellipse()
                        .fill(Theme.ink.opacity(0.45))
                        .frame(height: 14)
                        .blur(radius: 6)
                        .padding(.horizontal, 44)
                }
                .offset(y: 10)
            }
            .accessibilityLabel("Blue 2022 Subaru WRX")
    }
}
