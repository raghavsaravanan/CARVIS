import Foundation

/// Anything that can answer a step request.
/// Today that's MockBackendClient. Later a RealBackendClient will talk to the
/// server, and the rest of the app won't need to change.
protocol BackendClient {
    func send(_ request: StepRequest) async throws -> StepResponse
}
