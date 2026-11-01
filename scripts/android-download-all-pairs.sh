#!/usr/bin/env bash
# android-download-all-pairs.sh — on an emulator with a `--local-testing` APK set installed,
# open the app's settings dialog and tap "Download all language pairs", then wait for the
# fake asset-pack service to deliver every pack (about 20 s). The screenshot scripts need
# the pairs installed; /data is wiped on most AVDs at boot, so this runs after every
# `bundletool install-apks`. Usage: scripts/android-download-all-pairs.sh [serial]
#
# Don't poll the progress dialog with `uiautomator dump`: the dump fails while the
# indeterminate progress bar animates, which looks exactly like "dialog gone" — pressing
# Back / force-stopping at that point kills the download half-way. The wait below watches
# logcat for Play Core's notifyModuleCompleted lines instead and only then checks the UI.
set -u
SERIAL="${1:-emulator-5554}"
PKG=com.qvyshift.translate
ADB="${ADB:-$HOME/Library/Android/sdk/platform-tools/adb}"
case "$SERIAL" in emulator-*) ;; *) echo "refusing to run on '$SERIAL': emulators only" >&2; exit 1;; esac
a() { "$ADB" -s "$SERIAL" "$@"; }
dump() { a shell uiautomator dump /sdcard/ui.xml >/dev/null 2>&1; a shell cat /sdcard/ui.xml 2>/dev/null; }
center() { python3 -c 'import re,sys; m=re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", sys.argv[1]); print((int(m.group(1))+int(m.group(3)))//2, (int(m.group(2))+int(m.group(4)))//2)' "$1"; }
bounds_of() { dump | grep -o "resource-id=\"$PKG:id/$1\"[^>]*" | grep -o 'bounds="[^"]*"'; }
completed() { a logcat -d -t 5000 2>/dev/null | grep -c 'FakeAssetPackService : notifyModuleCompleted'; }

a shell am force-stop "$PKG"
a logcat -c 2>/dev/null
a shell am start -n "$PKG/.TranslatorActivity" >/dev/null 2>&1
sleep 10   # let the activity scan its installation before touching the toolbar

# Open the settings dialog (toolbar gear, id/manage); retry — a tap during start-up is lost.
DL=""
for attempt in 1 2 3 4 5; do
  M=$(bounds_of manage)
  [ -n "$M" ] || { sleep 4; continue; }
  read -r mx my <<<"$(center "$M")"; a shell input tap "$mx" "$my"; sleep 4
  DL=$(bounds_of downloadAllButton)
  [ -n "$DL" ] && break
  echo "settings dialog did not open (attempt $attempt), retrying"
done
[ -n "$DL" ] || { echo "ERROR: no Download-all button" >&2; exit 1; }
read -r dx dy <<<"$(center "$DL")"
echo "tapping Download all at $dx,$dy"
a shell input tap "$dx" "$dy"

t0=$(date +%s); last=-1; quiet=0
while :; do
  sleep 5
  c=$(completed)
  if [ "$c" = "$last" ]; then quiet=$((quiet + 1)); else quiet=0; fi
  last=$c
  echo "  $(( $(date +%s) - t0 ))s: $c packs delivered"
  if [ "$quiet" -ge 3 ]; then
    X=$(dump)
    if [ -n "$X" ] && ! echo "$X" | grep -q 'id/downloadProgress'; then break; fi
  fi
  if [ $(( $(date +%s) - t0 )) -gt 600 ]; then echo "ERROR: timed out" >&2; exit 1; fi
done
echo "done: $last packs delivered; remaining label: $(dump | grep -o "resource-id=\"$PKG:id/downloadAllButton\"[^>]*" | grep -o 'text="[^"]*"')"
a shell input keyevent BACK; sleep 1; a shell am force-stop "$PKG"
