import SwiftUI

/// The home screen, in sections:
/// 1. Your car: the car and its state (oil change, odometer, what's due next).
/// 2. Maintenance and specs.
/// 3. Chat with Carvis: the glasses and your recent questions.
/// 4. Service history.
/// 5. Team tools (mechanic / team accounts only).
/// A floating glass button starts a new job.
struct DashboardView: View {
    /// Shared ID that links the job card (or New job button) to the progress screen's zoom.
    static let jobZoomID = "current-job"

    let session: RepairSession
    let zoom: Namespace.ID

    @Environment(AccountStore.self) private var accounts
    @Environment(ChatHistory.self) private var chats

    @State private var isShowingNewJob = false
    @State private var isEditingCar = false
    @State private var isUpdatingOdometer = false
    @State private var isShowingAccount = false
    @State private var pendingJobName: String?

    private var garage: CarProfileStore { session.garage }
    private var profile: CarProfile { garage.profile }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 30) {
                TopBar(name: accounts.account?.name ?? "",
                       initials: accounts.account?.initials ?? "?",
                       isTeam: accounts.isTeam,
                       onEdit: { isEditingCar = true },
                       onAccount: { isShowingAccount = true })
                    .appearAnimation(index: 0)

                // 1. The car and its state, under its name
                VStack(alignment: .leading, spacing: 12) {
                    HStack(alignment: .firstTextBaseline, spacing: 6) {
                        Text("Subaru WRX")
                            .font(.system(size: 40, weight: .semibold))
                            .tracking(-1)
                        Text("2022")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Theme.inkSecondary)
                            .baselineOffset(20)
                    }
                    .padding(.horizontal, 6)
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(.isHeader)

                    DashboardSection(tint: Theme.accent.opacity(0.18)) {
                    CarHero(profile: profile)
                    Button { isEditingCar = true } label: {
                        OilChangeTile(item: profile.oilChange, odometer: profile.odometer, onSetUp: { isEditingCar = true })
                    }
                    .buttonStyle(PressableCardStyle())
                    .accessibilityHint("Edit your oil change schedule")
                    HStack(spacing: 12) {
                        Button { isUpdatingOdometer = true } label: {
                            OdometerTile(miles: profile.odometer, updated: profile.odometerUpdated)
                        }
                        .buttonStyle(PressableCardStyle())
                        .accessibilityHint("Update your odometer")

                        Button { isEditingCar = true } label: {
                            NextDueTile(items: profile.otherMaintenance, odometer: profile.odometer)
                        }
                        .buttonStyle(PressableCardStyle())
                    }
                    }
                }
                .appearAnimation(index: 1)

                if session.hasActiveJob, let current = session.current {
                    DashboardSection(title: "In progress") {
                        Button {
                            session.showProgress()
                        } label: {
                            CurrentJobCard(name: session.jobName, response: current)
                        }
                        .buttonStyle(PressableCardStyle())
                        .zoomSource(id: Self.jobZoomID, in: zoom)
                        .accessibilityHint("Shows the progress screen")
                    }
                    .transition(.blurReplace)
                }

                // 2. Maintenance and specs
                DashboardSection(title: "Maintenance and specs") {
                    MaintenanceCard(items: profile.otherMaintenance, odometer: profile.odometer, onEdit: { isEditingCar = true })
                        .scrollReveal()
                    SpecsCard(details: profile.details, onEdit: { isEditingCar = true })
                        .scrollReveal()
                }
                .appearAnimation(index: 2)

                // 3. Chat
                DashboardSection(title: "Chat with Carvis") {
                    ChatCard(recent: Array(chats.entries.prefix(2)), onOpen: session.showAsk)
                        .scrollReveal()
                }
                .appearAnimation(index: 3)

                // 4. Service history
                DashboardSection(title: "Service history") {
                    HistoryCard(records: session.history.records)
                        .scrollReveal()
                }
                .appearAnimation(index: 4)

                // 5. Team tools
                if accounts.isTeam {
                    DashboardSection(title: "Team tools") {
                        TeamToolsCard(onWakeTest: { session.path.append(.wakeTest) })
                        .scrollReveal()
                    }
                    .transition(.blurReplace)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 16)
            .animation(Motion.enter, value: session.hasActiveJob)
            .animation(Motion.enter, value: accounts.isTeam)
            .animation(Motion.change, value: profile)
        }
        .scrollIndicators(.hidden)
        // The button floats over the content, so the glass has something to refract as you scroll.
        .safeAreaInset(edge: .bottom) {
            newJobButton
        }
        // A soft fade under the status bar so cards don't collide with the clock.
        .overlay(alignment: .top) {
            LinearGradient(stops: [.init(color: Theme.sky, location: 0),
                                   .init(color: Theme.sky, location: 0.55),
                                   .init(color: Theme.sky.opacity(0), location: 1)],
                           startPoint: .top, endPoint: .bottom)
                .frame(height: 76)
                .ignoresSafeArea(edges: .top)
                .allowsHitTesting(false)
        }
        .background { CarvisBackground() }
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $isShowingNewJob, onDismiss: startPendingJob) {
            NewJobSheet { name in
                pendingJobName = name
                isShowingNewJob = false
            }
        }
        .sheet(isPresented: $isEditingCar) {
            CarProfileEditor(store: garage, history: session.history)
        }
        .sheet(isPresented: $isUpdatingOdometer) {
            OdometerSheet(current: profile.odometer) { garage.updateOdometer($0) }
        }
        .sheet(isPresented: $isShowingAccount) {
            AccountSheet(accounts: accounts)
        }
    }

    private var newJobButton: some View {
        Button {
            isShowingNewJob = true
        } label: {
            Label("New job", systemImage: "plus")
                .font(Theme.buttonFont)
                .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
        }
        .floatingGlassButton()
        // With no job card on screen, the progress screen zooms out of this button instead.
        .zoomSource(id: Self.jobZoomID, in: zoom, isEnabled: !session.hasActiveJob)
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
        .appearAnimation(index: 6)
    }

    /// Start the job only after the sheet has fully closed, so the zoom has a clear stage.
    private func startPendingJob() {
        guard let name = pendingJobName else { return }
        pendingJobName = nil
        Task { await session.start(jobName: name) }
    }
}

