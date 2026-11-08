import SwiftUI

// MARK: - Dashboard tile

/// "Your shop" on the dashboard (mechanic / team accounts): host one, or see it live.
struct ShopSummaryCard: View {
    @Environment(ShopStore.self) private var shops
    let liveYou: ShopMechanic?
    let onHost: () -> Void
    let onOpen: () -> Void

    private var floor: [ShopMechanic] { (liveYou.map { [$0] } ?? []) + shops.crew }
    private var active: Int { floor.filter { !$0.isDone }.count }

    var body: some View {
        if let shop = shops.shop {
            Button(action: onOpen) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(spacing: 8) {
                        LiveBadge()
                        Text(shop.name)
                            .font(.headline)
                            .foregroundStyle(.white)
                            .lineLimit(1)
                        Spacer()
                        Text(shop.code)
                            .font(.footnote.monospaced().weight(.semibold))
                            .foregroundStyle(.white.opacity(0.7))
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .background(.white.opacity(0.1), in: Capsule())
                    }

                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        RollingNumber(value: active, delay: 0.2)
                            .font(Theme.number(56))
                            .tracking(-1.5)
                            .foregroundStyle(.white)
                        Text(active == 1 ? "job on the floor" : "jobs on the floor")
                            .font(.title3)
                            .foregroundStyle(.white.opacity(0.55))
                    }

                    HStack(spacing: -10) {
                        ForEach(floor) { mechanic in
                            ProgressAvatar(mechanic: mechanic, size: 46, ringOnDark: true)
                        }
                    }

                    HStack {
                        Text("Open shop floor")
                            .font(.headline)
                        Spacer()
                        Image(systemName: "arrow.right")
                            .font(.headline)
                    }
                    .foregroundStyle(Theme.ink)
                    .padding(.horizontal, 20)
                    .frame(minHeight: 56)
                    .background(Theme.lime, in: Capsule())
                }
                .padding(22)
                .frame(maxWidth: .infinity, alignment: .leading)
                .carvisGlass(.dark, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
                .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            }
            .buttonStyle(PressableCardStyle())
            .onAppear { shops.startLive() }
        } else {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 14) {
                    Image(systemName: "person.3.fill")
                        .font(.title3)
                        .foregroundStyle(.white)
                        .frame(width: 52, height: 52)
                        .background(Theme.ink, in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Host a shop")
                            .font(.title3.weight(.semibold))
                        Text("See every mechanic's job and step, live.")
                            .font(.subheadline)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }
                Button(action: onHost) {
                    Label("Host a shop", systemImage: "plus")
                        .font(Theme.buttonFont)
                        .frame(maxWidth: .infinity, minHeight: Theme.buttonHeight)
                }
                .carvisButton()
            }
            .padding(20)
            .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        }
    }
}

/// Pulsing lime "Live" label.
private struct LiveBadge: View {
    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(Theme.lime)
                .frame(width: 8, height: 8)
                .phaseAnimator([false, true]) { dot, on in
                    dot.opacity(on ? 1 : 0.35)
                } animation: { _ in .easeInOut(duration: 0.9) }
            Text("Live")
                .font(.footnote.weight(.bold))
                .foregroundStyle(Theme.lime)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Theme.lime.opacity(0.12), in: Capsule())
    }
}

/// Initials with a ring that fills as their job progresses.
struct ProgressAvatar: View {
    let mechanic: ShopMechanic
    var size: CGFloat = 44
    var ringOnDark = false

