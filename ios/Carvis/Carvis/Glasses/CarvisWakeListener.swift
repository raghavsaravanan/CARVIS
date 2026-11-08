import Combine
import Foundation
import MWDATCore
import MWDATSpeech
import Observation
import OSLog
import UIKit

/// Foreground, armed listening using glasses-side ASR. Never records the phone mic.
@Observable
@MainActor
final class CarvisWakeListener {
    enum State: String {
        case disarmed, requestingPermission, waitingForSession, starting, listening, stopping, paused, failed
    }

    struct WakeEvent: Identifiable, Sendable {
        let id = UUID()
        let phrase: String
        let detectedAt: Date
        let confidence: Float
    }

    private(set) var isArmed = false
    private(set) var hasMicrophonePermission = false
    private(set) var state: State = .disarmed
    private(set) var message = "Disarmed"
    private(set) var lastTranscript = ""
    private(set) var transcriptIsFinal = false
    private(set) var locale: String?
    private(set) var lastWake: WakeEvent?
    private(set) var detectionCount = 0
    private(set) var errorMessage: String?

    /// Subscribe on the main actor. No Vapi/network side effect is attached.
    var wakeDetected: AnyPublisher<WakeEvent, Never> { events.eraseToAnyPublisher() }

    @ObservationIgnored private let events = PassthroughSubject<WakeEvent, Never>()
    @ObservationIgnored private let logger = Logger(subsystem: "Carvis", category: "WakeListener")
    @ObservationIgnored private var matcher = WakePhraseMatcher()
    @ObservationIgnored private var speech: MWDATSpeech.Speech?
    @ObservationIgnored private var attachedSession: DeviceSession?
    @ObservationIgnored private var tokens: [any AnyListenerToken] = []
    @ObservationIgnored private var cleanup: Task<Void, Never>?
    @ObservationIgnored private var armID = UUID()
    @ObservationIgnored private var attachmentID = UUID()

    /// Called only from the explicit Arm/Retry action, before any permission hop.
    func arm(using wearables: any WearablesInterface) async -> Bool {
        disarm()
        let request = UUID()
        armID = request
        isArmed = true
        state = .requestingPermission
        message = "Checking glasses microphone permission. Approve in Meta AI if asked."
        do {
            var permission = try await wearables.checkPermissionStatus(.microphone)
            guard armID == request, isArmed else { return false }
            if permission != .granted {
                permission = try await wearables.requestPermission(.microphone)
            }
            guard armID == request, isArmed else { return false }
            guard permission == .granted else {
                isArmed = false
                fail("Glasses microphone permission was not granted. Allow it in Meta AI, then tap Arm again.")
                return false
            }
            hasMicrophonePermission = true
            state = .waitingForSession
            message = "Waiting for a connected glasses session"
            return true
        } catch {
            guard armID == request, isArmed else { return false }
            isArmed = false
            fail("Glasses microphone permission: \(error.localizedDescription)")
            return false
        }
    }

    /// Attach only to the controller's started session; never create a competing session.
    func attach(to session: DeviceSession, using wearables: any WearablesInterface) async {
        guard isArmed, hasMicrophonePermission, state != .failed,
              session.state == .started, UIApplication.shared.applicationState == .active else { return }
        if attachedSession === session {
            if let speech {
                speechStateChanged(speech.state)
            }
            return
        }
        detach()
        attachedSession = session
        let attachment = UUID()
        attachmentID = attachment
        let pendingCleanup = cleanup
        await pendingCleanup?.value
        guard isCurrent(attachment, session) else { return }
        do {
            // Permission can have been revoked while disconnected/backgrounded.
            guard try await wearables.checkPermissionStatus(.microphone) == .granted else {
                guard isCurrent(attachment, session) else { return }
                hasMicrophonePermission = false
                fail("Glasses microphone permission changed. Disarm, then Arm to request it again.")
                return
            }
            guard isCurrent(attachment, session) else { return }
            guard let capability = try session.addSpeech() else {
                fail("Speech is unavailable for these glasses/app. Enable the experimental Speech capability in Wearables Developer Center and check firmware/account support.")
                return
            }
            speech = capability
            matcher.reset()
            state = .starting
            message = "Starting speech on the glasses microphone"
            // All four subscriptions are retained before start(), per SDK 1.0.1.
            tokens.append(capability.statePublisher.listen { [weak self] value in
                Task { @MainActor in
                    guard let self, self.isCurrent(attachment, session) else { return }
                    self.speechStateChanged(value)
                }
            })
            tokens.append(capability.localePublisher.listen { [weak self] value in
                Task { @MainActor in
                    guard let self, self.isCurrent(attachment, session) else { return }
                    self.locale = value
                }
            })
            tokens.append(capability.transcriptionPublisher.listen { [weak self] result in
                Task { @MainActor in
                    guard let self, self.isCurrent(attachment, session), self.state == .listening else { return }
                    self.consume(result)
                }
            })
            tokens.append(capability.errorPublisher.listen { [weak self] error in
                Task { @MainActor in
                    guard let self, self.isCurrent(attachment, session) else { return }
                    self.fail("Glasses speech: \(error.localizedDescription). Tap Retry listening; no phone microphone fallback is used.")
                }
            })
            locale = capability.locale
            capability.start()
        } catch {
            guard isCurrent(attachment, session) else { return }
            fail("Could not attach glasses speech: \(error.localizedDescription)")
        }
    }

