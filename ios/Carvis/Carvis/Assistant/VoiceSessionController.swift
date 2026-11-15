import Foundation

/// The provider owns one live call. Callbacks are installed for each attempt so late events
/// from an earlier attempt cannot change the current conversation.
@MainActor
protocol VoiceCallProvider: AnyObject {
    var onConnected: (() -> Void)? { get set }
    var onEnded: ((String?) -> Void)? { get set }
    func start(metadata: [String: Any], overrides: [String: Any]) async throws -> String
    func end()
    func setMicrophoneMuted(_ muted: Bool) async
    func deliver(question: String)
}

enum VoiceRouteStatus: Equatable {
    case ready
    case unavailable(String)
}

/// A route owns audio only from acquisition through release. Device policy lives in its adapter.
@MainActor
protocol VoiceAudioRoute: AnyObject {
    func acquire() async throws
    func status() -> VoiceRouteStatus
    func prefer() async
    func observeChanges(_ action: @escaping @MainActor () -> Void)
    func release() async
}

protocol VoiceSessionBackend: Sendable {
    func createSession(ownerName: String, vehicle: Vehicle) async throws -> ConversationHandle
    func updateVehicle(_ handle: ConversationHandle, vehicle: Vehicle) async throws
    func startCall(_ handle: ConversationHandle, openingQuestion: String?) async throws -> ConversationCall
    func bindCall(_ handle: ConversationHandle, generation: Int, vapiCallID: String) async throws
    func endCall(_ handle: ConversationHandle, generation: Int, reason: String) async throws
    func state(_ handle: ConversationHandle) async throws -> ConversationState
}

enum VoiceSessionEvent: Equatable {
    case connected
    case ended(String?)
    case startFailed(String)
    case routeReady
    case routeLost(String)
    case shutdownComplete
}

/// Coordinates Vapi, the server session, and an injected audio route. It has no wake,
/// wearable, camera, or SwiftUI dependency. ConversationMachine remains the transition rulebook.
@MainActor
final class VoiceSessionController {
    var onEvent: ((VoiceSessionEvent) -> Void)?
    var onCallStarted: ((ConversationHandle, Int) -> Void)?
    var onState: ((ConversationState) -> Void)?

    private let provider: any VoiceCallProvider
    private var route: any VoiceAudioRoute
    private var handle: ConversationHandle?
    private var handleVehicle: Vehicle?
    private var activeCall: (handle: ConversationHandle, generation: Int)?
    private var backend: (any VoiceSessionBackend)?
    private var warmupTask: Task<Void, Never>?
    private var startTask: Task<Void, Never>?
    private var routeTask: Task<Void, Never>?
    private var attempt = 0
    private var routeReady = false
    private var shuttingDown = false
    private var pendingActivation: (backend: (any VoiceSessionBackend)?, ownerName: String, vehicle: Vehicle?)?

    init(provider: any VoiceCallProvider, route: any VoiceAudioRoute) {
        self.provider = provider
        self.route = route
    }

    /// Switch only between calls, after the previous route has released its resources.
    @discardableResult
    func selectRoute(_ next: any VoiceAudioRoute) -> Bool {
        guard activeCall == nil, startTask == nil, !shuttingDown else { return false }
        route = next
        routeReady = false
        return true
    }

    func activate(backend: (any VoiceSessionBackend)?, ownerName: String, vehicle: Vehicle?) {
        if activeCall != nil || startTask != nil || shuttingDown {
            pendingActivation = (backend, ownerName, vehicle)
            return
        }
        attempt += 1
        warmupTask?.cancel()
        handle = nil
        handleVehicle = nil
        self.backend = backend
        guard let backend, let vehicle else { return }
        let token = attempt
        warmupTask = Task { [weak self] in
            _ = try? await self?.ensureSession(backend: backend, ownerName: ownerName, vehicle: vehicle, token: token)
        }
    }

