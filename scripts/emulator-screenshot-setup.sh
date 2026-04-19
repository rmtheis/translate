#!/usr/bin/env bash
# Prepare an Android emulator for Play Store screenshots: enter SysUI demo mode,
# pin a clean status bar (12:00, 100% battery, full wifi, no mobile, no notifications).
#
# Usage:  ./scripts/emulator-screenshot-setup.sh [emulator-serial]
# The serial defaults to emulator-5556; pass -s <serial> to adb if you need to override.
#
# Notes on each param (learned the hard way):
#   - wifi `-e fully true`   → removes the "no-internet" exclamation mark overlay
#   - mobile `hide`          → removes the "3G"/"LTE" cell-radio badge entirely
#     (alternatively `mobile show -e datatype none -e fully true` keeps the signal
#     bars but drops the data-type letters)
set -euo pipefail

SERIAL="${1:-emulator-5556}"
ADB="${ADB:-adb}"
demo() {
  "$ADB" -s "$SERIAL" shell "am broadcast -a com.android.systemui.demo -e command $*" >/dev/null
}

"$ADB" -s "$SERIAL" shell settings put global sysui_demo_allowed 1
demo enter
demo clock -e hhmm 1200
demo battery -e level 100 -e plugged false
demo network -e wifi show -e level 4 -e fully true
demo network -e mobile hide
demo notifications -e visible false

# Newer Android versions layer VoWiFi/IMS/ethernet indicators next to the wifi icon,
# producing a "two wifi icons" look. Hide every secondary status icon too.
for icon in vowifi ims ethernet bluetooth speakerphone mute volume tty location alarm \
            cast rotate headset work hotspot; do
  demo status -e "$icon" hide
done

echo "status bar ready on $SERIAL"
