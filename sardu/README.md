# Traduttore Sardo / Sardinian Translator (`com.qvyshift.sardu`)

Single-pair, fully offline Android translator: **Sardinian ⇄ Italian**, powered by
Apertium's `apertium-srd-ita` pair. Text only, no ads, no network permission. A
standalone test app to see whether a dedicated Sardinian app finds users; see
`RESEARCH-single-pair-apps-2026-09.md` in the (private, out-of-git) `translate/` dir for the why.

Status (2026-10-06): v1.0.1 (versionCode 3, with native debug symbols) — the input
escaping fix, see "How translation works" — is live on Google Play production at 100%
(uploaded 2026-09-29 with the stock release notes; it replaced v1.0.0, versionCode 2).
**v1.0.2 (versionCode 4)** is the toolchain / target-37 release: AGP 9.4.1, Gradle
9.6.1, compileSdk/targetSdk 37, fragment/activity pins, no app-code change. Built and
QA'd on 2026-10-06 (see "R8, resources and QA"); it goes to production at **5% staged**
with the stock notes (see "Google Play"). **Published 2026-10-06** (production, `inProgress` at 5%); the play-rollout advancer walks it up (`com.qvyshift.sardu` is in its roster).
Lives in the public `rmtheis/translate` repo as `sardu/`, deliberately separate from
`android/` so the monthly workflows in `.github/workflows/` (which only trigger on
schedule / workflow_dispatch and only touch `android/`, `ios/`, `scripts/`) never see it.

## Layout

```
sardu/
  app/src/main/java/com/qvyshift/sardu/
    MainActivity.java   UI: direction row, input, phrase chips, output card, About
    Translator.java     serial background queue, latest-wins, main-thread callback
    NativePipeline.java verbatim copy (package rename only) of the same class in
                        ../android — keep them in sync
    PairStore.java      copies assets/pair/* → filesDir/pair/ once per versionCode
    Direction.java      srd-ita / ita-srd
    App.java            kicks off PairStore extraction at process start
  app/src/main/assets/pair/     the 28 files from pair-jars/apertium-srd-ita.jar (committed)
  app/src/main/jniLibs/<abi>/   gitignored; UNSTRIPPED Apertium tools + libs, populated by
                                scripts/install-natives-unstripped.sh from the monorepo's
                                CI `natives-<abi>` artifacts (see "Native libs" below)
  scripts/install-natives-unstripped.sh  the populate step (same renames as
                                ../scripts/install-natives-android.sh, no llvm-strip)
  app/src/main/res/values/phrases.xml   curated phrase shortcuts (see below)
  scripts/verify-phrases.sh     re-runs every phrase through the real binaries on an
                                emulator over adb; flags unknown-word markers
  scripts/device-apertium.sh    the 12-stage srd-ita / ita-srd pipeline as a shell
                                script that runs on the device (used by the above)
  scripts/upload_to_play.py     uploads the release AAB to the Play production track
                                (see "Google Play")
  screenshots/                  emulator captures from 2026-09-05 (light/dark, it/sc/en)
```

## Native libs and debug symbols

The app does not build Apertium itself; it takes the arm64-v8a / armeabi-v7a output of
the monorepo's `release-android.yml` `natives` job (unstripped `bin/` + `lib/`):

```sh
RUN=$(gh run list -R rmtheis/translate --workflow release-android.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run download $RUN -R rmtheis/translate -n natives-arm64-v8a   -D /tmp/natives/arm64-v8a
gh run download $RUN -R rmtheis/translate -n natives-armeabi-v7a -D /tmp/natives/armeabi-v7a
scripts/install-natives-unstripped.sh arm64-v8a   /tmp/natives/arm64-v8a
scripts/install-natives-unstripped.sh armeabi-v7a /tmp/natives/armeabi-v7a
```

