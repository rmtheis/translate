# ios — Qvyshift Translate for iOS

The iOS half of the `translate` monorepo. A SwiftUI app that behaves
like the Android `qvyshift-translate` app (see `../android/`): fully
offline Apertium-based machine translation, per-pair On-Demand Resource
downloads, Material-equivalent UI, no account or network after
download.

## Layout

- `Translate/` — SwiftUI sources + bridging header + asset catalog.
- `project.yml` — xcodegen input; regenerate `Translate.xcodeproj` via
  `cd ios && xcodegen generate`.
- `native/` — cross-compile scripts that build
  `ApertiumCore.xcframework` (iOS device + simulator slices). Analogue
  of `../android/native/`.
- `PairResources/` — per-pair data staged by
  `../scripts/stage-pair-odrs.sh` at build time (gitignored).

## Reference points

- `../android/` — the working Android app. Same pair catalog, same
  behavior; iOS mirrors UX patterns and shares the pair-delivery model.
- `../android/native/prep-pair.sh` — fetches Debian nightly .debs and
  repacks platform-neutral JARs; iOS consumes the same JARs.
- `~/Documents/phrasebooks-ios/upload_appstore.py` + sibling scripts —
  existing JWT-based App Store Connect upload on this machine. Reuse
  as the template for the iOS release workflow.

## The core iOS blocker

iOS **forbids `fork`/`exec` for user processes**. The Android app's
`NativePipeline.java` invokes 13 stages (`lt-proc`, `cg-proc`,
`apertium-transfer`, `apertium-interchunk`, `apertium-postchunk`,
`apertium-anaphora`, `lrx-proc`, `lsx-proc`, `rtx-proc`,
`hfst-proc`, ...) as separate subprocess binaries piped stdin→stdout.
That architecture cannot exist on iOS.

**The port must link Apertium's C++ as a library**, invoking each
pipeline stage via function calls and passing data between stages in
memory as `std::string`. Apertium does expose a `libapertium`, but each
tool binary's `main()` does its own argv parsing, file I/O, and
stdin/stdout plumbing. Each stage needs to be rewritten as a callable
function roughly of the shape:

```cpp
std::string run_lt_proc(const std::string& input,
                        const std::string& bin_path,
                        const std::vector<std::string>& flags);
```

Roughly 12 such wrappers, composed into one `NativePipeline`-equivalent
that mirrors `NativePipeline.parseModeLine()` + `runPipeline()`.

What "library-ifying a `main()`" actually entails, beyond replacing
argv parsing and `cin`/`cout` with parameters and `istringstream`/
`ostringstream`:

- **`exit()` must throw, not exit.** Apertium tools call
  `exit(EXIT_FAILURE)` on malformed input — on iOS that kills the
  whole app. Patch at build time (`sed` pass across the upstream
  sources) to replace `exit(EXIT_FAILURE)` with
  `throw std::runtime_error(...)`. Wrap every stage in
  `try { ... } catch (const std::exception&)` at the C API boundary
  and surface as an error string.
- **`cerr`/`cout` must be captured.** Swap `std::cerr`/`std::cout`
  `rdbuf` for an `ostringstream` for the duration of each call;
  restore on exit. Errors go back to Swift alongside the error code.
- **Global state must reset between calls.** `getopt`'s `optind`, ICU
  locale caches, per-tool static buffers all leak across invocations.
  Each wrapper sets `optind = 1` on entry and zeros any static state
  the upstream code touches.
- **Calls must be serialized.** Apertium is not thread-safe. All
  translations run on one dispatch queue; UI awaits the result. That's
  fine — we translate one user request at a time anyway.

## Architecture

```
apertium-ios/
├── README.md                                    ← this file
├── apertium-ios-native/                         ← parallel to android/native/
│   ├── build-xcframework.sh                     ← produces ApertiumCore.xcframework
│   ├── wrappers/                                ← C++ functions wrapping each tool
│   │   ├── lt_proc.cpp
│   │   ├── cg_proc.cpp
│   │   ├── apertium_transfer.cpp
│   │   ├── hfst_proc.cpp
│   │   └── ...
│   ├── ApertiumCore.h                           ← public C API for Swift
│   └── ApertiumCore.cpp                         ← NativePipeline equivalent
├── TranslateIOS/                                ← Xcode project
│   ├── Translate.xcodeproj/
│   ├── Translate/                               ← SwiftUI app target
│   │   ├── TranslateApp.swift
│   │   ├── TranslatorView.swift                 ← mirrors TranslatorActivity
│   │   ├── PairCatalog.swift                    ← mirrors PairCatalog.java
│   │   ├── PairDownloadManager.swift            ← mirrors PairDownloadManager.java
│   │   ├── ApertiumInstallation.swift
│   │   ├── LanguageTitles.swift
│   │   ├── OnDemandResources.swift              ← ODR wrappers
│   │   └── Bridging/
│   │       └── ApertiumCore-Bridging-Header.h
│   └── PairResources/                           ← per-pair resources
│       └── pair_eng_spa/                        ← bundled (not ODR); others are ODR-tagged
│           └── apertium-eng-spa.jar
└── scripts/
    ├── stage-pair-odrs.sh                       ← Android's stage-pair-packs equivalent
    ├── pair-inventory.py                        ← reuse from Android
    ├── release-notes.py                         ← reuse from Android
    ├── store-listing.py                         ← reuse from Android
    └── _pair_catalog.py                         ← reuse from Android
```