// MARK: - Top

/// The car's name where the app name used to be, with your account and edit buttons.
private struct TopBar: View {
    let name: String
    let initials: String
    let isTeam: Bool
    let onEdit: () -> Void
    let onAccount: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Text(greeting)
                .font(.title3.weight(.medium))
                .foregroundStyle(Theme.inkSecondary)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
            Spacer()
            Button(action: onEdit) {
                CircleIcon(systemImage: "slider.horizontal.3")
            }
            .buttonStyle(PressableCardStyle())
            .accessibilityLabel("Edit your car")
            Button(action: onAccount) {
                Text(initials)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.white)
                    .frame(width: 48, height: 48)
                    .background(Theme.ink, in: Circle())
                    .overlay(alignment: .bottomTrailing) {
                        if isTeam {
                            Image(systemName: "wrench.and.screwdriver.fill")
                                .font(.system(size: 8, weight: .bold))
                                .foregroundStyle(Theme.ink)
                                .frame(width: 18, height: 18)
                                .background(Theme.lime, in: Circle())
                                .overlay(Circle().stroke(.white, lineWidth: 1.5))
                                .offset(x: 2, y: 2)
                        }
                    }
            }
            .buttonStyle(PressableCardStyle())
            .accessibilityLabel(isTeam ? "Account, mechanic or team mode" : "Account")
        }
    }

    private var greeting: String {
        let first = name.split(separator: " ").first.map(String.init)
        let base = switch Calendar.current.component(.hour, from: .now) {
        case 5..<12: "Good morning"
        case 12..<17: "Good afternoon"
        default: "Good evening"
        }
        return first.map { "\(base), \($0)" } ?? base
    }
}

/// A round white button, like the ones in the corners of the reference designs.
private struct CircleIcon: View {
    let systemImage: String

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Theme.ink)
            .frame(width: 48, height: 48)
            .carvisGlass(.card, in: Circle())
    }
}

