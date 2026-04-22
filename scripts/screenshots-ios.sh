#!/usr/bin/env bash
# Automated App Store screenshots for iPhone 6.9" (iPhone 16 Pro Max).
#
# For each entry in SCENES, launches the Translate app with three
# launch arguments the app honors at runtime:
#   -screenshot_pair       <apertium-xxx-yyy>
#   -screenshot_direction  forward | backward
#   -screenshot_input      "<text>"
#
# The app pre-selects the pair, types the input, and auto-runs the
# translate pipeline so the UI is settled before we capture.
#
# Prereq: an iPhone 16 Pro Max simulator is installed. Any OS works,
# but we prefer iOS 18+ for modern SwiftUI rendering fidelity.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="$REPO_ROOT/ios"
BUNDLE_ID="com.qvyshift.translate"

# ---------------------------------------------------------------------------
# Device selection.
#
# Default is iPhone 16 Pro Max (6.9" App Store tier). Pass KIND=ipad to
# target iPad Pro 13-inch (M4) (13" App Store tier, 2064×2752). Any
# other device name can be forced via DEVICE_NAME directly.
# ---------------------------------------------------------------------------
: "${KIND:=iphone}"
case "$KIND" in
  iphone) : "${DEVICE_NAME:=iPhone 16 Pro Max}";  OUT_SUBDIR=appstore-iphone-69 ;;
  ipad)   : "${DEVICE_NAME:=iPad Pro 13-inch (M4)}"; OUT_SUBDIR=appstore-ipad-13 ;;
  *) echo "unknown KIND: $KIND (expected iphone | ipad)"; exit 1 ;;
esac

OUT="$REPO_ROOT/screenshots/$OUT_SUBDIR"
mkdir -p "$OUT"

