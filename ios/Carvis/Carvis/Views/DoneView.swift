import SwiftUI

/// The job is finished. The one celebratory moment in the app: the check mark
/// pops in with a little bounce and a success haptic, then the cards follow.
struct DoneView: View {
    let session: RepairSession
    let response: StepResponse

    @State private var hasCelebrated = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 80, weight: .semibold))
                    .symbolRenderingMode(.palette)
                    .foregroundStyle(Color.white, Theme.amber)
                    .shadow(color: Theme.amber.opacity(0.4), radius: 16, y: 6)
                    .scaleEffect(hasCelebrated || reduceMotion ? 1 : 0.7)
                    .opacity(hasCelebrated ? 1 : 0)
                    .symbolEffect(.bounce, value: hasCelebrated)
                    .padding(.top, 24)
                    .accessibilityHidden(true)

                SummaryCard(title: response.displayText, summary: response.summary)
                    .appearAnimation(index: 2)

                if let nextStep = response.summary?.nextStep {
                    NextStepCard(nextStep: nextStep)
                        .appearAnimation(index: 3)
                }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 16)
        }
        .scrollIndicators(.hidden)
        .safeAreaInset(edge: .bottom) {
            Button {
                session.finish()
            } label: {
                Text("Finish")
                    .font(Theme.buttonFont)
                    .frame(maxWidth: .infinity, minHeight: Theme.primaryButtonHeight)
            }
            .carvisButton(prominent: true)
            .padding(.horizontal, 20)
            .padding(.bottom, 8)
            .appearAnimation(index: 4)
        }
        .background { CarvisBackground() }
        .navigationBarBackButtonHidden()
        .toolbar(.hidden, for: .navigationBar)
        .sensoryFeedback(.success, trigger: hasCelebrated)
        .onAppear {
            withAnimation(reduceMotion ? .easeOut(duration: 0.2) : Motion.celebrate.delay(0.1)) {
                hasCelebrated = true
            }
        }
    }
}

private struct SummaryCard: View {
    let title: String
    let summary: Summary?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title)
                .font(.title.weight(.semibold))
                .accessibilityAddTraits(.isHeader)

            if let summary {
                let log = summary.serviceLog
                VStack(spacing: 12) {
                    LogRow(label: "Date", value: log.date)
                    Divider()
                    LogRow(label: "Mileage", value: "\(log.mileage.formatted()) mi")
                    Divider()
                    LogRow(label: "Oil", value: log.oil)
                    Divider()
                    LogRow(label: "Filter", value: log.filter)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text("Next service")
                        .font(.subheadline)
                        .foregroundStyle(Theme.inkSecondary)
                    Text(summary.nextService)
                        .font(.body)
                        .fixedSize(horizontal: false, vertical: true)   // wrap instead of cutting off
                }
                .accessibilityElement(children: .combine)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(24)
        .carvisGlass(.hero, in: RoundedRectangle(cornerRadius: Theme.Radius.card, style: .continuous))
    }
}

/// One label/value line in the service log, like "Filter    New oil filter".
private struct LogRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .foregroundStyle(Theme.inkSecondary)
            Spacer(minLength: 16)
            Text(value)
                .fontWeight(.semibold)
                .multilineTextAlignment(.trailing)
        }
        .font(.body)
        .accessibilityElement(children: .combine)
    }
}

private struct NextStepCard: View {
    let nextStep: NextStep

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(nextStep.title)
                .font(.headline)
            Text(nextStep.detail)
                .font(.body)
                .foregroundStyle(Theme.inkSecondary)
            Text(nextStep.cta)
                .font(.subheadline.weight(.semibold))
                .padding(.top, 4)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(20)
        .carvisGlass(.card, in: RoundedRectangle(cornerRadius: Theme.Radius.small, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}
