# android — Translate (Experimental) for Android

Package `com.qvyshift.translate`. Offline Apertium translation: the Apertium C++
tools are cross-compiled with the NDK (`native/`), shipped as `lib*.so` executables
in `app/src/main/jniLibs/`, and run as a stdin→stdout pipeline via `ProcessBuilder`
(`NativePipeline.java`). There is no JNI. Language pairs are on-demand Play Asset
Delivery packs (`pair_<src>_<tgt>/`). No ads, no Firebase; one optional donation through
Play Billing (see "Donate button").

## Releases (CI only)

Releases are built and published by `.github/workflows/release-android.yml`, on a
monthly cron and on manual dispatch. Don't upload by hand.

- **natives** (cross-compile, cached by the `android/native/` tree SHA) → **pairs**
  (`scripts/list-enabled-pairs.sh` → `android/native/prep-pair.sh` per pair →
  `scripts/pair-inventory.py`) → **build** (`install-natives-android.sh`,
  `check-pair-tools.py`, `stage-pair-packs.sh`, version bump,
  `./gradlew :app:testDebugUnitTest`, then `./gradlew :app:bundleRelease`) → **deploy**.
- The deploy job publishes only when a pair changed since `.ci/prior-pair-inventory-android.json`,
  unless the run was dispatched with `force_publish=true`. `stock_notes=true` swaps the
  pair-diff notes for the stock "Behind-the-scenes changes…" line. Either way the English
  notes go to en-US and the other English languages only: `scripts/play_release_notes.py`
  writes every other listing language's own stock line (the `whatsNew` of
  `play/listings/<language>.json`) as `whatsnew/whatsnew-<language>`, so no non-English
  listing shows English notes (added 2026-11-01; Play shows en-US's notes to any language
  without a file, which is how 1.0.13 and 1.0.14 went out — back-filled by hand that day).
- **Every release goes to production as a 5% staged rollout** (`status: inProgress`,
  `userFraction: 0.05`; changed from `completed` on 2026-10-06). The central advancer
  in `~/Documents/app-store-optimization/play-rollout/` walks it to 100% and holds it
  when crash/ANR vitals regress. Emergency stop: halt the release in Play Console.
- App-code-only release (manual):

  ```sh
  gh workflow run release-android.yml -R rmtheis/translate --ref master \
    -f force_publish=true -f stock_notes=true
  ```

- **versionCode** is `yyyymmddHH` (UTC) of the build, written into the manifest by
  CI; the manifest's checked-in `1031` is a placeholder. **versionName**: CI bumps
  the patch of the checked-in value (1.0.11 → 1.0.12) and commits the bump back
  after a successful publish. Never bump versionName by hand, or CI skips a number.
- Signing: CI decodes `PLAY_UPLOAD_KEYSTORE_BASE64` into `app/upload.keystore` and
  passes `UPLOAD_KEYSTORE_PASSWORD` / `UPLOAD_KEY_ALIAS` / `UPLOAD_KEY_PASSWORD`.
  Without that file, `release` falls back to the debug key (local QA builds).
- The jobs run on `ubuntu-latest`, which became **Ubuntu 26.04** in November 2026. Its
  coreutils are the Rust **uutils** multicall binary, which picks the utility from argv[0]:
  the 2026-11-01 cron (run 41272141038) failed two `NativePipelineTest` tests because they
  stood in for the Apertium binaries with symlinks to `/bin/cat`, and `liblt_proc.so` is not
  a utility name ("function/utility not found", exit 1, stdin unread). The test now writes
  `#!/bin/sh` shims that exec the tool by path. Never symlink or copy a host tool under
  another name in anything that runs on the runner.
- **Play "Installer check" is OFF for this app** (Play Console → app → Protected with Play →
  Automatic protection → Manage; turned off 2026-11-01). Google's automatic protection now
  requires minSdk 24, and with the check on, Play rejects every upload of this minSdk-21 app
  ("Play automatic protection requires a minimum SDK version of 24 or higher"; 1.0.13 still
  uploaded fine on 2026-10-07, when the floor was 21). Don't turn it back on while minSdk is 21.

## Toolchain

- Gradle 9.6.1 wrapper, AGP 9.4.1, JDK 17 (CI: temurin 17; locally
  `~/.gradle/gradle.properties` points at Corretto 17).
- compileSdk 37, targetSdk 37, **minSdk 21: never raise it**.
- `androidx.fragment` 1.8.9 and `androidx.activity` 1.11.0 are pinned directly
  (asset-delivery and material otherwise drag in fragment 1.1.0, which Play Console
  flags). They are the last releases that declare minSdk 21; don't bump past them.
