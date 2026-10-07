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
# Runs on a dedicated simulator ("Translate screenshots (<device type>)",
# created on the newest iOS runtime if missing), because the run erases
# it. Needs ImageMagick (`magick`) for the Dynamic Island composite.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJ="$REPO_ROOT/ios"
BUNDLE_ID="com.qvyshift.translate"

command -v magick >/dev/null || { echo "ERROR: needs ImageMagick (brew install imagemagick)"; exit 1; }

# ---------------------------------------------------------------------------
# Device selection.
#
# Default is iPhone 16 Pro Max (6.9" App Store tier, 1320×2868). Pass
# KIND=ipad for iPad Pro 13-inch (M4) (13" tier, 2064×2752). DEVICE_TYPE
# forces another simctl device type name.
# ---------------------------------------------------------------------------
: "${KIND:=iphone}"
case "$KIND" in
  iphone) : "${DEVICE_TYPE:=iPhone 16 Pro Max}";     OUT_SUBDIR=appstore-iphone-69 ;;
  ipad)   : "${DEVICE_TYPE:=iPad Pro 13-inch (M4)}"; OUT_SUBDIR=appstore-ipad-13 ;;
  *) echo "unknown KIND: $KIND (expected iphone | ipad)"; exit 1 ;;
esac

OUT="$REPO_ROOT/screenshots/$OUT_SUBDIR"
mkdir -p "$OUT"

# The run erases its simulator, so it uses its own device, never one that
# happens to be booted with the same model name (other sessions share the
# simulator set). Created on the newest available iOS runtime when missing.
DEVICE_NAME="Translate screenshots ($DEVICE_TYPE)"
pick_device() {
  /usr/bin/python3 - "$DEVICE_NAME" "$DEVICE_TYPE" <<'PY'
import json, subprocess, sys
name, dtype = sys.argv[1], sys.argv[2]
j = lambda *a: json.loads(subprocess.check_output(["xcrun", "simctl", "list", *a, "--json"]))
for rt, ds in j("devices")["devices"].items():
    for d in ds:
        if d["name"] == name and d.get("isAvailable", True):
            print(d["udid"]); sys.exit(0)
types = [t for t in j("devicetypes")["devicetypes"] if t["name"] == dtype]
runtimes = [r for r in j("runtimes")["runtimes"]
            if r.get("isAvailable") and r.get("platform") == "iOS"]
if not types or not runtimes:
    sys.exit(f"ERROR: no '{dtype}' device type or no iOS runtime available")
runtimes.sort(key=lambda r: [int(x) for x in r["version"].split(".")])
print(subprocess.check_output(["xcrun", "simctl", "create", name,
      types[0]["identifier"], runtimes[-1]["identifier"]], text=True).strip())
PY
}

DEVICE=$(pick_device)
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

# Older Xcodes needed a Simulator window for `simctl io screenshot` to have
# a surface. Xcode 27 has no Simulator.app (Device Hub replaced it) and
# captures headless.
open -a Simulator 2>/dev/null || true

# ---------------------------------------------------------------------------
# Clean status bar — matches Android's emulator-screenshot-setup.sh intent.
# Xcode 27's simctl rejects --time "12:00" ("Invalid, non-ISO date/time
# string") and takes ISO 8601 only with fractional seconds, shown in the
# simulator's (= the host's) time zone: pass today 12:00 local, in UTC.
# --batteryState charged now draws a green charging bolt; discharging at
# 100% is the plain full battery.
# ---------------------------------------------------------------------------
NOON_UTC=$(date -u -r "$(date -j -f '%Y-%m-%d %H:%M:%S' "$(date +%Y-%m-%d) 12:00:00" +%s)" \
           +%Y-%m-%dT%H:%M:%S.000Z)
