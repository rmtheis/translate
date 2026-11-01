#!/usr/bin/env bash
# screenshots-android.sh — capture the Google Play phone screenshots of the Android app
# (com.qvyshift.translate) in every Play listing language, on an Android emulator.
#
# Usage:
#   LANGS=ca,da-DK,... APKS=/path/to/qa.apks scripts/screenshots-android.sh [serial]
#
#   serial  adb serial of the emulator (default emulator-5554). Always an emulator, never the
#           physical phone, and never a Pixel_* AVD (status-bar sizing bug). Use the Android 14
#           Medium Phone AVD (Screenshots_API_34): from Android 15 the app is drawn edge-to-edge
#           and android:statusBarColor is ignored, so API 35/36 emulators give a cream status bar
#           with a near-invisible white clock instead of the live set's dark-red bar (the 15
#           language sets of 2026-11-01 were shot on API 34; see android/README.md for its
#           boot/wipe-data gotcha).
#   LANGS   comma-separated Play language codes to capture; default = the 15 non-English rows
#           of LANG_TABLE below. `en-US` is also a valid row (regenerates the English set).
#   APKS    optional: an APK set built with `bundletool build-apks --local-testing`. When set,
#           the script extracts base + ABI + density + the language split of EVERY locale in
#           LANGS and installs them with `adb install-multiple -r -t`. Do NOT install the set
#           with `bundletool install-apks`: that pushes only the device's own language split,
#           so `cmd locale set-app-locales` has no strings to switch to and the UI stays English.
#   OUT     output root (default: <repo>/screenshots/play-phone).
#   SHEETS  optional directory: also write a scaled 6-up contact sheet per language there
#           (`play_<lang>.png`, needs ImageMagick `montage`) for eyeballing status bar,
#           keyboard, leftover English and the translation.
#   ADB     adb binary (default ~/Library/Android/sdk/platform-tools/adb).
#
# What it reproduces — the en-US convention. The live en-US Play listing has 6 phone
# screenshots: plain 1080x2400 captures of the Medium Phone emulator, no device frame, no
# caption. They are three scenes, each shot twice:
#     01_spa_cat_input / 02_spa_cat_output   Spanish → Catalan    (mode spa-cat)
#     03_por_cat_input / 04_por_cat_output   Portuguese → Catalan (mode por-cat)
#     05_swe_dan_input / 06_swe_dan_output   Swedish → Danish     (mode swe-dan)
# Each scene is a cold start of TranslatorActivity through an ACTION_SEND intent carrying the
# input sentence (EXTRA_TEXT) and the pair (`mode` extra = the dropdown title). The "input"
# shot is the app as it settled after that launch (output field empty, hint showing, soft
# keyboard dismissed); the "output" shot is taken after tapping Translate, once the output
# field is filled. Files go to $OUT/<play-language>/0N_<pair>_<input|output>.png.
#
# Per-app locale. The app ships no localeConfig, so the UI language is switched with
#   adb shell cmd locale set-app-locales com.qvyshift.translate --user 0 --locales <tag>
# (column 2 of LANG_TABLE: es-419 → es-MX, no-NO → nb, ...). That only works when the language
# split for that locale is installed — see APKS. The app is force-stopped before every scene,
# so the new locale always applies.
#
# Title matching. The `mode` extra is matched literally against the titles of the INSTALLED
# pairs; the app builds those from ICU display names in the current UI locale, lower-case in
# most languages ("espanyol → català", arrow U+2192 with one space each side). LANG_TABLE holds
# the CLDR names. For each scene the script tries the table form, then the same title with
# each language name capitalized (some ICU locales capitalize), and treats any other dropdown
# text as a miss: on a miss the app falls back to the first installed pair, so the shot would
# be wrong and is not taken. Instead the script opens the dropdown and saves a screenshot of
# it to $OUT/_debug/<lang>_<pair>_dropdown.png — uiautomator cannot see the popup list, so
# read the real names off that image and fix the table row. A pair that is not installed
# looks exactly like a miss, which is why the English preflight below runs first.
#
# One-time manual step per emulator /data: the three pairs are on-demand asset packs and must
# be downloaded in the app once (with a --local-testing APK set they come from the device in
# a few seconds). Launch the app, open the "Choose languages" dropdown, tap "Spanish → Catalan",
# accept the "Download now" dialog; repeat for "Portuguese → Catalan" and "Swedish → Danish".
# Do NOT use "Download all" (fills /data on the Medium Phone AVD; see android/README.md,
# "Local builds and QA"). Before touching any language the script checks, in English, that
# all three pairs are installed and stops with this instruction if one is missing.
#
# Status bar. Before EVERY capture the script runs scripts/emulator-screenshot-setup.sh and
# re-broadcasts the wifi demo state, because Android 15+ drops demo mode after a few minutes.
# Every shot therefore shows 12:00, full wifi without "!", 100 % battery, no cell indicator
# and no notification icons. Once per run it also disables the two emulator packages that
# post persistent notifications (adservices, wellbeing) and snoozes the remaining system
# notifications — both are no-ops when already done. It never touches permissioncontroller.
#
# Exit status: 0 when every requested language produced its 6 files, 1 otherwise. The
# per-language summary at the end lists the matched titles (marking the capitalized form),
# the Translate button label (must be in that language) and the files written.
set -u

