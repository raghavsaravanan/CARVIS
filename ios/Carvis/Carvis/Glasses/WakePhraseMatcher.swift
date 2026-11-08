import Foundation

/// Transcript matching only. This is not an always-on acoustic wake-word engine.
struct WakePhraseMatcher {
    private var lastDetection: TimeInterval?
    let cooldown: TimeInterval = 2

    mutating func reset() { lastDetection = nil }

    mutating func consume(_ text: String, isFinal: Bool, isListening: Bool,
                          now: TimeInterval) -> String? {
        guard isListening, isFinal else { return nil }
        let words = text.lowercased().split { !$0.isLetter && !$0.isNumber }
        guard words.count >= 2, words[1] == "carvis",
              words[0] == "hey" || words[0] == "hi" else { return nil }
        if let lastDetection, now - lastDetection < cooldown { return nil }
        lastDetection = now
        return words[0] == "hey" ? "Hey Carvis" : "Hi Carvis"
    }
}
