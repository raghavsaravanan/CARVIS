import SwiftUI

/// Hardware diagnostic: real glasses transcripts and real wakeDetected events only.
struct WakeTestView: View {
    @Environment(GlassesController.self) private var glasses
    @State private var receivedEvents = 0
    @State private var lastEvent: CarvisWakeListener.WakeEvent?
    @State private var showCamera = false
    @State private var isCapturing = false
    @State private var captureResult = "No capture attempted"

    var body: some View {
        let wake = glasses.wakeListener
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("Glasses wake test").font(.largeTitle.bold())
                Text("Foreground only. Locking the phone pauses listening. This test never uses the phone microphone or starts Vapi.")
                    .foregroundStyle(.secondary)
                if !glasses.isConnected {
                    Button("Connect glasses", action: glasses.connect)
                }
                GroupBox("Meta glasses microphone") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("State: \(wake.state.rawValue)").font(.headline)
                            .accessibilityIdentifier("wakeState")
                        Text(wake.message)
                        Text("Microphone permission: \(wake.hasMicrophonePermission ? "granted" : "not yet granted")")
                        Text("Recognition locale: \(wake.locale ?? "not reported")")
                        Text("Arm opens Meta AI if glasses microphone permission is needed.")
                            .font(.footnote).foregroundStyle(.secondary)
                        HStack {
                            if wake.isArmed {
                                Button("Disarm", action: glasses.disarmWakeListener)
                                if wake.state == .failed || wake.state == .waitingForSession || wake.state == .paused {
                                    Button("Retry listening", action: glasses.armWakeListener)
                                        .disabled(!glasses.isConnected)
                                }
                            } else {
                                Button("Arm wake listener", action: glasses.armWakeListener)
                                    .disabled(!glasses.isConnected)
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        if let error = wake.errorMessage {
                            Text(error).foregroundStyle(.red).textSelection(.enabled)
                        }
                        if let error = glasses.errorMessage {
                            Text(error).foregroundStyle(.red).textSelection(.enabled)
                        }
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("Speak: Hi Carvis or Hey Carvis") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("wakeDetected events received: \(receivedEvents)")
                            .font(.title3.bold()).accessibilityIdentifier("wakeEventCount")
                        Text("Listener total: \(wake.detectionCount)")
                        if let lastEvent {
                            Text("Detected: \(lastEvent.phrase)")
                            Text(lastEvent.detectedAt, style: .time)
                        }
                        Text("Last glasses transcript (\(wake.transcriptIsFinal ? "final" : "partial")):")
                        Text(wake.lastTranscript.isEmpty ? "Waiting for speech…" : wake.lastTranscript)
                            .textSelection(.enabled).accessibilityIdentifier("wakeTranscript")
                        Text("Only final transcripts starting with a wake phrase count. Allow two seconds between attempts. Transcripts stay in memory and are cleared when disarmed.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
                GroupBox("Camera concurrency check") {
                    VStack(alignment: .leading, spacing: 12) {
                        Toggle("Camera preview", isOn: $showCamera)
                            .onChange(of: showCamera) { _, enabled in
                                if enabled { glasses.startPreview() } else { glasses.stopPreview() }
                            }
                        Text("Camera state: \(String(describing: glasses.streamState))")
                        if showCamera, let frame = glasses.frame {
                            Image(uiImage: frame).resizable().scaledToFit().frame(maxHeight: 240)
                        }
                        Button(isCapturing ? "Capturing…" : "Capture test JPEG") { capture() }
                            .disabled(!glasses.isLive || isCapturing)
                        Text(captureResult).font(.footnote)
                        Text("The JPEG stays in memory; nothing is uploaded or saved. Turning preview off restarts the shared session in speech-only mode.")
                            .font(.footnote).foregroundStyle(.secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                }
            }.padding(20)
        }
        .navigationTitle("Wake test")
        .onReceive(wake.wakeDetected) { event in
            receivedEvents += 1
            lastEvent = event
        }
        .onDisappear {
            // A diagnostic screen does not leave a microphone armed invisibly.
            glasses.disarmWakeListener()
            glasses.stopPreview()
        }
    }

    private func capture() {
        isCapturing = true
        captureResult = "Waiting for a real JPEG from the glasses"
        Task {
            defer { isCapturing = false }
            do {
                let data = try await glasses.capturePhoto()
                captureResult = "Captured \(data.count) JPEG bytes at \(Date().formatted(date: .omitted, time: .standard))"
            } catch {
                captureResult = "Capture failed: \(error.localizedDescription)"
            }
        }
    }
}