SERIAL="${1:-emulator-5554}"
ADB="${ADB:-$HOME/Library/Android/sdk/platform-tools/adb}"
PKG=com.qvyshift.translate
ACTIVITY=.TranslatorActivity
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/screenshots/play-phone}"
SHEETS="${SHEETS:-}"
APKS="${APKS:-}"
LANGS="${LANGS:-ca,da-DK,es-ES,es-419,fr-FR,fr-CA,hr,it-IT,no-NO,pt-BR,pt-PT,ro,ru-RU,sv-SE,uk}"
SETTLE_SECS="${SETTLE_SECS:-3}"       # cold start → first dump
TRANSLATE_TIMEOUT="${TRANSLATE_TIMEOUT:-20}"

# Play language | per-app locale | spa→cat title | por→cat title | swe→dan title
# (CLDR display names; the capitalized variant is derived automatically)
LANG_TABLE='
en-US|en-US|Spanish → Catalan|Portuguese → Catalan|Swedish → Danish
ca|ca|espanyol → català|portuguès → català|suec → danès
da-DK|da|spansk → catalansk|portugisisk → catalansk|svensk → dansk
es-ES|es|español → catalán|portugués → catalán|sueco → danés
es-419|es-MX|español → catalán|portugués → catalán|sueco → danés
fr-FR|fr|espagnol → catalan|portugais → catalan|suédois → danois
fr-CA|fr-CA|espagnol → catalan|portugais → catalan|suédois → danois
hr|hr|španjolski → katalonski|portugalski → katalonski|švedski → danski
it-IT|it|spagnolo → catalano|portoghese → catalano|svedese → danese
no-NO|nb|spansk → katalansk|portugisisk → katalansk|svensk → dansk
pt-BR|pt-BR|espanhol → catalão|português → catalão|sueco → dinamarquês
pt-PT|pt-PT|espanhol → catalão|português → catalão|sueco → dinamarquês
ro|ro|spaniolă → catalană|portugheză → catalană|suedeză → daneză
ru-RU|ru|испанский → каталанский|португальский → каталанский|шведский → датский
sv-SE|sv|spanska → katalanska|portugisiska → katalanska|svenska → danska
uk|uk|іспанська → каталонська|португальська → каталонська|шведська → данська
'

# scene number | pair slug (file name) | input sentence
SCENES='
1|spa_cat|La biblioteca de la ciudad abre cada mañana a las nueve.
2|por_cat|A biblioteca da cidade abre todas as manhãs às nove.
3|swe_dan|Hunden springer över gatan mot parken.
'

