import SwiftUI

/// The home screen. The top half is your car's own dashboard: the car,
/// the oil change countdown, the odometer, and what's due next. Below that:
/// the glasses, the job in progress, your maintenance list, your specs,
/// and the service history. A floating button starts a new job.
struct DashboardView: View {
    /// Shared ID that links the job card (or New job button) to the progress screen's zoom.
    static let jobZoomID = "current-job"

    let session: RepairSession
    let zoom: Namespace.ID

    @State private var isShowingNewJob = false
    @State private var isEditingCar = false
    @State private var isUpdatingOdometer = false
    @State private var pendingJobName: String?

    private var garage: CarProfileStore { session.garage }
    private var profile: CarProfile { garage.profile }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                TopBar(onEdit: { isEditingCar = true })
                    .appearAnimation(index: 0)

                CarHero(profile: profile)
                    .padding(.bottom, 4)

                OilChangeTile(item: profile.oilChange, odometer: profile.odometer, onSetUp: { isEditingCar = true })
                    .appearAnimation(index: 2)

                HStack(spacing: 14) {
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
                .appearAnimation(index: 3)

                GlassesCard(onAsk: session.showAsk)
                    .appearAnimation(index: 4)

                if session.hasActiveJob, let current = session.current {
                    Button {
                        session.showProgress()
                    } label: {
                        CurrentJobCard(name: session.jobName, response: current)
                    }
                    .buttonStyle(PressableCardStyle())
                    .zoomSource(id: Self.jobZoomID, in: zoom)
                    .accessibilityHint("Shows the progress screen")
                    .transition(.blurReplace)
                }

                MaintenanceCard(items: profile.otherMaintenance, odometer: profile.odometer, onEdit: { isEditingCar = true })
                    .appearAnimation(index: 5)

                SpecsCard(details: profile.details, onEdit: { isEditingCar = true })
                    .appearAnimation(index: 6)

                HistoryCard(records: session.history.records)
                    .appearAnimation(index: 7)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 16)
            .animation(Motion.enter, value: session.hasActiveJob)
            .animation(Motion.change, value: profile)
        }
        .scrollIndicators(.hidden)
        // The button floats over the content, so the glass has something to refract as you scroll.
        .safeAreaInset(edge: .bottom) {
            newJobButton
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
    }

    private var newJobButton: some View {
        Button {
            isShowingNewJob = true
        } label: {
            Label("New job", systemImage: "plus")
                .font(Theme.buttonFont)
                .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
        }
        .carvisButton(prominent: true)
        // With no job card on screen, the progress screen zooms out of this button instead.
        .zoomSource(id: Self.jobZoomID, in: zoom, isEnabled: !session.hasActiveJob)
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
        .appearAnimation(index: 8)
    }

    /// Start the job only after the sheet has fully closed, so the zoom has a clear stage.
    private func startPendingJob() {
        guard let name = pendingJobName else { return }
        pendingJobName = nil
        Task { await session.start(jobName: name) }
    }
}

// MARK: - Top

private struct TopBar: View {
    @Environment(GlassesController.self) private var glasses
    let onEdit: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 0) {
                Text(greeting)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Theme.inkSecondary)
                Text("Carvis")
                    .font(.system(.title, design: .rounded, weight: .semibold))
                    .accessibilityAddTraits(.isHeader)
            }
            Spacer()
            CircleIcon(systemImage: "eyeglasses", dot: glasses.isConnected ? Theme.lime : nil)
                .accessibilityLabel(glasses.isConnected ? "Glasses connected" : "Glasses not connected")
            Button(action: onEdit) {
                CircleIcon(systemImage: "slider.horizontal.3")
            }
            .buttonStyle(PressableCardStyle())
            .accessibilityLabel("Edit your car")
        }
    }

    private var greeting: String {
        switch Calendar.current.component(.hour, from: .now) {
        case 5..<12: "Good morning"
        case 12..<17: "Good afternoon"
        default: "Good evening"
        }
    }
}

/// A round white button, like the ones in the corners of the reference designs.
private struct CircleIcon: View {
    let systemImage: String
    var dot: Color?

    var body: some View {
        Image(systemName: systemImage)
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Theme.ink)
            .frame(width: 48, height: 48)
            .carvisGlass(.card, in: Circle())
            .overlay(alignment: .topTrailing) {
                if let dot {
                    Circle()
                        .fill(dot)
                        .frame(width: 11, height: 11)
                        .overlay(Circle().stroke(Color.white, lineWidth: 2))
                        .offset(x: -2, y: 2)
                        .transition(.scale(scale: 0.5).combined(with: .opacity))
                }
            }
            .frame(minWidth: 48, minHeight: 48)
    }
}

/// The car, big, with its name and your details as chips.
private struct CarHero: View {
    let profile: CarProfile
    @State private var arrived = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var chips: [String] {
        [profile.trim, profile.color, profile.plate].filter { !$0.isEmpty }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("Subaru WRX")
                    .font(.system(size: 40, weight: .regular))
                    .tracking(-1)
                Text("2022")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.inkSecondary)
                    .baselineOffset(18)
            }
            .accessibilityElement(children: .combine)

            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(chips, id: \.self) { Chip(text: $0) }
                }
            }
            .scrollIndicators(.hidden)
            .scrollClipDisabled()

            Image("WRX")
                .resizable()
                .scaledToFit()
                .accessibilityLabel("Blue 2022 Subaru WRX")
                .background(alignment: .bottom) {
                    // A soft shadow so the car sits on the floor instead of floating.
                    Ellipse()
                        .fill(Theme.ink.opacity(0.22))
                        .frame(height: 26)
                        .blur(radius: 14)
                        .padding(.horizontal, 30)
                        .offset(y: 6)
                }
                .padding(.top, 6)
                .padding(.horizontal, -8)
                // The car rolls in once, the first time the dashboard appears.
                .offset(x: arrived || reduceMotion ? 0 : 80)
                .opacity(arrived ? 1 : 0)
                .onAppear {
                    guard !arrived else { return }
                    withAnimation(.spring(duration: 0.9, bounce: 0.12).delay(0.1)) { arrived = true }
                }
        }
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
                    Text(max(milesLeft, 0).formatted())
                        .font(Theme.number(68))
                        .tracking(-2)
                        .monospacedDigit()
                        .contentTransition(.numericText(value: Double(milesLeft)))
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

    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Capsule().fill(.white.opacity(0.12))
                Capsule()
                    .fill(color)
                    .frame(width: max(8, geometry.size.width * fraction))
                    .shadow(color: color.opacity(0.7), radius: 8)
            }
        }
        .frame(height: 8)
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
                Text(miles.formatted())
                    .font(Theme.number(30))
                    .tracking(-0.8)
                    .monospacedDigit()
                    .minimumScaleFactor(0.7)
                    .lineLimit(1)
                    .contentTransition(.numericText(value: Double(miles)))
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

/// Are the glasses connected? Connect them, or look at a part and ask about it.
private struct GlassesCard: View {
    @Environment(GlassesController.self) private var glasses
    let onAsk: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                Image(systemName: "eyeglasses")
                    .font(.title2)
                    .foregroundStyle(.white)
                    .frame(width: 52, height: 52)
                    .background(Theme.ink, in: Circle())
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

            if glasses.isConnected {
                Button(action: onAsk) {
                    Label("Ask about a part", systemImage: "camera.viewfinder")
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
                            .frame(width: geometry.size.width * (item.used(odometer: odometer) ?? 0))
                    }
                }
                .frame(height: 5)
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
            CardHeader(title: "Service history", systemImage: "clock.arrow.circlepath")

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