### Library-linking build

Cross-compile each upstream Apertium project as a static lib. Target
triples: `aarch64-apple-ios` (device), `aarch64-apple-ios-simulator`,
`x86_64-apple-ios-simulator` (Rosetta Macs). Wrap into XCFramework
slices so Xcode can consume one artifact across all three. Mirror
`android/native/build.sh` step for step, including `openfst` + `hfst`
(see HFST below).

Expose a minimal C API (`ApertiumCore.h`) that Swift can import:

```c
typedef struct ApertiumResult {
  char* output;  // NULL on failure
  char* error;   // NULL on success; otherwise diagnostic string
} ApertiumResult;

ApertiumResult apertium_translate(const char* mode_file_path,
                                  const char* pair_base_dir,
                                  const char* input,
                                  int display_marks);
void apertium_result_free(ApertiumResult r);
```

Keep it C, not C++, so Swift bridging is painless. Ship as
`ApertiumCore.xcframework` + a thin `ApertiumCore.swift` that handles
`String` marshalling.

### Stage composition

Each wrapper takes `std::string` in, returns `std::string` out.
`ApertiumCore.cpp` parses the `.mode` file (port of
`NativePipeline.parseModeLine`) and composes stages by feeding one
stage's output into the next. Input is small (single translations
typically <1 KB); the string copies are irrelevant to performance.

### Threading, safety, and crash recovery

- Translation calls are serialized on a dedicated serial
  `DispatchQueue` in `ApertiumCore.swift`. Apertium globals make
  concurrent calls unsafe.
- C++ exceptions caught at the stage boundary; converted to an error
  string returned via `ApertiumResult`.
- `.bin` files have magic-byte headers — wrapper validates before
  invoking the stage to catch obviously-corrupt pair data early.
- **A corrupt pair can still crash the app** via segfault inside
  Apertium's C++. We do NOT try to catch `SIGSEGV` in-process on iOS
  (it fights CrashReporter and Apple discourages it). Mitigation for
  v1 is "don't ship corrupt pairs". If this becomes a real problem
  post-launch, move translation to an XPC service — out of scope now.

### HFST / OpenFST

Android ships `apertium-sme-nob` which needs HFST, built on OpenFST
1.8.5 per `android/native/build.sh`'s `build_hfst` + `build_openfst`.
iOS does the same — we want FST on iOS from the start. The Android
patches (OpenFST `configure.ac` cross-compile fallback, HFST
`HfstInputStream.h` Tropical/Log forward-decl swap) are reused. Darwin
has `glob(3)` and `wordexp(3)` natively so the bionic shims
(`shims/glob.h`, `shims/wordexp.h`) aren't needed. `hfst-proc` gets
library-ified the same way as every other Apertium tool.

### Pair-content delivery — On-Demand Resources (ODR)

**ODR** is iOS's equivalent of Android's Play Asset Delivery. Each
pair's JAR becomes a resource tag in the Xcode project; the tag lives
in the `.ipa`, the actual bytes sit on Apple's CDN, and the app fetches
them at runtime via `NSBundleResourceRequest(tags: ["pair_eng_spa"])`.
`beginAccessingResources(completionHandler:)` triggers the download if
the tag isn't already cached. Progress is `request.progress` (a
KVO-observable `Progress`) — maps cleanly to the existing download
dialog UX.

Caps (Apple docs, as of 2026): 2 GB per tag, 20 GB total per app
version, 20 GB on-device across an app's ODR. Our full
trunk+staging+sme-nob catalog is ~475 MB — comfortably under.

Unpack target: ODR content sits in a read-only bundle directory; on
first fetch we unzip each JAR into `Library/Caches/pairs/<pkg>/` and
keep a version sidecar (`<pkg>.version` = app build number) so an app
update re-extracts — matching Android's
`PairDownloadManager.refreshStalePacks()` semantics.

