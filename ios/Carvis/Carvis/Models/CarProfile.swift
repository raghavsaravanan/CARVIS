import Foundation
import Observation

/// Something you service on a schedule, like an oil change.
/// Every number here is yours: you set the interval from your owner's manual
/// and Carvis just keeps count.
struct MaintenanceItem: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var symbol: String = "wrench.and.screwdriver.fill"
    var isOilChange = false
    var intervalMiles: Int?
    var intervalMonths: Int?
    var lastMiles: Int?
    var lastDate: Date?

    enum Status { case ok, soon, overdue, notSetUp }

    func milesLeft(odometer: Int) -> Int? {
        guard let intervalMiles, let lastMiles else { return nil }
        return lastMiles + intervalMiles - odometer
    }

    var dueDate: Date? {
        guard let intervalMonths, let lastDate else { return nil }
        return Calendar.current.date(byAdding: .month, value: intervalMonths, to: lastDate)
    }

    func daysLeft(now: Date = .now) -> Int? {
        guard let dueDate else { return nil }
        let start = Calendar.current.startOfDay(for: now)
        let end = Calendar.current.startOfDay(for: dueDate)
        return Calendar.current.dateComponents([.day], from: start, to: end).day
    }

    /// How much of the interval is used up, 0 to 1. Whichever comes first, miles or time.
    func used(odometer: Int, now: Date = .now) -> Double? {
        var fractions: [Double] = []
        if let intervalMiles, intervalMiles > 0, let lastMiles {
            fractions.append(Double(odometer - lastMiles) / Double(intervalMiles))
        }
        if let dueDate, let lastDate {
            let total = dueDate.timeIntervalSince(lastDate)
            if total > 0 { fractions.append(now.timeIntervalSince(lastDate) / total) }
        }
        guard let worst = fractions.max() else { return nil }
        return min(max(worst, 0), 1)
    }

    func status(odometer: Int, now: Date = .now) -> Status {
        let miles = milesLeft(odometer: odometer)
        let days = daysLeft(now: now)
        if miles == nil && days == nil { return .notSetUp }
        if (miles ?? 1) <= 0 || (days ?? 1) <= 0 { return .overdue }
        if let used = used(odometer: odometer, now: now), used >= 0.85 { return .soon }
        return .ok
    }
}

/// A fact about your car that you typed in, like "Tire pressure: 36 psi".
struct CarDetail: Codable, Identifiable, Equatable {
    var id = UUID()
    var label: String
    var value: String
}

struct CarProfile: Codable, Equatable {
    var trim = ""
    var color = ""
    var plate = ""
    var vin = ""
    var odometer = 0
    var odometerUpdated = Date.now
    var maintenance: [MaintenanceItem] = []
    var details: [CarDetail] = []

    var oilChange: MaintenanceItem? { maintenance.first { $0.isOilChange } }
    var otherMaintenance: [MaintenanceItem] { maintenance.filter { !$0.isOilChange } }

    /// Example numbers so the demo dashboard isn't empty. They're placeholders for the
    /// owner's own values; edit them to match your owner's manual and odometer.
    static var demo: CarProfile {
        let day: TimeInterval = 86_400
        return CarProfile(
            trim: "",
            color: "WR Blue Pearl",
            plate: "",
            vin: "",
            odometer: 18_240,
            odometerUpdated: .now,
            maintenance: [
                MaintenanceItem(name: "Oil change", symbol: "drop.fill", isOilChange: true,
                                intervalMiles: 6_000, intervalMonths: 6,
                                lastMiles: 13_960, lastDate: .now - 101 * day),
                MaintenanceItem(name: "Tire rotation", symbol: "circle.circle",
                                intervalMiles: 6_000, lastMiles: 13_960),
                MaintenanceItem(name: "Engine air filter", symbol: "wind",
                                intervalMiles: 15_000, lastMiles: 4_100),
                MaintenanceItem(name: "Wiper blades", symbol: "windshield.front.and.wiper",
                                intervalMonths: 12, lastDate: .now - 300 * day),
            ],
            details: [
                CarDetail(label: "Engine", value: "2.4L turbo boxer"),
                CarDetail(label: "Drive", value: "AWD"),
            ]
        )
    }
}

/// Your car's profile, saved to a small file on the phone.
@Observable
final class CarProfileStore {
    var profile: CarProfile {
        didSet { save() }
    }

    private let fileURL = URL.documentsDirectory.appending(path: "car-profile.json")

    init() {
        if let data = try? Data(contentsOf: fileURL),
           let saved = try? JSONDecoder().decode(CarProfile.self, from: data) {
            profile = saved
        } else {
            profile = .demo
        }
    }

    func updateOdometer(_ miles: Int) {
        profile.odometer = miles
        profile.odometerUpdated = .now
    }

    /// Called when a guided oil change finishes: restart its count from today.
    func markOilChangeDone() {
        guard let index = profile.maintenance.firstIndex(where: \.isOilChange) else { return }
        profile.maintenance[index].lastMiles = profile.odometer
        profile.maintenance[index].lastDate = .now
    }

    private func save() {
        do {
            try JSONEncoder().encode(profile).write(to: fileURL)
        } catch {
            print("Carvis couldn't save the car profile: \(error)")
        }
    }
}
