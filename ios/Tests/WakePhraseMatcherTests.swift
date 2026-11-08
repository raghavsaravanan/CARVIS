import Foundation

/// Run with the CLI command in ios/WAKE_TEST.md; no Meta device is simulated here.
@main
struct WakePhraseMatcherTests {
    static func main() {
        var detector = WakePhraseMatcher()
        var checks = 0
        func check(_ value: Bool, _ description: String) {
            precondition(value, description)
            checks += 1
        }
        check(detector.consume("Hi Carvis", isFinal: true, isListening: false, now: 0) == nil, "disarmed")
        check(detector.consume("Hi Carvis", isFinal: false, isListening: true, now: 0) == nil, "partial cannot emit")
        check(detector.consume("Hi, Carvis!", isFinal: true, isListening: true, now: 0) == "Hi Carvis", "punctuation")
        check(detector.consume("Hi, Carvis!", isFinal: true, isListening: true, now: 0.1) == nil, "replayed final")
        check(detector.consume("Hey Carvis", isFinal: true, isListening: true, now: 1.9) == nil, "shared cooldown")
        check(detector.consume("HEY CARVIS, are you there?", isFinal: true, isListening: true, now: 2) == "Hey Carvis", "prefix and case")
        for text in ["Carvis", "Hi", "Hey car", "Hi Carvison", "I said hi Carvis", "Say Hey Carvis", "", "High Carvis"] {
            check(detector.consume(text, isFinal: true, isListening: true, now: 5) == nil, "false positive: \(text)")
        }
        check(detector.consume("Hi Carvis", isFinal: true, isListening: false, now: 5) == nil, "paused")
        check(detector.consume("Hey—Carvis", isFinal: true, isListening: true, now: 5) == "Hey Carvis", "unicode punctuation")
        detector.reset()
        check(detector.consume("Hi Carvis", isFinal: true, isListening: true, now: 5.1) == "Hi Carvis", "new arm/session resets gate")
        // Common speech-recognition misses of "Carvis"
        check(detector.consume("Hey Jarvis what's the torque", isFinal: true, isListening: true, now: 10) == "Hey Carvis", "Jarvis")
        check(detector.consume("Hey car vis, look at this", isFinal: true, isListening: true, now: 20) == "Hey Carvis", "car vis")
        check(detector.consume("OK Carver what is this", isFinal: true, isListening: true, now: 30) == "Hey Carvis", "OK Carver")
        check(detector.consume("Hey car wash", isFinal: true, isListening: true, now: 40) == nil, "car wash")
        check(detector.consume("I said hey Jarvis", isFinal: true, isListening: true, now: 50) == nil, "mid-sentence variant")
        print("\(checks) wake phrase checks passed")
    }
}
