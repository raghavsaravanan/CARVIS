import Foundation
import Observation

/// The list of finished jobs. It's saved to a small file on the phone,
/// so it's still there after you close the app.
@Observable
final class JobHistory {
    /// Newest first.
    private(set) var records: [JobRecord] = []

    private let fileURL = URL.documentsDirectory.appending(path: "job-history.json")

    init() {
        load()
    }

    func add(_ record: JobRecord) {
        records.insert(record, at: 0)
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let saved = try? JSONDecoder().decode([JobRecord].self, from: data)
        else { return }   // no file yet means no history yet
        records = saved
    }

    private func save() {
        do {
            let data = try JSONEncoder().encode(records)
            try data.write(to: fileURL)
        } catch {
            print("Carvis couldn't save job history: \(error)")
        }
    }
}
