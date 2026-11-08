import Foundation
import Observation
import SwiftUI

/// A job's steps, as titles only. No specs or numbers; those come from the manual.
struct Procedure: Equatable {
    struct Step: Equatable {
        let title: String
        let symbol: String
        var safety = false
        var camera = false
    }

    let name: String
    let symbol: String
    let steps: [Step]

    static let oilChange = Procedure(
        name: "Oil change", symbol: "drop.fill",
        steps: (1...12).map { number in
            let visual = StepVisual.forStep(number)
            return Step(title: visual.title, symbol: visual.symbol, safety: number == 2 || number == 5, camera: number == 6)
        }
    )

    static let brakePads = Procedure(name: "Brake pads", symbol: "exclamationmark.brakesignal", steps: [
        Step(title: "Loosen the wheel nuts", symbol: "arrow.counterclockwise"),
        Step(title: "Lift onto jack stands", symbol: "arrow.up.circle.fill", safety: true),
        Step(title: "Remove the wheel", symbol: "circle.circle"),
        Step(title: "Remove the caliper bolts", symbol: "wrench.adjustable.fill"),
        Step(title: "Swap the brake pads", symbol: "rectangle.2.swap"),
        Step(title: "Inspect the rotor", symbol: "camera.viewfinder", camera: true),
        Step(title: "Reinstall the caliper", symbol: "wrench.and.screwdriver.fill"),
        Step(title: "Reinstall the wheel", symbol: "circle.circle"),
        Step(title: "Lower and tighten the wheel nuts", symbol: "arrow.down.circle.fill"),
    ])

    static let tireRotation = Procedure(name: "Tire rotation", symbol: "circle.circle", steps: [
        Step(title: "Loosen the wheel nuts", symbol: "arrow.counterclockwise"),
        Step(title: "Lift onto jack stands", symbol: "arrow.up.circle.fill", safety: true),
        Step(title: "Remove all four wheels", symbol: "circle.circle"),
        Step(title: "Move wheels to new positions", symbol: "arrow.triangle.2.circlepath"),
        Step(title: "Reinstall the wheels", symbol: "wrench.and.screwdriver.fill"),
        Step(title: "Lower and tighten the wheel nuts", symbol: "arrow.down.circle.fill"),
    ])

    static let airFilter = Procedure(name: "Engine air filter", symbol: "wind", steps: [
        Step(title: "Open the hood", symbol: "car.fill"),
        Step(title: "Open the air box", symbol: "shippingbox.fill"),
        Step(title: "Remove the old filter", symbol: "arrow.up.circle.fill"),
        Step(title: "Fit the new filter", symbol: "camera.viewfinder", camera: true),
        Step(title: "Close the air box", symbol: "checkmark.circle.fill"),
    ])

    static let all: [Procedure] = [.oilChange, .brakePads, .tireRotation, .airFilter]
}

/// The shop you host. Saved on this phone.
struct Shop: Codable, Equatable {
    var name: String
    var code: String
    var createdAt = Date.now
}

/// One mechanic on the shop floor and the job they're doing.
struct ShopMechanic: Identifiable, Equatable {
    enum Status { case working, safety, camera, done }

    let id: UUID
    let name: String
    let colorHex: UInt32
    let bay: Int
    var vehicle: String
    var procedure: Procedure
    var step: Int                 // 1-based
    var jobStartedAt: Date
    var stepStartedAt: Date
    var stepDuration: TimeInterval
    var finishedAt: Date?
    var isYou = false

    var isDone: Bool { finishedAt != nil }
    var total: Int { procedure.steps.count }
    var current: Procedure.Step { procedure.steps[min(max(step, 1), total) - 1] }
    var progress: Double { isDone ? 1 : Double(step - 1) / Double(max(total, 1)) }
    var color: Color { Color(hex: colorHex) }

    var status: Status {
        if isDone { return .done }
        if current.safety { return .safety }
        if current.camera { return .camera }
        return .working
    }

    var initials: String {
        String(name.split(separator: " ").prefix(2).compactMap(\.first)).uppercased()
    }
}

/// One line in the live activity feed.
struct ShopEvent: Identifiable, Equatable {
    let id = UUID()
    let date: Date
    let who: String
    let colorHex: UInt32
    let text: String
    let symbol: String
}

/// The shop you host and its live floor.
///
/// SPACETIMEDB HOOK-UP: this is the only place the shop floor gets its data. For now the crew
/// is simulated (`seedCrew` and `tick` move mechanics through real step lists on a timer).
/// When the SpacetimeDB module is ready, replace those two with a subscription that fills
/// `crew`, `events`, and `finishedToday`, and publish this phone's own job (`ShopMechanic.you`)
/// to it. The screens in ShopViews.swift only read these properties and need no changes.
@Observable
final class ShopStore {
    var shop: Shop? { didSet { save() } }
    private(set) var crew: [ShopMechanic] = []
    private(set) var events: [ShopEvent] = []
    private(set) var finishedToday = 0

    @ObservationIgnored private var loop: Task<Void, Never>?
    @ObservationIgnored private let fileURL = URL.documentsDirectory.appending(path: "shop.json")
    @ObservationIgnored private var isLoading = false

