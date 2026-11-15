import AVFoundation
import Combine

/// The optional Meta conversation route. Its policy requires the same glasses mic and output;
/// a phone or unrelated Bluetooth route never makes a call live.
@MainActor
final class MetaGlassesAudioRoute: VoiceAudioRoute {
    private let glasses: GlassesController
    private let provider: VapiAgent
    private var observation: AnyCancellable?
    private var interruptionObservation: AnyCancellable?
    private var interrupted = false

    init(glasses: GlassesController, provider: VapiAgent) {
        self.glasses = glasses
        self.provider = provider
    }

    func acquire() async throws {
        guard glasses.isConnected else {
            throw ConversationSetupError.message("Connect your glasses.")
        }
        let glassesName = glasses.activeDeviceName
        try await AudioSessionQueue.run {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.allowBluetoothHFP])
            try session.setActive(true)
            let inputs = session.availableInputs ?? []
            guard let mic = inputs.first(where: {
                $0.portType == .bluetoothHFP && GlassesRouteCheck.matches($0.portName, glassesName)
            }) else {
                throw ConversationSetupError.message("Your glasses' microphone isn't connected to this iPhone. Check Bluetooth in Settings.")
            }
            try session.setPreferredInput(mic)
        }
    }

    func status() -> VoiceRouteStatus {
        if interrupted { return .unavailable("Audio was interrupted.") }
        if !glasses.isConnected { return .unavailable("Connect your glasses.") }
        let ports = AudioRoute.currentPorts()
        let result = GlassesRouteCheck.evaluate(inputs: ports.inputs, outputs: ports.outputs,
                                                glassesName: glasses.activeDeviceName)
        switch result {
        case .ready: return .ready
        case .noMicrophone: return .unavailable("Your glasses' microphone isn't connected.")
        case .noSpeaker: return .unavailable("Your glasses' speakers aren't connected.")
        case .otherDevice(let name): return .unavailable("Audio is going to \(name), not your glasses.")
        }
    }

    func prefer() async { await provider.preferBluetooth() }

    func observeChanges(_ action: @escaping @MainActor () -> Void) {
        observation = NotificationCenter.default.publisher(for: AVAudioSession.routeChangeNotification)
            .receive(on: DispatchQueue.main)
            .sink { _ in Task { @MainActor in action() } }
        interruptionObservation = NotificationCenter.default.publisher(for: AVAudioSession.interruptionNotification)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] note in
                Task { @MainActor [weak self] in
                    guard let self, let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                          let kind = AVAudioSession.InterruptionType(rawValue: raw) else { return }
                    self.interrupted = kind == .began
                    action()
                }
            }
    }

    func release() async {
        observation = nil
        interruptionObservation = nil
        interrupted = false
        _ = try? await AudioSessionQueue.run {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
        AudioOwnership.conversationOwnsAudio = false
        SystemSpeechOutput.usePlaybackSession()
    }
}
