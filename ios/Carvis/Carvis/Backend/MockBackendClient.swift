import Foundation

/// A fake backend with a hardcoded 12-step oil change for the visual step guide.
/// It follows the same contract the real server will.
/// It deliberately contains no torque values, oil amounts, or intervals: those must come
/// from the WRX service manual, and the oil section isn't loaded yet.
struct MockBackendClient: BackendClient {

    func send(_ request: StepRequest) async throws -> StepResponse {
        let current = request.stepNumber

        switch request.utterance {
        case nil:
            // No utterance means "begin": return step 1.
            return response(forStep: 1, spoken: steps[0].spoken, advance: true, intent: "start")

        case "repeat":
            let number = clamp(current)
            return response(forStep: number, spoken: steps[number - 1].spoken, advance: false, intent: "repeat")

        case "why":
            let number = clamp(current)
            return response(forStep: number, spoken: steps[number - 1].why, advance: false, intent: "why")

        default:
            // Treat anything else as "next".
            if current >= steps.count {
                return doneResponse(sessionID: request.sessionID)
            }
            let number = current + 1
            return response(forStep: number, spoken: steps[number - 1].spoken, advance: true, intent: "next")
        }

        // Builds a response for one step. Kept inside send(_:) so it can use the session ID.
        func response(forStep number: Int, spoken: String, advance: Bool, intent: String) -> StepResponse {
            let step = steps[number - 1]
            let intentTrace = TraceEntry(tool: "intent_classifier", input: request.utterance ?? "(start)", result: intent, ms: 18)
            return StepResponse(
                sessionID: request.sessionID,
                stepNumber: number,
                totalSteps: steps.count,
                spokenText: spoken,
                displayText: step.display,
                advance: advance,
                safetyGate: step.safetyGate,
                checkpoint: step.checkpoint,
                confidence: 0.94,
                trace: [intentTrace] + step.trace,
                done: false,
                summary: nil
            )
        }
    }

    private func clamp(_ number: Int) -> Int {
        min(max(number, 1), steps.count)
    }

    private func doneResponse(sessionID: String) -> StepResponse {
        StepResponse(
            sessionID: sessionID,
            stepNumber: steps.count,
            totalSteps: steps.count,
            spokenText: "Oil change done. I logged it. Check your maintenance schedule for when the next one is due.",
            displayText: "Oil change done",
            advance: true,
            safetyGate: false,
            checkpoint: Checkpoint(type: .none, prompt: ""),
            confidence: 0.97,
            trace: [
                TraceEntry(tool: "service_log", input: "write oil change record", result: "saved", ms: 34),
                TraceEntry(tool: "schedule_lookup", input: "next oil change", result: "not in loaded manual", ms: 27)
            ],
            done: true,
            summary: Summary(
                serviceLog: ServiceLog(
                    date: Date.now.formatted(date: .abbreviated, time: .omitted),
                    mileage: 42_318,
                    oil: "Oil and amount per service manual",
                    filter: "New oil filter"
                ),
                nextService: "Check your maintenance schedule for the next oil change.",
                nextStep: NextStep(
                    title: "Tire rotation",
                    detail: "Carvis will walk you through it.",
                    cta: "Coming soon"
                )
            )
        )
    }

    // MARK: - The 12 steps

    private struct MockStep {
        let display: String
        let spoken: String
        let why: String
        var safetyGate = false
        var checkpoint = Checkpoint(type: .none, prompt: "")
        let trace: [TraceEntry]
    }