- AGP 9 adds `kotlin-stdlib` to the classpath even in this Java-only app (built-in
  Kotlin); R8 strips what isn't used.
- AGP 9 only creates unit-test tasks for the tested build type: CI's
  `:app:testDebugUnitTest` exists, `testReleaseUnitTest` doesn't.
- **Lint `NewApi` is fatal and fails the release build** (`app/build.gradle`): every
  `bundleRelease` runs `lintVitalRelease`, which checks only fatal issues. That needs
  `abortOnError = true` as well: with it off (as it was until 2026-10-07), lintVital prints
  the errors and the build still succeeds. A full `:app:lintRelease` now also fails on plain
  errors (none at the moment). Java 8+ library calls need an `SDK_INT` check or an
  API-21 equivalent: D8 doesn't backport `Map.computeIfAbsent`, `Comparator.comparing`,
  `File.toPath` or `Process.isAlive`, and R8's API outlining adds no version check, so on
  an older device they throw `NoSuchMethodError` / `NoClassDefFoundError`. Core library
  desugaring would cover some of them, at a cost in APK size and R8 time; the app doesn't
  use it.

## R8 and resources (checked for 1.0.12, the first AGP-9 / target-37 release)

- `release` is minified with `proguard-android-optimize.txt` (AGP 9 rejects
  `proguard-android.txt`), so R8 optimizes the app for the first time. `-dontobfuscate`
  stays (`proguard-project.txt`). The universal APK dropped from 2,492 to 1,351
  classes. Verify every R8 change on the minified build: translate in several pairs,
  pair download, settings, upgrade from the live build.
- No WorkManager, Room, Firebase or ML Kit, so none of the AGP-9 constructor traps
  apply. The manifest and `androidx.startup` classes keep `<init>()`.
- `usage.txt` is identical with and without `-Pandroid.r8.strictFullModeForKeepRules=false`
  (`--rerun-tasks`). Resource shrinking is off: the resource table and every `res/`
  file match 1.0.11, plus one id from `androidx.core:core-viewtree`.

## Native libraries

- `packaging.jniLibs.useLegacyPackaging = true` (and the manifest's
  `extractNativeLibs="true"`, which AGP warns about) keep the tools compressed in the
  APK and extracted to `nativeLibraryDir` at install, so they can be exec'd. The
  zip-offset rule for 16 KB pages therefore doesn't apply; every arm64 `.so` has
  ELF `p_align` ≥ 0x4000.
- AGP 9.4.1's default `ndkVersion` is 28.2.13676358, the same NDK the workflow
  installs, so AGP now re-strips the already-stripped libs (only `.shstrtab` and the
  section headers move) and stores `.sym` files under `BUNDLE-METADATA/` in the AAB.
  Users don't download them.
- **Which tools ship**: the `TOOLS` list in `scripts/install-natives-android.sh`.
  Each tool a pair's `.mode` file runs also needs a `TOOL_LIBS` entry in
  `NativePipeline.java` (mode-file name → `lib*.so`). `scripts/check-pair-tools.py`
  fails the CI build when a direction `PairCatalog` offers runs a tool missing from
  either. In the 1.0.12 pair set, `hfst-proc` (sme-nob) and `lt-merge` (nob-nno) are
  each used by one direction; `hfst-proc` ships as the real `hfst-apertium-proc` binary
  (HFST installs `hfst-proc` as a symlink to it).
- CI uses `scripts/install-natives-android.sh`; `android/native/install-to-app.sh` is
  the older script for a local cross-compile. They drifted once already (the CI one
  never shipped `hfst-proc`), and `install-to-app.sh` still lacks `lt-merge`. Fix that
  with the next real `android/native/` change, not on its own: any edit under
  `android/native/` changes the natives cache key, and the cache-miss rebuild (~1 h)
  clones lttoolbox, apertium, cg3, HFST, ... at upstream HEAD, so every tool changes.

## Pair-data workarounds in `NativePipeline`

Two pair-data bugs that segfault apertium-transfer are worked around in the app, not in
`android/native/prep-pair.sh`: a changed pair JAR changes its hash, which trips the monthly
release gate and turns into inventory-diff release notes. iOS has the same two in
`ios/native/wrappers/apertium_core.cpp` (`ios/README.md`, "Mode-file tools and flags").

