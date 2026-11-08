import Foundation

/// The one session shared by this app, Vapi, and the server.
struct ConversationHandle: Equatable, Sendable {
    let sessionID: String
    /// Good for this session only. Kept in memory, never saved.
    let deviceToken: String
}

struct ConversationCall: Sendable {
    let generation: Int
    let variableValues: [String: String]
}

struct CameraCommand: Equatable, Sendable {
    let requestID: String
    let generation: Int
    let question: String
    let secondsRemaining: Double
}

/// What the server currently holds as true. Display only; the server is the authority.
struct ConversationState: Decodable, Equatable, Sendable {
    struct Answer: Decodable, Equatable, Sendable {
        let query: String
        let text: String
    }

    struct Visual: Decodable, Equatable, Sendable {
        let component: String?
        let confidence: Double?
    }

    let vehicle_summary: String
    let vehicle_confirmed: Bool
    let component: String?
    let grounded_answer: Answer?
    let visual: Visual?
}

struct ConversationAPIError: LocalizedError {
    let status: Int
    let detail: String
    var errorDescription: String? { detail }
    /// The server no longer wants this result (finished, cancelled, or from an earlier call).
    var isStale: Bool { status == 409 }
}

/// Talks to the backend's /conversation API. Holds no backend API keys.
struct ConversationClient: Sendable {
    let baseURL: URL
    var session: URLSession = .shared

    func createSession(ownerName: String, vehicle: Vehicle) async throws -> ConversationHandle {
        struct Body: Encodable {
            let owner_name: String
            let vehicle: Vehicle
        }
        struct Reply: Decodable {
            let session_id: String
            let device_token: String
        }
        let reply: Reply = try await send(path: "conversation/sessions", method: "POST", token: nil,
                                          body: Body(owner_name: ownerName, vehicle: vehicle))
        return ConversationHandle(sessionID: reply.session_id, deviceToken: reply.device_token)
    }

    func updateVehicle(_ handle: ConversationHandle, vehicle: Vehicle) async throws {
        struct Reply: Decodable {}
        let _: Reply = try await send(path: "conversation/sessions/\(handle.sessionID)/vehicle", method: "PUT",
                                      token: handle.deviceToken, body: vehicle)
    }

    func state(_ handle: ConversationHandle) async throws -> ConversationState {
        try await send(path: "conversation/sessions/\(handle.sessionID)", method: "GET", token: handle.deviceToken, body: Optional<Vehicle>.none)
    }

    func startCall(_ handle: ConversationHandle, openingQuestion: String?) async throws -> ConversationCall {
        struct Body: Encodable { let opening_question: String? }
        struct Reply: Decodable {
            let generation: Int
            let variable_values: [String: String]
        }
        let reply: Reply = try await send(path: "conversation/sessions/\(handle.sessionID)/calls", method: "POST",
                                          token: handle.deviceToken, body: Body(opening_question: openingQuestion))
        return ConversationCall(generation: reply.generation, variableValues: reply.variable_values)
    }

    func bindCall(_ handle: ConversationHandle, generation: Int, vapiCallID: String) async throws {
        struct Body: Encodable { let vapi_call_id: String }
        struct Reply: Decodable {}
        let _: Reply = try await send(path: "conversation/sessions/\(handle.sessionID)/calls/\(generation)/bind", method: "POST",
                                      token: handle.deviceToken, body: Body(vapi_call_id: vapiCallID))
    }

    func endCall(_ handle: ConversationHandle, generation: Int, reason: String) async throws {
        struct Body: Encodable { let reason: String }
        struct Reply: Decodable {}
        let _: Reply = try await send(path: "conversation/sessions/\(handle.sessionID)/calls/\(generation)/end", method: "POST",
                                      token: handle.deviceToken, body: Body(reason: reason))
    }

    /// Long poll: waits up to `wait` seconds and returns nil if nothing was asked for.
    func nextCameraCommand(_ handle: ConversationHandle, wait: Int = 20) async throws -> CameraCommand? {
        struct Reply: Decodable {
            let request_id: String
            let generation: Int
            let question: String
            let seconds_remaining: Double
        }
        var request = URLRequest(url: baseURL.appending(path: "conversation/sessions/\(handle.sessionID)/camera/next")
            .appending(queryItems: [URLQueryItem(name: "wait", value: String(wait))]))
        request.timeoutInterval = TimeInterval(wait + 10)
        request.setValue("Bearer \(handle.deviceToken)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 204 { return nil }
        guard status == 200 else { throw Self.error(status, data) }
        let reply = try JSONDecoder().decode(Reply.self, from: data)
        return CameraCommand(requestID: reply.request_id, generation: reply.generation,
                             question: reply.question, secondsRemaining: reply.seconds_remaining)
    }

    /// Uploads the photo for a command. Returns once the part has been identified.
    func uploadPhoto(_ handle: ConversationHandle, requestID: String, jpeg: Data, timeout: TimeInterval) async throws {
        let boundary = "carvis-\(UUID().uuidString)"
        var request = URLRequest(url: baseURL.appending(path: "conversation/sessions/\(handle.sessionID)/camera/\(requestID)/photo"))
        request.httpMethod = "POST"
        request.timeoutInterval = max(timeout, 5)
        request.setValue("Bearer \(handle.deviceToken)", forHTTPHeaderField: "Authorization")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        var body = Data()
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"glasses.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8))
        body.append(jpeg)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        request.httpBody = body
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else { throw Self.error(status, data) }
    }

    func reportCameraFailure(_ handle: ConversationHandle, requestID: String, reason: String) async throws {
        struct Body: Encodable { let reason: String }
        struct Reply: Decodable {}
        let _: Reply = try await send(path: "conversation/sessions/\(handle.sessionID)/camera/\(requestID)/failure", method: "POST",
                                      token: handle.deviceToken, body: Body(reason: reason))
    }

    private func send<Reply: Decodable, Body: Encodable>(path: String, method: String, token: String?, body: Body?) async throws -> Reply {
        var request = URLRequest(url: baseURL.appending(path: path))
        request.httpMethod = method
        request.timeoutInterval = 15
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(body)
        }
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else { throw Self.error(status, data) }
        return try JSONDecoder().decode(Reply.self, from: data)
    }

    private static func error(_ status: Int, _ data: Data) -> ConversationAPIError {
        struct Detail: Decodable { let detail: String }
        let detail = (try? JSONDecoder().decode(Detail.self, from: data))?.detail
            ?? String(data: data, encoding: .utf8) ?? "No details."
        return ConversationAPIError(status: status, detail: "Server error \(status): \(detail)")
    }
}
