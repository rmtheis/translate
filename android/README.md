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
  `stage-pair-packs.sh`, version bump, `./gradlew :app:testDebugUnitTest`, then
  `./gradlew :app:bundleRelease`) → **deploy**.
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
./scripts/stage-pair-packs.sh /tmp/pairs/pair-jars   # rewrites the tracked pair JARs: use a worktree
cd android && ./gradlew :app:testDebugUnitTest && ./gradlew :app:bundleRelease
```

- Without `app/upload.keystore`, `bundleRelease` gives the QA build: minified,
  optimized, non-debuggable, debug-signed.
- On-demand pair packs only work when installed with bundletool's local testing:
  `bundletool build-apks --local-testing --bundle=app/build/outputs/bundle/release/app-release.aab --output=qa.apks --ks ~/.android/debug.keystore ...`
  then `bundletool install-apks --apks=qa.apks --device-id=<emulator>`.
- arm64 emulators only (no x86 natives). Never a physical device for QA.
