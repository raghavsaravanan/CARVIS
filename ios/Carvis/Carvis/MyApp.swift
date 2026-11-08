import MWDATCore
import SwiftUI

@main struct MyApp: App {
    init() {
        // Start Meta's glasses SDK once, when the app launches.
        do {
            try Wearables.configure()
        } catch {
            print("Couldn't start the Meta glasses SDK: \(error)")
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
