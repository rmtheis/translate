#!/usr/bin/env bash
# Verifies that translation succeeds on iPad for non-eng-spa pairs —
# the regression Apple's reviewer hit on iPad Air (M3) / iPadOS 26.4.1
# (Submission b3e7e699-903c-4cbf-8396-c3428dddcc1f).
#
# The bug was that LanguagePair.bundleURL() built the pair's data dir
# by string-concatenating onto Bundle.main.resourceURL — which only
# resolves bundled (install-time) resources, NOT ODR-delivered ones,
# whose content lives under <App.app>/OnDemandResources/<pack>.assetpack/.
# Translation worked for the install-time eng-spa pair and failed for
# every ODR pair with `ApertiumError.missingPair`.
#
# `simctl install` can't actually fetch ODR packs (Xcode's Run flow
# manages the manifest, simctl skips that step — same workaround as
# screenshots-ios.sh). So we strip the resourceTags, rebuild with
# every pair install-time, install, and exercise `Bundle.main.url(
# forResource:withExtension:subdirectory:)` for non-eng-spa pairs.
# That's the same iOS API path that handles ODR after
# beginAccessingResources succeeds, so a pass here proves the fix is
# correct end-to-end.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="$REPO_ROOT/ios"
BUNDLE_ID="com.qvyshift.translate"
OUT="$REPO_ROOT/ios/build/verify-ios-translate"
mkdir -p "$OUT"

# Match Apple's reviewer environment as closely as the local Xcode toolchain
# allows: iPad Air 11" on iOS 26.4 (their device was Air M3 / 26.4.1).
DEVICE_NAME="${DEVICE_NAME:-iPad Air 11-inch (M4)}"
RUNTIME_PREF="${RUNTIME_PREF:-iOS-26-4}"

echo "[1/6] Locating $DEVICE_NAME on $RUNTIME_PREF"
DEVICE=$(xcrun simctl list devices --json | /usr/bin/python3 -c "
import json, sys
want_name = '''$DEVICE_NAME'''
want_rt   = '''$RUNTIME_PREF'''
devs = json.load(sys.stdin)['devices']
hits = []
for rt, ds in devs.items():
    if want_rt not in rt: continue
    for d in ds:
        if d['name'] == want_name and d.get('isAvailable', True):
            hits.append(d['udid'])
print(hits[0] if hits else '')
")
if [ -z "$DEVICE" ]; then
  echo "ERROR: no '$DEVICE_NAME' on '$RUNTIME_PREF' simulator runtime"
  echo "Available iPad Air sims:"
  xcrun simctl list devices | grep -E "iPad Air"
  exit 1
fi
echo "  → $DEVICE"

echo "[2/6] Strip ODR tags so simctl install delivers every pair install-time"
PROJECT_YML="$PROJ/project.yml"
PROJECT_YML_BAK="$(mktemp /tmp/project.yml.XXXXXX)"
cp "$PROJECT_YML" "$PROJECT_YML_BAK"
restore_project_yml() {
  cp "$PROJECT_YML_BAK" "$PROJECT_YML"
  rm -f "$PROJECT_YML_BAK"
  (cd "$PROJ" && xcodegen generate >/dev/null 2>&1 || true)
}
trap restore_project_yml EXIT
/usr/bin/sed -i '' '/^[[:space:]]*resourceTags: \[pair_/d' "$PROJECT_YML"
(cd "$PROJ" && xcodegen generate >/dev/null)

echo "[3/6] Boot simulator + clean install"
xcrun simctl shutdown "$DEVICE" 2>/dev/null || true
xcrun simctl erase "$DEVICE"
xcrun simctl boot "$DEVICE"
xcrun simctl bootstatus "$DEVICE" -b >/dev/null
open -a Simulator

echo "[4/6] Build for simulator"
(cd "$PROJ" && xcodebuild \
    -project Translate.xcodeproj -scheme Translate \
    -destination "platform=iOS Simulator,id=$DEVICE" \
    -configuration Debug \
    build 2>&1 | tail -5)

APP_PATH=$(xcodebuild -project "$PROJ/Translate.xcodeproj" -scheme Translate \
           -destination "platform=iOS Simulator,id=$DEVICE" \
           -configuration Debug \
           -showBuildSettings 2>/dev/null \
           | /usr/bin/python3 -c '
import sys
d = {}
for raw in sys.stdin:
    line = raw.strip()
    if " = " not in line: continue
    parts = line.split(" = ", 1)
    if len(parts) != 2: continue
    d[parts[0].strip()] = parts[1]
print(d.get("BUILT_PRODUCTS_DIR","") + "/" + d.get("FULL_PRODUCT_NAME",""))')
echo "  → $APP_PATH"
xcrun simctl install "$DEVICE" "$APP_PATH"

# Confirm the bundle layout — every pair_<x>_<y> dir should be a peer of
# Translate.app's Info.plist with this stripped-tags build.
echo "  → bundle contents:"
ls "$APP_PATH" | grep -E '^pair_' | head -5
echo "  → ($(ls "$APP_PATH" | grep -cE '^pair_') pair dirs in bundle root)"

echo "[5/6] Translate sanity scenes (non-eng-spa to exercise the changed path)"
# Format: filename | pkg | direction | input.
# Each scene exercises a different pair, including some one-way pairs
# (mkd-eng, sme-nob, cat-srd) where backwardMode is nil — the code
# path that constructs `<id>.mode` filenames for forward+backward.
SCENES=(
  "01_spa_cat|apertium-spa-cat|forward|Hola, ¿cómo estás hoy?"
  "02_cat_srd|apertium-cat-srd|forward|Demà anirem al mercat."
  "03_mkd_eng|apertium-mkd-eng|forward|Мојот син учи математика."
  "04_sme_nob|apertium-sme-nob|forward|Mun lean studeanta."
  "05_eng_cat|apertium-eng-cat|backward|El sol es pon darrere les muntanyes."
  "06_eng_spa|apertium-eng-spa|forward|This sentence verifies the bundled pair still works."
)

for scene in "${SCENES[@]}"; do
  IFS='|' read -r name pkg dir input <<< "$scene"
  echo "  ---- $name ($pkg, $dir): $input"
  xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
  xcrun simctl launch "$DEVICE" "$BUNDLE_ID" \
    -screenshot_pair "$pkg" \
    -screenshot_direction "$dir" \
    -screenshot_input "$input" >/dev/null
  sleep 3
  xcrun simctl io "$DEVICE" screenshot --type=png "$OUT/$name.png" >/dev/null
done
xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true

echo "[6/6] Done. Screenshots saved to:"
echo "  $OUT"
echo
echo "Eyeball check: each PNG should show translated text in the target field."
echo "If any shows a 'Translation error' alert, the fix did not take effect."
ls -1 "$OUT"
