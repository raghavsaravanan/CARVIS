import SwiftUI

/// Every color, corner size, and key measurement in one place.
/// The look: a cool grey garage floor, white "bento" cards, one dark stat tile,
/// near-black pill buttons, and the car's own WR Blue as the accent.
enum Theme {
    // Surfaces
    static let pearl = Color(hex: 0xECEEF1)      // the background
    static let sky = Color(hex: 0xF7F8FA)        // the lighter part of the background
    static let card = Color.white                // bento cards
    static let tile = Color(hex: 0x15171B)       // the dark stat tile

    // Color with meaning
    static let accent = Color(hex: 0x2152E0)     // WR Blue: progress, selection, links
    static let lime = Color(hex: 0xC8F25A)       // progress on the dark tile
    static let warning = Color(hex: 0xD08C2E)    // due soon
    static let safetyRed = Color(hex: 0xD9534F)  // overdue and safety warnings only
    static let ink = Color(hex: 0x111418)        // all text and the main buttons

    static let inkSecondary = ink.opacity(0.6)
    static let inkTertiary = ink.opacity(0.38)

    // Bigger, more important things get rounder corners.
    enum Radius {
        static let hero: CGFloat = 32   // big panels
        static let card: CGFloat = 28   // bento cards
        static let small: CGFloat = 18  // fields and small tiles inside cards
    }

    // Big targets for greasy hands.
    static let buttonHeight: CGFloat = 64
    static let primaryButtonHeight: CGFloat = 72

    // Large Title is 34pt by default and grows with the user's text size setting.
    static let instructionFont = Font.system(.largeTitle, weight: .semibold)
    static let buttonFont = Font.title3.weight(.semibold)

    /// Big thin numbers, like a car's instrument cluster.
    static func number(_ size: CGFloat) -> Font {
        .system(size: size, weight: .light)
    }
}

extension Color {
    /// Lets us write colors as hex, like Color(hex: 0x2152E0).
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}
