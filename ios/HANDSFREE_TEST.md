# Hands-free test

This proves the whole loop on the real iPhone and Ray-Ban Meta glasses. A stage counts only
if it was seen on the glasses and appears in the logs. Passing tests on a computer doesn't
count here.

## 1. Setup (once)

1. Put `VAPI_PRIVATE_KEY=...` in `backend/.env`, using your editor. Never paste it in chat.
2. Copy `Carvis/Config/VapiConfig.example.plist` to `VapiConfig.plist` and fill in `PublicKey`.
3. Start the server and keep its log:

   ```sh
   cd backend
   CARVIS_QDRANT_COLLECTION=carvis_specs_v2 ../.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 2>&1 | tee ../server.log
   ```

4. In another terminal, run `ngrok http 8000` and copy its `https://` address.
5. Create the assistant, then put the printed ID in `VapiConfig.plist` as `AssistantID`:

   ```sh
   .venv/bin/python backend/vapi_assistant.py --public-url https://YOUR-NGROK-ADDRESS
   ```

6. In Wearables Developer Center, enable the Speech capability if the app reports it's
   unavailable.
7. Build and install. In the app, enter your car's year, make, and model.

The ngrok address changes each time it restarts unless you have a reserved one. Run step 5
again if it changes, with `VAPI_ASSISTANT_ID` set in `backend/.env` so the same assistant is
updated.

## 2. Capture the phone's log

With the phone unlocked:

```sh
xcrun devicectl device process launch --device <UDID> --terminate-existing --console \
  com.gabrieleisenbergpersonalteam.Carvis 2>&1 | tee app.log
```

## 3. Stages, in order

| # | Do | Pass when | Log line |
|---|---|---|---|
| 1 | Start a job | The row says it's listening through your glasses | `listening through glasses speech` |
| 2 | Say "Hey Carvis" | Carvis greets you by name **in the glasses** | `wake heard`, `route check: ready`, `microphone live` |
| 3 | Confirm your car aloud | Carvis accepts it | server `vehicle_confirmed` |
| 4 | Ask what you're looking at | The tick plays only while it works, then Carvis names the part | `captured N bytes`, `photo identified`, server `vision_done` |
| 5 | Ask for the ride-height tolerance | The answer matches the manual | server `lookup_answered` |
| 6 | Ask a follow-up | It uses what was already established | server trace |
| 7 | Talk over Carvis | Carvis stops and listens | transcript in `app.log` |
| 8 | Turn the glasses' Bluetooth off, then on | The row says paused, then the call resumes. Nothing goes through the phone | `route changed`, `route check: ready` |
| 9 | Say goodbye, then "Hey Carvis" again | A new conversation starts, and the earlier facts are remembered | `shutdown complete`, then `wake heard` |

Also try "Hey Carvis, what's the ride-height tolerance?" in one breath. The question must be
answered once, with no greeting in front of it.

## 4. Five touch-free runs

After arming, do not touch the phone for any of the five runs. Each run needs stages 2 to 5
and a clean end. Then score them:

```sh
python3 ios/Tests/handsfree_report.py app.log server.log
```

The script reports only what's in the logs, and needs 5 complete runs. It counts taps on the
voice and End controls; watch the phone for any other touch.

## 5. If the camera fails during a call

This is the main unknown: whether a glasses photo works while Bluetooth call audio is
running. If it fails, save the `camera failed` line and the Meta error, and check Meta's
current documentation. Never replace the glasses' camera or microphone with the phone's.

## 6. Locked screen and background (separate)

Test these on their own, and record what happens. This build arms the wake phrase in the
foreground only, so don't claim lock-screen wake.

- Lock the phone while listening: expected to pause.
- Lock the phone during a call: record whether audio continues.
- Unlock: record whether it recovers without a touch.
