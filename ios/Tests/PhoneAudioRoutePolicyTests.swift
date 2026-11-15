import Foundation

// The real status type is in VoiceSessionController; this stand-in keeps route checks SDK-free.
enum VoiceRouteStatus: Equatable {
    case ready
    case unavailable(String)
}

@main
struct PhoneAudioRoutePolicyTests {
    static func main() {
        var checks = 0
        func check(_ condition: Bool, _ message: String) {
            precondition(condition, message)
            checks += 1
        }
        let phone = PhoneAudioSnapshot(input: .builtIn, output: .speaker)
        check(PhoneAudioRoutePolicy.status(permissionGranted: false, interrupted: false, route: phone)
              == .unavailable("Allow microphone access for Carvis in Settings."), "denied microphone")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false, route: phone) == .ready,
              "built-in mic and speaker")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: true, route: phone)
              == .unavailable("Audio was interrupted."), "interruption holds microphone")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false, route: phone) == .ready,
              "route recovers when interruption ends")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false,
              route: PhoneAudioSnapshot(input: .builtIn, output: .receiver)) != .ready,
              "receiver is not the promised speaker")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false,
              route: PhoneAudioSnapshot(input: .wired, output: .wired)) == .ready, "wired headset")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false,
              route: PhoneAudioSnapshot(input: .bluetooth, output: .bluetooth)) == .ready, "Bluetooth HFP")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false,
              route: PhoneAudioSnapshot(input: .builtIn, output: .bluetooth)) == .ready,
              "Bluetooth headphones with phone microphone")
        check(PhoneAudioRoutePolicy.status(permissionGranted: true, interrupted: false,
              route: PhoneAudioSnapshot(input: nil, output: .speaker)) != .ready, "missing microphone")
        check(PhoneAudioRoutePolicy.preference(for: .speaker) == .speakerphone, "speakerphone preference")
        check(PhoneAudioRoutePolicy.preference(for: .bluetooth) == .bluetooth, "Bluetooth preference")
        check(PhoneAudioRoutePolicy.preference(for: .wired) == .wired, "wired preference")
        print("\(checks) phone audio route checks passed")
    }
}