/// The car with its drop shadow and your details as chips.
private struct CarHero: View {
    let profile: CarProfile
    @State private var arrived = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var chips: [String] {
        [profile.plate, profile.vin.isEmpty ? "" : "VIN \(profile.vin.suffix(6))"].filter { !$0.isEmpty }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !chips.isEmpty {
                HStack(spacing: 8) {
                    ForEach(chips, id: \.self) { Chip(text: $0) }
                }
            }
            CarImage()
                .padding(.top, 4)
                .padding(.bottom, 18)  // room for the floor shadow
                // As you scroll down, the car drifts and shrinks slightly behind the cards.
                .scrollTransition(.interactive) { [moves = !reduceMotion] car, phase in
                    let away = moves ? max(0, -phase.value) : 0
                    return car
                        .offset(y: away * 36)
                        .scaleEffect(1 - away * 0.06)
                }
                // The car rolls in once, the first time the dashboard appears.
                .offset(x: arrived || reduceMotion ? 0 : 80)
                .opacity(arrived ? 1 : 0)
                .onAppear {
                    guard !arrived else { return }
                    withAnimation(.spring(duration: 0.9, bounce: 0.12).delay(0.1)) { arrived = true }
                }
        }
        .padding(.horizontal, 4)
    }
}

private struct Chip: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.footnote.weight(.medium))
            .foregroundStyle(Theme.inkSecondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(Theme.card.opacity(0.85), in: Capsule())
            .overlay(Capsule().stroke(Theme.ink.opacity(0.06), lineWidth: 1))
    }
}

// MARK: - Car stats

/// The dark instrument-style tile: miles left until the next oil change.
private struct OilChangeTile: View {
    let item: MaintenanceItem?
    let odometer: Int
    let onSetUp: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Label("Oil change", systemImage: "drop.fill")
                    .font(.headline)
                Spacer()
                if let days = item?.daysLeft() {
                    Text(days > 0 ? "\(days) days left" : "Due now")
                        .font(.subheadline.weight(.medium))
                        .monospacedDigit()
                        .foregroundStyle(days > 0 ? .white.opacity(0.7) : Theme.warning)
                }
            }
            .foregroundStyle(.white)

            if let item, let milesLeft = item.milesLeft(odometer: odometer) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    RollingNumber(value: max(milesLeft, 0), delay: 0.35)
                        .font(Theme.number(68))
                        .tracking(-2)
                    Text(milesLeft > 0 ? "mi left" : "mi · overdue")
                        .font(.title3)
                        .foregroundStyle(milesLeft > 0 ? .white.opacity(0.55) : Theme.safetyRed)
                }
                .foregroundStyle(.white)
                .accessibilityElement(children: .combine)

                GlowBar(fraction: 1 - (item.used(odometer: odometer) ?? 0),
                        color: milesLeft > 0 ? Theme.lime : Theme.safetyRed)

                HStack {
                    if let last = item.lastMiles {
                        Text("Last at \(last.formatted()) mi")
                    }
                    Spacer()
                    if let last = item.lastMiles, let interval = item.intervalMiles {
                        Text("Due at \((last + interval).formatted()) mi")
                    }
                }
                .font(.footnote.weight(.medium))
                .monospacedDigit()
                .foregroundStyle(.white.opacity(0.45))
            } else {
                Text("Add your oil change interval to start the countdown.")
                    .font(.title3)
                    .foregroundStyle(.white.opacity(0.8))
                Button("Set it up", action: onSetUp)
                    .font(.headline)
                    .foregroundStyle(Theme.ink)
                    .padding(.horizontal, 22)
                    .frame(minHeight: 48)
                    .background(Theme.lime, in: Capsule())
            }
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .carvisGlass(.dark, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

/// A thin bar with a soft glow on its fill, like a charging indicator.
private struct GlowBar: View {
    let fraction: Double
    let color: Color
    @State private var filled = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.12))
                Capsule()
                    .fill(color)
                    .frame(width: max(8, geometry.size.width * (filled ? fraction : 0)))
                    // The glow breathes slowly, like a charging light.
                    .phaseAnimator(reduceMotion ? [false] : [false, true]) { bar, bright in
                        bar.shadow(color: color.opacity(bright ? 0.85 : 0.45), radius: bright ? 12 : 6)
                    } animation: { _ in .easeInOut(duration: 1.8) }
            }
        }
        .frame(height: 8)
        .modifier(FillOnAppear(delay: 0.35, filled: $filled))
        .animation(Motion.change, value: fraction)
        .accessibilityHidden(true)
    }
}

private struct OdometerTile: View {
    let miles: Int
    let updated: Date

    var body: some View {
        SmallTile(title: "Odometer", systemImage: "gauge.with.dots.needle.33percent") {
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                RollingNumber(value: miles, delay: 0.45)
                    .font(Theme.number(30))
                    .tracking(-0.8)
                    .minimumScaleFactor(0.7)
                    .lineLimit(1)
                Text("mi")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            }
        } footer: {
            Text("Updated \(updated.formatted(.relative(presentation: .named)))")
        }
    }
}

