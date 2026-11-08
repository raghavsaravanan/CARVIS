import Foundation

// These structs mirror the backend JSON contract exactly.
// CodingKeys map Swift's camelCase names to the contract's snake_case keys.

/// What the app sends for every turn: POST {BASE_URL}/step
struct StepRequest: Codable {
    let sessionID: String
    let procedure: String
    let stepNumber: Int
    let utterance: String?   // "next", "repeat", "why", or nil to begin
    let frameB64: String?    // camera frame, unused until a later phase

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case procedure
        case stepNumber = "step_number"
        case utterance
        case frameB64 = "frame_b64"
    }
}

/// What the backend sends back.
struct StepResponse: Codable {
    let sessionID: String
    let stepNumber: Int
    let totalSteps: Int
    let spokenText: String
    let displayText: String
    let advance: Bool
    let safetyGate: Bool
    let checkpoint: Checkpoint
    let confidence: Double
    let trace: [TraceEntry]
    let done: Bool
    let summary: Summary?

    enum CodingKeys: String, CodingKey {
        case sessionID = "session_id"
        case stepNumber = "step_number"
        case totalSteps = "total_steps"
        case spokenText = "spoken_text"
        case displayText = "display_text"
        case advance
        case safetyGate = "safety_gate"
        case checkpoint, confidence, trace, done, summary
    }
}

/// How the current step gets confirmed before moving on.
struct Checkpoint: Codable {
    enum Kind: String, Codable {
        case none, voice, vision
    }

    let type: Kind
    let prompt: String
}

/// One thing the backend's agent did, like looking up a torque spec.
struct TraceEntry: Codable {
    let tool: String
    let input: String
    let result: String
    let ms: Int
}

/// Only present on the final response.
struct Summary: Codable {
    let serviceLog: ServiceLog
    let nextService: String
    let nextStep: NextStep?

    enum CodingKeys: String, CodingKey {
        case serviceLog = "service_log"
        case nextService = "next_service"
        case nextStep = "next_step"
    }
}

struct ServiceLog: Codable {
    let date: String
    let mileage: Int
    let oil: String
    let filter: String
}

struct NextStep: Codable {
    let title: String
    let detail: String
    let cta: String
}
