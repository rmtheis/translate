# android — Translate (Experimental) for Android

Package `com.qvyshift.translate`. Offline Apertium translation: the Apertium C++
tools are cross-compiled with the NDK (`native/`), shipped as `lib*.so` executables
in `app/src/main/jniLibs/`, and run as a stdin→stdout pipeline via `ProcessBuilder`
(`NativePipeline.java`). There is no JNI. Language pairs are on-demand Play Asset
Delivery packs (`pair_<src>_<tgt>/`). No ads, no billing, no Firebase.

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
  pair-diff notes for the stock "Behind-the-scenes changes…" line.
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
  download by screenshot coordinates.

## Known issues

- In 1.0.12 and earlier, Northern Sami → Norwegian Bokmål and Norwegian Bokmål → Nynorsk
  fail, and so do Serbo-Croatian → Macedonian and Occitan → Catalan on many inputs ("Dobar
  dan.", "L'ostal es grand."; apertium-transfer exits with 139, a segfault). The fixes ship
  with the next release (see the release log and "Pair-data workarounds in
  `NativePipeline`").
- Occitan → Catalan is the 2022 Debian nightly's data: its analyzer misses common words, so
  "L'ostal es grand." comes out as "El *ostal *es *grand.", the same as on iOS.

## Release log

- **Next release** (on master, not yet released): ships `libhfst_proc.so` and
  `liblt_merge.so` for both ABIs, plus the `lt-merge` mapping in `NativePipeline`. Fixes
  sme→nob ("native binary not executable: …/libhfst_proc.so") and nob→nno ("no native
  binary mapping for tool 'lt-merge'"). sme→nob was broken since at least 1.0.11; nob→nno
  at least since the April 2026 pair JARs, whose mode already ran `lt-merge`. CI now runs
  `check-pair-tools.py`. Natives unchanged: the build reuses the cached 1.0.12 natives
  (same `android/native/` SHA) as long as the cache is still there. GitHub evicts caches
  unused for 7 days, and the 1.0.12 run last used it 2026-10-07 00:29 UTC.
  QA 2026-10-06 on Medium_Phone_API_37: 18/18 unit tests, CI 1.0.12 natives + pairs.
  On-device upgrade from the live 1.0.12 AAB: before the upgrade, all 8 sme→nob and
  4 nob→nno test sentences failed; after it, all translate (escaped `/` and `@`
  included). eng→spa, spa→eng and nno→nob are byte-identical to 1.0.12 (11/11). The
  new arm64 libs have `p_align` 0x4000/0x10000. armeabi-v7a is checked only statically
  (ELF + `DT_NEEDED`); there's no arm32 emulator.
- **Next release, continued** (committed 2026-10-07): Serbo-Croatian → Macedonian and
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
- **1.0.12** (versionCode = the CI run's `yyyymmddHH`; prepared 2026-10-06): AGP 9.4.1,
  Gradle 9.6.1, target 37, first R8-optimized build, first 5% staged release. QA on the
  minified, debug-signed QA build: 18/18 unit tests, lintVital clean, smoke PASS on
  Medium_Phone_API_37 and Medium_Tablet_API_37, translations byte-identical to 1.0.11 in
  6 directions (eng↔spa, spa→cat, nno→nob, rus→ukr, cat→ita), upgrade from 1.0.11 keeps
  the chosen pair, the marks setting and the downloaded pairs.
- **1.0.11** (2026092911): input-escaping fix, 100% on production.
