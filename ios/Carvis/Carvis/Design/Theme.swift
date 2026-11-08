import SwiftUI

/// Every color, corner size, and key measurement in one place.
enum Theme {
    // The five palette colors.
    static let pearl = Color(hex: 0xF8F6F1)      // base
    static let sky = Color(hex: 0xD6E6F5)        // base
    static let amber = Color(hex: 0xD08C2E)      // the one accent: progress, main button, selection
    static let safetyRed = Color(hex: 0xD9534F)  // safety warnings only
    static let ink = Color(hex: 0x1B2430)        // all text

    static let inkSecondary = ink.opacity(0.68)

    // Bigger, more important things get rounder corners.
    enum Radius {
        static let hero: CGFloat = 36   // step instruction panel
        static let card: CGFloat = 24   // vehicle, summary, safety banner
        static let small: CGFloat = 18  // camera placeholder
    }

    // Big targets for greasy hands.
    static let buttonHeight: CGFloat = 64
    static let primaryButtonHeight: CGFloat = 72

    // Large Title is 34pt by default and grows with the user's text size setting.
    static let instructionFont = Font.system(.largeTitle, weight: .semibold)
    static let buttonFont = Font.title3.weight(.semibold)
}

extension Color {
    /// Lets us write colors as hex, like Color(hex: 0xD08C2E).
    init(hex: UInt32) {
        self.init(
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255
        )
    }
}
