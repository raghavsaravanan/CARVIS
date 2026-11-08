import Combine
import Foundation
import Observation
import Vapi

/// The Vapi keys Carvis needs, read from Config/VapiConfig.plist (ignored by git).
struct VapiConfig {
    let publicKey: String
    let assistantID: String

    /// Nil when the file or either value is missing; Carvis then uses its built-in voice.
    static func load() -> VapiConfig? {
        guard let url = Bundle.main.url(forResource: "VapiConfig", withExtension: "plist"),
              let values = NSDictionary(contentsOf: url) as? [String: Any],
              let key = (values["PublicKey"] as? String)?.trimmingCharacters(in: .whitespaces), !key.isEmpty,
              let id = (values["AssistantID"] as? String)?.trimmingCharacters(in: .whitespaces), !id.isEmpty
        else { return nil }
        return VapiConfig(publicKey: key, assistantID: id)
    }
}

/// A live voice conversation with the Carvis assistant on Vapi.
///
/// Vapi does the listening, thinking, and talking. Spec questions go from Vapi to the
/// Carvis backend's /vapi-tool. When the assistant needs to see a part, it calls the
/// `look_at_part` tool; Carvis takes a glasses photo, asks /vision-query, and hands the
/// manual's answer back into the conversation word for word.
@Observable
@MainActor
final class VapiAgent {
    enum State: Equatable {
        case idle
        case connecting
        case listening          // your turn
        case speaking           // Carvis is talking
        case lookingAtPart      // taking a photo and checking the manual
        case failed(String)
    }

    struct Line: Identifiable, Equatable {
        let id = UUID()
        let fromCarvis: Bool
        let text: String
    }

    private(set) var state: State = .idle
    /// The conversation so far, newest last.
    private(set) var lines: [Line] = []
    /// What you're saying right now, before Vapi finalizes it.
    private(set) var partial = ""

    var isInCall: Bool {
        switch state {
        case .connecting, .listening, .speaking, .lookingAtPart: true
        case .idle, .failed: false
        }
    }

    /// Takes a glasses photo for this question and returns the manual's answer (or refusal).
    @ObservationIgnored var lookAtPart: ((String) async -> String)?
    /// Called when the conversation ends, however it ends.
    @ObservationIgnored var onEnded: (() -> Void)?

    @ObservationIgnored private let config: VapiConfig
    @ObservationIgnored private var vapi: Vapi?
    @ObservationIgnored private var events: AnyCancellable?
    @ObservationIgnored private var openingQuestion: String?

    init(config: VapiConfig) {
        self.config = config
    }

    func start(vehicle: Vehicle, sessionID: String, openingQuestion: String?) async {
        guard !isInCall else { return }
        lines = []
        partial = ""
        state = .connecting
        self.openingQuestion = openingQuestion

        let vapi = Vapi(publicKey: config.publicKey)
        self.vapi = vapi
        events = vapi.eventPublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] event in self?.handle(event) }

        // The vehicle is always explicit; the assistant must never guess it.
        let vehicleFields: [String: Any] = [
            "year": vehicle.year, "make": vehicle.make, "model": vehicle.model,
            "vehicle": vehicle.displayName, "session_id": sessionID,
        ]
        do {
            _ = try await vapi.start(
                assistantId: config.assistantID,
                metadata: vehicleFields,
                assistantOverrides: ["variableValues": vehicleFields]
            )
            print("[Vapi] call requested")
        } catch {
            print("[Vapi] start failed: \(error)")
            finish(failure: "Couldn't start the conversation: \(error.localizedDescription)")
        }
    }

    func end() {
        guard vapi != nil else { return }
        vapi?.stop()
    }

    // MARK: - Events

    private func handle(_ event: Vapi.Event) {
        switch event {
        case .callDidStart:
            print("[Vapi] call started")
            state = .listening
            if let question = openingQuestion, !question.isEmpty {
                // The question you asked along with "Hey Carvis", so you don't repeat it.
                openingQuestion = nil
                send(role: "user", question)
            }

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
            guard update.role == .assistant, state != .lookingAtPart else { return }
            state = update.status == .started ? .speaking : .listening

        case .toolCalls(let calls):
            for call in calls.toolCallList {
                guard let request = ToolRequest(call), request.name == "look_at_part" else { continue }
                lookAtPart(question: request.question ?? lines.last(where: { !$0.fromCarvis })?.text ?? "")
            }

        case .error(let error):
            print("[Vapi] error: \(error)")
            state = .failed(error.localizedDescription)

        default:
            break
        }
    }

    private func lookAtPart(question: String) {
        guard let lookAtPart else { return }
        state = .lookingAtPart
        Task {
            let result = await lookAtPart(question)
            send(role: "system", """
                look_at_part result from the Carvis service-manual lookup: \(result)
                Tell the mechanic this result exactly. Do not add, change, or estimate any number.
                """)
            if state == .lookingAtPart { state = .listening }
        }
    }

    private func send(role: String, _ content: String) {
        guard let vapi else { return }
        Task {
            do {
                try await vapi.send(message: VapiMessage(type: "add-message", role: role, content: content))
            } catch {
                print("[Vapi] send failed: \(error)")
            }
        }
    }

    private func finish(failure: String?) {
        events?.cancel()
        events = nil
        vapi = nil
        partial = ""
        state = failure.map { .failed($0) } ?? .idle
        onEnded?()
    }
}

/// One tool call from Vapi: `{ "function": { "name": ..., "arguments": {...} or "{...}" } }`.
private struct ToolRequest {
    let name: String
    let question: String?

    init?(_ value: JSONValue) {
        guard case .object(let call) = value,
              case .object(let function)? = call["function"],
              case .string(let name)? = function["name"]
        else { return nil }
        self.name = name

        var arguments: [String: JSONValue] = [:]
        switch function["arguments"] {
        case .object(let object)?:
            arguments = object
        case .string(let text)?:
            if let data = text.data(using: .utf8),
               let decoded = try? JSONDecoder().decode([String: JSONValue].self, from: data) {
                arguments = decoded
            }
        default:
            break
        }
        if case .string(let question)? = arguments["question"] {
            self.question = question
        } else {
            self.question = nil
        }
    }
}