/// The soonest thing coming up, other than the oil change.
private struct NextDueTile: View {
    let items: [MaintenanceItem]
    let odometer: Int

    private var next: MaintenanceItem? {
        items
            .filter { $0.status(odometer: odometer) != .notSetUp }
            .max { ($0.used(odometer: odometer) ?? 0) < ($1.used(odometer: odometer) ?? 0) }
    }

    var body: some View {
        SmallTile(title: "Next up", systemImage: next?.symbol ?? "calendar") {
            Text(next?.name ?? "Nothing set")
                .font(.system(size: 22, weight: .regular))
                .tracking(-0.4)
                .lineLimit(2)
                .minimumScaleFactor(0.8)
                .multilineTextAlignment(.leading)
        } footer: {
            if let next {
                DueText(item: next, odometer: odometer)
            } else {
                Text("Add maintenance items")
            }
        }
    }
}

private struct SmallTile<Content: View, Footer: View>: View {
    let title: String
    let systemImage: String
    @ViewBuilder var content: Content
    @ViewBuilder var footer: Footer

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(Theme.inkSecondary)
            Spacer(minLength: 0)
            content
            footer
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.inkTertiary)
                .lineLimit(1)
        }
        .padding(18)
        .frame(maxWidth: .infinity, minHeight: 150, alignment: .topLeading)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

/// "In 2,300 mi" / "In 41 days" / "Overdue", colored by urgency.
private struct DueText: View {
    let item: MaintenanceItem
    let odometer: Int

    var body: some View {
        Text(text)
            .foregroundStyle(color)
            .monospacedDigit()
    }

    private var text: String {
        let miles = item.milesLeft(odometer: odometer)
        let days = item.daysLeft()
        if item.status(odometer: odometer) == .overdue { return "Overdue" }
        if let miles, let days, let intervalMiles = item.intervalMiles, let months = item.intervalMonths {
            // Show whichever runs out first, as a share of its own interval.
            let milesShare = Double(miles) / Double(max(intervalMiles, 1))
            let daysShare = Double(days) / Double(max(months * 30, 1))
            return milesShare <= daysShare ? "In \(miles.formatted()) mi" : "In \(days) days"
        }
        if let miles { return "In \(miles.formatted()) mi" }
        if let days { return "In \(days) days" }
        return "Not set up"
    }

    private var color: Color {
        switch item.status(odometer: odometer) {
        case .overdue: Theme.safetyRed
        case .soon: Theme.warning
        default: Theme.inkTertiary
        }
    }
}

// MARK: - Cards

/// Small icon + title used at the top of each card.
private struct CardHeader: View {
    let title: String
    let systemImage: String
    var action: (() -> Void)?

    var body: some View {
        HStack {
            Label {
                Text(title)
            } icon: {
                Image(systemName: systemImage)
                    .foregroundStyle(Theme.accent)
            }
            .font(.headline)
            .accessibilityAddTraits(.isHeader)
            Spacer()
            if let action {
                Button(action: action) {
                    Image(systemName: "arrow.up.right")
                        .font(.subheadline.weight(.semibold))
                        .frame(width: 44, height: 44)
                        .background(Theme.pearl, in: Circle())
                }
                .buttonStyle(PressableCardStyle())
                .accessibilityLabel("Edit \(title.lowercased())")
            }
        }
    }
}