# Prefer the newest OS available for the selected device, but fall back
# to any runtime. Any iPhone 16 Pro Max renders at 1320×2868 (6.9"); any
# iPad Pro 13" M4 renders at 2064×2752 — both match App Store Connect's
# top-tier expected sizes.
pick_device() {
  local name="$1"
  # Already booted?
  local booted
  booted=$(xcrun simctl list devices --json \
    | /usr/bin/python3 -c "
import json,sys
devs = json.load(sys.stdin)['devices']
for rt, ds in devs.items():
    for d in ds:
        if d.get('state') == 'Booted' and d['name'] == '$name':
            print(d['udid']); sys.exit(0)
")
  if [ -n "$booted" ]; then echo "$booted"; return; fi
  # Pick an available one; any runtime is fine.
  local picked
  picked=$(xcrun simctl list devices --json \
    | /usr/bin/python3 -c "
import json,sys
devs = json.load(sys.stdin)['devices']
candidates = []
for rt, ds in devs.items():
    for d in ds:
        if d['name'] == '$name' and d.get('isAvailable', True):
            candidates.append((rt, d['udid']))
# Prefer the lexicographically-last runtime name (typically the newest).
candidates.sort()
print(candidates[-1][1] if candidates else '')
")
  if [ -z "$picked" ]; then
    echo "ERROR: no '$name' simulator found" >&2
    exit 1
  fi
  echo "$picked"
}

DEVICE=$(pick_device "$DEVICE_NAME")
echo "using $DEVICE_NAME ($DEVICE) → $OUT"

# Force a clean English locale + default orientation. `simctl erase`
# wipes the sim's data to factory state, which also resets
# AppleLanguages / AppleLocale to en_US and clears any user-side
# rotation preference. Cheap because the sim is either fresh or already
# used only for screenshot runs.
echo "resetting device to factory (English locale, portrait)…"
xcrun simctl shutdown "$DEVICE" 2>/dev/null || true
xcrun simctl erase "$DEVICE"
xcrun simctl boot "$DEVICE"
xcrun simctl bootstatus "$DEVICE" -b >/dev/null

# Foreground the Simulator window so the device renders (required for
# snapshot; headless boot doesn't produce a surface).
open -a Simulator

# ---------------------------------------------------------------------------
# Clean status bar — matches Android's emulator-screenshot-setup.sh intent.
# ---------------------------------------------------------------------------
xcrun simctl status_bar "$DEVICE" override \
  --time "12:00" \
  --dataNetwork wifi --wifiMode active --wifiBars 3 \
  --cellularMode notSupported \
  --batteryState charged --batteryLevel 100 \
  --operatorName "" >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# Build the app in Debug for the chosen sim; install.
#
# Screenshot builds bundle every pair install-time. The default
# project.yml carries `resourceTags:` on 26 of the 27 pairs so the
# release binary can use ODR — but `simctl install` doesn't register
# the ODR manifest with the simulator, so those fetches fail and every
# screenshot ends up showing the error alert. We strip the tags in a
# scratch copy of project.yml for the screenshot build only, and
# restore on exit.
# ---------------------------------------------------------------------------

PROJECT_YML="$PROJ/project.yml"
PROJECT_YML_BAK="$(mktemp /tmp/project.yml.XXXXXX)"
cp "$PROJECT_YML" "$PROJECT_YML_BAK"
restore_project_yml() {
  cp "$PROJECT_YML_BAK" "$PROJECT_YML"
  rm -f "$PROJECT_YML_BAK"
  (cd "$PROJ" && xcodegen generate >/dev/null)
}
trap restore_project_yml EXIT

echo "stripping ODR tags for screenshot build…"
# Drop every `resourceTags: [pair_*]` line, keeping the enclosing
# `- path:` entry so all pair folders still build into the bundle.
/usr/bin/sed -i '' '/^[[:space:]]*resourceTags: \[pair_/d' "$PROJECT_YML"

echo "regenerating Xcode project…"
(cd "$PROJ" && xcodegen generate >/dev/null)

echo "building…"
(cd "$PROJ" && xcodebuild \
    -project Translate.xcodeproj -scheme Translate \
    -destination "platform=iOS Simulator,id=$DEVICE" \
    -configuration Debug \
    build 2>&1 | tail -2)

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
if [ ! -d "$APP_PATH" ]; then
  echo "ERROR: app not found at $APP_PATH"; exit 1
fi
echo "installing $APP_PATH"
xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl uninstall "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl install "$DEVICE" "$APP_PATH"

# ----------------------------------------------------------------------
# ODR fetches fail under `simctl install` — the simulator never
# ingests the ODR manifest (that's Xcode's Run flow's job). For
# screenshot capture we don't care about the ODR split, so the
# screenshot build above was already configured to bundle every pair
# install-time. We preserved that via a project.yml override toggled
# around the xcodegen step — no runtime change needed.
# ----------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Scenes: (filename, pair, direction, input). Variety = pair-family mix
# + sentence length mix + a selection that avoids too many unknown markers.
# ---------------------------------------------------------------------------
# Format: <filename>|<pkg>|<forward|backward>|<input>
SCENES=(
  "01_dan_nob|apertium-dan-nor|forward|Vejret er meget koldt her om vinteren."
  "02_cat_ita|apertium-cat-ita|forward|La platja és plena de turistes aquest estiu."
  "03_cat_spa|apertium-spa-cat|backward|Els arbres han perdut les fulles aquesta tardor."
  "04_fra_cat|apertium-fra-cat|forward|La chanson traverse les rues du village."
  "05_por_cat|apertium-por-cat|forward|A música toca no jardim durante o anoitecer."
  "06_nno_nob|apertium-nno-nob|forward|Vi ynskjer deg ein god sommar."
  "07_sme_nob|apertium-sme-nob|forward|Mun lean studeanta ja orun Kárášjogas."
  "08_oci_fra|apertium-oci-fra|forward|Los aucèls cantan dins los arbres."
  "09_spa_glg|apertium-spa-glg|forward|Mañana vamos a la playa con la familia."
  "10_rus_ukr|apertium-rus-ukr|forward|Сегодня очень солнечный и тёплый день."
)

SETTLE=2   # seconds between launch and snapshot

for scene in "${SCENES[@]}"; do
  IFS='|' read -r name pkg dir input <<< "$scene"
  echo "---- scene $name ($pkg, $dir): $input"
  xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
  xcrun simctl launch "$DEVICE" "$BUNDLE_ID" \
    -screenshot_pair "$pkg" \
    -screenshot_direction "$dir" \
    -screenshot_input "$input" >/dev/null
  sleep "$SETTLE"
  xcrun simctl io "$DEVICE" screenshot --type=png "$OUT/$name.png"
done

xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl status_bar "$DEVICE" clear >/dev/null 2>&1 || true

echo
echo "wrote $(ls "$OUT"/*.png | wc -l | tr -d ' ') PNGs to $OUT"