**Bundle one pair inside the app.** Ship `apertium-eng-spa` (~5 MB) as
an ordinary bundled resource, not ODR, so a fresh install can translate
immediately without network and so sideloaded / TestFlight builds have
a working pair on first launch. All other pairs are ODR.

TestFlight caveat: ODR does work in TestFlight but the first download
per tag can lag a minute or two behind what the App Store would give a
retail user. Acceptable; worth verifying end-to-end on the first
TestFlight build.

ODR tags are declared in Xcode under Build Phases → "Tag Resources".
Automate with `stage-pair-odrs.sh` that mirrors `stage-pair-packs.sh`.

### UI — SwiftUI

Port the Material layouts to SwiftUI. The dropdown-grouped-by-tier
pattern maps to a `Picker` or custom `List` with section headers.
Material About/Settings dialog → `Sheet` with a `Form`. Download
progress → modal sheet with `ProgressView`.

iPad size classes work out of the box with SwiftUI. Dark mode and
Dynamic Type are on by default. Accessibility labels mirror the
Android `contentDescription` set.

App-level structure matches Android 1:1:
```swift
@main struct TranslateApp: App {
  @StateObject var installation = ApertiumInstallation()
  @StateObject var downloadManager = PairDownloadManager()
  var body: some Scene {
    WindowGroup { TranslatorView() }
      .onAppear {
        installation.rescanForPackages()
        downloadManager.installAlreadyDelivered()
        downloadManager.refreshStalePacks()
      }
  }
}
```

### Testing strategy

- **Stage-level unit tests** (XCTest): each C++ wrapper gets a test
  that feeds a known input and compares against captured output from
  the Android `NativePipeline` for the same stage. Locks in parity.
- **End-to-end parity test**: a curated sentence set is translated via
  `ApertiumCore` on the iOS simulator AND via `adb shell` on a
  connected Android build; byte-for-byte match required.
- **UI snapshot tests**: `TranslatorView` across light/dark,
  iPhone/iPad.
- **ODR smoke**: fresh simulator state → pick a non-bundled pair →
  confirm download dialog → success → translate.

## License + App Store considerations

The Android app already ships GPLv3 because CG-3 is GPLv3 and we need
CG-3 for most modern pairs. iOS mirrors: **GPLv3 for the iOS app**.
Apple has historically permitted GPL apps (VLC is back after an
earlier pull), but case-by-case rejection or pressure to change terms
is a real risk. Accept the risk, contingent on Apple continuing to
allow GPL at submission time. Fallback if Apple rejects on license
grounds: publish a reduced variant that drops `libcg3.a` and excludes
the pairs that depend on it — a significant catalog cut, so it's
a Plan B, not Plan A.

The `apertium-ios` source repo (Swift code + build scripts) can be
MIT-licensed; only the compiled C++ binaries inside the xcframework
are GPL, and that propagates to the final `.ipa`.

**Resources vs executable code (App Review).** Apertium pair files
(`.bin` compacted FSTs, `.rlx.bin` rule files, `.mode` text files) are
data, not executable code. Apple's prohibition on downloading
executable code doesn't apply to ODR of data. Have that explanation
ready in case a reviewer asks.

### Privacy manifest (iOS 17+)

`PrivacyInfo.xcprivacy` declares:
- No tracking domains.
- No data collection.
- API reason codes for any of FileTimestamp (`C617.1`), DiskSpace
  (`85F4.1`), UserDefaults (`CA92.1`), SystemBootTime (`35F9.1`) that
  the app actually uses.

Fully-offline app, no analytics; the manifest is short.

### Apple Developer, bundle ID, naming

- Existing Apple Developer account reused across `rmtheis` apps.
- Bundle id: default `com.qvyshift.translate` for Android parity; flip
  to `com.qvyshift.translate.ios` only if ASC returns a conflict from
  the same-team prior use.
- App name in the App Store: leaning "Qvyshift Translate" — plain
  "Translate" collides with Apple's built-in Translate app in search.
- Payment/model: free, no IAP, no ads (same as Android).

## Shared tooling from the Android app

Pull these verbatim, minimal adaptation:

- `scripts/_pair_catalog.py` — parses `PairCatalog.java`. We'll need a
  Swift equivalent of `PairCatalog`, but the Python parser can either
  keep reading the Java file (source of truth) or we duplicate the
  catalog into Swift and write a new parser.
- `scripts/pair-inventory.py` — unchanged, operates on a dir of JARs.
- `scripts/release-notes.py` — unchanged, generates App Store release
  notes from inventory diffs.