    var body: some View {
        ZStack {
            Circle()
                .fill(mechanic.color)
            Text(mechanic.isYou ? "You" : mechanic.initials)
                .font(.system(size: size * (mechanic.isYou ? 0.3 : 0.34), weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
        .padding(4)
        .background {
            Circle().fill(ringOnDark ? Theme.tile : Theme.card)
        }
        .overlay {
            Circle()
                .stroke(ringOnDark ? .white.opacity(0.12) : Theme.ink.opacity(0.08), lineWidth: 3)
                .padding(1.5)
            Circle()
                .trim(from: 0, to: mechanic.progress)
                .stroke(mechanic.isDone ? Theme.lime : mechanic.color, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .padding(1.5)
        }
        .accessibilityLabel("\(mechanic.name), \(Int(mechanic.progress * 100)) percent")
    }
}

// MARK: - Host

/// Name the shop; Carvis makes a join code.
struct HostShopSheet: View {
    let suggestedName: String
    let onCreate: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @FocusState private var isFocused: Bool

    init(suggestedName: String, onCreate: @escaping (String) -> Void) {
        self.suggestedName = suggestedName
        self.onCreate = onCreate
        _name = State(initialValue: suggestedName)
    }

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Image(systemName: "building.2.fill")
                .font(.title2)
                .foregroundStyle(.white)
                .frame(width: 60, height: 60)
                .background(Theme.ink, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            VStack(alignment: .leading, spacing: 4) {
                Text("Host a shop")
                    .font(.title2.weight(.semibold))
                Text("You'll see each mechanic's job, step, and progress as they work. They join with your shop code.")
                    .font(.body)
                    .foregroundStyle(Theme.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            TextField("Shop name", text: $name)
                .font(.title3)
                .submitLabel(.done)
                .focused($isFocused)
                .onSubmit(create)
                .padding(.horizontal, 20)
                .frame(minHeight: 60)
                .background(Theme.pearl, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
            Spacer(minLength: 0)
            Button(action: create) {
                Text("Create shop")
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
            }
            .floatingGlassButton()
            .disabled(trimmed.isEmpty)
        }
        .padding(24)
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }

    private func create() {
        guard !trimmed.isEmpty else { return }
        onCreate(trimmed)
        dismiss()
    }
}

// MARK: - Shop floor

/// The admin view: every mechanic, their vehicle, job, step, and progress, live.
struct ShopFloorView: View {
    @Environment(ShopStore.self) private var shops
    let liveYou: ShopMechanic?

    @State private var selected: ShopMechanic?
    @State private var isConfirmingClose = false
    @Environment(\.dismiss) private var dismiss

    private var floor: [ShopMechanic] { (liveYou.map { [$0] } ?? []) + shops.crew }

    /// Mechanics grouped by vehicle, so people on the same car sit together.
    private var groups: [(vehicle: String, mechanics: [ShopMechanic])] {
        let grouped = Dictionary(grouping: floor, by: \.vehicle)
        return grouped
            .map { (vehicle: $0.key, mechanics: $0.value.sorted { $0.bay < $1.bay }) }
            .sorted { $0.mechanics.count != $1.mechanics.count ? $0.mechanics.count > $1.mechanics.count : $0.vehicle < $1.vehicle }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                header
                stats
                ForEach(groups, id: \.vehicle) { group in
                    DashboardSection(title: group.vehicle,
                                     subtitle: group.mechanics.count > 1 ? "\(group.mechanics.count) mechanics on this model" : nil) {
                        ForEach(group.mechanics) { mechanic in
                            Button { selected = mechanic } label: {
                                MechanicCard(mechanic: mechanic)
                            }
                            .buttonStyle(PressableCardStyle())
                            .transition(.blurReplace)
                        }
                    }
                }
                DashboardSection(title: "Activity") {
                    ActivityFeed(events: Array(shops.events.prefix(8)))
                }
                Text("Demo crew. Live sync between phones is coming with the shop server.")
                    .font(.footnote)
                    .foregroundStyle(Theme.inkTertiary)
                    .padding(.horizontal, 6)
                Button("Close shop", role: .destructive) { isConfirmingClose = true }
                    .font(.headline)
                    .frame(maxWidth: .infinity, minHeight: 52)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 24)
            .animation(.spring(duration: 0.6, bounce: 0), value: groups.map(\.vehicle))
        }
        .scrollIndicators(.hidden)
        .background { CarvisBackground() }
        .navigationTitle("Shop floor")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.hidden, for: .navigationBar)
        .onAppear { shops.startLive() }
        .sheet(item: $selected) { mechanic in
            MechanicDetailSheet(mechanic: floor.first { $0.id == mechanic.id } ?? mechanic)
        }
        .sensoryFeedback(.increase, trigger: shops.finishedToday)
        .confirmationDialog("Close this shop? Mechanics would need a new code to join.",
                            isPresented: $isConfirmingClose, titleVisibility: .visible) {
            Button("Close shop", role: .destructive) {
                shops.close()
                dismiss()
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Circle()
                    .fill(Theme.accent)
                    .frame(width: 8, height: 8)
                    .phaseAnimator([false, true]) { dot, on in dot.opacity(on ? 1 : 0.3) } animation: { _ in .easeInOut(duration: 0.9) }
                Text("Live")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.accent)
            }
            Text(shops.shop?.name ?? "Shop")
                .font(.system(size: 36, weight: .semibold))
                .tracking(-0.8)
            if let code = shops.shop?.code {
                HStack(spacing: 10) {
                    Text("Join code")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                    Text(code)
                        .font(.headline.monospaced())
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Theme.card, in: Capsule())
                    ShareLink(item: "Join my Carvis shop with code \(code)") {
                        Image(systemName: "square.and.arrow.up")
                            .font(.headline)
                            .frame(width: 44, height: 44)
                            .carvisGlass(.card, in: Circle())
                    }
                    .accessibilityLabel("Share join code")
                }
            }
        }
        .padding(.horizontal, 6)
        .padding(.top, 4)
    }

    private var stats: some View {
        let active = floor.filter { !$0.isDone }
        let average = active.isEmpty ? 0 : Int(active.map(\.progress).reduce(0, +) / Double(active.count) * 100)
        let safety = active.filter { $0.status == .safety }.count
        return Grid(horizontalSpacing: 12, verticalSpacing: 12) {
            GridRow {
                StatTile(title: "On the floor", value: active.count, unit: nil, symbol: "person.3.fill", tint: Theme.ink)
                StatTile(title: "Average progress", value: average, unit: "%", symbol: "chart.bar.fill", tint: Theme.accent)
            }
            GridRow {
                StatTile(title: "Safety checks now", value: safety, unit: nil, symbol: "exclamationmark.triangle.fill",
                         tint: safety > 0 ? Theme.safetyRed : Theme.inkSecondary)
                StatTile(title: "Finished today", value: shops.finishedToday, unit: nil, symbol: "checkmark.seal.fill", tint: Theme.accent)
            }
        }
    }
}

private struct StatTile: View {
    let title: String
    let value: Int
    let unit: String?
    let symbol: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.medium))
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.85)
            HStack(alignment: .firstTextBaseline, spacing: 2) {
                RollingNumber(value: value, delay: 0.15)
                    .font(Theme.number(40))
                    .tracking(-1)
                if let unit {
                    Text(unit)
                        .font(.title3)
                        .foregroundStyle(Theme.inkSecondary)
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

/// One mechanic: who, which bay and car, the job, the step they're on, and how far along.
private struct MechanicCard: View {
    let mechanic: ShopMechanic

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                ProgressAvatar(mechanic: mechanic, size: 44)
                VStack(alignment: .leading, spacing: 2) {
                    Text(mechanic.isYou ? "You" : mechanic.name)
                        .font(.headline)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Text(mechanic.isYou ? "This phone" : "Bay \(mechanic.bay)")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                        .lineLimit(1)
                }
                .layoutPriority(1)
                Spacer(minLength: 8)
                StatusChip(status: mechanic.status)
                    .fixedSize()
            }

            if mechanic.isDone {
                Text("Job finished. Next job starting soon.")
                    .font(.title3.weight(.semibold))
            } else {
                HStack(alignment: .center, spacing: 12) {
                    Image(systemName: mechanic.current.symbol)
                        .font(.headline)
                        .foregroundStyle(.white)
                        .frame(width: 40, height: 40)
                        .background(mechanic.status == .safety ? Theme.safetyRed : mechanic.color, in: Circle())
                        .symbolEffect(.bounce, value: mechanic.step)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("\(mechanic.procedure.name) · Step \(mechanic.step) of \(mechanic.total)")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(Theme.inkSecondary)
                            .contentTransition(.numericText(value: Double(mechanic.step)))
                        Text(mechanic.current.title)
                            .font(.title3.weight(.semibold))
                            .lineLimit(2)
                            .contentTransition(.opacity)
                    }
                }
            }

            StepBar(step: mechanic.isDone ? mechanic.total + 1 : mechanic.step, total: mechanic.total, tint: mechanic.color)

            TimelineView(.periodic(from: .now, by: 1)) { context in
                HStack {
                    if !mechanic.isDone {
                        Label("On this step \(Self.clock(context.date.timeIntervalSince(mechanic.stepStartedAt)))", systemImage: "timer")
                    }
                    Spacer()
                    Text("\(Int(mechanic.progress * 100))%")
                        .fontWeight(.semibold)
                        .foregroundStyle(mechanic.color)
                }
                .font(.footnote.monospacedDigit())
                .foregroundStyle(Theme.inkSecondary)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous)
                .strokeBorder(mechanic.status == .safety ? Theme.safetyRed.opacity(0.4) : .clear, lineWidth: 2)
        )
        .contentShape(RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    static func clock(_ seconds: TimeInterval) -> String {
        let s = max(0, Int(seconds))
        return String(format: "%d:%02d", s / 60, s % 60)
    }
}

