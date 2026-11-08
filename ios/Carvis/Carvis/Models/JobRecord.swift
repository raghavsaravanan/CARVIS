import Foundation

/// One finished job, saved on the phone for the service history.
struct JobRecord: Codable, Identifiable {
    var id = UUID()
    let name: String        // what you named the job, like "Sunday oil change"
    let finishedAt: Date
    let summary: Summary    // the summary the backend sent at the end
}