- `useRulesXmlForBin()`, applied in `parseModeLine`: apertium-transfer, -interchunk and
  -postchunk get `X.t1x` in place of the mode's rules XML when the stage's `.bin` is
  `X.t1x.bin` and `X.t1x` is in the pair dir. A `.bin`'s rule numbers index the XML it was
  compiled from. The 2022 Debian oci-cat mode passes the unfiltered
  `apertium-oci-cat.oci-cat.t1x`/`t2x`/`t3x` (155/23/12 rules) with `.bin`s built from the
  `alt`-filtered `oci-cat.t1x`/... (132/22/7), so every oci→cat sentence ran the wrong rules.
  In the 1.0.12 pair set no other mode's stages have such a file.
- `stripDependencyTags()`: every cg-proc stage's output is read whole (the pipe to the next
  stage, or the final drain: sme-nob's mode ends with `cg-proc -1 -n -g`), and CG-3
  dependency tags (`<#1→2>`) inside lexical units are dropped. hbs-mkd.rlx's SETPARENT rules
  make cg-proc print them, apertium-pretransfer reads the `#` as a multiword split, and
  apertium-transfer crashes. Escaped text and `[superblanks]` pass through, and output without
  a `→` is passed on as the same bytes, so the other directions that run cg-proc don't change.

## Local builds and QA

`jniLibs/` and the pair JARs are populated from CI artifacts (they expire 7 days after
a run):

```sh
RUN=$(gh run list -R rmtheis/translate --workflow release-android.yml --limit 1 --json databaseId -q '.[0].databaseId')
gh run download $RUN -R rmtheis/translate -n natives-arm64-v8a   -D /tmp/natives/arm64-v8a
gh run download $RUN -R rmtheis/translate -n natives-armeabi-v7a -D /tmp/natives/armeabi-v7a
gh run download $RUN -R rmtheis/translate -n pairs -D /tmp/pairs
chmod +x /tmp/natives/*/bin/*
ANDROID_NDK_HOME=~/Library/Android/sdk/ndk/28.2.13676358 ./scripts/install-natives-android.sh arm64-v8a /tmp/natives/arm64-v8a
ANDROID_NDK_HOME=~/Library/Android/sdk/ndk/28.2.13676358 ./scripts/install-natives-android.sh armeabi-v7a /tmp/natives/armeabi-v7a
python3 scripts/check-pair-tools.py /tmp/pairs/pair-jars android/app/src/main/jniLibs
./scripts/stage-pair-packs.sh /tmp/pairs/pair-jars   # rewrites the tracked pair JARs: use a worktree
cd android && ./gradlew :app:testDebugUnitTest && ./gradlew :app:bundleRelease
```

- Without `app/upload.keystore`, `bundleRelease` gives the QA build: minified,
  optimized, non-debuggable, debug-signed.
- On-demand pair packs only work when installed with bundletool's local testing:
  `bundletool build-apks --local-testing --bundle=app/build/outputs/bundle/release/app-release.aab --output=qa.apks --ks ~/.android/debug.keystore ...`
  then `bundletool install-apks --apks=qa.apks --device-id=<emulator>`.
- A clean worktree has no `local.properties`: `export ANDROID_HOME=~/Library/Android/sdk`
  first (CI runners set it).
- arm64 emulators only (no x86 natives). Never a physical device for QA.
- Upgrade test: install the live AAB's APK set (`build-apks --local-testing` re-signs it
  with the debug key), download a few pairs, change settings, then `install-apks` the
  new set over it. The app restarts during that install and asks for the stale packs
  *before* bundletool has pushed the new ones, so the refresh hangs; force-stop and
  relaunch, and the pairs re-extract at the new versionCode. Don't use "Download all"
  on the Medium Phone AVD: the extracted pairs fill `/data`, and the upgrade install
  then fails with "not enough space".
- The upgrade install needs a higher versionCode than the live build, and the
  checked-in `1031` is lower (`INSTALL_FAILED_VERSION_DOWNGRADE`). In the QA worktree,
  apply CI's bump before `bundleRelease`: versionCode `$(date -u +%Y%m%d%H)`,
  versionName +1 patch. Never commit that.
- Driving translations from adb: `adb shell input text` can't type non-ASCII (Sami,
  Nordic letters), so cold-start the activity with the text and pair instead:
  `am start -n com.qvyshift.translate/.TranslatorActivity -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT '<text>' --es mode '<dropdown title>'`
  (e.g. `Northern Sami → Norwegian Bokmål`), then tap Translate. The pair must already
  be downloaded. uiautomator can't see the pair dropdown's popup list, so pick pairs to
  download by screenshot coordinates, or download them all: tap Settings (`id/manage`),
  then `id/downloadAllButton` (about 10 s with local testing; give the AVD
  `disk.dataPartition.size=16G` first).
