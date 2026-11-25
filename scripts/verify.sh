#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="python3"
if [[ -x .venv/bin/python ]]; then
  PYTHON=".venv/bin/python"
fi

# Long local runs can corrupt work in progress when the disk fills (docs/development-workflow.md,
# "Local run hygiene"). Read-only; CARVIS_MIN_FREE_GIB changes the minimum.
echo "== Disk space =="
bash scripts/check-disk-space.sh

echo "== Backend tests =="
"$PYTHON" -m pytest backend/tests -q

echo "== Python compilation =="
"$PYTHON" -m compileall -q backend

echo "== Conversation state machine =="
swiftc -module-cache-path /tmp/carvis-conversation-swift-cache \
  ios/Carvis/Carvis/Assistant/ConversationMachine.swift \
  ios/Tests/ConversationMachineTests.swift \
  -o /tmp/carvis-conversation-tests
/tmp/carvis-conversation-tests

echo "== Voice session controller =="
swiftc -module-cache-path /tmp/carvis-voice-swift-cache \
  ios/Carvis/Carvis/Assistant/VoiceSessionController.swift \
  ios/Tests/VoiceSessionControllerTests.swift \
  -o /tmp/carvis-voice-session-tests
/tmp/carvis-voice-session-tests

echo "== Phone audio route policy =="
swiftc -module-cache-path /tmp/carvis-phone-route-swift-cache \
  ios/Carvis/Carvis/Speech/PhoneAudioRoutePolicy.swift \
  ios/Tests/PhoneAudioRoutePolicyTests.swift \
  -o /tmp/carvis-phone-route-tests
/tmp/carvis-phone-route-tests

echo "== Wake phrase matcher =="
swiftc -module-cache-path /tmp/carvis-wake-swift-cache \
  ios/Carvis/Carvis/Glasses/WakePhraseMatcher.swift \
  ios/Tests/WakePhraseMatcherTests.swift \
  -o /tmp/carvis-wake-tests
/tmp/carvis-wake-tests

echo "== SpacetimeDB TypeScript =="
if [[ ! -x backend/spacetimedb/module/node_modules/.bin/tsc ]]; then
  echo "Missing module dependencies. Run: npm ci --prefix backend/spacetimedb/module" >&2
  exit 1
fi
backend/spacetimedb/module/node_modules/.bin/tsc \
  --project backend/spacetimedb/module/tsconfig.json --noEmit

echo "== Apple configuration =="
plutil -lint \
  ios/Carvis/Carvis-Info.plist \
  ios/Carvis/Carvis.entitlements \
  ios/Carvis/Carvis.xcodeproj/project.pbxproj

echo "== iOS simulator build =="
if xcodebuild -version >/dev/null 2>&1; then
  xcodebuild -project ios/Carvis/Carvis.xcodeproj -scheme Carvis \
    -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
else
  echo "SKIP: full Xcode is unavailable; Command Line Tools cannot build the iOS app."
fi

echo "== Repository structure =="
test ! -d frontend
test ! -d carvis-module
test -f backend/spacetimedb/module/src/index.ts
bash scripts/check-docs.sh

echo "== Review packet tests =="
bash scripts/tests/review-scope-test.sh

echo "== Workflow script tests =="
bash scripts/tests/check-disk-space-test.sh

echo "== CI plan and gate script tests =="
PYTHON="$PYTHON" bash scripts/tests/ci-scripts-test.sh
"$PYTHON" scripts/tests/ci-workflow-test.py

echo "All available repository checks passed."
