import Foundation

/// Transcript matching only. This is not an always-on acoustic wake-word engine.
/// "Carvis" isn't a dictionary word, so speech recognition often writes a near miss
/// ("Jarvis", "Carver", "car vis"); those count too. The phrase must start the sentence,
/// so "I said hi Carvis" in conversation doesn't trigger it.
struct WakePhraseMatcher {
    private var lastDetection: TimeInterval?
    let cooldown: TimeInterval = 2

    static let greetings: Set<Substring> = ["hey", "hi", "hay", "ok", "okay"]
    static let names: Set<Substring> = ["carvis", "jarvis", "carver", "carvas", "carves", "carvus", "cervis", "garvis", "kervis", "carbis"]

    mutating func reset() { lastDetection = nil }

    mutating func consume(_ text: String, isFinal: Bool, isListening: Bool,
                          now: TimeInterval) -> String? {
        guard isListening, isFinal else { return nil }
        let words = text.lowercased().split { !$0.isLetter && !$0.isNumber }
        guard let greeting = Self.wakeGreeting(in: words) else { return nil }
        if let lastDetection, now - lastDetection < cooldown { return nil }
        lastDetection = now
        return greeting == "hi" ? "Hi Carvis" : "Hey Carvis"
    }

    /// The greeting word if `words` starts with a wake phrase, or nil.
    static func wakeGreeting(in words: [Substring]) -> Substring? {
        guard words.count >= 2, greetings.contains(words[0]) else { return nil }
        if names.contains(words[1]) { return words[0] }
        // "car vis" split into two words
        if words[1] == "car", words.count >= 3, words[2] == "vis" { return words[0] }
        return nil
    }
}
