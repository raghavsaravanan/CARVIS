import Foundation

// Small contract stand-ins let the controller run on macOS without Vapi, Meta, or AVAudioSession.
struct Vehicle: Equatable, Sendable { let model: String }
struct ConversationHandle: Equatable, Sendable { let sessionID: String; let deviceToken: String }
struct ConversationCall: Sendable { let generation: Int; let variableValues: [String: String] }
struct ConversationState: Sendable { let summary: String }
struct ConversationAPIError: LocalizedError { let status: Int; var errorDescription: String? { "server error" } }

@MainActor
final class FakeProvider: VoiceCallProvider {
    var onConnected: (() -> Void)?
    var onEnded: ((String?) -> Void)?
    var startError: Error?
    var connectBeforeFailure = false
    var holdStart = false
    var continuation: CheckedContinuation<String, Error>?
    var ends = 0
    var starts = 0
    var mutes: [Bool] = []
    var delivered: [String] = []
    var metadata: [String: Any] = [:]
    var overrides: [String: Any] = [:]

    func start(metadata: [String: Any], overrides: [String: Any]) async throws -> String {
        starts += 1
        self.metadata = metadata
        self.overrides = overrides
        if connectBeforeFailure { onConnected?() }
        if let startError { throw startError }
        if holdStart { return try await withCheckedThrowingContinuation { continuation = $0 } }
        return "vapi-call"
    }
    func end() { ends += 1 }
    func setMicrophoneMuted(_ muted: Bool) async { mutes.append(muted) }
    func deliver(question: String) { delivered.append(question) }
}

@MainActor
final class FakeRoute: VoiceAudioRoute {
    var current: VoiceRouteStatus = .ready
    var acquireError: Error?
    var holdAcquire = false
    var acquireContinuation: CheckedContinuation<Void, Error>?
    var acquired = 0
    var released = 0
    var preferred = 0
    var observer: (@MainActor () -> Void)?
    func acquire() async throws {
        acquired += 1
        if let acquireError { throw acquireError }
        if holdAcquire { try await withCheckedThrowingContinuation { acquireContinuation = $0 } }
    }
    func status() -> VoiceRouteStatus { current }
    func prefer() async { preferred += 1 }
    func observeChanges(_ action: @escaping @MainActor () -> Void) { observer = action }
    func release() async { released += 1 }
    func change(_ status: VoiceRouteStatus) { current = status; observer?() }
}

actor FakeBackend: VoiceSessionBackend {
    var createError: Error?
    var bindError: Error?
    var createCount = 0
    var updated: [Vehicle] = []
    var started: [String?] = []
    var bindings: [String] = []
    var ended: [Int] = []
    func setCreateError(_ error: Error) { createError = error }
    func setBindError(_ error: Error) { bindError = error }
    func createSession(ownerName: String, vehicle: Vehicle) async throws -> ConversationHandle {
        createCount += 1
        if let createError { throw createError }
        return ConversationHandle(sessionID: "session-\(createCount)", deviceToken: "token")
    }
    func updateVehicle(_ handle: ConversationHandle, vehicle: Vehicle) async throws { updated.append(vehicle) }
    func startCall(_ handle: ConversationHandle, openingQuestion: String?) async throws -> ConversationCall {
        started.append(openingQuestion)
        return ConversationCall(generation: started.count, variableValues: ["vehicle": "server verified"])
    }
    func bindCall(_ handle: ConversationHandle, generation: Int, vapiCallID: String) async throws {
        if let bindError { throw bindError }
        bindings.append(vapiCallID)
    }
    func endCall(_ handle: ConversationHandle, generation: Int, reason: String) async throws { ended.append(generation) }
    func state(_ handle: ConversationHandle) async throws -> ConversationState { ConversationState(summary: "server") }
}

