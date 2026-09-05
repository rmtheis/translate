#!/usr/bin/env bash
# Re-verify the phrase shortcuts (app/src/main/res/values/phrases.xml) against the exact
# binaries + pair data the app ships, by running Apertium ON AN ARM64 EMULATOR over adb.
#
# Usage:  scripts/verify-phrases.sh [emulator-serial]      (default: emulator-5554)
#
# Prints every phrase with its translation in both directions. Anything containing an
# unknown-word marker (* # @) is flagged with "!!". There is no macOS build of Apertium,
# so the emulator is the reference environment; the 12-stage pipeline is the one from
# srd-ita.mode / ita-srd.mode, spelled out in scripts/device-apertium.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SERIAL="${1:-emulator-5554}"
ADB="${ADB:-$HOME/Library/Android/sdk/platform-tools/adb}"
DEV=/data/local/tmp/ap

abi=$("$ADB" -s "$SERIAL" shell getprop ro.product.cpu.abi | tr -d '\r')
case "$abi" in arm64-v8a|armeabi-v7a) ;; *) echo "need an arm emulator (got $abi)"; exit 1;; esac

"$ADB" -s "$SERIAL" shell "rm -rf $DEV && mkdir -p $DEV/bin $DEV/pair" >/dev/null
"$ADB" -s "$SERIAL" push "$ROOT/app/src/main/jniLibs/$abi/." "$DEV/bin/" >/dev/null
"$ADB" -s "$SERIAL" push "$ROOT/app/src/main/assets/pair/." "$DEV/pair/" >/dev/null
"$ADB" -s "$SERIAL" push "$HERE/device-apertium.sh" "$DEV/apx.sh" >/dev/null
"$ADB" -s "$SERIAL" shell "chmod 755 $DEV/bin/* $DEV/apx.sh"

extract() {  # $1 = array name → one phrase per line
  python3 - "$ROOT/app/src/main/res/values/phrases.xml" "$1" <<'PY'
import sys, xml.etree.ElementTree as ET
root = ET.parse(sys.argv[1]).getroot()
for arr in root.findall("string-array"):
    if arr.get("name") == sys.argv[2]:
        for item in arr.findall("item"):
            print((item.text or "").replace("\\'", "'"))
PY
}

run() {  # $1 = mode, stdin = text
  "$ADB" -s "$SERIAL" shell "cat > $DEV/in.txt"
  "$ADB" -s "$SERIAL" shell "$DEV/apx.sh $1 < $DEV/in.txt" | tr -d '\r'
}

bad=0
for spec in "ita-srd phrases_it" "srd-ita phrases_sc"; do
  set -- $spec
  echo "== $1 =="
  extract "$2" > /tmp/verify-src.txt
  run "$1" < /tmp/verify-src.txt > /tmp/verify-out.txt
  paste -d '|' /tmp/verify-src.txt /tmp/verify-out.txt | while IFS='|' read -r src out; do
    flag=""; case "$out" in *\**|*\#*|*@*) flag="!!"; esac
    printf '%-2s %-32s -> %s\n' "$flag" "$src" "$out"
  done
  if grep -qE '[*#@]' /tmp/verify-out.txt; then bad=1; fi
done
exit $bad