private struct StatusChip: View {
    let status: ShopMechanic.Status

    var body: some View {
        Label(text, systemImage: symbol)
            .font(.caption.weight(.semibold))
            .foregroundStyle(foreground)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(background, in: Capsule())
            .contentTransition(.opacity)
    }

    private var text: String {
        switch status {
        case .working: "Working"
        case .safety: "Safety check"
        case .camera: "Camera check"
        case .done: "Done"
        }
    }
    private var symbol: String {
        switch status {
        case .working: "wrench.and.screwdriver.fill"
        case .safety: "exclamationmark.triangle.fill"
        case .camera: "eyeglasses"
        case .done: "checkmark"
        }
    }
    private var foreground: Color {
        switch status {
        case .working: Theme.accent
        case .safety: Theme.safetyRed
        case .camera: Theme.accent
        case .done: Theme.ink
        }
    }
    private var background: Color {
        switch status {
        case .working, .camera: Theme.accent.opacity(0.1)
        case .safety: Theme.safetyRed.opacity(0.12)
        case .done: Theme.lime
        }
    }
}

/// One segment per step, in the mechanic's color.
private struct StepBar: View {
    let step: Int
    let total: Int
    let tint: Color

    var body: some View {
        HStack(spacing: 3) {
            ForEach(1...max(total, 1), id: \.self) { number in
                Capsule()
                    .fill(number < step ? tint : number == step ? tint.opacity(0.4) : Theme.ink.opacity(0.08))
                    .frame(height: 6)
            }
        }
        .accessibilityHidden(true)
    }
}