@main
@MainActor
struct VoiceSessionControllerTests {
    static var checks = 0
    static func check(_ value: Bool, _ label: String) {
        precondition(value, label)
        checks += 1
    }
    static func until(_ condition: @escaping @MainActor () async -> Bool) async {
        for _ in 0..<1000 {
            if await condition() { return }
            await Task.yield()
        }
        preconditionFailure("timed out waiting for test state")
    }
    static func main() async {
        let vehicle = Vehicle(model: "WRX")

        // Session warmup, call start/bind, route loss/recovery, termination, and duplicate end.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            var calls: [(String, Int)] = []
            controller.onEvent = { events.append($0) }
            controller.onCallStarted = { calls.append(($0.sessionID, $1)) }
            controller.activate(backend: backend, ownerName: "Technician", vehicle: vehicle)
            await until { await backend.createCount == 1 }
            controller.start(backend: backend, ownerName: "Technician", vehicle: vehicle, openingQuestion: "where is it")
            await until { calls.count == 1 }
            check(await backend.createCount == 1, "warm session reused")
            check(provider.metadata["carvis_session_id"] as? String == "session-1", "session passed to Vapi")
            check(provider.overrides["firstMessageMode"] as? String == "assistant-waits-for-user", "opening turn waits")
            check(await backend.bindings == ["vapi-call"], "call bound to generation")
            provider.onConnected?()
            controller.verifyRoute()
            await until { events.contains(.routeReady) }
            route.change(.unavailable("disconnected"))
            check(events.contains(.routeLost("disconnected")), "disconnect pauses route")
            route.change(.ready)
            check(events.filter { $0 == .routeReady }.count == 2, "reconnect restores route")
            controller.deliver(question: "where is it")
            check(provider.delivered == ["where is it"], "question delivered once")
            let staleEnd = provider.onEnded
            controller.end()
            provider.onEnded?(nil)
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(await backend.ended == [1] && route.released == 1, "server generation and audio released once")
            staleEnd?("late")
            check(events.filter { if case .ended = $0 { return true }; return false }.count == 1, "stale callback ignored")
            check(calls.count == 1 && calls[0].0 == "session-1" && calls[0].1 == 1, "one call opened")
        }