    init() {
        isLoading = true
        if let data = try? Data(contentsOf: fileURL), let saved = try? JSONDecoder().decode(Shop.self, from: data) {
            shop = saved
        }
        isLoading = false
        if shop != nil { seedCrew() }
    }

    func host(name: String) {
        shop = Shop(name: name, code: Self.makeCode())
        seedCrew()
        startLive()
    }

    func close() {
        loop?.cancel()
        loop = nil
        shop = nil
        crew = []
        events = []
        finishedToday = 0
    }

    /// Starts the live updates. Safe to call more than once.
    func startLive() {
        guard loop == nil, shop != nil else { return }
        loop = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1.5))
                self?.tick()
            }
        }
    }

    // MARK: - Simulation

    private static let roster: [(name: String, color: UInt32, vehicle: String, procedure: Procedure, step: Int)] = [
        ("Maya Chen", 0x2152E0, "2022 Subaru WRX", .oilChange, 5),
        ("Luis Ortega", 0xD08C2E, "2022 Subaru WRX", .oilChange, 9),
        ("Priya Nair", 0x7A4FD6, "2019 Toyota Camry", .brakePads, 3),
        ("Jordan Brooks", 0x1F9D74, "2021 Ford F-150", .tireRotation, 5),
    ]

    private static let vehicles = ["2022 Subaru WRX", "2019 Toyota Camry", "2021 Ford F-150", "2020 Honda Civic"]

    private func seedCrew() {
        let now = Date.now
        crew = Self.roster.enumerated().map { index, entry in
            ShopMechanic(
                id: UUID(), name: entry.name, colorHex: entry.color, bay: index + 1,
                vehicle: entry.vehicle, procedure: entry.procedure, step: entry.step,
                jobStartedAt: now - Double(entry.step) * 95 - Double(index) * 40,
                // Staggered so they don't all move at once.
                stepStartedAt: now - Double(index) * 3.5,
                stepDuration: Double.random(in: 9...16)
            )
        }
        finishedToday = 3
        events = crew.reversed().map { mechanic in
            ShopEvent(date: now - Double(mechanic.bay) * 20, who: mechanic.name, colorHex: mechanic.colorHex,
                      text: "Step \(mechanic.step) · \(mechanic.current.title)", symbol: mechanic.current.symbol)
        }
    }

    private func tick() {
        let now = Date.now
        withAnimation(.spring(duration: 0.6, bounce: 0)) {
            for index in crew.indices {
                var mechanic = crew[index]
                if let finished = mechanic.finishedAt {
                    // A short break, then the next job.
                    guard now.timeIntervalSince(finished) > 12 else { continue }
                    mechanic.procedure = Procedure.all.randomElement() ?? .oilChange
                    mechanic.vehicle = Self.vehicles.randomElement() ?? mechanic.vehicle
                    mechanic.step = 1
                    mechanic.finishedAt = nil
                    mechanic.jobStartedAt = now
                    mechanic.stepStartedAt = now
                    mechanic.stepDuration = Double.random(in: 8...14)
                    log(mechanic, "Started \(mechanic.procedure.name.lowercased()) on a \(mechanic.vehicle)", symbol: "play.fill")
                } else if now.timeIntervalSince(mechanic.stepStartedAt) > mechanic.stepDuration {
                    if mechanic.step < mechanic.total {
                        mechanic.step += 1
                        mechanic.stepStartedAt = now
                        mechanic.stepDuration = Double.random(in: 8...15) + (mechanic.current.safety ? 5 : 0)
                        let prefix = mechanic.current.safety ? "Safety check · " : ""
                        log(mechanic, "\(prefix)Step \(mechanic.step) · \(mechanic.current.title)", symbol: mechanic.current.symbol)
                    } else {
                        mechanic.finishedAt = now
                        finishedToday += 1
                        log(mechanic, "Finished \(mechanic.procedure.name.lowercased()) on the \(mechanic.vehicle)", symbol: "checkmark.seal.fill")
                    }
                }
                crew[index] = mechanic
            }
        }
    }

    private func log(_ mechanic: ShopMechanic, _ text: String, symbol: String) {
        events.insert(ShopEvent(date: .now, who: mechanic.name, colorHex: mechanic.colorHex, text: text, symbol: symbol), at: 0)
        if events.count > 30 { events.removeLast(events.count - 30) }
    }

    private static func makeCode() -> String {
        let letters = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
        return String((0..<6).map { _ in letters.randomElement()! })
    }

    private func save() {
        guard !isLoading else { return }
        if let shop {
            try? JSONEncoder().encode(shop).write(to: fileURL)
        } else {
            try? FileManager.default.removeItem(at: fileURL)
        }
    }
}

extension ShopMechanic {
    private static let youID = UUID()

    /// This phone's own job, shown live on the shop floor as "You".
    static func you(from session: RepairSession) -> ShopMechanic? {
        guard session.hasActiveJob, let current = session.current else { return nil }
        let step = current.stepNumber
        return ShopMechanic(
            id: youID, name: "You", colorHex: 0x111418, bay: 0,
            vehicle: Vehicle.demo.displayName, procedure: .oilChange, step: min(step, Procedure.oilChange.steps.count),
            jobStartedAt: .now, stepStartedAt: session.stepStartedAt, stepDuration: .infinity, isYou: true
        )
    }
}
