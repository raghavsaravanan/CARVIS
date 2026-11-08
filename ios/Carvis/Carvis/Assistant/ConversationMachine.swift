import Foundation

/// The rules of a hands-free conversation, with no audio, network, or SDK in it, so they can
/// be tested on their own (ios/Tests/ConversationMachineTests.swift). The coordinator tells
/// this what happened and carries out the effects it returns.
enum ConversationPhase: Equatable {
    case off
    case muted
    case arming
    /// Can't listen yet, and why.
    case waiting(String)
    case listening
    case releasingWake
    case startingCall
    /// Connected, microphone held muted until the glasses are confirmed as the route.
    case verifyingRoute
    case inCall
    /// The glasses route went away. Muted, never moved to the phone's microphone.
    case routeLost(String)
    case endingCall
    case shuttingDown
}

enum ConversationEvent: Equatable {
    case activate
    case deactivate
    case mute
    case unmute
    case wakeReady
    case wakeUnavailable(String)
    /// "Hey Carvis", with whatever was said after it.
    case wake(question: String?)
    case wakeReleased
    case callStartFailed(String)
    case callConnected
    case routeVerified
    case routeLost(String)
    case userEnded
    /// The call is over, for any reason, including an error.
    case callEnded(error: String?)
    case shutdownComplete
}

enum ConversationEffect: Equatable {
    case startWake
    case stopWake
    case releaseWake
    case startCall(openingQuestion: String?)
    case verifyRoute
    case setMicMuted(Bool)
    case deliverQuestion(String)
    case endCall
    case shutdownCall
}

struct ConversationMachine {
    private(set) var phase: ConversationPhase = .off
    private(set) var lastError: String?
    private var isActive = false
    private var isMuted = false
    /// The words said with the wake phrase. Taken exactly once, when it's delivered.
    private var pendingQuestion: String?

    var isInCallPhase: Bool {
        switch phase {
        case .startingCall, .verifyingRoute, .inCall, .routeLost, .endingCall: true
        default: false
        }
    }

    mutating func handle(_ event: ConversationEvent) -> [ConversationEffect] {
        switch event {
        case .activate:
            guard !isActive else { return [] }
            isActive = true
            // Still coming down from the last call: shutdownComplete does the re-arming.
            if phase == .endingCall || phase == .shuttingDown { return [] }
            guard !isMuted else {
                phase = .muted
                return []
            }
            phase = .arming
            return [.startWake]

        case .deactivate:
            guard isActive else { return [] }
            isActive = false
            return stop()

        case .mute:
            guard !isMuted else { return [] }
            isMuted = true
            // Muting never cuts off a conversation; it applies when listening resumes.
            if phase == .listening || phase == .arming || isWaiting {
                phase = .muted
                return [.stopWake]
            }
            return []

        case .unmute:
            guard isMuted else { return [] }
            isMuted = false
            guard isActive, phase == .muted else { return [] }
            phase = .arming
            return [.startWake]

        case .wakeReady:
            guard phase == .arming || isWaiting else { return [] }
            phase = .listening
            lastError = nil
            return []

        case .wakeUnavailable(let reason):
            guard phase == .arming || phase == .listening || isWaiting else { return [] }
            phase = .waiting(reason)
            return []

        case .wake(let question):
            // Only while listening: a second wake can never start a second call.
            guard phase == .listening else { return [] }
            pendingQuestion = question.flatMap { $0.isEmpty ? nil : $0 }
            phase = .releasingWake
            return [.releaseWake]

        case .wakeReleased:
            guard phase == .releasingWake else { return [] }
            phase = .startingCall
            return [.startCall(openingQuestion: pendingQuestion)]

        case .callStartFailed(let reason):
            guard phase == .startingCall || phase == .releasingWake else { return [] }
            lastError = reason
            pendingQuestion = nil
            phase = .shuttingDown
            return [.shutdownCall]

        case .callConnected:
            guard phase == .startingCall else { return [] }
            phase = .verifyingRoute
            return [.setMicMuted(true), .verifyRoute]

        case .routeVerified:
            switch phase {
            case .verifyingRoute, .routeLost:
                phase = .inCall
                var effects: [ConversationEffect] = [.setMicMuted(false)]
                // Delivered the first time the route is good, however long that took.
                if let question = pendingQuestion {
                    pendingQuestion = nil
                    effects.append(.deliverQuestion(question))
                }
                return effects
            default:
                return []
            }

        case .routeLost(let reason):
            guard phase == .inCall || phase == .verifyingRoute else {
                if case .routeLost = phase {
                    phase = .routeLost(reason)
                }
                return []
            }
            phase = .routeLost(reason)
            return [.setMicMuted(true), .verifyRoute]

        case .userEnded:
            guard isInCallPhase, phase != .endingCall else { return [] }
            phase = .endingCall
            return [.endCall]

        case .callEnded(let error):
            guard isInCallPhase else { return [] }
            lastError = error
            pendingQuestion = nil
            phase = .shuttingDown
            return [.shutdownCall]

        case .shutdownComplete:
            guard phase == .shuttingDown else { return [] }
            guard isActive else {
                phase = .off
                return []
            }
            guard !isMuted else {
                phase = .muted
                return []
            }
            // Listening resumes only here, after the call has completely shut down.
            phase = .arming
            return [.startWake]
        }
    }

    private var isWaiting: Bool {
        if case .waiting = phase { return true }
        return false
    }

    private mutating func stop() -> [ConversationEffect] {
        pendingQuestion = nil
        switch phase {
        case .startingCall, .verifyingRoute, .inCall, .routeLost:
            phase = .endingCall
            return [.endCall]
        case .endingCall, .shuttingDown:
            return []   // already on the way down; shutdownComplete finishes it
        case .releasingWake:
            phase = .shuttingDown
            return [.shutdownCall]
        default:
            phase = .off
            return [.stopWake]
        }
    }
}

/// One audio port as iOS reports it.
struct AudioPortInfo: Equatable {
    let name: String
    let isBluetoothHFP: Bool
    let isBluetoothOutput: Bool
}

enum GlassesRouteStatus: Equatable {
    case ready(name: String)
    case noMicrophone(current: String?)
    case noSpeaker(current: String?)
    case otherDevice(name: String)
}

/// Decides whether audio is really going through the glasses. Both directions must be the
/// glasses over Bluetooth. A phone microphone or another headset never counts.
enum GlassesRouteCheck {
    static func evaluate(inputs: [AudioPortInfo], outputs: [AudioPortInfo], glassesName: String?) -> GlassesRouteStatus {
        guard let mic = inputs.first(where: \.isBluetoothHFP) else {
            return .noMicrophone(current: inputs.first?.name)
        }
        guard matches(mic.name, glassesName) else { return .otherDevice(name: mic.name) }
        guard let speaker = outputs.first(where: \.isBluetoothOutput) else {
            return .noSpeaker(current: outputs.first?.name)
        }
        guard matches(speaker.name, glassesName) else { return .otherDevice(name: speaker.name) }
        return .ready(name: mic.name)
    }

    /// A Bluetooth port is the glasses if it's named like Meta glasses or matches the name the
    /// Meta SDK reports for the connected device.
    static func matches(_ portName: String, _ glassesName: String?) -> Bool {
        let port = portName.lowercased()
        if port.contains("ray-ban") || port.contains("rayban") || port.contains("meta") || port.contains("oakley") {
            return true
        }
        guard let glasses = glassesName?.lowercased(), !glasses.isEmpty else { return false }
        return port.contains(glasses) || glasses.contains(port)
    }
}
