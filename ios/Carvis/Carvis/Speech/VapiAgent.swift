import Combine
import Daily
import Foundation
import Observation
import Vapi

/// The Vapi keys Carvis needs, read from Config/VapiConfig.plist (ignored by git).
struct VapiConfig {
    let publicKey: String
    let assistantID: String

    /// Nil when the file or either value is missing.
    static func load() -> VapiConfig? {
        guard let url = Bundle.main.url(forResource: "VapiConfig", withExtension: "plist"),
              let values = NSDictionary(contentsOf: url) as? [String: Any],
              let key = (values["PublicKey"] as? String)?.trimmingCharacters(in: .whitespaces), !key.isEmpty,
              let id = (values["AssistantID"] as? String)?.trimmingCharacters(in: .whitespaces), !id.isEmpty
        else { return nil }
        return VapiConfig(publicKey: key, assistantID: id)
    }
}

/// One live Vapi call. Vapi and Daily handle the listening, thinking, and talking; the
/// coordinator decides when a call starts and ends. Tools run on the server, not here.
@Observable
@MainActor
final class VapiAgent {
    enum State: Equatable {
        case idle
        case connecting
        case listening          // their turn
        case speaking           // Carvis is talking
        case failed(String)
    }

    struct Line: Identifiable, Equatable {
        let id = UUID()
        let fromCarvis: Bool
        let text: String
    }

    private(set) var state: State = .idle
    /// The conversation so far, newest last. For display; the server holds the real memory.
    private(set) var lines: [Line] = []
    /// What they're saying right now, before Vapi finalizes it.
    private(set) var partial = ""

    var isInCall: Bool {
        switch state {
        case .connecting, .listening, .speaking: true
        case .idle, .failed: false
        }
    }

    /// The assistant has joined and is ready to talk.
    @ObservationIgnored var onConnected: (() -> Void)?
    /// The call is completely over. Exactly once per call, with an error if it failed.
    @ObservationIgnored var onEnded: ((String?) -> Void)?

    @ObservationIgnored private let config: VapiConfig
    @ObservationIgnored private var vapi: Vapi?
    @ObservationIgnored private var events: AnyCancellable?
    @ObservationIgnored private var endWatchdog: Task<Void, Never>?
    @ObservationIgnored private var joinMute: Task<Void, Never>?

    init(config: VapiConfig) {
        self.config = config
    }

    /// Starts a call and returns its Vapi ID. Throws if Vapi wouldn't start it.
    func start(metadata: [String: Any], overrides: [String: Any]) async throws -> String {
        lines = []
        partial = ""
        state = .connecting
        let vapi = Vapi(publicKey: config.publicKey)
        self.vapi = vapi
        events = vapi.eventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in self?.handle(event) }
        do {
            let call = try await vapi.start(assistantId: config.assistantID, metadata: metadata, assistantOverrides: overrides)
            print("[Vapi] call requested: \(call.id)")
            holdMicrophoneMuted(on: vapi)
            return call.id
        } catch {
            discard(vapi)
            throw error
        }
    }

    func end() {
        guard let vapi else { return }
        vapi.stop()
        endWatchdog?.cancel()
        endWatchdog = Task { [weak self] in
            // The SDK can't leave a call that is still joining, so ask again once it has.
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            vapi.stop()
            // A call that never finished joining doesn't report leaving. Don't wait forever.
            try? await Task.sleep(for: .seconds(3.5))
            guard !Task.isCancelled else { return }
            self?.finish(failure: nil)
        }
    }

    /// The SDK joins with the microphone on, just after `start` returns. Mute as soon as
    /// there is a call to mute, so nothing is heard before the glasses route is checked.
    private func holdMicrophoneMuted(on vapi: Vapi) {
        joinMute = Task { [weak self] in
            for _ in 0..<100 {
                guard let self, self.vapi === vapi, !Task.isCancelled else { return }
                do {
                    try await vapi.setMuted(true)
                    print("[Vapi] microphone held muted until the route is verified")
                    return
                } catch {
                    try? await Task.sleep(for: .milliseconds(30))
                }
            }
        }
    }

    /// Clears a call that never got going, so the screens don't show it as connecting.
    private func discard(_ failed: Vapi) {
        guard vapi === failed else { return }
        joinMute?.cancel()
        joinMute = nil
        events?.cancel()
        events = nil
        vapi = nil
        partial = ""
        state = .idle
    }

    /// Sends the words said with "Hey Carvis" as the mechanic's first turn.
    func deliver(question: String) {
        guard let vapi else { return }
        Task {
            do {
                try await vapi.send(message: VapiMessage(type: "add-message", role: "user", content: question))
                print("[Vapi] opening question delivered")
            } catch {
                print("[Vapi] couldn't deliver the opening question: \(error)")
            }
        }
    }

    func setMicrophoneMuted(_ muted: Bool) async {
        do {
            try await vapi?.setMuted(muted)
            print("[Vapi] microphone \(muted ? "muted" : "live")")
        } catch {
            print("[Vapi] mute change failed: \(error)")
        }
    }

    /// Asks the call to use Bluetooth. Whether that really is the glasses is checked separately.
    func preferBluetooth() async {
        do {
            try await vapi?.setAudioDeviceType(.bluetooth)
        } catch {
            print("[Vapi] couldn't select Bluetooth: \(error)")
        }
    }

    private func handle(_ event: Vapi.Event) {
        switch event {
        case .callDidStart:
            print("[Vapi] assistant connected")
            state = .listening
            onConnected?()

        case .callDidEnd:
            print("[Vapi] call ended")
            finish(failure: nil)

        case .transcript(let transcript):
            let fromCarvis = transcript.role == .assistant
            if transcript.transcriptType == .final {
                lines.append(Line(fromCarvis: fromCarvis, text: transcript.transcript))
                if lines.count > 12 { lines.removeFirst(lines.count - 12) }
                if !fromCarvis { partial = "" }
            } else if !fromCarvis {
                partial = transcript.transcript
            }

        case .speechUpdate(let update):
            guard update.role == .assistant, isInCall else { return }
            state = update.status == .started ? .speaking : .listening

        case .error(let error):
            // The SDK only reports this when the call has already failed.
            print("[Vapi] call failed: \(error)")
            finish(failure: error.localizedDescription)

        default:
            break
        }
    }

    private func finish(failure: String?) {
        guard vapi != nil else { return }
        endWatchdog?.cancel()
        endWatchdog = nil
        joinMute?.cancel()
        joinMute = nil
        events?.cancel()
        events = nil
        vapi = nil
        partial = ""
        state = failure.map { .failed($0) } ?? .idle
        onEnded?(failure)
    }
}
