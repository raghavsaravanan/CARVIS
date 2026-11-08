import SwiftUI

/// The home screen: the vehicle, the job in progress, upcoming maintenance,
/// service history, and a floating glass button to start a new job.
struct DashboardView: View {
    /// Shared ID that links the job card (or New job button) to the progress screen's zoom.
    static let jobZoomID = "current-job"

    let session: RepairSession
    let zoom: Namespace.ID

    @State private var isShowingNewJob = false
    @State private var pendingJobName: String?
    @ScaledMetric(relativeTo: .largeTitle) private var wordmarkSize: CGFloat = 44

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Carvis")
                    .font(.system(size: wordmarkSize, weight: .semibold, design: .rounded))
                    .tracking(-0.5)
                    .padding(.bottom, 4)
                    .accessibilityAddTraits(.isHeader)
                    .appearAnimation(index: 0)

                VehicleCard()
                    .appearAnimation(index: 1)

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

                GlassesCard(onAsk: session.showAsk)
                    .appearAnimation(index: 2)

                Button("Glasses wake test", systemImage: "waveform") {
                    session.path.append(.wakeTest)
                }
                .buttonStyle(.bordered)

                if let latest = session.history.records.first {
                    UpcomingCard(summary: latest.summary)
                        .appearAnimation(index: 3)
                        .transition(.blurReplace)
                }

                HistoryCard(records: session.history.records)
                    .appearAnimation(index: 4)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .padding(.bottom, 16)
            .animation(Motion.enter, value: session.hasActiveJob)
            .animation(Motion.enter, value: session.history.records.count)
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
        .appearAnimation(index: 5)
    }

    /// Start the job only after the sheet has fully closed, so the zoom has a clear stage.
    private func startPendingJob() {
        guard let name = pendingJobName else { return }
        pendingJobName = nil
        Task { await session.start(jobName: name) }
    }
}

/// Small icon + title used at the top of each card.
private struct CardHeader: View {
    let title: String
    let systemImage: String

    var body: some View {
        Label {
            Text(title)
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(Theme.amber)
        }
        .font(.subheadline.weight(.semibold))
        .foregroundStyle(Theme.inkSecondary)
        .accessibilityAddTraits(.isHeader)
    }
}

private struct VehicleCard: View {
    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: "car.side.fill")
                .font(.title2)
                .foregroundStyle(Theme.ink)
                .frame(width: 52, height: 52)
                .background(Theme.sky.opacity(0.8), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text("Your vehicle")
                    .font(.subheadline)
                    .foregroundStyle(Theme.inkSecondary)
                Text(Vehicle.demo.displayName)
                    .font(.title3.weight(.semibold))
            }
            Spacer(minLength: 0)
        }
        .padding(18)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
        .accessibilityElement(children: .combine)
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

/// Are the glasses connected? Connect them, or look at a part and ask about it.
private struct GlassesCard: View {
    @Environment(GlassesController.self) private var glasses
    let onAsk: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 14) {
                Image(systemName: "eyeglasses")
                    .font(.title2)
                    .foregroundStyle(Theme.ink)
                    .frame(width: 52, height: 52)
                    .background(Theme.amber.opacity(0.18), in: Circle())
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
        }
    }
}

/// What's due next, from the most recent finished job.
private struct UpcomingCard: View {
    let summary: Summary

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            CardHeader(title: "Upcoming", systemImage: "calendar")

            Text(summary.nextService)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)

            if let nextStep = summary.nextStep {
                Divider()
                VStack(alignment: .leading, spacing: 4) {
                    Text(nextStep.title)
                        .font(.body.weight(.semibold))
                    Text(nextStep.detail)
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
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
                .foregroundStyle(Theme.amber)
                .frame(width: 36, height: 36)
                .background(Theme.amber.opacity(0.14), in: Circle())
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
