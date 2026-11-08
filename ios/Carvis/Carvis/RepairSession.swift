import Foundation
import Observation

/// The brain of the app. It remembers which screen we're on, the job in
/// progress, and every step seen so far. It sends requests to the backend,
/// speaks each answer, and saves finished jobs to the history.
@Observable
final class RepairSession {
    /// Screens that open on top of the dashboard.
    enum Route: Hashable {
        case progress, done, ask
    }

    /// Which screens are open. Empty means the dashboard is showing.
    var path: [Route] = []
    private(set) var jobName = ""
    private(set) var current: StepResponse?

    /// Every step we've seen in this job, by step number. Used to draw the timeline.
    private(set) var seenSteps: [Int: StepResponse] = [:]

    let history: JobHistory

    private let backend: any BackendClient
    private let speech: any SpeechOutput
    private var sessionID = UUID().uuidString
    private var isSending = false

    init(backend: any BackendClient = MockBackendClient(),
         speech: any SpeechOutput = SystemSpeechOutput(),
         history: JobHistory = JobHistory()) {
        self.backend = backend
        self.speech = speech
        self.history = history
    }

    /// True while a job is started and not finished yet.
    var hasActiveJob: Bool {
        guard let current else { return false }
        return !current.done
    }

    func start(jobName: String) async {
        self.jobName = jobName
        sessionID = UUID().uuidString
        current = nil
        seenSteps = [:]
        path = [.progress]
        await send(nil)
    }

    // Later, the glasses will trigger these by voice.
    func next() async { await send("next") }
    func repeatStep() async { await send("repeat") }
    func why() async { await send("why") }

    func showAsk() {
        path.append(.ask)
    }

    func showProgress() {
        if hasActiveJob { path = [.progress] }
    }

    /// Close the finished job and go back to the dashboard.
    func finish() {
        speech.stop()
        current = nil
        seenSteps = [:]
        jobName = ""
        path = []
    }

    private func send(_ utterance: String?) async {
        guard !isSending else { return }   // ignore double taps
        isSending = true
        defer { isSending = false }

        let request = StepRequest(
            sessionID: sessionID,
            procedure: "oil_change_2022_wrx",
            stepNumber: current?.stepNumber ?? 0,
            utterance: utterance,
            frameB64: nil
        )

        do {
            let response = try await backend.send(request)
            current = response

            if response.done {
                if let summary = response.summary {
                    history.add(JobRecord(name: jobName, finishedAt: .now, summary: summary))
                }
                path = [.done]   // replaces the progress screen
            } else {
                seenSteps[response.stepNumber] = response
            }

            speech.speak(response.spokenText)
        } catch {
            // Spoken error messages come in a later phase.
            print("Carvis backend error: \(error)")
        }
    }
}