private struct ActivityFeed: View {
    let events: [ShopEvent]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(events) { event in
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: event.symbol)
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.white)
                        .frame(width: 32, height: 32)
                        .background(Color(hex: event.colorHex), in: Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.who)
                            .font(.subheadline.weight(.semibold))
                        Text(event.text)
                            .font(.subheadline)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    Spacer(minLength: 8)
                    TimelineView(.periodic(from: .now, by: 5)) { context in
                        Text(Self.ago(event.date, now: context.date))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(Theme.inkTertiary)
                    }
                }
                .padding(.vertical, 10)
                .transition(.asymmetric(insertion: .move(edge: .top).combined(with: .opacity), removal: .opacity))
                if event.id != events.last?.id { Divider() }
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 8)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .animation(.spring(duration: 0.5, bounce: 0), value: events.map(\.id))
    }

    static func ago(_ date: Date, now: Date) -> String {
        let seconds = Int(now.timeIntervalSince(date))
        if seconds < 10 { return "now" }
        if seconds < 60 { return "\(seconds)s" }
        return "\(seconds / 60)m"
    }
}

// MARK: - Mechanic detail

/// Every step of one mechanic's job: done, now, and next.
private struct MechanicDetailSheet: View {
    let mechanic: ShopMechanic

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack(spacing: 14) {
                    ProgressAvatar(mechanic: mechanic, size: 56)
                    VStack(alignment: .leading, spacing: 3) {
                        Text(mechanic.isYou ? "You" : mechanic.name)
                            .font(.title2.weight(.semibold))
                        Text(mechanic.isYou ? mechanic.vehicle : "Bay \(mechanic.bay) · \(mechanic.vehicle)")
                            .font(.subheadline)
                            .foregroundStyle(Theme.inkSecondary)
                    }
                    Spacer()
                    StatusChip(status: mechanic.status)
                }

                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text("\(Int(mechanic.progress * 100))")
                        .font(Theme.number(56))
                        .tracking(-1.5)
                    Text("% through \(mechanic.procedure.name.lowercased())")
                        .font(.title3)
                        .foregroundStyle(Theme.inkSecondary)
                }

                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(mechanic.procedure.steps.enumerated()), id: \.offset) { index, step in
                        let number = index + 1
                        let state: Int = mechanic.isDone || number < mechanic.step ? 0 : number == mechanic.step ? 1 : 2
                        HStack(spacing: 12) {
                            ZStack {
                                Circle()
                                    .fill(state == 0 ? mechanic.color : state == 1 ? mechanic.color.opacity(0.15) : Theme.pearl)
                                if state == 0 {
                                    Image(systemName: "checkmark")
                                        .font(.caption.weight(.bold))
                                        .foregroundStyle(.white)
                                } else {
                                    Text("\(number)")
                                        .font(.caption.weight(.semibold))
                                        .foregroundStyle(state == 1 ? mechanic.color : Theme.inkTertiary)
                                }
                            }
                            .frame(width: 30, height: 30)
                            Text(step.title)
                                .font(state == 1 ? .body.weight(.semibold) : .body)
                                .foregroundStyle(state == 2 ? Theme.inkTertiary : Theme.ink)
                            Spacer()
                            if step.safety {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundStyle(Theme.safetyRed)
                                    .accessibilityLabel("Safety check")
                            } else if step.camera {
                                Image(systemName: "eyeglasses")
                                    .foregroundStyle(Theme.accent)
                                    .accessibilityLabel("Camera check")
                            }
                        }
                        .padding(.vertical, 10)
                        .padding(.horizontal, 12)
                        .background(state == 1 ? mechanic.color.opacity(0.08) : .clear,
                                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                }
                .padding(8)
                .background(Theme.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
            }
            .padding(24)
        }
        .background(Theme.pearl.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}
