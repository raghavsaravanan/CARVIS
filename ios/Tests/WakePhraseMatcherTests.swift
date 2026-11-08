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
        print("\(checks) wake phrase checks passed")
    }
}