(Artifacts expire 7 days after the monthly run; `android/native/build.sh` is the
fallback.) `app/build.gradle` sets `ndkVersion` and `release.ndk.debugSymbolLevel = 'FULL'`,
so AGP strips the libs it packages and stores the symbols under
`BUNDLE-METADATA/com.android.tools.build.debugsymbols/` in the AAB (~90 MB, not
downloaded by users); Play Console then symbolicates native crashes/ANRs. Without a
configured NDK, AGP silently ships the libs unstripped and emits no symbols; check with
`unzip -l app-release.aab | grep debugsymbols`. v1.0.0 versionCode 1 was built from an
older local build without symbols and was superseded before it went live.

## Build / run

```sh
./gradlew assembleDebug
~/Library/Android/sdk/platform-tools/adb -s emulator-5554 install -r app/build/outputs/apk/debug/app-debug.apk
```

- Gradle 9.6.1 wrapper, AGP 9.4.1, compileSdk/targetSdk 37 (since 1.0.2), **minSdk 26**
  (adaptive icon only, no legacy PNGs). JDK 17: `~/.gradle/gradle.properties` points
  Gradle at Corretto 17. Java only, so AGP 9's built-in Kotlin, kapt and `buildconfig`
  changes don't apply (AGP 9 still puts `kotlin-stdlib` on the classpath; R8 drops it).
- `androidx.activity` 1.13.0 and `androidx.fragment` 1.9.1 are pinned directly (Play
  Console flags old transitive versions; material pulls in fragment 1.1.0). Both need
  minSdk 23. Check the resolved versions in `META-INF/androidx.*.version` in the AAB.
- There are no unit tests (`testDebugUnitTest` is NO-SOURCE). AGP 9 only creates
  unit-test tasks for the tested build type, so `testReleaseUnitTest` doesn't exist.
- ABIs: `arm64-v8a` + `armeabi-v7a` only. **x86 emulators cannot run it**; use an arm64
  AVD (`Medium_Phone_API_37` / `Medium_Tablet_API_37`, or `Medium_Phone_API_36`).
- Native tools are stored **compressed** in the APK and extracted to `nativeLibraryDir`
  at install (`packaging.jniLibs.useLegacyPackaging = true` plus the manifest's
  `extractNativeLibs="true"`, which AGP warns about), so `ProcessBuilder` can exec them.
  The 16 KB zip-offset rule therefore doesn't apply; every arm64 `.so` has ELF `p_align`
  ≥ 0x4000. Play reports ~23 MB install size per device.
- To install the release AAB on the emulator exactly as Play would ship it:
  `bundletool build-apks --bundle=… --connected-device --device-id=emulator-5554 --ks=app/upload.keystore …`
  then `bundletool install-apks`.
- No `INTERNET` permission, on purpose.
- Edge-to-edge via `androidx.activity` `EdgeToEdge.enable` (API 35+ enforces it);
  the app bar pads for the status bar and stays red in both themes (`@color/app_bar`).
- Per-app locale testing on the emulator:
  `adb shell cmd locale set-app-locales com.qvyshift.sardu --locales it-IT` (or `sc`;
  pass `""` to reset).

## R8, resources and QA (checked for 1.0.2, the first AGP-9 / target-37 release)

- `release` is minified with `proguard-android-optimize.txt` (it always was) plus
  `-dontobfuscate`, and resource shrinking is on. AGP 9's R8 removed more dead library
  code: the universal APK went from 1,172 to 964 classes.
- No WorkManager, Room, Firebase, ML Kit or JNI (the Apertium tools are exec'd as
  processes), so none of the AGP-9 constructor traps apply. `App`, `MainActivity`, the
  `androidx.startup` provider/initializers, `ProfileInstallReceiver` and
  `MaterialComponentsViewInflater` keep `<init>()`.
- `usage.txt` is identical with and without
  `-Pandroid.r8.strictFullModeForKeepRules=false` (`--rerun-tasks` both times).
- AGP 9's R8 resource shrinker drops more than 1.0.1 did (3,667 vs 4,312 resource
  names): unused Material date/time-picker, bottom-sheet and navigation resources, plus
  the never-referenced `color/sardu_cream` and `color/sardu_red_dark`. No code looks up
  app or library resources by name (`getIdentifier` is only called for `android:`
  framework resources), and every reference in the shipped XML resolves.