        // A failed session cannot start a provider or acquire an audio route.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            await backend.setCreateError(ConversationAPIError(status: 503))
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { events.contains { if case .startFailed = $0 { return true }; return false } }
            check(route.acquired == 0 && provider.metadata.isEmpty, "session failure stops before audio and Vapi")
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(route.released == 1, "failure releases route")
        }

        // Vapi initialization failure closes the server generation and releases the route.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            provider.startError = ConversationAPIError(status: 500)
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { events.contains { if case .startFailed = $0 { return true }; return false } }
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(await backend.ended == [1] && route.released == 1, "provider failure cleans up")
        }

        // A provider that connects then fails still delivers an end event for shutdown.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            provider.connectBeforeFailure = true
            provider.startError = ConversationAPIError(status: 500)
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { events.contains { if case .ended = $0 { return true }; return false } }
            check(events.contains(.connected), "early provider connection observed")
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(await backend.ended == [1], "connected startup failure closes generation")
        }

        // Audio acquisition failure also closes any server generation that already opened.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            route.acquireError = ConversationSetupError.message("glasses route unavailable")
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { events.contains { if case .startFailed = $0 { return true }; return false } }
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(await backend.ended == [1], "failed route closes server generation")
            check(route.released == 1 && provider.metadata.isEmpty, "failed route never starts Vapi")
        }

        // A Vapi call without a server binding cannot continue taking voice turns.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            await backend.setBindError(ConversationAPIError(status: 503))
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { events.contains { if case .startFailed = $0 { return true }; return false } }
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(provider.starts == 1 && provider.ends >= 1, "unbound Vapi call stopped")
            check(await backend.ended == [1] && route.released == 1, "bind failure closes server generation and audio")
        }

        // Ending while provider.start is suspended cannot revive or bind a stale call.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            provider.holdStart = true
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { provider.continuation != nil }
            let staleConnect = provider.onConnected
            controller.end()
            controller.shutdown()
            provider.continuation?.resume(returning: "too-late")
            await until { events.contains(.shutdownComplete) }
            staleConnect?()
            check(!events.contains(.connected), "late connection ignored")
            check(await backend.bindings.isEmpty && route.released == 1, "cancelled call never bound and audio released")
            check(provider.ends >= 1, "late provider stopped")
        }

        // Cancellation during route acquisition still ends the server call after it opens.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            route.holdAcquire = true
            let controller = VoiceSessionController(provider: provider, route: route)
            var events: [VoiceSessionEvent] = []
            controller.onEvent = { events.append($0) }
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { route.acquireContinuation != nil }
            controller.end()
            controller.shutdown()
            route.acquireContinuation?.resume()
            await until { events.contains(.shutdownComplete) }
            check(await backend.ended == [1], "cancelled route still closes generation")
            check(route.released == 1 && provider.metadata.isEmpty, "cancelled route releases audio without Vapi")
        }

        // The confirmed vehicle context is updated before the next call.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            let controller = VoiceSessionController(provider: provider, route: route)
            var calls = 0
            controller.onCallStarted = { _, _ in calls += 1 }
            controller.activate(backend: backend, ownerName: "", vehicle: vehicle)
            await until { await backend.createCount == 1 }
            controller.start(backend: backend, ownerName: "", vehicle: Vehicle(model: "Civic"), openingQuestion: nil)
            await until { calls == 1 }
            check(await backend.updated == [Vehicle(model: "Civic")], "vehicle update precedes call")
            controller.shutdown()
        }

        // Reactivation during a previous call's shutdown waits for release and starts fresh.
        do {
            let provider = FakeProvider(), route = FakeRoute(), backend = FakeBackend()
            let controller = VoiceSessionController(provider: provider, route: route)
            var calls = 0
            var shutdowns = 0
            controller.onCallStarted = { _, _ in calls += 1 }
            controller.onEvent = { if $0 == .shutdownComplete { shutdowns += 1 } }
            controller.activate(backend: backend, ownerName: "", vehicle: vehicle)
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { calls == 1 }
            controller.activate(backend: backend, ownerName: "", vehicle: Vehicle(model: "Civic"))
            controller.shutdown()
            await until { let count = await backend.createCount; return shutdowns == 1 && count == 2 }
            check(route.released == 1, "old audio released before next session")
            check(await backend.createCount == 2, "new activation makes a new session")
        }

        // Phone/glasses route selection is exclusive, and rapid starts create one generation.
        do {
            let provider = FakeProvider(), glassesRoute = FakeRoute(), phoneRoute = FakeRoute()
            let backend = FakeBackend()
            let controller = VoiceSessionController(provider: provider, route: glassesRoute)
            var calls = 0
            var events: [VoiceSessionEvent] = []
            controller.onCallStarted = { _, _ in calls += 1 }
            controller.onEvent = { events.append($0) }
            check(controller.selectRoute(phoneRoute), "phone route selected before call")
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { calls == 1 }
            let generationCount = await backend.started.count
            check(provider.starts == 1 && generationCount == 1, "rapid taps create one call")
            check(phoneRoute.acquired == 1 && glassesRoute.acquired == 0, "phone route owns audio")
            check(!controller.selectRoute(glassesRoute), "route cannot switch during call")
            provider.onEnded?(nil)
            controller.shutdown()
            await until { events.contains(.shutdownComplete) }
            check(phoneRoute.released == 1, "phone route released before switch")
            check(controller.selectRoute(glassesRoute), "glasses route restored between calls")
            controller.activate(backend: backend, ownerName: "", vehicle: vehicle)
            controller.start(backend: backend, ownerName: "", vehicle: vehicle, openingQuestion: nil)
            await until { calls == 2 }
            check(glassesRoute.acquired == 1, "glasses path can start again")
            controller.shutdown()
        }
        print("\(checks) voice session controller checks passed")
    }
}
