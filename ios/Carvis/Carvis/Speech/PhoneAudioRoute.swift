import AVFoundation
import Combine

/// Audio for an explicitly started phone call. Configure the category before Vapi joins, then
/// let Vapi/Daily activate the session and choose its device. Never force a preferred input
/// while Vapi owns the call.
@MainActor
final class PhoneAudioRoute: VoiceAudioRoute {
    private let provider: VapiAgent
    private var routeObservation: AnyCancellable?
    private var interruptionObservation: AnyCancellable?
    private var permissionGranted = false
    private var interrupted = false

    init(provider: VapiAgent) { self.provider = provider }

    func acquire() async throws {
        guard await AVAudioApplication.requestRecordPermission() else {
            throw ConversationSetupError.message("Allow microphone access for Carvis in Settings.")
        }
        permissionGranted = true
        // Daily activates/deactivates the session for its call. This only sets the desired
        // category before joining, with speaker as the no-accessory default.
        try await AudioSessionQueue.run {
            try AVAudioSession.sharedInstance().setCategory(
                .playAndRecord, mode: .voiceChat,
                options: [.defaultToSpeaker, .allowBluetoothHFP, .allowBluetoothA2DP]
            )
        }
    }

    func status() -> VoiceRouteStatus {
        let result = PhoneAudioRoutePolicy.status(permissionGranted: permissionGranted,
                                                   interrupted: interrupted, route: snapshot())
        switch result {
        case .ready: return .ready
        case .unavailable(let reason): return .unavailable(reason)
        }
    }

    func prefer() async {
        switch PhoneAudioRoutePolicy.preference(for: snapshot().output) {
        case .speakerphone: await provider.preferSpeakerphone()
        case .wired: await provider.preferWired()
        case .bluetooth: await provider.preferBluetooth()
        }
    }

    func observeChanges(_ action: @escaping @MainActor () -> Void) {
        routeObservation = NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
            .receive(on: DispatchQueue.main)
            .sink { _ in Task { @MainActor in action() } }
        interruptionObservation = NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] note in
                Task { @MainActor [weak self] in
                    guard let self, let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                          let kind = AVAudioSession.InterruptionType(rawValue: raw) else { return }
                    if kind == .began {
                        self.interrupted = true
                        action()
                    } else {
                        await self.prefer()
                        self.interrupted = false
                        action()
                    }
                }
            }
    }

    func release() async {
        routeObservation = nil
        interruptionObservation = nil
        interrupted = false
        permissionGranted = false
        _ = try? await AudioSessionQueue.run {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        AudioOwnership.conversationOwnsAudio = false
        SystemSpeechOutput.usePlaybackSession()
    }

    private func snapshot() -> PhoneAudioSnapshot {
        let route = AVAudioSession.sharedInstance().currentRoute
        return PhoneAudioSnapshot(input: route.inputs.first.map(input),
                                  output: route.outputs.first.map(output))
    }

    private func input(_ port: AVAudioSessionPortDescription) -> PhoneAudioInput {
        switch port.portType {
        case .builtInMic: .builtIn
        case .headsetMic, .lineIn: .wired
        case .bluetoothHFP: .bluetooth
        case .usbAudio: .usb
        default: .unsupported
        }
    }

    private func output(_ port: AVAudioSessionPortDescription) -> PhoneAudioOutput {
        switch port.portType {
        case .builtInSpeaker: .speaker
        case .builtInReceiver: .receiver
        case .headphones, .lineOut: .wired
        case .bluetoothHFP, .bluetoothA2DP, .bluetoothLE: .bluetooth
        case .usbAudio: .usb
        default: .unsupported
        }
    }
}