- The native libs, pair assets and debug symbols in the 1.0.2 AAB are byte-identical
  to 1.0.1's.
- QA build: build the release AAB, then make a debug-signed universal APK from it
  (exactly the release code: minified, non-debuggable):
  `bundletool build-apks --mode=universal --bundle=app/build/outputs/bundle/release/app-release.aab --output=qa.apks --ks ~/.android/debug.keystore --ks-pass pass:android --ks-key-alias androiddebugkey --key-pass pass:android`.
  Do the same with the previous release's AAB for the upgrade test (both
  debug-signed, so `adb install -r` works).
- To drive the app over adb with any text (apostrophes, `$`, `\`), push the text to
  the device and send it in: `adb shell 'am start -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "$(cat /data/local/tmp/t.txt)" -n com.qvyshift.sardu/.MainActivity'`
  after a force-stop (`am start` reuses a running `singleTop` MainActivity, and the app
  doesn't handle `onNewIntent`). Read the result with `uiautomator dump`
  (`outputText`).

## How translation works

`Translator` → `NativePipeline.translate(modeFile, pairDir, text)` parses
`srd-ita.mode` / `ita-srd.mode`, rewrites the `/usr/share/apertium/apertium-srd-ita/…`
paths to `filesDir/pair/`, and spawns the 12 stages as processes from
`nativeLibraryDir` piped together. Measured: ~310 ms per short sentence on the
emulator, well under that on the phone. Unknown words come back with a `*` prefix and
are shown as-is (the footnote explains it).

The mode files start at `lt-proc`, not at Apertium's deformatter, so `NativePipeline`
does the deformatter's escaping itself (1.0.1+): it backslash-escapes the stream
characters `\ [ ] { } ^ $ / @ < >` in the input (the set `apertium-destxt` escapes) and
strips the surviving escapes from the output. Without it, lt-proc stopped with
"Malformed input stream" at the first `/`, `@`, `$`, … (a date like 5/9, an email, a
URL) and the translation was silently cut off there (1.0.0 behaviour). Two upstream
quirks are worked around there too: lrx-proc mis-reads an escaped `^` after the last
word (that trailing text bypasses the pipeline and is re-attached verbatim), and the
generator double-escapes words it can't inflect (a second unescape pass). Any stage
that exits non-zero or reports a malformed stream now fails the translation with the
stage named in the error ("Errore: Apertium stage N (tool) failed …") instead of
returning partial text.

The UI auto-translates 600 ms after typing stops, on IME Done, on the Translate
button, on a phrase chip, and after Paste. Swap moves the current output into the
input (unless it contains a `*`) and re-translates.

## Sardinian written form

The pair targets **Limba Sarda Comuna (LSC)**, the Region's 2006 standard. Output is
LSC; Sardinian input should be in standard spelling (Campidanese spellings hit unknown
words more often). The About dialog says so. Default app locale is Italian; English in
`values-en`, a partial LSC set in `values-sc` (missing strings fall back to Italian).

## Phrase shortcuts

`res/values/phrases.xml` holds 28 aligned Italian/Sardinian pairs. Selection rule: the
phrase had to come out **correct and natural in both directions** with the shipped
data, no `*`/`#`/`@` markers, judged by hand from a ~140-phrase trial run
(`scripts/verify-phrases.sh` reproduces the run; the trial lists live in the session
scratchpad, not here). Things that were rejected, for the record:

- Italian generation bugs in srd→ita: `non` comes out as `no` ("No lo so"), `buon`
  as `buono` ("Buono compleanno"), `ho` as `tengo` ("Tengo fame"), so negatives,
  "Buon X" wishes and avere-idioms are excluded on the Sardinian side.
- Compound greetings `Buonasera`/`Buonanotte` are unknown in ita→srd (two-word
  `Buona notte` works); `Prego` and `Benvenuti` pass through untranslated.
- `abito`/`sono` get mis-tagged ("Abito a Cagliari" → "Bestire in Casteddu";
  "Sono di Sassari" → "Sunt de Tàtari"); use "Vivo a…" / "Io sono di…".
- Some good idiomatic outputs are one-way only (`Buon appetito` → `Bona gana`,
  `A presto` → `A si bìere luego`).

Re-run the script after any pair update and prune anything that regresses.

## Updating the pair data

The bundled files are Apertium Debian nightly `1.3.0+g1147~376bdb52-1~sid1`
(`../pair-jars/apertium-srd-ita.version`). To refresh: rebuild the jar with
`../android/native/prep-pair.sh` (or take the newer jar from `../pair-jars/`), unzip it into `app/src/main/assets/pair/`, bump `versionCode` (that is
what triggers re-extraction on devices), and re-run `scripts/verify-phrases.sh`.

## Licensing

Apertium core and the srd-ita data are GPL-2+; the shipped binaries include
VISL CG-3 (GPL-3), so the app is **GPL-3**. Source must be public when it ships,
and the About dialog names the repo (github.com/rmtheis/translate, `sardu/`).

## Google Play

- Package `com.qvyshift.sardu`, Play Console app id `4973198328359141606`, developer
  account Qvyshift LLC. Created 2026-09-05; first production release 1.0.0
  (versionCode 2) submitted for review the same day, all 177 countries, no staged
  rollout (single release, straight to production per house rule).
- Listing languages: en-US (default, "Sardinian Italian Translator") and it-IT
  ("Traduttore Sardo Italiano"). Play has no Sardinian listing locale. Text, icon,
  feature graphic and phone screenshots were pushed with the Play Developer API
  (`edits.listings`, `edits.images`); the bundle too (`edits.bundles.upload`). The
  declarations (privacy policy, ads = none, sign-in = none, IARC = all ages, target
  age 18+, data safety = no collection, no government/financial/health features,
  advertising ID = not used) and category (Tools) were done in the console UI.
- Privacy policy: https://www.qvyshift.com/privacy-policy-sardu.html (in the
  `qvyshift-website` repo, `public/`; deploys on push to master).