- The AVDs on this Mac have `disk.dataPartition.path=<temp>` (avdmanager writes it for new
  ones too): `/data` is wiped at every boot, so install and download the pairs again.
- Old Android: AVDs `Translate_API23` and `Translate_API25` (Medium Phone profile, 16G data)
  use `system-images;android-23;default;arm64-v8a` and `…android-25;default;arm64-v8a`. The
  `google_apis` arm64 images for 23–25 reportedly freeze after boot on Apple Silicon. API 23
  covers 21–23 (libcore's `ProcessManager`, no `java.util.function`), API 25 covers 24–25
  (OpenJDK's `UNIXProcess`, still no `Process.isAlive`). Driver gotchas there: uiautomator
  reports an EditText's text, and the pair dropdown's, as `<text>, <hint>`
  (`"El gat dorm.\n, Catalan"`); API 23 can't `uiautomator dump /dev/tty` via `exec-out`
  (dump to a file and `cat` it); `pm clear` also deletes the local-testing packs under
  `/sdcard/Android/data/`, after which pair downloads hang (uninstall and `install-apks`
  again instead).

## Localization

- UI strings: `values/` (English) and one `values-<lang>/` per UI language (49 besides
  English, the same set as the iOS string catalog). Regional variants exist only where the
  text differs from the base language; added 2026-11-01 for the App Store / Play locales:
  `values-pt-rPT/` ("transferir", "línguas"), `values-es-rMX/` ("En preparación",
  "se descargaron") and `values-fr-rCA/` (no space before "?", app name "Traduire").
  en-GB / en-AU / en-CA resolve to `values/`. Keep the format placeholders (`%1$d`,
  `%1$s`) exactly as in English and never copy English into a non-English file.
  `app_name` (launcher label and toolbar title) is translated in every Play listing
  language and matches the listing title's first word (da "Oversæt", es "Traducir",
  pt "Traduzir", ro "Traducere", sv "Översätt", uk "Переклад" were added 2026-11-01 so
  the localized screenshots show no English); other languages still say "Translate".
- Pair titles in the dropdown (`LanguageTitles`): Java's `Locale.getDisplayLanguage()` in
  the UI language, falling back to the English table. The fallback test compares against
  the English display name, not the code: in Catalan the name of Russian is "rus", which
  equals the ISO code. Codes Java doesn't know (hbs) show the English title in every
  language ("Serbo-Croatian → engleski").
- Running the app in a language on an AVD: `adb shell cmd locale set-app-locales
  com.qvyshift.translate --user 0 --locales pt-PT` (per-app locale; the app has no
  `localeConfig`, so only adb can set it; reset with `--locales ""`). The language splits
  must be installed: `bundletool install-apks` pushes only the device's language, so
  `bundletool extract-apks --apks qa.apks --output-dir d --device-spec spec.json` with a
  `supportedLocales` list of every language needed, then `adb install-multiple -r -t
  d/*.apk`. The `--es mode` title of the SEND cold start is the dropdown title in that
  language (`català → espanyol`; for hbs `Serbo-Croatian → engleski`); wrap the whole
  `am start` in `adb shell "…"` so the spaces survive.
- Sample captures (main screen + open picker, 8 locales, Medium Phone API 36, SysUI demo
  status bar): `screenshots/localization-sample/android/`; the gallery with iOS side by
  side is `screenshots/localization-sample/index.html`, rendered by
  `scripts/localization-gallery.py` and opened with `open -a "Brave Browser" <path>`.

## Donate button (Play Billing)

The About + Settings dialog has a "Donate" button under the download button, in the same
outlined style (`dialog_about_settings.xml`): a one-time Play product, id `support_2026`
(`support_product_id` in `values/strings.xml`; code in `SupportPurchase.java`, `App.java`,
`TranslatorActivity.configureDonateButton`, modeled on Loyalty Card Wallet's). `SupportPurchase` is one instance per process: `App` creates it when
the first activity is resumed, so the Play connection and the price lookup run in the
background before anyone opens the dialog (logcat tag `SupportPurchase`). Not from
`Application.onCreate` itself: on Android 14 that connection never completes until an activity
makes a billing call.

- The button reads plain `about_donate` until Play's localized price is known, then
  "DONATE • <price>" (`about_donate_row`). The style is all caps, but only the label follows it:
  Play's price stays exactly as Play formatted it. **No price is hardcoded anywhere**, and
  `DonateStringsTest` fails on a digit in those strings. Without Play Billing (emulators with no
  account, sideloads on a device with no account) it stays "DONATE", still looks enabled, and a
  tap does nothing.
- After a purchase, or when `queryPurchasesAsync` finds an earlier one, the button is disabled and
  shows `about_support_thanks`, like the download button once every pair is downloaded. Right
  after a purchase a dialog says thank you (`donation_thanks_title`, `donation_thanks_message`).
  Purchases are acknowledged, never consumed, and unlock nothing. Debuggable builds: long-press
  the button to preview that dialog.
- The strings are translated in all 52 `values-*` folders (`DonateStringsTest` checks that none
  is missing or English). The ones not taken from Loyalty Card Wallet, written 2026-11-02 and not
  reviewed by a native speaker: af an ast br crh cy eo fo gl hr is kk mk ms mt nn oc pt-PT sc scn se
  sr-Latn szl tet ur.
- **Billing is pinned to 8.0.0**, the newest release with minSdkVersion 21 (8.1.0 raised it to
  23, checked from the AAR manifests 2026-11-02). Google's deprecation table takes 8.x in new
  updates until 2027-08-31, extension 2027-11-01. Before then minSdk has to rise to 23 or the button
  has to go. billing pulls `play-services-location` but no location permission; the merged
  manifest gains only `com.android.vending.BILLING` and `ACCESS_NETWORK_STATE`.
- Play side: `scripts/play_create_donation_product.py` (dry run by default, `--create`, `--show`;
  US$ 2.99 converted once with `monetization.convertRegionPrices`, 174 regional prices, listing
  text per store language in `scripts/_donation_i18n.py`). **Play refuses the product ("Can't
  create product. To fix, request billing permission.") until an uploaded bundle declares
  `BILLING`**, so run `--create` right after the first release that carries this code; the button
  stays plain "DONATE" and inert until then. Status 2026-11-02: code not released, product not
  created. Credentials as for `play_upload_listings.py`.

QA on 2026-11-02: unit tests; debug on API 23 and 36 emulators (button, locales, RTL, thank-you
preview); R8 release build on API 36; debug on the moto g (Android 14, real Play: "Billing
connected" 1 s after launch). The price and a real purchase are unverified until the product exists.

## Known issues

- In 1.0.12 and earlier, Northern Sami → Norwegian Bokmål and Norwegian Bokmål → Nynorsk
  fail, and so do Serbo-Croatian → Macedonian and Occitan → Catalan on many inputs ("Dobar
  dan.", "L'ostal es grand."; apertium-transfer exits with 139, a segfault). Fixed in
  1.0.13 (see the release log and "Pair-data workarounds in `NativePipeline`").
- 1.0.12 and earlier don't work on Android 5.0–7.1 (API 21–25), although minSdk is 21. On
  API 21–23 the app crashes at every launch (`NoClassDefFoundError` for the
  `Map.computeIfAbsent` lambda in `PairListAdapter`: its class implements
  `java.util.function.Function`, API 24). On API 24–25 every translation fails with
  "error: java.lang.NoSuchMethodError: No virtual method isAlive()Z" (`NativePipeline`), and
  once a pair is downloaded every launch crashes in `App.onCreate` (`File.toPath` in
  `PairDownloadManager.readMarker`, API 26). Play's install export has no API 21–25 installs
  through September 2026 and Play reports no crashes. Fixed in 1.0.13, and lint
  now fails the release build on such calls (see "Toolchain").
- In 1.0.12 and earlier, text over about 64 KiB never translates: the button stays on
  "Translating…" (and disabled) until the app is killed. Stage 0's
  stdin was written on the translation thread before stage 1 was started, so nothing drained
  stage 0's stdout and both pipes filled. Fixed in 1.0.13.
- Occitan → Catalan is the 2022 Debian nightly's data: its analyzer misses common words, so
  "L'ostal es grand." comes out as "El *ostal *es *grand.", the same as on iOS.

## Release log

- **1.0.14** (2026110112; published 2026-11-01 to production at 5% staged by
  release-android.yml run 41305484232, manual dispatch with default inputs, so the
  pair-diff notes): the four pairs the monthly check found updated — fra-cat 116 → 117,
  nno-nob g9174 → g9200, oci-fra 9 → 10, sme-nob 95 → 128. App code change: only the
  `NativePipelineTest` shell shims (`019f2cb`). **Natives are new**: the Nov 1 cron run
  (41272141038) missed the natives cache (expired after 7 unused days) and rebuilt every
  tool from upstream HEAD; the dispatches reused that cache. So 1.0.14 ships 2026-11-01
  upstream code, not the QA'd 1.0.12 natives — watch vitals during the rollout.
  Two attempts failed first: the cron itself (two unit tests, see the `ubuntu-latest`
  note under "Releases") and dispatch 41300955395 (Play rejected the AAB: "Play automatic
  protection requires a minimum SDK version of 24"; fixed by turning Installer check off,
  see "Releases"). 1.0.13 had reached 100% before this. Shipped with `whatsnew-en-US`
  only, so the 18 other listing languages showed the English pair-diff notes; on
  2026-11-01 the stock lines were added to both 1.0.14 and 1.0.13 on the production
  track by a `tracks.update` that left the rollout state alone, and the workflow now
  writes them itself (see "Releases").
- **1.0.13** (2026100720; published 2026-10-07 to production at 5% staged by
  release-android.yml run 37678897602, `force_publish` + `stock_notes`): ships `libhfst_proc.so` and
  `liblt_merge.so` for both ABIs, plus the `lt-merge` mapping in `NativePipeline`. Fixes
  sme→nob ("native binary not executable: …/libhfst_proc.so") and nob→nno ("no native
  binary mapping for tool 'lt-merge'"). sme→nob was broken since at least 1.0.11; nob→nno
  at least since the April 2026 pair JARs, whose mode already ran `lt-merge`. CI now runs
  `check-pair-tools.py`. Natives unchanged: the run restored the cached 1.0.12 natives
  (same `android/native/` SHA, cache hit for both ABIs), the ones QA'd below.
  QA 2026-10-06 on Medium_Phone_API_37: 18/18 unit tests, CI 1.0.12 natives + pairs.
  On-device upgrade from the live 1.0.12 AAB: before the upgrade, all 8 sme→nob and
  4 nob→nno test sentences failed; after it, all translate (escaped `/` and `@`
  included). eng→spa, spa→eng and nno→nob are byte-identical to 1.0.12 (11/11). The
  new arm64 libs have `p_align` 0x4000/0x10000. armeabi-v7a is checked only statically
  (ELF + `DT_NEEDED`); there's no arm32 emulator.
- **1.0.13, continued** (committed 2026-10-07): Serbo-Croatian → Macedonian and
  Occitan → Catalan translate instead of failing with "apertium-transfer failed with exit
  code 139" (see "Pair-data workarounds in `NativePipeline`"). App code only; pair JARs and
  natives unchanged. QA 2026-10-07 on Medium_Phone_API_36 with the release-android.yml run
  37552230291 (1.0.12) arm64 natives and pair JARs, minified QA builds of ccbbe53 without and
  with the change, 49 directions through the app UI (the iOS QA corpus):
  - 47 directions byte-identical (157 sentences).
  - hbs→mkd: 6 of 8 sentences failed before, 8/8 translate after; oci→cat: 4 of 8 failed
    before, 8/8 after. All 16 match the iOS output (`a5f2578`), e.g. "Dobar dan." →
    "Добар даден.", "Ja sam student." → "Јас сам студент.", "Lo gat dormís sus la cadièra
    vièlha." → "El gat dorm sobre la *cadièra *vièlha.".
  - A further 28 hbs→mkd and 25 oci→cat sentences (caps, punctuation, email, `$`/`€`, a
    typed `<#1→2>`, which comes through unchanged) all translate.
  - Unit tests: 28/28 on master with this change (`NativePipelineTest` 24, 6 of them new
    for the two workarounds; `LanguageTitlesTest` 4).
- **1.0.13, continued** (`ce128a9`, 2026-10-07): the pair list names Serbo-Croatian
  instead of showing the code ("hbs → Macedonian", "Macedonian → hbs (SR)", "hbs → English",
  "English → hbs"). `LanguageTitles` asks `Locale` first, and no Android version names the
  `hbs` macrolanguage, so `codeToTitle` now has it ("Serbo-Croatian", as on iOS). Every other
  code in the 49 offered directions gets a `Locale` name: checked on API 29/34/35/36 emulators
  in all 74 system UI languages, and for API 21–28 against the ICU 53–60 source. A pair title
  is also the saved selection (`PREF_lastModeTitle`) and the `mode` extra, so a title that
  isn't installed goes through `LanguageTitles.upgradeTitle()` (bare code → current name)
  before the first-pair fallback. QA 2026-10-07 on Medium_Phone_API_37 with minified QA builds
  of ccbbe53 without and with the change (CI 1.0.12 natives + pairs): 22/22 unit tests; with
  "Macedonian → hbs (SR)" saved and English → Spanish also installed, the upgraded app reopens
  on "Macedonian → Serbo-Croatian (SR)"; `--es mode 'hbs → Macedonian'` opens
  "Serbo-Croatian → Macedonian".
- **1.0.13, continued** (2026-10-07): the app works on Android 5.0–7.1 (API 21–25)
  again, and long text translates instead of hanging (both in "Known issues"). App code
  only; pair JARs and natives unchanged.
  - `NativePipeline` checks `SDK_INT` before `Process.isAlive`/`destroyForcibly` (`destroy()`
    below 26) and writes stage 0's stdin on its own thread; `PairDownloadManager.readMarker`
    reads with a `FileInputStream`; `PairListAdapter` no longer uses `computeIfAbsent` or
    `Comparator.comparing`. The unused `App.isOnline()` is gone (its `MissingPermission` was
    lint's only other error). `NewApi` now fails the release build (see "Toolchain").
  - QA 2026-10-07 with the release-android.yml run 37552230291 (1.0.12) arm64 natives and
    pair JARs, minified QA builds of `5302c06` without and with the change. Unit tests 31/31
    (3 new run `runPipeline` with `cat`/`true`/`false` as stages; the 1 MiB one times out
    on the old code). `:app:lintRelease` has no errors, and `bundleRelease` fails at
    `lintVitalRelease` with the old `PairListAdapter` put back. In the dex, the old build
    calls all six API-24/26 methods unguarded; the new one only `isAlive`/`destroyForcibly`,
    behind `SDK_INT >= 26`.
  - API 36 (two Medium Phone AVDs on the same image): 49 directions, 220 sentences (the iOS
    corpus plus the hbs/oci stress sets) byte-identical before and after. A 40-line input
    is identical in eng→spa, eng→cat and spa→eng. A 100 KB eng→spa paste: before, still
    "Translating…" after 240 s with only stage 0 running; after, done in 7 s.
  - `Translate_API23` and `Translate_API25`: the old build crashes at launch on 23; on 25
    a translation gives the `isAlive` error and the next launch, with a pair downloaded,
    crashes. The new build downloads all 27 pairs and translates on both: the 220-sentence
    run (a cold start per sentence) is byte-identical to API 36, with no crash, and the
    100 KB paste takes 6 s.
- **1.0.12** (versionCode = the CI run's `yyyymmddHH`; prepared 2026-10-06): AGP 9.4.1,
  Gradle 9.6.1, target 37, first R8-optimized build, first 5% staged release. QA on the
  minified, debug-signed QA build: 18/18 unit tests, lintVital clean, smoke PASS on
  Medium_Phone_API_37 and Medium_Tablet_API_37, translations byte-identical to 1.0.11 in
  6 directions (eng↔spa, spa→cat, nno→nob, rus→ukr, cat→ita), upgrade from 1.0.11 keeps
  the chosen pair, the marks setting and the downloaded pairs.
- **1.0.11** (2026092911): input-escaping fix, 100% on production.

## Play listing graphics

- `play/icon_512.png` is the icon. The feature graphics are generated:
  `scripts/feature-graphic.py` sets the two text lines of every listing language
  (its `TEXTS` table; the subtitle carries the pair count, 27 since 1.0.13) on
  `play/feature_graphic_base.png` — the designer's background, watermark and
  logo with the text removed (reconstructed 2026-11-01) — in Helvetica Neue via
  CoreText (`ct_text.py` in `~/Documents/app-store-optimization/tools/feature-graphic/`,
  so Cyrillic renders with real fonts), fitted into the Play safe box x 100..924
  (Play web crops cards to 16:9). Output: `play/feature_graphic.png` (en-US) and
  `play/feature_graphic_<language>.png` for the 15 other languages; en-GB/en-AU/
  en-CA reuse en-US's. Run with `/usr/local/bin/python3` (has PyObjC); `--check`
  writes the 16:9 preview crops next to the files.
- Phone screenshots: six plain 1080x2400 Medium Phone captures per language
  (Spanish → Catalan, Portuguese → Catalan, Swedish → Danish; each before and
  after Translate), `screenshots/play-phone/<language>/`, made by
  `scripts/screenshots-android.sh` (see its header; en-US's live set is the
  model). No tablet images. Capture on the **Android 14** Medium Phone AVD
  (`Screenshots_API_34`): from Android 15 the app is drawn edge-to-edge and
  `android:statusBarColor` is ignored, so an API 35/36 emulator gives a cream
  status bar with a near-invisible white clock instead of the dark-red bar of
  the live set. `Screenshots_API_34` keeps its `/data` across boots despite
  `disk.dataPartition.path=<temp>`; if `system_server` crash-loops at boot
  with "There must be exactly one permissions manager; found []", start it
  once with `-wipe-data`, then `bundletool install-apks --apks qa.apks
  --device-id emulator-NNNN` (pushes the local-testing packs) and
  `scripts/android-download-all-pairs.sh emulator-NNNN`, which taps Settings →
  Download all and waits on Play Core's logcat lines (all 27 pairs fit in its
  6 GB `/data`; don't poll the progress dialog with `uiautomator dump` — it
  fails while the bar animates and a Back/force-stop then kills the download).
- Upload: `SA_JSON_FILE=<androidpublisher key> python3 scripts/play_upload_images.py`
  replaces the phone screenshots and the feature graphic of every language that
  has files (en-GB/en-AU/en-CA copy en-US's live screenshots) with
  `images.deleteall` + upload; dry run validates and deletes the edit, `--commit`
  publishes; `--languages`, `--no-feature-graphic`, `--no-screenshots` narrow it.
  Play shows the default language's images to a language without its own, so a
  new listing language needs its images in the same release as its text.

## Play listing text

- CI maintains the pair list of every listing language: after a pair change the deploy
  job of `release-android.yml` runs
  `scripts/update-store-description.py listing-languages.txt pair-inventory.json`, which
  in one edit replaces the text between the `<!-- AUTO-GENERATED LANGUAGES -->` markers of
  every listing — en-US with the block `scripts/store-listing.py` rendered (English
  names), each other language with the block `scripts/_listing_i18n.py` renders from the
  `pairsHeader` of `play/listings/<language>.json` and the CLDR names in
  `scripts/language-names.json` — and commits once. Titles, short descriptions and the
  text before the markers are not touched; a language without a listing JSON or without
  markers is skipped with a warning annotation, and the English block never goes into
  another language. `--dry-run` opens and deletes the edit instead of committing,
  `--render-dir DIR` writes the composed texts, `SA_JSON_FILE=<path>` stands in for
  `SA_JSON` locally. Release notes: `scripts/play_release_notes.py whatsnew/whatsnew-en-US
  whatsnew` writes one `whatsnew-<language>` file per listing language — the English
  languages get the English notes, every other language the `whatsNew` stock line of its
  listing JSON, never English — because Play shows the default language's notes to any
  language without its own file. `python3 scripts/test-listing-i18n.py` checks all of
  this offline against the real listings and inventory.
- Pair-list order: since 2026-11-01 `_listing_i18n.sorted_for()` uses its own collation
  key (`_TAILORING`), identical on macOS and on the ubuntu runner. Before, it used the OS
  collation, which the ubuntu runner lacks and which macOS gets wrong for Croatian (Š
  between O and P): the hr listing uploaded on 2026-11-01 has that order, and the next
  release re-sorts it (12 lines move). Every other language's order is unchanged.
- 18 more languages are drafted in `play/listings/<language>.json` (title, short
  description, full-description preamble, pair-list header): ca, da-DK, en-GB, en-AU,
  en-CA, fr-FR, fr-CA, hr, it-IT, no-NO, pt-BR, pt-PT, ro, ru-RU, es-ES, es-419, sv-SE, uk
  — the languages of the shipped Apertium pairs that both Play and the App Store list as
  listing locales (Aragonese, Asturian, Belarusian, Galician, Macedonian, Nynorsk,
  Occitan, Northern Sámi and Sardinian have no store locale). `scripts/_listing_i18n.py`
  renders the pair list per language from `scripts/language-names.json` (CLDR names;
  regenerate with `scripts/gen-language-names.py` when a pair adds a language) with the
  catalog's ↔/→ arrows and the language's collation.
- Upload: `SA_JSON_FILE=<androidpublisher key> python3 scripts/play_upload_listings.py`
  is a dry run (stages the listings, runs Play's validation, deletes the edit); add
  `--commit` to publish, `--languages ca,da-DK` to limit it, `--render-dir DIR` to read
  the composed texts. Only texts are written; Play serves the en-US graphics to languages
  without their own. Re-run it after editing a JSON's title, short description or preamble;
  CI keeps the pair lists fresh. The 18 languages went live on 2026-11-01 (Robert's go in
  the localization session).