# ---------------------------------------------------------------------------------------
adbs() { "$ADB" -s "$SERIAL" "$@" </dev/null; }
log()  { printf '%s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

lang_row()   { grep -- "^$1|" <<<"$LANG_TABLE" | head -1; }
row_col()    { awk -F'|' -v c="$2" '{print $c}' <<<"$1"; }

# Title with the first letter of each language name upper-cased ("spansk → dansk" → "Spansk → Dansk").
capitalize_title() {
  python3 -c '
import sys
t = sys.argv[1]
print(" → ".join(s[:1].upper() + s[1:] for s in t.split(" → ")))' "$1"
}

# Escape for a single-quoted argument inside `adb shell "..."`.
sq() { printf '%s' "$1" | sed "s/'/'\\\\''/g"; }

# uiautomator dump → lines "id<TAB>text<TAB>centerX<TAB>centerY" for this app's views.
dump() {
  local tries=0 out=""
  while [ $tries -lt 4 ]; do
    out=$(adbs exec-out uiautomator dump /dev/tty 2>/dev/null | python3 -c '
import sys, re, html
pkg = sys.argv[1]
s = sys.stdin.read()
for m in re.finditer(r"<node [^>]*>", s):
    n = m.group(0)
    rid = re.search(r"resource-id=\"([^\"]*)\"", n).group(1)
    txt = html.unescape(re.search(r" text=\"([^\"]*)\"", n).group(1))
    x0, y0, x1, y1 = map(int, re.findall(r"\d+", re.search(r"bounds=\"([^\"]*)\"", n).group(1)))
    if rid.startswith(pkg + ":id/"):
        print(rid.split("/")[-1] + "\t" + txt.replace("\n", " ").strip() + "\t" + str((x0 + x1) // 2) + "\t" + str((y0 + y1) // 2))' "$PKG")
    [ -n "$out" ] && break
    tries=$((tries + 1)); sleep 1
  done
  printf '%s\n' "$out"
}
field()  { awk -F'\t' -v k="$1" '$1==k {print $2; exit}' <<<"$DUMP"; }
center() { awk -F'\t' -v k="$1" '$1==k {print $3" "$4; exit}' <<<"$DUMP"; }

statusbar() {
  bash "$ROOT/scripts/emulator-screenshot-setup.sh" "$SERIAL" >/dev/null </dev/null
  adbs shell "am broadcast -a com.android.systemui.demo -e command network -e wifi show -e level 4 -e fully true -e inflate true" >/dev/null
}

app_in_front() { adbs shell dumpsys activity activities | grep -q "topResumedActivity.*$PKG/"; }

# The en-US reference shots show no soft keyboard: dismiss it if the cold start raised it.
keyboard_down() {
  if adbs shell dumpsys input_method | grep -q 'mInputShown=true'; then
    adbs shell input keyevent 4; sleep 1
    app_in_front || log "    WARNING: app not in front after dismissing the keyboard"
  fi
}

screencap() { # file
  statusbar; sleep 1
  adbs exec-out screencap -p > "$1"
  local dims; dims=$(file "$1" | grep -o '[0-9]* x [0-9]*' | head -1)
  [ "$dims" = "1080 x 2400" ] || log "    WARNING: $1 is $dims, expected 1080 x 2400"
}

cold_start() { # title input  → sets DUMP; returns 0 when the dropdown shows exactly $title
  local title="$1" input="$2" i
  adbs shell "am force-stop $PKG; am start -n $PKG/$ACTIVITY -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT '$(sq "$input")' --es mode '$(sq "$title")'" >/dev/null
  sleep "$SETTLE_SECS"
  for i in 1 2 3 4 5; do
    DUMP=$(dump)
    [ -n "$(field languagePairDropdown)" ] && [ "$(field inputtext)" = "$input" ] && break
    sleep 1
  done
  [ "$(field inputtext)" = "$input" ] || log "    WARNING: input field shows '$(field inputtext)'"
  [ "$(field languagePairDropdown)" = "$title" ]
}

# Try the table title, then the capitalized one. Sets MATCHED ("" on miss) and MATCH_NOTE.
select_pair() { # title input
  local title="$1" input="$2" alt
  MATCHED=""; MATCH_NOTE=""
  if cold_start "$title" "$input"; then MATCHED="$title"; return 0; fi
  SHOWN=$(field languagePairDropdown)
  alt=$(capitalize_title "$title")
  if [ "$alt" != "$title" ] && cold_start "$alt" "$input"; then
    MATCHED="$alt"; MATCH_NOTE=" (capitalized form; table says '$title')"; return 0
  fi
  SHOWN=$(field languagePairDropdown)
  return 1
}

save_dropdown_debug() { # lang pair
  mkdir -p "$OUT/_debug"
  read -r dx dy <<<"$(center languagePairDropdown)"
  [ -n "${dx:-}" ] || return
  adbs shell input tap "$dx" "$dy"; sleep 1.5
  adbs exec-out screencap -p > "$OUT/_debug/$1_$2_dropdown.png"
  adbs shell input keyevent 4; sleep 0.5
  log "    dropdown saved to $OUT/_debug/$1_$2_dropdown.png (read the real pair names off it)"
}

tap_translate_and_wait() { # → 0 when outputText changed to non-empty text within the timeout
  local before now i tx ty
  before=$(field outputText)
  read -r tx ty <<<"$(center translateButton)"
  adbs shell input tap "$tx" "$ty"
  i=0
  while [ $i -lt "$TRANSLATE_TIMEOUT" ]; do
    sleep 1; i=$((i + 1))
    DUMP=$(dump); now=$(field outputText)
    if [ -n "$now" ] && [ "$now" != "$before" ]; then
      OUTPUT="$now"
      case "$now" in *'*'*|*'#'*) log "    WARNING: output carries unknown-word marks: $now";; esac
      return 0
    fi
  done
  OUTPUT=""; return 1
}

install_apks() {
  command -v bundletool >/dev/null || die "bundletool not on PATH (brew install bundletool)"
  local tmp spec locales="\"en-US\"" l row sdk density abi
  tmp=$(mktemp -d)
  for l in $(tr ',' ' ' <<<"$LANGS"); do
    row=$(lang_row "$l"); [ -n "$row" ] || die "unknown language '$l' (not in LANG_TABLE)"
    locales="$locales,\"$(row_col "$row" 2)\""
  done
  sdk=$(adbs shell getprop ro.build.version.sdk | tr -d '\r')
  density=$(adbs shell wm density | grep -o '[0-9]*' | tail -1)
  abi=$(adbs shell getprop ro.product.cpu.abilist | tr -d '\r' | cut -d, -f1)
  spec="$tmp/device-spec.json"
  printf '{"supportedAbis":["%s"],"supportedLocales":[%s],"screenDensity":%s,"sdkVersion":%s}\n' \
    "$abi" "$locales" "$density" "$sdk" > "$spec"
  log "Extracting splits from $APKS for locales [$locales] ..."
  bundletool extract-apks --apks "$APKS" --output-dir "$tmp/apks" --device-spec "$spec" >/dev/null 2>&1 \
    || die "bundletool extract-apks failed"
  log "Installing $(ls "$tmp/apks"/*.apk | wc -l | tr -d ' ') APKs ..."
  adbs install-multiple -r -t "$tmp"/apks/*.apk | tail -1
  rm -rf "$tmp"
}

boot_prep() {
  adbs shell pm disable-user com.google.android.adservices.api >/dev/null 2>&1 || true
  adbs shell pm disable-user com.google.android.apps.wellbeing >/dev/null 2>&1 || true
  local keys k
  keys=$(adbs shell dumpsys notification | awk -F 'key=' '/^    NotificationRecord/ {print $2}' | awk -F ':' '{print $1}' | grep '|android|' || true)
  for k in $keys; do adbs shell "cmd notification snooze --for 86400000 '$k'" >/dev/null 2>&1 || true; done
}

set_locale() { adbs shell cmd locale set-app-locales "$PKG" --user 0 --locales "$1" >/dev/null; }

# ---------------------------------------------------------------------------------------
[ -x "$ADB" ] || die "adb not found at $ADB"
adbs get-state >/dev/null 2>&1 || die "no device with serial $SERIAL"
case "$SERIAL" in emulator-*) ;; *) die "refusing to run on '$SERIAL': screenshots are captured on an emulator only";; esac
[ "$(adbs shell getprop sys.boot_completed | tr -d '\r')" = "1" ] || die "$SERIAL has not finished booting"

[ -n "$APKS" ] && install_apks
adbs shell pm path "$PKG" >/dev/null 2>&1 || die "$PKG is not installed on $SERIAL (pass APKS=...)"
boot_prep
mkdir -p "$OUT"

# Preflight in English: every pair installed? (a missing pair is indistinguishable from a title miss)
log "Preflight (en-US): checking the three pairs are installed ..."
set_locale en-US
EN_ROW=$(lang_row en-US)
while IFS='|' read -r n slug input; do
  [ -n "$n" ] || continue
  title=$(row_col "$EN_ROW" $((n + 2)))
  if cold_start "$title" "$input"; then
    log "  $title: installed"
  else
    log "  $title: NOT installed (dropdown fell back to '$(field languagePairDropdown)')"
    die "download the pair in the app first: open the dropdown, tap '$title', accept the download (see the header of this script)"
  fi
done <<<"$SCENES"

SUMMARY=""
FAILED=0
for LANG in $(tr ',' ' ' <<<"$LANGS"); do
  ROW=$(lang_row "$LANG")
  if [ -z "$ROW" ]; then log "unknown language '$LANG', skipping"; FAILED=$((FAILED + 1)); continue; fi
  LOCALE=$(row_col "$ROW" 2)
  DIR="$OUT/$LANG"; mkdir -p "$DIR"
  log ""
  log "== $LANG (app locale $LOCALE) → $DIR"
  set_locale "$LOCALE"
  LANG_OK=1; TITLES=""; FILES=""; BUTTON=""
  while IFS='|' read -r n slug input; do
    [ -n "$n" ] || continue
    title=$(row_col "$ROW" $((n + 2)))
    f_in="$DIR/$(printf '%02d' $((2 * n - 1)))_${slug}_input.png"
    f_out="$DIR/$(printf '%02d' $((2 * n)))_${slug}_output.png"
    log "  scene $n ($slug): '$title'"
    if ! select_pair "$title" "$input"; then
      log "    MISS: dropdown shows '$SHOWN' (tried '$title' and '$(capitalize_title "$title")')"
      save_dropdown_debug "$LANG" "$slug"
      LANG_OK=0; TITLES="$TITLES [$slug: MISS, shows '$SHOWN']"
      continue
    fi
    log "    matched '$MATCHED'$MATCH_NOTE"
    TITLES="$TITLES [$slug: $MATCHED$MATCH_NOTE]"
    BUTTON=$(field translateButton)
    keyboard_down
    screencap "$f_in";  log "    wrote $(basename "$f_in")"
    if tap_translate_and_wait; then
      log "    output: $OUTPUT"
    else
      log "    FAIL: no translation output within ${TRANSLATE_TIMEOUT}s"; LANG_OK=0; continue
    fi
    keyboard_down
    screencap "$f_out"; log "    wrote $(basename "$f_out")"
    FILES="$FILES $(basename "$f_in") $(basename "$f_out")"
  done <<<"$SCENES"
  if [ "$LANG" != "en-US" ] && [ "$BUTTON" = "TRANSLATE" ]; then
    log "  WARNING: Translate button still reads 'TRANSLATE' — language split for $LOCALE missing?"; LANG_OK=0
  fi
  if [ -n "$SHEETS" ] && command -v montage >/dev/null; then
    mkdir -p "$SHEETS"
    montage "$DIR"/0?_*.png -tile 6x1 -geometry 324x720+4+4 -background '#ffffff' "$SHEETS/play_$LANG.png" 2>/dev/null \
      && log "  sheet: $SHEETS/play_$LANG.png"
  fi
  STATUS=OK; [ $LANG_OK = 1 ] || { STATUS=FAILED; FAILED=$((FAILED + 1)); }
  SUMMARY="$SUMMARY
$LANG ($LOCALE): $STATUS  button='$BUTTON' $TITLES
    files:$FILES"
done

set_locale en-US
log ""
log "================ summary ================"
log "$SUMMARY"
log ""
N=$(tr ',' '\n' <<<"$LANGS" | grep -c .)
log "$((N - FAILED))/$N languages complete; output in $OUT"
[ $FAILED = 0 ]