- Play "automatic protection" (installer check) was turned OFF at app creation:
  GPL app, sideloading must keep working.
- Release notes: leave empty, or use the stock behind-the-scenes set (house rule).
- Releasing an update: check every track's versionCodes first (never reuse one), bump
  `versionCode`/`versionName` in `app/build.gradle`, build the signed AAB (see "Not
  done / open" for the upload-key env vars), then
  `python3 scripts/upload_to_play.py --rollout 0.05 --release-notes-dir
  ~/Documents/app-store-optimization/stock-release-notes/behind-the-scenes`
  (production track, 5% staged, `inProgress`; Play keeps only the en-US and it-IT
  notes). From 1.0.2 on, releases are staged and the central play-rollout advancer
  (`~/Documents/app-store-optimization/play-rollout/`, `packages.json`) walks them to
  100%; 1.0.0 and 1.0.1 went straight to 100% with `--status completed`. Add
  `--dry-run` to upload, set the track and validate, then delete the edit (nothing
  published). The script uses the shared publisher OAuth token at
  `~/Documents/mines/android/.oauth_token.json`; without `--rollout`/`--status` it
  only creates a draft.
- Screenshots for Play must be 9:16 to 16:9: crop the 1080x2400 emulator captures
  to 1080x1920 (the bottom is empty anyway).

## Not done / open

- No CI. Release signing: `app/upload.keystore` (gitignored) is the dedicated
  sardu upload key; the master copy and its passwords are in the private
  `translate/` dir (`sardu-upload.keystore`, `HANDOFF.md`). Build a signed AAB with
  `UPLOAD_KEYSTORE_PASSWORD=… UPLOAD_KEY_ALIAS=upload UPLOAD_KEY_PASSWORD=… ./gradlew bundleRelease`.
- No release CI yet: bump `versionCode`, `./gradlew bundleRelease` with the upload-key
  env vars, then `scripts/upload_to_play.py` (see "Google Play").
- Consider trimming to arm64-only for the first release if size matters.