set_status_bar() {
  xcrun simctl status_bar "$DEVICE" override \
    --time "$NOON_UTC" \
    --dataNetwork wifi --wifiMode active --wifiBars 3 \
    --cellularMode notSupported \
    --batteryState discharging --batteryLevel 100 \
    --operatorName ""
}
set_status_bar

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
# Scenes: (filename, pair, direction, input). Every scene showcases an
# obscure source language — the point of the app is the Apertium
# language models, not mainstream-pair translation, so the screenshots
# deliberately skip eng/spa/fra source text in favor of Aragonese,
# Occitan, Sardinian, Macedonian, Northern Sami, Belarusian, etc.
# ---------------------------------------------------------------------------
# Format: <filename>|<pkg>|<forward|backward>|<input>
SCENES=(
  "01_arg_cat|apertium-arg-cat|forward|Os críos chugan en o campo dimpués d'a escuela."
  "02_cat_srd|apertium-cat-srd|forward|Demà anirem al mercat del poble a comprar fruita fresca."
  # Macedonian→English and Sardinian→Italian stand in for oci→cat and
  # hbs→mkd, which crashed in apertium-transfer on iOS through 1.0.6
  # (pair-data bugs, worked around in a5f2578) — equally obscure sources.
  "03_mkd_eng|apertium-mkd-eng|forward|Мојот син учи математика во училиште секој ден."
  "04_oci_fra|apertium-oci-fra|forward|Lo libre es pausat sus la taula dins la cosina."
  "05_srd_ita|apertium-srd-ita|forward|Su cane est in sa pratza e abojat a sa genti de su biginadu."
  "06_sme_nob|apertium-sme-nob|forward|Mun lean studeanta ja orun Kárášjogas."
  "07_bel_rus|apertium-bel-rus|forward|У нашым горадзе шмат музеяў і старадаўніх будынкаў."
  "08_cat_glg|apertium-cat-glg|forward|El sol es pon lentament darrere les muntanyes a l'horitzó."
)

SETTLE=4   # seconds between launch and snapshot

# Under Xcode 27, `simctl io screenshot` leaves the Dynamic Island out of
# default and --mask=ignored captures (pre-27 captures always had it, with
# square corners); --mask=black draws it but also blacks out the rounded
# corners. Paste the island from a --mask=black capture ($2) onto the
# --mask=ignored one ($1, rewritten). No-op on devices without an island.
add_island() {
  local shot="$1" masked="$2" w h x0 bw bh geo gw gh gx gy
  read -r w h < <(magick identify -format '%w %h\n' "$shot")
  x0=$((w / 4)); bw=$((w / 2)); bh=$((h / 12))
  # The island is where the two captures differ in the top-center band
  # (the black mask's corners lie outside it).
  geo=$(magick "$masked" "$shot" -compose difference -composite \
          -crop "${bw}x${bh}+${x0}+0" +repage -colorspace gray -threshold 8% \
          -format '%@' info:)
  case "$geo" in ''|0x0*|1x1*) return ;; esac
  IFS='x+' read -r gw gh gx gy <<< "$geo"
  gx=$((gx + x0))
  magick "$shot" \( "$masked" -crop "${gw}x${gh}+${gx}+${gy}" +repage \) \
    -geometry "+${gx}+${gy}" -composite "$shot"
}

MASKED_DIR="$(mktemp -d -t translate-shots)"
MASKED="$MASKED_DIR/masked.png"
for scene in "${SCENES[@]}"; do
  IFS='|' read -r name pkg dir input <<< "$scene"
  echo "---- scene $name ($pkg, $dir): $input"
  xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
  xcrun simctl launch "$DEVICE" "$BUNDLE_ID" \
    -screenshot_pair "$pkg" \
    -screenshot_direction "$dir" \
    -screenshot_input "$input" >/dev/null
  set_status_bar   # re-assert; the override can lapse across launches
  sleep "$SETTLE"
  xcrun simctl io "$DEVICE" screenshot --type=png --mask=ignored "$OUT/$name.png"
  xcrun simctl io "$DEVICE" screenshot --type=png --mask=black "$MASKED" >/dev/null 2>&1
  add_island "$OUT/$name.png" "$MASKED"
done
rm -rf "$MASKED_DIR"

xcrun simctl terminate "$DEVICE" "$BUNDLE_ID" 2>/dev/null || true
xcrun simctl status_bar "$DEVICE" clear >/dev/null 2>&1 || true

echo
echo "wrote $(ls "$OUT"/*.png | wc -l | tr -d ' ') PNGs to $OUT"
