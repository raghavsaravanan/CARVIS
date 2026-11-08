import Foundation
import Observation

/// Who is using Carvis on this phone, and how much detail they want to see.
/// This is a local profile, saved on the phone only; there's no account server yet.
struct Account: Codable, Equatable {
    enum Mode: String, Codable, CaseIterable, Identifiable {
        // "developer" is the saved value from before the rename, so existing accounts still load.
        case personal
        case team = "developer"
        var id: Self { self }

        var title: String {
            switch self {
            case .personal: "Personal"
            case .team: "Mechanic / team"
            }
        }

        var summary: String {
            switch self {
            case .personal: "A clean dashboard for your own car."
            case .team: "For shops and teams. Adds tools to set the server and check the glasses and voice."
            }
        }

        var symbol: String {
            switch self {
            case .personal: "person.fill"
            case .team: "wrench.and.screwdriver.fill"
            }
        }
    }

    var name: String
    var mode: Mode
    var createdAt = Date.now

    var initials: String {
        let letters = name.split(separator: " ").prefix(2).compactMap(\.first)
        return letters.isEmpty ? "?" : String(letters).uppercased()
    }
}

/// The signed-in profile and team settings, saved to a small file on the phone.
@Observable
final class AccountStore {
    var account: Account? { didSet { save() } }
    /// Mechanic / team mode only: send questions to this server instead of the one in Info.plist.
    var serverOverride: String = "" { didSet { save() } }

    var isTeam: Bool { account?.mode == .team }

    /// The server Carvis talks to: the team override if set, otherwise Info.plist.
    var visionClient: CarvisVisionClient? {
        let text = serverOverride.trimmingCharacters(in: .whitespaces)
        if isTeam, !text.isEmpty, let url = URL(string: text), url.scheme != nil {
            return CarvisVisionClient(baseURL: url)
        }
        return CarvisVisionClient.fromInfoPlist()
    }

    private struct Saved: Codable {
        var account: Account?
        var serverOverride: String
    }

    private let fileURL = URL.documentsDirectory.appending(path: "account.json")
    private var isLoading = false

    init() {
        isLoading = true
        if let data = try? Data(contentsOf: fileURL),
           let saved = try? JSONDecoder().decode(Saved.self, from: data) {
            account = saved.account
            serverOverride = saved.serverOverride
        }
        isLoading = false
    }

    func signOut() {
        account = nil
    }

    private func save() {
        guard !isLoading else { return }
        try? JSONEncoder().encode(Saved(account: account, serverOverride: serverOverride)).write(to: fileURL)
    }
}

/// One question you asked Carvis and what came back.
struct ChatEntry: Codable, Identifiable, Equatable {
    var id = UUID()
    var date = Date.now
    let question: String
    let reply: String
    /// True when the reply came from the service manual; false for refusals and errors.
    let fromManual: Bool
}

/// Your recent questions, so the dashboard can show the latest ones. Saved on the phone.
@Observable
final class ChatHistory {
    private(set) var entries: [ChatEntry] = []   // newest first
    private let fileURL = URL.documentsDirectory.appending(path: "chat-history.json")

    init() {
        if let data = try? Data(contentsOf: fileURL),
           let saved = try? JSONDecoder().decode([ChatEntry].self, from: data) {
            entries = saved
        }
    }

    func add(question: String, reply: String, fromManual: Bool) {
        entries.insert(ChatEntry(question: question, reply: reply, fromManual: fromManual), at: 0)
        if entries.count > 50 { entries.removeLast(entries.count - 50) }
        try? JSONEncoder().encode(entries).write(to: fileURL)
    }
}