    private let steps: [MockStep] = [
        MockStep(
            display: "Park on level ground. Turn the engine off and set the parking brake.",
            spoken: "Park on level ground. Turn the engine off and set the parking brake. If you just drove, let the engine cool for 30 minutes.",
            why: "Level ground keeps the car from rolling and gives an accurate oil reading. A cool engine means the oil won't burn you.",
            checkpoint: Checkpoint(type: .voice, prompt: "Say next when the car is parked."),
            trace: [
                TraceEntry(tool: "vehicle_lookup", input: "profile vehicle", result: "found", ms: 38),
                TraceEntry(tool: "manual_lookup", input: "oil change prep", result: "level surface, engine cool", ms: 61)
            ]
        ),
        MockStep(
            display: "The car must rest on jack stands before you go under it.",
            spoken: "Lift the front with a jack at the front lift point, then lower it onto two jack stands. Never go under a car held up only by a jack.",
            why: "Jacks can slip or slowly lose pressure. Jack stands lock in place, so they hold the car if the jack fails.",
            safetyGate: true,
            checkpoint: Checkpoint(type: .voice, prompt: "Say next when the car is on jack stands."),
            trace: [
                TraceEntry(tool: "safety_check", input: "lift method", result: "jack stands required", ms: 12),
                TraceEntry(tool: "manual_lookup", input: "front lift point", result: "see owner's manual lift points", ms: 54)
            ]
        ),
        MockStep(
            display: "Get your tools: a wrench for the drain plug, an oil filter wrench, a drain pan, a new filter, a new drain plug gasket, and the oil your service manual calls for.",
            spoken: "Get your tools: a wrench for the drain plug, an oil filter wrench, a drain pan, a new filter, a new drain plug gasket, and the oil your service manual calls for.",
            why: "Having everything in reach means you won't leave the car while the oil is draining.",
            trace: [
                TraceEntry(tool: "parts_lookup", input: "oil spec", result: "not in loaded manual", ms: 47),
                TraceEntry(tool: "parts_lookup", input: "drain plug", result: "replace gasket", ms: 39)
            ]
        ),
        MockStep(
            display: "Slide the drain pan under the engine, right below the drain plug.",
            spoken: "Slide the drain pan under the engine, right below the drain plug.",
            why: "The plug sits at the lowest point of the oil pan, so the oil comes straight down.",
            trace: [
                TraceEntry(tool: "manual_lookup", input: "drain plug location", result: "lowest point of oil pan", ms: 44)
            ]
        ),
        MockStep(
            display: "Oil can be hot. Wear gloves and eye protection.",
            spoken: "Put on gloves and eye protection. Turn the drain plug counterclockwise with your wrench, then finish by hand and let the oil drain.",
            why: "Hot oil can burn skin. Finishing by hand keeps the plug from dropping into the pan.",
            safetyGate: true,
            checkpoint: Checkpoint(type: .voice, prompt: "Say next when the oil is draining."),
            trace: [
                TraceEntry(tool: "safety_check", input: "hot fluid", result: "gloves and eye protection", ms: 10),
                TraceEntry(tool: "manual_lookup", input: "drain plug direction", result: "counterclockwise to loosen", ms: 29)
            ]
        ),
        MockStep(
            display: "Wait until the oil slows to a drip. This takes about 10 minutes.",
            spoken: "Wait until the oil slows to a drip. This takes about 10 minutes.",
            why: "Draining fully removes the old oil and the dirt it carries.",
            checkpoint: Checkpoint(type: .vision, prompt: "Show me the drain plug opening."),
            trace: [
                TraceEntry(tool: "timer", input: "drain time", result: "about 10 min", ms: 5),
                TraceEntry(tool: "vision_check", input: "drain opening", result: "pending camera", ms: 0)
            ]
        ),
        MockStep(
            display: "Wipe the drain plug, fit the new gasket, and thread it in by hand. Tighten to the torque in your service manual.",
            spoken: "Wipe the drain plug, fit the new gasket, and thread it in by hand. Then tighten it to the torque in your service manual.",
            why: "A new gasket seals the plug. Threading by hand first keeps you from stripping the oil pan threads.",
            trace: [
                TraceEntry(tool: "torque_lookup", input: "drain plug", result: "not in loaded manual", ms: 52)
            ]
        ),
        MockStep(
            display: "Move the drain pan under the oil filter. Turn the filter counterclockwise with the filter wrench to remove it.",
            spoken: "Move the drain pan under the oil filter. Turn the filter counterclockwise with the filter wrench to remove it.",
            why: "The old filter is full of oil, so keep the pan under it as it comes off.",
            trace: [
                TraceEntry(tool: "manual_lookup", input: "oil filter location", result: "see service manual", ms: 48)
            ]
        ),
        MockStep(
            display: "Wipe the filter mount clean. Rub fresh oil on the new filter's seal, then screw it on hand-tight plus three-quarters of a turn.",
            spoken: "Make sure the old seal came off with the old filter. Wipe the mount clean, rub fresh oil on the new filter's seal, then screw it on hand-tight plus three-quarters of a turn.",
            why: "Fresh oil helps the seal seat evenly. Overtightening makes the filter hard to remove next time.",
            trace: [
                TraceEntry(tool: "manual_lookup", input: "filter install", result: "hand-tight + 3/4 turn", ms: 41)
            ]
        ),
        MockStep(
            display: "Clear tools from under the car. Lift it off the jack stands, remove them, and lower the car.",
            spoken: "Clear your tools from under the car. Lift it off the jack stands, remove them, and lower the car to the ground.",
            why: "The oil level only reads correctly when the car is level on its wheels.",
            trace: [
                TraceEntry(tool: "safety_check", input: "lowering vehicle", result: "area clear required", ms: 9)
            ]
        ),
        MockStep(
            display: "Open the hood and remove the oil filler cap. Pour in a little less than the oil amount in your service manual, then replace the cap.",
            spoken: "Open the hood and remove the oil filler cap. Pour in a little less than the oil amount in your service manual, then put the cap back on.",
            why: "Starting a little under keeps you from overfilling, and you'll top up after checking.",
            trace: [
                TraceEntry(tool: "parts_lookup", input: "oil capacity", result: "not in loaded manual", ms: 33)
            ]
        ),
        MockStep(
            display: "Run the engine for 30 seconds and check for leaks. Turn it off, wait 2 minutes, and check the dipstick. Top up to the full mark.",
            spoken: "Start the engine and let it run for 30 seconds while you check for leaks. Turn it off, wait 2 minutes, then check the dipstick and top up to the full mark.",
            why: "Running the engine fills the new filter, which lowers the oil level a little.",
            checkpoint: Checkpoint(type: .voice, prompt: "Say next when the dipstick reads full."),
            trace: [
                TraceEntry(tool: "manual_lookup", input: "level check", result: "engine off, wait 2 min", ms: 36)
            ]
        )
    ]
}
