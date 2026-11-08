import Foundation

/// Run: swiftc -parse-as-library ios/Tests/ConversationMachineTests.swift \
///          ios/Carvis/Carvis/Assistant/ConversationMachine.swift -o /tmp/m && /tmp/m
/// No audio or Meta device is simulated. These are the rules the coordinator follows.
@main
struct ConversationMachineTests {
    static var checks = 0

    static func check(_ value: Bool, _ description: String, line: Int = #line) {
        precondition(value, "line \(line): \(description)")
        checks += 1
    }

    static func armed() -> ConversationMachine {
        var m = ConversationMachine()
        _ = m.handle(.activate)
        _ = m.handle(.wakeReady)
        return m
    }

    /// Runs a wake through to a verified call and returns every effect after the wake.
    static func inCall(question: String?) -> (ConversationMachine, [ConversationEffect]) {
        var m = armed()
        var effects = m.handle(.wake(question: question))
        effects += m.handle(.wakeReleased)
        effects += m.handle(.callConnected)
        effects += m.handle(.routeVerified)
        return (m, effects)
    }

    static func deliveries(_ effects: [ConversationEffect]) -> [String] {
        effects.compactMap { if case .deliverQuestion(let q) = $0 { return q } else { return nil } }
    }

    static func main() {
        var m = ConversationMachine()
        check(m.handle(.activate) == [.startWake], "activating arms the wake word")
        check(m.phase == .arming, "arming")
        check(m.handle(.wake(question: "x")) == [], "no wake before it's listening")
        _ = m.handle(.wakeReady)
        check(m.phase == .listening, "listening")

        // Audio ownership order
        var effects = m.handle(.wake(question: nil))
        check(effects == [.releaseWake], "wake releases the listeners first and starts nothing else")
        check(m.handle(.wake(question: "again")) == [], "a second wake is ignored")
        effects = m.handle(.wakeReleased)
        check(effects == [.startCall(openingQuestion: nil)], "the call starts only after release")
        effects = m.handle(.callConnected)
        check(effects == [.setMicMuted(true), .verifyRoute], "mic stays muted until the route is verified")
        effects = m.handle(.routeVerified)
        check(effects == [.setMicMuted(false)], "a bare wake delivers nothing")
        check(m.phase == .inCall, "in call")

        // Wake plus question
        var (q, all) = inCall(question: "what is the ride height tolerance")
        check(deliveries(all) == ["what is the ride height tolerance"], "question delivered")
        check(q.handle(.routeVerified) == [], "verifying again delivers nothing")
        _ = q.handle(.routeLost("gone"))
        all = q.handle(.routeVerified)
        check(deliveries(all).isEmpty, "recovering the route doesn't redeliver")
        check(all == [.setMicMuted(false)], "recovery unmutes")

        // A question survives a slow route check
        var slow = armed()
        _ = slow.handle(.wake(question: "torque"))
        _ = slow.handle(.wakeReleased)
        _ = slow.handle(.callConnected)
        _ = slow.handle(.routeLost("not yet"))
        check(deliveries(slow.handle(.routeVerified)) == ["torque"], "a slow route check still delivers the question")
        _ = slow.handle(.routeLost("again"))
        check(deliveries(slow.handle(.routeVerified)).isEmpty, "and only once")

        var quick = armed()
        _ = quick.handle(.wake(question: "torque"))
        _ = quick.handle(.wakeReleased)
        check(quick.handle(.routeVerified) == [], "no delivery before connecting")
        _ = quick.handle(.callConnected)
        check(deliveries(quick.handle(.routeVerified)) == ["torque"], "delivered once connected and verified")

        // Empty question is a bare wake
        check(deliveries(inCall(question: "").1).isEmpty, "empty text delivers nothing")

        // Route loss
        var r = inCall(question: nil).0
        check(r.handle(.routeLost("gone")) == [.setMicMuted(true), .verifyRoute], "route loss mutes and rechecks")
        check(r.phase == .routeLost("gone"), "paused")
        check(r.handle(.wake(question: "x")) == [], "no wake while paused")
        _ = r.handle(.routeLost("still gone"))
        check(r.phase == .routeLost("still gone"), "reason updates while paused")

        // Re-arm only after complete shutdown
        var e = inCall(question: nil).0
        check(e.handle(.userEnded) == [.endCall], "ending")
        check(e.handle(.callEnded(error: nil)) == [.shutdownCall], "shut down when the call is over")
        check(e.phase == .shuttingDown, "shutting down")
        check(e.handle(.wake(question: "x")) == [], "no wake during shutdown")
        check(e.handle(.shutdownComplete) == [.startWake], "re-arm after shutdown")
        check(e.phase == .arming, "arming again")

        // Errors shut down the same way
        var f = inCall(question: "lost").0
        check(f.handle(.callEnded(error: "network")) == [.shutdownCall], "errors shut down")
        check(f.lastError == "network", "error kept")
        check(f.handle(.shutdownComplete) == [.startWake], "re-arm after an error")
        check(f.handle(.callEnded(error: "late")) == [], "late events do nothing")

        var s = armed()
        _ = s.handle(.wake(question: "keep"))
        _ = s.handle(.wakeReleased)
        check(s.handle(.callStartFailed("no key")) == [.shutdownCall], "start failure shuts down")
        check(s.handle(.shutdownComplete) == [.startWake], "re-arm after a failed start")
        _ = s.handle(.wakeReady)
        _ = s.handle(.wake(question: nil))
        _ = s.handle(.wakeReleased)
        _ = s.handle(.callConnected)
        check(deliveries(s.handle(.routeVerified)).isEmpty, "a failed call's question is not delivered later")

        // Leaving while on a call
        var d = inCall(question: nil).0
        check(d.handle(.deactivate) == [.endCall], "leaving ends the call")
        check(d.handle(.callEnded(error: nil)) == [.shutdownCall], "then shuts down")
        check(d.handle(.shutdownComplete) == [], "and doesn't re-arm when inactive")
        check(d.phase == .off, "off")

        // Muting
        var u = armed()
        check(u.handle(.mute) == [.stopWake], "mute stops listening")
        check(u.phase == .muted, "muted")
        check(u.handle(.wake(question: "x")) == [], "no wake while muted")
        check(u.handle(.unmute) == [.startWake], "unmute re-arms")
        var v = inCall(question: nil).0
        check(v.handle(.mute) == [], "mute doesn't cut off a conversation")
        check(v.phase == .inCall, "still in call")
        _ = v.handle(.callEnded(error: nil))
        check(v.handle(.shutdownComplete) == [], "stays quiet after the call when muted")
        check(v.phase == .muted, "muted afterward")

        // Waiting
        var w = ConversationMachine()
        _ = w.handle(.activate)
        _ = w.handle(.wakeUnavailable("connect glasses"))
        check(w.phase == .waiting("connect glasses"), "waiting with a reason")
        check(w.handle(.wake(question: "x")) == [], "no wake while waiting")
        _ = w.handle(.wakeReady)
        check(w.phase == .listening, "recovers to listening")

        // A new job starting while the last call is still coming down
        var comingDown = armed()
        _ = comingDown.handle(.wake(question: nil))
        _ = comingDown.handle(.wakeReleased)
        _ = comingDown.handle(.callConnected)
        _ = comingDown.handle(.routeVerified)
        _ = comingDown.handle(.deactivate)
        check(comingDown.phase == .endingCall, "leaving the job ends the call")
        check(comingDown.handle(.activate) == [], "no listening while the call is ending")
        check(comingDown.phase == .endingCall, "still ending")
        check(comingDown.handle(.callEnded(error: nil)) == [.shutdownCall], "call over, shut down")
        check(comingDown.handle(.activate) == [], "already active")
        check(comingDown.handle(.shutdownComplete) == [.startWake], "listens only after complete shutdown")
        var endedEarly = armed()
        _ = endedEarly.handle(.wake(question: nil))
        _ = endedEarly.handle(.wakeReleased)
        _ = endedEarly.handle(.userEnded)
        check(endedEarly.phase == .endingCall, "ended while still connecting")
        check(endedEarly.handle(.callEnded(error: nil)) == [.shutdownCall], "a call that never started still shuts down")
        check(endedEarly.handle(.callConnected) == [], "a late connection can't revive it")

        // Audio route
        let mic = AudioPortInfo(name: "Ray-Ban Meta", isBluetoothHFP: true, isBluetoothOutput: false)
        let speaker = AudioPortInfo(name: "Ray-Ban Meta", isBluetoothHFP: false, isBluetoothOutput: true)
        let phoneMic = AudioPortInfo(name: "iPhone Microphone", isBluetoothHFP: false, isBluetoothOutput: false)
        let phoneSpeaker = AudioPortInfo(name: "Speaker", isBluetoothHFP: false, isBluetoothOutput: false)
        let airpodsIn = AudioPortInfo(name: "Gabriel's AirPods", isBluetoothHFP: true, isBluetoothOutput: false)
        let airpodsOut = AudioPortInfo(name: "Gabriel's AirPods", isBluetoothHFP: false, isBluetoothOutput: true)
        check(GlassesRouteCheck.evaluate(inputs: [mic], outputs: [speaker], glassesName: nil) == .ready(name: "Ray-Ban Meta"), "glasses both ways")
        check(GlassesRouteCheck.evaluate(inputs: [phoneMic], outputs: [speaker], glassesName: nil) == .noMicrophone(current: "iPhone Microphone"), "phone mic never counts")
        check(GlassesRouteCheck.evaluate(inputs: [mic], outputs: [phoneSpeaker], glassesName: nil) == .noSpeaker(current: "Speaker"), "phone speaker never counts")
        check(GlassesRouteCheck.evaluate(inputs: [airpodsIn], outputs: [airpodsOut], glassesName: nil) == .otherDevice(name: "Gabriel's AirPods"), "other headsets never count")
        let custom = AudioPortInfo(name: "Workshop Glasses", isBluetoothHFP: true, isBluetoothOutput: true)
        check(GlassesRouteCheck.evaluate(inputs: [custom], outputs: [custom], glassesName: "Workshop Glasses") == .ready(name: "Workshop Glasses"), "a renamed pair matches the Meta SDK name")
        check(GlassesRouteCheck.evaluate(inputs: [custom], outputs: [custom], glassesName: nil) == .otherDevice(name: "Workshop Glasses"), "unknown name isn't assumed to be the glasses")

        print("\(checks) conversation machine checks passed")
    }
}
