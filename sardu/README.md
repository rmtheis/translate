# Traduttore Sardo / Sardinian Translator (`com.qvyshift.sardu`)

Single-pair, fully offline Android translator: **Sardinian ⇄ Italian**, powered by
Apertium's `apertium-srd-ita` pair. Text only, no ads, no network permission. A
standalone test app to see whether a dedicated Sardinian app finds users; see
`RESEARCH-single-pair-apps-2026-09.md` in the (private, out-of-git) `translate/` dir for the why.

Status (2026-09-05): v1.0.0 (versionCode 2, with native debug symbols) submitted to Google
Play production, awaiting review.
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
fallback.) `app/build.gradle` sets `ndkVersion` and `release.ndk.debugSymbolLevel 'FULL'`,
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

- Gradle 8.11.1 wrapper, AGP 8.9.2, compileSdk/targetSdk 36, **minSdk 26** (adaptive
  icon only, no legacy PNGs). `~/.gradle/gradle.properties` points Gradle at
  Corretto 17.
- ABIs: `arm64-v8a` + `armeabi-v7a` only. **x86 emulators cannot run it**; use an arm64
  AVD (`Medium_Phone_API_36` = `emulator-5554` on this Mac).
- Native tools are stored uncompressed (`useLegacyPackaging`, required so
  `ProcessBuilder` can exec them). Play reports ~23 MB install size per device.
- To install the release AAB on the emulator exactly as Play would ship it:
  `bundletool build-apks --bundle=… --connected-device --device-id=emulator-5554 --ks=app/upload.keystore …`
  then `bundletool install-apks`.
- No `INTERNET` permission, on purpose.
- Edge-to-edge via `androidx.activity` `EdgeToEdge.enable` (API 35+ enforces it);
  the app bar pads for the status bar and stays red in both themes (`@color/app_bar`).
- Per-app locale testing on the emulator:
  `adb shell cmd locale set-app-locales com.qvyshift.sardu --locales it-IT` (or `sc`;
  pass `""` to reset).

## How translation works

`Translator` → `NativePipeline.translate(modeFile, pairDir, text)` parses
`srd-ita.mode` / `ita-srd.mode`, rewrites the `/usr/share/apertium/apertium-srd-ita/…`
paths to `filesDir/pair/`, and spawns the 12 stages as processes from
`nativeLibraryDir` piped together. Measured: ~310 ms per short sentence on the
emulator, well under that on the phone. Unknown words come back with a `*` prefix and
are shown as-is (the footnote explains it).

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
- Screenshots for Play must be 9:16 to 16:9: crop the 1080x2400 emulator captures
  to 1080x1920 (the bottom is empty anyway).

## Not done / open

- No CI. Release signing: `app/upload.keystore` (gitignored) is the dedicated
  sardu upload key; the master copy and its passwords are in the private
  `translate/` dir (`sardu-upload.keystore`, `HANDOFF.md`). Build a signed AAB with
  `UPLOAD_KEYSTORE_PASSWORD=… UPLOAD_KEY_ALIAS=upload UPLOAD_KEY_PASSWORD=… ./gradlew bundleRelease`.
- No release CI yet: bump `versionCode`, `./gradlew bundleRelease` with the upload-key
  env vars, upload with the Play API (see the monorepo's `android/upload` scripts for
  the pattern) or in the console.
- Consider trimming to arm64-only for the first release if size matters.
