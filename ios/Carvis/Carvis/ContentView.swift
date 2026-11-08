import SwiftUI

/// The root view. The dashboard is home; the progress and done screens open
/// on top of it. On iOS 18+ the progress screen zooms out of the card you tapped.
struct ContentView: View {
    @State private var session: RepairSession
    @State private var glasses: GlassesController
    @State private var accounts: AccountStore
    @State private var chats: ChatHistory
    @State private var shops = ShopStore()
    @State private var assistant: CarvisConversationCoordinator
    @Namespace private var zoom

    init() {
        // One voice for the whole app, so step readouts and answers never talk over each other.
        let speech = SystemSpeechOutput()
        let glasses = GlassesController()
        let accounts = AccountStore()
        let chats = ChatHistory()
        let garage = CarProfileStore()
        _session = State(initialValue: RepairSession(speech: speech, garage: garage))
        _glasses = State(initialValue: glasses)
        _accounts = State(initialValue: accounts)
        _chats = State(initialValue: chats)
        _assistant = State(initialValue: CarvisConversationCoordinator(glasses: glasses, accounts: accounts, chats: chats, garage: garage, speech: speech))
    }

    var body: some View {
        NavigationStack(path: $session.path) {
            DashboardView(session: session, zoom: zoom)
                .navigationDestination(for: RepairSession.Route.self) { route in
                    destination(for: route)
                }
        }
        .environment(glasses)
        .environment(accounts)
        .environment(chats)
        .environment(shops)
        .environment(assistant)
        // Starting a job turns Carvis on (camera live, listening for "Hey Carvis") until it ends.
        .onChange(of: session.hasActiveJob) { _, active in
            if active {
                assistant.activate(.job)
            } else {
                assistant.deactivate(.job)
            }
        }
        // Sign-up on first launch, and again after signing out.
        .fullScreenCover(isPresented: Binding(get: { accounts.account == nil }, set: { _ in })) {
            OnboardingView(accounts: accounts, garage: session.garage)
                .tint(Theme.ink)
                .foregroundStyle(Theme.ink)
        }
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
            AskView()
        case .wakeTest:
            WakeTestView()
        case .shop:
            ShopFloorView(liveYou: ShopMechanic.you(from: session))
        }
    }
}

#Preview {
    ContentView()
}
