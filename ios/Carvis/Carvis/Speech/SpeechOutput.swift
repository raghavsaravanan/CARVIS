import AVFoundation

/// Anything that can read text out loud.
protocol SpeechOutput {
    func speak(_ text: String)
    /// Speaks and returns once it has finished (or was cut off).
    func speakAndWait(_ text: String) async
    func stop()
}

/// Reads text aloud with Apple's built-in voice (AVSpeechSynthesizer).
/// It plays wherever the audio is routed: the glasses when they're the
/// Bluetooth output, otherwise the phone speaker.
final class SystemSpeechOutput: NSObject, SpeechOutput, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private var finished: CheckedContinuation<Void, Never>?

    override init() {
        super.init()
        synthesizer.delegate = self
        Self.usePlaybackSession()
    }

    /// "playback" lets Carvis speak even when the silent switch is on.
    /// Used whenever Carvis isn't listening for "Hey Carvis".
    static func usePlaybackSession() {
        AudioSessionQueue.runDetached {
            try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        }
    }

    func speak(_ text: String) {
        // Cut off anything still playing so the newest thing is what you hear.
        synthesizer.stopSpeaking(at: .immediate)
        resumeWaiter()
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.speak(utterance)
    }

    func speakAndWait(_ text: String) async {
        speak(text)
        await withCheckedContinuation { continuation in
            finished = continuation
        }
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
        resumeWaiter()
    }

    private func resumeWaiter() {
        finished?.resume()
        finished = nil
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.resumeWaiter() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.resumeWaiter() }
    }
}

/// Where spoken answers are playing right now, so the screen can say so honestly.
enum AudioRoute {
    /// The name of the Bluetooth device speech is going to (for example your glasses),
    /// or nil when it's the phone's own speaker.
    static var bluetoothOutputName: String? {
        #if os(iOS)
        let bluetooth: Set<AVAudioSession.Port> = [.bluetoothA2DP, .bluetoothHFP, .bluetoothLE]
        return AVAudioSession.sharedInstance().currentRoute.outputs
            .first { bluetooth.contains($0.portType) }?
            .portName
        #else
        return nil
        #endif
    }
}

/// Changes to the phone's audio setup can take a moment, and Apple warns against making
/// them on the main thread (it can freeze the screen). Every change goes through this one
/// background queue, in order, so a quick off-then-on can't run out of order.
enum AudioSessionQueue {
    private static let queue = DispatchQueue(label: "carvis.audio-session", qos: .userInitiated)

    static func run<T: Sendable>(_ work: @escaping @Sendable () throws -> T) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            queue.async { continuation.resume(with: Result { try work() }) }
        }
    }

    static func runDetached(_ work: @escaping @Sendable () -> Void) {
        queue.async(execute: work)
    }
}
