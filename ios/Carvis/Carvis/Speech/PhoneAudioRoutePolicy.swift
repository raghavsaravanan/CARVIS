/// Pure route rules for a tapped iPhone call. Vapi/Daily selects the device; the app checks
/// the resulting iOS route before it unmutes the microphone.
enum PhoneAudioInput: Equatable {
    case builtIn, wired, bluetooth, usb, unsupported
}

enum PhoneAudioOutput: Equatable {
    case speaker, receiver, wired, bluetooth, usb, unsupported
}

struct PhoneAudioSnapshot: Equatable {
    let input: PhoneAudioInput?
    let output: PhoneAudioOutput?
}

enum PhoneAudioPreference: Equatable {
    case speakerphone, wired, bluetooth
}

enum PhoneAudioRoutePolicy {
    static func status(permissionGranted: Bool, interrupted: Bool,
                       route: PhoneAudioSnapshot) -> VoiceRouteStatus {
        guard permissionGranted else { return .unavailable("Allow microphone access for Carvis in Settings.") }
        if interrupted { return .unavailable("Audio was interrupted.") }
        guard let input = route.input, let output = route.output else {
            return .unavailable("Waiting for an audio input and output.")
        }
        guard input != .unsupported else { return .unavailable("This microphone route is unavailable for calls.") }
        switch output {
        case .speaker, .wired, .bluetooth, .usb: return .ready
        case .receiver: return .unavailable("Switching the call to the speaker.")
        case .unsupported: return .unavailable("This audio output is unavailable for calls.")
        }
    }

    static func preference(for output: PhoneAudioOutput?) -> PhoneAudioPreference {
        switch output {
        case .bluetooth: .bluetooth
        case .wired, .usb: .wired
        default: .speakerphone
        }
    }
}
