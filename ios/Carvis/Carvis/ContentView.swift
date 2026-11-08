import SwiftUI

/// The root view. The dashboard is home; the progress and done screens open
/// on top of it. On iOS 18+ the progress screen zooms out of the card you tapped.
struct ContentView: View {
    @State private var session = RepairSession()
    @State private var glasses = GlassesController()
    @State private var askSpeech = SystemSpeechOutput()
    @Namespace private var zoom

    var body: some View {
        NavigationStack(path: $session.path) {
            DashboardView(session: session, zoom: zoom)
                .navigationDestination(for: RepairSession.Route.self) { route in
                    destination(for: route)
                }
        }
        .environment(glasses)
        // The Meta AI app sends you back here after you connect your glasses.
        .onOpenURL { glasses.handle(url: $0) }
        .tint(Theme.ink)
        .foregroundStyle(Theme.ink)
        .preferredColorScheme(.light)   // light only for now
    }

    @ViewBuilder
    private func destination(for route: RepairSession.Route) -> some View {
        switch route {
        case .progress:
            if let response = session.current {
                JobProgressView(session: session, response: response)
                    .zoomDestination(id: DashboardView.jobZoomID, in: zoom)
            }
        case .done:
            if let response = session.current {
                DoneView(session: session, response: response)
            }
        case .ask:
            AskView(vehicle: .demo, client: CarvisVisionClient.fromInfoPlist(), speech: askSpeech)
        case .wakeTest:
            WakeTestView()
        }
    }
}

#Preview {
    ContentView()
}