    func start(backend: (any VoiceSessionBackend)?, ownerName: String, vehicle: Vehicle?, openingQuestion: String?) {
        guard startTask == nil, activeCall == nil, !shuttingDown else { return }
        let token = attempt
        self.backend = backend
        startTask = Task { [weak self] in
            guard let self else { return }
            do {
                guard let backend, let vehicle else {
                    throw ConversationSetupError.message("Carvis needs a server address and your car's details first.")
                }
                await warmupTask?.value
                try current(token)
                let handle = try await ensureSession(backend: backend, ownerName: ownerName, vehicle: vehicle, token: token)
                try current(token)
                // Start both without making route acquisition the sole owner of the server result.
                let serverCall = Task { try await backend.startCall(handle, openingQuestion: openingQuestion) }
                do {
                    try await route.acquire()
                } catch {
                    if let call = try? await serverCall.value { activeCall = (handle, call.generation) }
                    throw error
                }
                let call = try await serverCall.value
                activeCall = (handle, call.generation)
                try current(token)
                var overrides: [String: Any] = ["variableValues": call.variableValues]
                if openingQuestion != nil { overrides["firstMessageMode"] = "assistant-waits-for-user" }
                provider.onConnected = { [weak self] in self?.providerConnected(token) }
                provider.onEnded = { [weak self] error in self?.providerEnded(token, error: error) }
                let callID = try await provider.start(metadata: ["carvis_session_id": handle.sessionID], overrides: overrides)
                guard token == attempt, !Task.isCancelled else {
                    provider.end()
                    return
                }
                try await backend.bindCall(handle, generation: call.generation, vapiCallID: callID)
                guard token == attempt, !Task.isCancelled else { return }
                route.observeChanges { [weak self] in self?.routeChanged(token) }
                onCallStarted?(handle, call.generation)
                startTask = nil
            } catch is CancellationError {
                if token == attempt { onEvent?(.ended(nil)) }
            } catch is VoiceSessionCancelled {
                if token == attempt { onEvent?(.ended(nil)) }
            } catch {
                guard token == attempt else { return }
                if let apiError = error as? ConversationAPIError, apiError.status == 401 || apiError.status == 404 {
                    handle = nil
                    handleVehicle = nil
                }
                let reason = error.localizedDescription
                onEvent?(.startFailed(reason))
                // A provider can report connected before its start promise fails. In that case
                // ConversationMachine has already left startingCall and needs an end event.
                if activeCall != nil { onEvent?(.ended(reason)) }
            }
        }
    }

    func verifyRoute() {
        routeTask?.cancel()
        let token = attempt
        routeTask = Task { [weak self] in
            guard let self else { return }
            var tries = 0
            while !Task.isCancelled, token == attempt {
                if tries % 10 == 0 { await route.prefer() }
                guard !Task.isCancelled, token == attempt else { return }
                switch route.status() {
                case .ready:
                    routeReady = true
                    onEvent?(.routeReady)
                    return
                case .unavailable(let reason):
                    tries += 1
                    if tries == 40 { onEvent?(.routeLost(reason)) }
                }
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
    }

    func refreshRoute() { routeChanged(attempt) }

    func setMicrophoneMuted(_ muted: Bool) {
        let token = attempt
        Task { [weak self] in
            guard let self, token == self.attempt else { return }
            await self.provider.setMicrophoneMuted(muted)
        }
    }

    func deliver(question: String) { provider.deliver(question: question) }

    func end() {
        let wasStarting = startTask != nil
        startTask?.cancel()
        provider.end()
        // If no provider was started, there will be no provider end callback.
        if wasStarting { onEvent?(.ended(nil)) }
    }

    func shutdown() {
        guard !shuttingDown else { return }
        shuttingDown = true
        attempt += 1
        warmupTask?.cancel()
        let starting = startTask
        startTask = nil
        starting?.cancel()
        routeTask?.cancel()
        routeReady = false
        provider.onConnected = nil
        provider.onEnded = nil
        provider.end()
        route.observeChanges({})
        let backend = backend
        Task { [weak self] in
            guard let self else { return }
            await starting?.value
            let finished = activeCall
            activeCall = nil
            if let finished, let backend {
                try? await backend.endCall(finished.handle, generation: finished.generation, reason: "app")
                if let state = try? await backend.state(finished.handle) { onState?(state) }
            }
            await route.release()
            shuttingDown = false
            if let pending = pendingActivation {
                pendingActivation = nil
                activate(backend: pending.backend, ownerName: pending.ownerName, vehicle: pending.vehicle)
            }
            onEvent?(.shutdownComplete)
        }
    }

    private func ensureSession(backend: any VoiceSessionBackend, ownerName: String, vehicle: Vehicle, token: Int) async throws -> ConversationHandle {
        if let handle {
            if handleVehicle != vehicle {
                try await backend.updateVehicle(handle, vehicle: vehicle)
                try current(token)
                handleVehicle = vehicle
            }
            return handle
        }
        let created = try await backend.createSession(ownerName: ownerName, vehicle: vehicle)
        try current(token)
        handle = created
        handleVehicle = vehicle
        return created
    }

    private func current(_ token: Int) throws {
        guard token == attempt, !Task.isCancelled else { throw VoiceSessionCancelled() }
    }

    private func providerConnected(_ token: Int) {
        guard token == attempt else { return }
        onEvent?(.connected)
    }

    private func providerEnded(_ token: Int, error: String?) {
        guard token == attempt else { return }
        onEvent?(.ended(error))
    }

    private func routeChanged(_ token: Int) {
        guard token == attempt, activeCall != nil else { return }
        switch route.status() {
        case .ready:
            if !routeReady { routeReady = true; onEvent?(.routeReady) }
        case .unavailable(let reason):
            if routeReady { routeReady = false; onEvent?(.routeLost(reason)) }
        }
    }
}

private struct VoiceSessionCancelled: Error {}

enum ConversationSetupError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case .message(let text): text
        }
    }
}