/// The glasses, your latest questions, and the way into the chat.
private struct ChatCard: View {
    @Environment(GlassesController.self) private var glasses
    let recent: [ChatEntry]
    let onOpen: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 14) {
                Image(systemName: "eyeglasses")
                    .font(.title2)
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(Theme.ink, in: Circle())
                    .overlay(alignment: .topTrailing) {
                        if glasses.isConnected {
                            Circle()
                                .fill(Theme.lime)
                                .frame(width: 13, height: 13)
                                .overlay(Circle().stroke(.white, lineWidth: 2))
                                .transition(.scale(scale: 0.5).combined(with: .opacity))
                        }
                    }
                    .symbolEffect(.bounce, value: glasses.isConnected)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Meta glasses")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                    Text(statusText)
                        .font(.title3.weight(.semibold))
                        .contentTransition(.opacity)
                }
                Spacer(minLength: 0)
            }
            .accessibilityElement(children: .combine)

            if recent.isEmpty {
                Text("Say \u{201C}Hey Carvis\u{201D} or type a question. Answers come only from your service manual.")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(recent.reversed()) { entry in
                        ChatBubble(text: entry.question, mine: true)
                        ChatBubble(text: entry.reply, mine: false, dimmed: !entry.fromManual)
                    }
                }
            }

            if glasses.isConnected {
                Button(action: onOpen) {
                    Label("Open chat", systemImage: "bubble.left.and.text.bubble.right.fill")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()
            } else {
                Button(action: glasses.connect) {
                    Text(glasses.status == .connecting ? "Finish in the Meta AI app" : "Connect glasses")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()
                .disabled(glasses.status == .connecting)
            }
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .animation(Motion.change, value: glasses.isConnected)
    }

    private var statusText: String {
        switch glasses.status {
        case .notConnected: "Not connected"
        case .connecting: "Connecting"
        case .lookingForGlasses: "Connected · put them on"
        case .ready, .startingCamera: "Connected"
        case .live: "Live"
        case .paused: "Paused"
        case .needsCameraAccess: "Waiting for camera access"
        }
    }
}

private struct ChatBubble: View {
    let text: String
    let mine: Bool
    var dimmed = false

    var body: some View {
        Text(text)
            .font(.subheadline)
            .lineLimit(3)
            .foregroundStyle(mine ? .white : Theme.ink.opacity(dimmed ? 0.6 : 1))
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .background(mine ? Theme.ink : Theme.pearl,
                        in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
            .frame(maxWidth: .infinity, alignment: mine ? .trailing : .leading)
            .accessibilityLabel((mine ? "You asked: " : "Carvis: ") + text)
    }
}

/// Mechanic / team mode: where questions go, and whether the server, glasses, and Vapi are ready.
private struct TeamToolsCard: View {
    /// Opens Raghav's glasses wake-word test screen (Meta Speech on the glasses).
    let onWakeTest: () -> Void
    @Environment(AccountStore.self) private var accounts
    @Environment(GlassesController.self) private var glasses
    @State private var health: String?
    @State private var isChecking = false

    var body: some View {
        @Bindable var accounts = accounts
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Server")
                    .font(.headline)
                TextField(CarvisVisionClient.fromInfoPlist()?.baseURL.absoluteString ?? "https://…",
                          text: $accounts.serverOverride)
                    .font(.body.monospaced())
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .padding(.horizontal, 14)
                    .frame(minHeight: 52)
                    .background(Theme.pearl, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
                Text("Leave empty to use the address in Carvis-Info.plist.")
                    .font(.footnote)
                    .foregroundStyle(Theme.inkTertiary)
            }

            HStack {
                Button {
                    Task { await checkServer() }
                } label: {
                    HStack(spacing: 8) {
                        if isChecking { ProgressView() }
                        Text("Check server")
                    }
                    .font(.headline)
                    .padding(.horizontal, 18)
                    .frame(minHeight: 48)
                }
                .carvisButton()
                .disabled(isChecking)
                Spacer()
            }
            if let health {
                Text(health)
                    .font(.footnote.monospaced())
                    .foregroundStyle(health.hasPrefix("OK") ? Theme.accent : Theme.safetyRed)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Divider()

            DevRow(label: "Glasses", value: glasses.isConnected ? glasses.detail : "Not registered")
            DevRow(label: "Vapi", value: VapiConfig.load() == nil ? "Not configured, built-in voice" : "Configured")
            DevRow(label: "Vehicle", value: "\(Vehicle.demo.year) / \(Vehicle.demo.make) / \(Vehicle.demo.model)")

            Button(action: onWakeTest) {
                Label("Glasses wake test", systemImage: "waveform")
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 52)
            }
            .carvisButton()
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }

    private func checkServer() async {
        guard let base = accounts.visionClient?.baseURL else {
            health = "No server address set."
            return
        }
        isChecking = true
        defer { isChecking = false }
        var request = URLRequest(url: base.appending(path: "health"))
        request.timeoutInterval = 8
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let body = String(data: data, encoding: .utf8) ?? ""
            health = (status == 200 ? "OK" : "HTTP \(status)") + " · \(base.absoluteString)\n\(body.prefix(200))"
        } catch {
            health = "Unreachable · \(base.absoluteString)\n\(error.localizedDescription)"
        }
    }
}

private struct DevRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(.subheadline.weight(.semibold))
            Spacer(minLength: 12)
            Text(value)
                .font(.footnote.monospaced())
                .foregroundStyle(Theme.inkSecondary)
                .multilineTextAlignment(.trailing)
        }
    }
}

