import Foundation
import MWDATCore

/// Configure the official SDK before accessing its singleton. A missing local Meta configuration
/// leaves the optional glasses integration unavailable without preventing Carvis from launching.
@MainActor
enum MetaWearablesRuntime {
    static let wearables: any WearablesInterface = {
        do {
            try Wearables.configure()
            return Wearables.shared
        } catch {
            print("[Carvis] Meta glasses unavailable: \(error.localizedDescription)")
            return UnavailableWearables()
        }
    }()
}

private struct UnavailableListenerToken: AnyListenerToken {
    func cancel() async {}
}

/// No SDK session or device is created when Meta configuration is unavailable.
private struct UnavailableWearables: WearablesInterface {
    var registrationState: RegistrationState { .unavailable }
    var devices: [DeviceIdentifier] { [] }

    func addRegistrationStateListener(_ listener: @escaping @Sendable (RegistrationState) -> Void) -> any AnyListenerToken {
        listener(.unavailable)
        return UnavailableListenerToken()
    }
    func registrationStateStream() -> AsyncStream<RegistrationState> {
        AsyncStream { continuation in continuation.yield(.unavailable); continuation.finish() }
    }
    func addDevicesListener(_ listener: @escaping @Sendable ([DeviceIdentifier]) -> Void) -> any AnyListenerToken {
        listener([])
        return UnavailableListenerToken()
    }
    func devicesStream() -> AsyncStream<[DeviceIdentifier]> {
        AsyncStream { continuation in continuation.yield([]); continuation.finish() }
    }
    func deviceForIdentifier(_ identifier: DeviceIdentifier) -> Device? { nil }

    func startRegistration() async throws(RegistrationError) { throw .configurationInvalid }
    func handleUrl(_ url: URL) async throws(WearablesHandleURLError) -> Bool { throw .registrationError }
    func startUnregistration() async throws(UnregistrationError) { throw .configurationInvalid }
    func openFirmwareUpdate() async throws(NavigationError) { throw .notRegistered }
    func openDATGlassesAppUpdate() async throws(NavigationError) { throw .notRegistered }
    func checkPermissionStatus(_ permission: Permission) async throws(PermissionError) -> PermissionStatus { throw .noDevice }
    func requestPermission(_ permission: Permission) async throws(PermissionError) -> PermissionStatus { throw .noDevice }
    func createSession(deviceSelector: any DeviceSelector) throws(DeviceSessionError) -> DeviceSession { throw .noEligibleDevice }
}