    func disarm() {
        armID = UUID() // Late permission callbacks cannot re-arm the listener.
        isArmed = false
        hasMicrophonePermission = false
        detach()
        matcher.reset()
        state = .disarmed
        message = "Disarmed"
        errorMessage = nil
        lastTranscript = ""
        locale = nil
    }

    func suspend(_ reason: String) {
        detach()
        if isArmed {
            state = .paused
            message = reason
        }
    }

    func sessionEnded() {
        detach()
        if isArmed, state != .failed {
            state = UIApplication.shared.applicationState == .active ? .waitingForSession : .paused
            message = "Waiting for foreground and a connected glasses session"
        }
    }

    func sessionPaused() {
        if isArmed, state != .failed {
            // Keep the capability attached across an SDK pause. Removing it
            // while the DeviceSession is paused is not a supported assumption.
            state = .paused
            message = "Glasses session paused; waiting for the device to resume"
            matcher.reset()
        }
    }

    private func isCurrent(_ id: UUID, _ session: DeviceSession) -> Bool {
        isArmed && attachmentID == id && attachedSession === session
            && session.state == .started && UIApplication.shared.applicationState == .active
    }

    private func speechStateChanged(_ value: SpeechState) {
        guard speech?.state == value else { return } // Ignore queued obsolete snapshots.
        switch value {
        case .starting:
            state = .starting
        case .started:
            state = .listening
            message = "Listening through the glasses microphone"
            errorMessage = nil
            logger.info("Glasses speech listening; foreground only")
        case .stopping:
            if state == .listening { message = "Glasses speech stopping"; state = .stopping }
        case .stopped:
            // Ignore an initial stopped snapshot before start() completes.
            if state == .paused {
                state = .starting
                message = "Restarting speech after the glasses session resumed"
                speech?.start()
            } else if state == .stopping || state == .listening {
                fail("Glasses speech stopped. Tap Retry listening.")
            }
        @unknown default:
            fail("Unknown glasses speech state. Tap Retry listening.")
        }
    }

    private func consume(_ result: TranscriptionResult) {
        lastTranscript = String(result.text.prefix(500)) // Memory/UI only; never logged or saved.
        transcriptIsFinal = result.isFinal
        // -1 means confidence unavailable in this SDK. Do not discard it.
        guard let phrase = matcher.consume(result.text, isFinal: result.isFinal,
            isListening: isArmed && state == .listening, now: ProcessInfo.processInfo.systemUptime) else { return }
        let event = WakeEvent(phrase: phrase, detectedAt: Date(), confidence: result.confidence)
        lastWake = event
        detectionCount += 1
        logger.notice("wakeDetected from glasses speech; count=\(self.detectionCount)")
        events.send(event)
    }

    private func fail(_ text: String) {
        detach()
        state = .failed
        errorMessage = text
        message = text
        logger.error("\(text, privacy: .public)")
    }

    private func detach() {
        attachmentID = UUID() // Reject already-enqueued callbacks immediately.
        let oldTokens = tokens
        let oldSpeech = speech
        let oldSession = attachedSession
        let previousCleanup = cleanup
        tokens = []
        speech = nil
        attachedSession = nil
        guard !oldTokens.isEmpty || oldSpeech != nil else { return }
        // SDK cancellation is async. Serialize detach/reattach and cancel listeners
        // before stop/remove so callbacks from an old capability cannot wake Carvis.
        cleanup = Task { @MainActor in
            await previousCleanup?.value
            for token in oldTokens { await token.cancel() }
            oldSpeech?.stop()
            if let oldSession, oldSession.state == .started {
                try? oldSession.removeSpeech()
            }
        }
    }
}