/// The job you're working on right now.
private struct CurrentJobCard: View {
    let name: String
    let response: StepResponse

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                LiveDot()
                Text("In progress")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.inkSecondary)
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.inkSecondary)
            }
            Text(name)
                .font(.title2.weight(.semibold))
                .multilineTextAlignment(.leading)
            ProgressCapsule(step: response.stepNumber, total: response.totalSteps)
        }
        .padding(20)
        .carvisGlass(.hero, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

/// Everything you service on a schedule, besides the oil change, with how close each one is.
private struct MaintenanceCard: View {
    let items: [MaintenanceItem]
    let odometer: Int
    let onEdit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            CardHeader(title: "Maintenance", systemImage: "wrench.and.screwdriver.fill", action: onEdit)

            if items.isEmpty {
                Text("Add the things you service on a schedule, like tire rotations.")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            } else {
                ForEach(items) { item in
                    MaintenanceRow(item: item, odometer: odometer)
                    if item.id != items.last?.id { Divider() }
                }
            }
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

private struct MaintenanceRow: View {
    let item: MaintenanceItem
    let odometer: Int
    @State private var filled = false

    private var barColor: Color {
        switch item.status(odometer: odometer) {
        case .overdue: Theme.safetyRed
        case .soon: Theme.warning
        default: Theme.accent
        }
    }

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: item.symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .frame(width: 40, height: 40)
                .background(Theme.pearl, in: Circle())
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(item.name)
                        .font(.body.weight(.semibold))
                    Spacer(minLength: 8)
                    DueText(item: item, odometer: odometer)
                        .font(.subheadline.weight(.medium))
                }
                GeometryReader { geometry in
                    ZStack(alignment: .leading) {
                        Capsule().fill(Theme.ink.opacity(0.07))
                        Capsule()
                            .fill(barColor)
                            .frame(width: geometry.size.width * (filled ? (item.used(odometer: odometer) ?? 0) : 0))
                    }
                }
                .frame(height: 5)
                .modifier(FillOnAppear(delay: 0.15, filled: $filled))
                .accessibilityHidden(true)
                Text(schedule)
                    .font(.footnote)
                    .foregroundStyle(Theme.inkTertiary)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var schedule: String {
        var parts: [String] = []
        if let miles = item.intervalMiles { parts.append("\(miles.formatted()) mi") }
        if let months = item.intervalMonths { parts.append("\(months) mo") }
        return parts.isEmpty ? "No interval set" : "Every " + parts.joined(separator: " or ")
    }
}

/// The facts about your car you've typed in.
private struct SpecsCard: View {
    let details: [CarDetail]
    let onEdit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            CardHeader(title: "Your specs", systemImage: "list.bullet.rectangle", action: onEdit)

            if details.isEmpty {
                Text("Add details like tire pressure or your oil type.")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            } else {
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                    ForEach(details) { detail in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(detail.label)
                                .font(.footnote.weight(.medium))
                                .foregroundStyle(Theme.inkTertiary)
                            Text(detail.value)
                                .font(.body.weight(.semibold))
                                .lineLimit(2)
                        }
                        .frame(maxWidth: .infinity, minHeight: 64, alignment: .leading)
                        .padding(14)
                        .background(Theme.pearl.opacity(0.7), in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

/// Every finished job, newest first.
private struct HistoryCard: View {
    let records: [JobRecord]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            if records.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("No finished jobs yet")
                        .font(.body.weight(.semibold))
                    Text("Tap New job and Carvis will guide you through your glasses.")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } else {
                ForEach(records) { record in
                    HistoryRow(record: record)
                        .transition(.blurReplace)
                    if record.id != records.last?.id {
                        Divider()
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

private struct HistoryRow: View {
    let record: JobRecord

    var body: some View {
        let log = record.summary.serviceLog
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "drop.fill")
                .font(.subheadline)
                .foregroundStyle(Theme.accent)
                .frame(width: 40, height: 40)
                .background(Theme.accent.opacity(0.1), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline) {
                    Text(record.name)
                        .font(.body.weight(.semibold))
                    Spacer(minLength: 12)
                    Text(log.date)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                }
                Text("\(log.mileage.formatted()) mi · \(log.oil)")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
            }
        }
        .accessibilityElement(children: .combine)
    }
}