- `scripts/store-listing.py` — emit the same "Included language pairs"
  block. App Store's description has a 4000-char cap like Play; same
  splice-between-markers pattern works.
- `android/native/prep-pair.sh` — exactly reusable. It fetches Debian
  `.debs` and repacks platform-neutral JARs. The iOS side consumes the
  same output.
- `~/Documents/phrasebooks-ios/upload_appstore.py` + siblings —
  reference template for the JWT-based ASC upload. Same posture as the
  Android Play Developer API work; no Fastlane.

## CI / release

- GitHub Actions workflow patterned on
  `../.github/workflows/release.yml`.
- Jobs: `natives` (xcframework build, matrix over simulator/device) →
  `pairs` (prep-pair.sh unchanged) → `build` (Xcode archive) →
  `deploy` (App Store Connect API upload).
- Per project CLAUDE.md: "Always use the App Store Connect API directly
  (via PyJWT + requests) for any ASC operations." Never Fastlane.
- ASC credentials: check `~/Documents/keystore/` for an existing API
  key `.p8`; otherwise generate a new App Store Connect API key. Store
  as `APP_STORE_CONNECT_API_KEY_P8`, `APP_STORE_CONNECT_API_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID` in GitHub secrets.

## First-session plan (new session picks up here)

Ordered. Each step should be verifiable before moving on.

1. Clone `android/native/`'s structure as `apertium-ios-native/`.
   Adapt cross-compile scripts to iOS triples + xcframework output.
2. Build `lttoolbox` as xcframework. Write a minimal Swift CLI (or
   iOS-simulator unit test) that calls the wrapped `lt-proc` on a
   `.bin` analyzer and dumps the result. **Milestone:** "Hola" through
   the eng-spa analyzer produces `Hola/hola<pron>...`. Apply the
   `exit`→throw, stdout capture, and `optind`-reset patches from
   "library-ifying a `main()`" above and carry them forward to every
   subsequent wrapper.
3. Add one transfer stage (`apertium-transfer` + `eng-spa.t1x.bin`).
   **Milestone:** a two-stage in-process pipeline works.
4. Wrap the remaining Apertium stages (`apertium`, `cg3`, `lex-tools`,
   `recursive`, `anaphora`, `separable`).
5. Port `NativePipeline.parseModeLine` + `runPipeline` into
   `ApertiumCore.cpp`. Expose via the C API.
6. Add `openfst` + `hfst` to the xcframework build; wrap `hfst-proc`.
   Validate `apertium-sme-nob` end-to-end.
7. Parity test: a curated sentence set through `spa-cat`, `eng-spa`,
   `sme-nob`, byte-for-byte match against Android output.
8. Port `TranslatorView` + helpers to SwiftUI with `eng-spa` bundled.
   Ship a single-pair dev build.
9. Wire ODR for one non-bundled pair (`spa-cat`). **Milestone:** fresh
   install → pick spa-cat → download dialog → translate.
10. Port full catalog, tier grouping, remember-last-pair, combined
    About/Settings dialog.
11. Ship `PrivacyInfo.xcprivacy` with accurate declarations.
12. Write the GitHub Actions release workflow (natives → pairs → build
    → deploy).
13. First TestFlight build via the App Store Connect API.
14. Inventory-diff release notes (reuse Python scripts verbatim);
    store listing; privacy policy HTML on `qvyshift.website` (clone of
    the Android page with iOS-specific swaps).

Pause before pushing anything to GitHub. Wait for user to say when to
create `github.com/rmtheis/translate-ios` and push.

## Open questions for the new session

- Xcode project vs SwiftPM: start with Xcode project (needs it for
  xcframework integration and ODR tag declaration anyway); SwiftPM
  later only if it buys anything.
- Deployment target: propose iOS 16 for modern SwiftUI; ODR itself is
  iOS 9+ so that axis is fine.
- App name: confirm "Qvyshift Translate" vs another differentiator
  from Apple's Translate.
- Bundle id: `com.qvyshift.translate` (default) unless ASC returns a
  conflict.
- Bundled pair: default bundle `apertium-eng-spa` for first-run UX;
  open to not bundling if minimizing install size matters more.

## Not-doing in the first iOS session

- No Apple Translate / `NaturalLanguage` framework. Different product —
  see the separate ML Kit handoff for that direction.
- No iOS-specific conveniences (Siri shortcut, Share Extension,
  Widget). Keep scope to "feature parity with Android".

---

When the new session starts, work through "First-session plan" above.
Pause before pushing anything to GitHub. The user will tell you when
to create `github.com/rmtheis/translate-ios` (or whatever name) and
push.
