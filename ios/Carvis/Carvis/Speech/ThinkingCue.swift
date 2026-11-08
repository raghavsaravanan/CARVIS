import AVFoundation

/// A soft repeating tick through the glasses while Carvis is actually doing something:
/// taking a photo, uploading it, or identifying the part. Never played otherwise, and
/// never speech, so it adds no scripted words to the conversation.
@MainActor
final class ThinkingCue {
    private var player: AVAudioPlayer?

    func start() {
        guard player == nil else { return }
        do {
            let player = try AVAudioPlayer(data: Self.tickWAV())
            player.numberOfLoops = -1
            player.volume = 0.35
            player.play()
            self.player = player
        } catch {
            print("[Cue] couldn't play: \(error)")
        }
    }

    func stop() {
        player?.stop()
        player = nil
    }

    /// 0.9 seconds of 16-bit mono audio: one short, faded tone, then silence.
    private static func tickWAV() -> Data {
        let rate = 16_000.0
        let total = Int(rate * 0.9)
        let toneLength = Int(rate * 0.09)
        var samples = [Int16](repeating: 0, count: total)
        for i in 0..<toneLength {
            let progress = Double(i) / Double(toneLength)
            let envelope = sin(.pi * progress)
            samples[i] = Int16(envelope * 9_000 * sin(2 * .pi * 720 * Double(i) / rate))
        }
        let bytes = UInt32(total * 2)
        var data = Data()
        func append(_ text: String) { data.append(Data(text.utf8)) }
        func append32(_ value: UInt32) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
        func append16(_ value: UInt16) { withUnsafeBytes(of: value.littleEndian) { data.append(contentsOf: $0) } }
        append("RIFF"); append32(36 + bytes); append("WAVE")
        append("fmt "); append32(16); append16(1); append16(1)
        append32(UInt32(rate)); append32(UInt32(rate) * 2); append16(2); append16(16)
        append("data"); append32(bytes)
        samples.withUnsafeBufferPointer { data.append(Data(buffer: $0)) }
        return data
    }
}
