import Foundation

/// The car the photo questions are about. Sent to George on every question,
/// because a photo alone must never decide which car it is.
struct Vehicle: Codable, Equatable {
    let year: String
    let make: String
    let model: String

    /// The demo car. George only has this car's service manual loaded.
    static let demo = Vehicle(year: "2022", make: "subaru", model: "wrx")

    var displayName: String { "\(year) Subaru WRX" }
}

/// What George thinks the photo shows. This only helps the search;
/// it never decides the answer.
struct VisionComponent: Codable, Equatable {
    let component: String
    let confidence: Double
    let visualContext: String?
    let uncertainty: String?

    enum CodingKeys: String, CodingKey {
        case component, confidence
        case visualContext = "visual_context"
        case uncertainty
    }
}

enum VisionResult: Equatable {
    /// Found in the service manual.
    case answer(text: String, component: VisionComponent, vehicle: Vehicle)
    /// George looked and the manual doesn't have it, so it refused instead of guessing.
    case notInManual(message: String, component: VisionComponent?)
}

/// Sends a photo and a question to George's /vision-query.
protocol VisionClient {
    func ask(photo jpeg: Data, question: String, vehicle: Vehicle, sessionID: String) async throws -> VisionResult
}

struct VisionClientError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

/// Talks to the George backend over HTTP. No API keys live in the app;
/// the backend holds them.
struct GeorgeVisionClient: VisionClient {
    let baseURL: URL
    var session: URLSession = .shared

    /// Reads the backend address from Info.plist (key GeorgeBaseURL).
    static func fromInfoPlist() -> GeorgeVisionClient? {
        guard let text = Bundle.main.object(forInfoDictionaryKey: "GeorgeBaseURL") as? String,
              let url = URL(string: text.trimmingCharacters(in: .whitespaces)), url.scheme != nil
        else { return nil }
        return GeorgeVisionClient(baseURL: url)
    }

    func ask(photo jpeg: Data, question: String, vehicle: Vehicle, sessionID: String) async throws -> VisionResult {
        let boundary = "carvis-\(UUID().uuidString)"
        var request = URLRequest(url: baseURL.appending(path: "vision-query"))
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = Self.multipartBody(boundary: boundary, jpeg: jpeg, fields: [
            ("question", question),
            ("year", vehicle.year),
            ("make", vehicle.make),
            ("model", vehicle.model),
            ("session_id", sessionID),
        ])

        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw VisionClientError(message: "Couldn't reach the Carvis server at \(baseURL.absoluteString). \(error.localizedDescription)")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let decoder = JSONDecoder()

        switch status {
        case 200:
            struct Success: Decodable {
                let answer: String
                let component: VisionComponent
                let vehicle: Vehicle
            }
            let body = try decoder.decode(Success.self, from: data)
            return .answer(text: body.answer, component: body.component, vehicle: body.vehicle)
        case 404:
            // George's refusal: {"error": "...", "component": {...}}
            struct Refusal: Decodable {
                let error: String
                let component: VisionComponent?
            }
            if let body = try? decoder.decode(Refusal.self, from: data) {
                return .notInManual(message: body.error, component: body.component)
            }
            throw VisionClientError(message: "The server answered 404 at \(request.url?.absoluteString ?? "").")
        default:
            // Every other failure: {"detail": "..."}
            struct Failure: Decodable { let detail: String }
            let detail = (try? decoder.decode(Failure.self, from: data))?.detail
                ?? String(data: data, encoding: .utf8)
                ?? "No details."
            throw VisionClientError(message: "Server error \(status): \(detail)")
        }
    }

    private static func multipartBody(boundary: String, jpeg: Data, fields: [(String, String)]) -> Data {
        var body = Data()
        func add(_ text: String) { body.append(Data(text.utf8)) }
        for (name, value) in fields {
            add("--\(boundary)\r\n")
            add("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
            add("\(value)\r\n")
        }
        add("--\(boundary)\r\n")
        add("Content-Disposition: form-data; name=\"file\"; filename=\"glasses.jpg\"\r\n")
        add("Content-Type: image/jpeg\r\n\r\n")
        body.append(jpeg)
        add("\r\n--\(boundary)--\r\n")
        return body
    }
}
