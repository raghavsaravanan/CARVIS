import AVFoundation

/// Anything that can read text out loud.
/// Today it's the iPhone's built-in voice. Later it could be the Meta glasses' speakers.
protocol SpeechOutput {
    func speak(_ text: String)
    func stop()
}

/// Reads text aloud with Apple's built-in voice (AVSpeechSynthesizer).
final class SystemSpeechOutput: SpeechOutput {
    private let synthesizer = AVSpeechSynthesizer()

    init() {
        #if os(iOS)
        // "playback" lets Carvis speak even when the silent switch is on.
        try? AVAudioSession.sharedInstance().setCategory(.playback, mode: .spokenAudio)
        #endif
    }

    func speak(_ text: String) {
        // Cut off anything still playing so the newest step is what you hear.
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        synthesizer.speak(utterance)
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
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
