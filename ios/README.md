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
  `throw std::runtime_error(...)`. Catch every exception at the C API
  boundary and surface it as an error string. (The sed pass was never
  done; the catch is `aix::run_wrapper`. See "Threading, safety, and
  crash recovery".)
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

The mode files start at `lt-proc`, not at the deformatter, so
`apertium_translate` (`native/wrappers/apertium_core.cpp`) escapes the raw
input the way `apertium-destxt` does (`\ [ ] { } ^ $ / @ < >`) and
unescapes the final output — mirror of Android's
`NativePipeline.escapeStream`/`unescapeStream`. Unescaped, stage 1 threw
"Malformed input stream" on any `/`, `@`, `$`, … (dates, emails, URLs).
`ApertiumCore.swift` holds back a trailing `^` run after the last word and
re-attaches it (lrx-proc mis-reads an escaped `^` there), same as
`NativePipeline.caretTailStart`.

### Mode-file tools and flags

`run_stage()` in `native/wrappers/apertium_core.cpp` maps each `.mode`
stage's tool name to its wrapper. A tool without a case fails the whole
direction with `stage N (<tool>): unknown tool: <tool>`. That is how
Bokmål → Nynorsk failed through 1.0.6: `nob-nno.mode` runs `lt-merge`
twice. A new tool needs `wrappers/<tool>.cpp`, a declaration in
`apertium_core.h`, a `tool_options()` entry and a `dispatch_stage()` case.
`build.sh wrappers` compiles every `wrappers/*.cpp`, so there's no list to
update there.

- Options: `tool_options()` holds each tool's option table, copied from
  its upstream `main()` (`lt_proc.cc`, `cg-proc.cpp`, `hfst-proc.cc`,
  ...). `parse_argv()` reads a stage's arguments with it the way
  getopt_long does on Linux/Android, where the Android app runs the real
  binaries: `-bc`, `-N1` or `-N 1`, `--weight-classes 1`, long-option
  prefixes. Options without a value reach the wrapper as letters (`"wg"`
  for `-w -g`), counts (`-N`, `-L`, `-M`, hfst-proc `-l`) as ints. An
  option the tool doesn't define fails the stage (the CLI prints its usage
  and exits). So does one marked `on_ios = false`: lt-proc `-i`/`-r`,
  cg-proc `-s`/`-r` and `-f` other than 1, hfst-proc `-C`/`-x`/`-j`/`-v`,
  and a few more that no wrapper implements and no offered direction uses.
  cg-proc has no long options, because cg3's CMake build never defines
  `HAVE_GETOPT_LONG`.
- `scripts/check-pair-tools.py --ios <pair-jars-dir>` checks every
  direction `PairCatalog.swift` offers: each tool needs a `run_stage()`
  case and each option must parse against `tool_options()`. The `pairs`
  job of `release-ios.yml` runs it. In the 2026-10 pair set the 49
  directions use 14 tools, and `lt-merge` was the only one missing.
- Until 2026-10-07 the dispatcher kept only a few options and dropped the
  rest without an error: lt-proc got only its mode letter, so `-w`
  (dictionary case, 42 directions), `-c` (rus-bel, spa-ast) and `-N1`
  (nno-nob) were ignored, and `-N1` was split into the letters N and 1.
- lt-proc (`wrappers/lt_proc.cpp`) picks its mode and settings as
  `lt_proc.cc` does. The checks run in a fixed order, whatever the order
  on the command line, so `lt-proc $1 -b X.autogen.bin` (nob-nno and 9
  other directions) and `lt-proc -b $1` (sme-nob) are both bilingual
  generation. Until 2026-10-06 `$1 -b` ran plain generation, and nob→nno
  printed every generator alternative ("enno/ennå").
- cg-proc: `-g` turns on `surface_readings` as well as turning off LU
  delimiting, as `cg-proc.cpp` does. Readings then print without tags, and
  a leading `@` becomes `#` (`cg-proc -1 -n -g` after bilingual generation
  in 11 directions). The grammar's embedded `CMDARGS` go into vislcg3's
  option table before `setOptions()`, as in cg-proc (nob-nno's
  `merge-quotes.rlx` carries `--num-windows 10`). That table is a process
  global, and the wrapper restores it after each call.
- hfst-proc: options as in `hfst-proc.cc`, including its default of
  filtering compound analyses (`-k` turns it off). The filter only counts
  boundaries when `-e` is given, so it doesn't affect sme-nob
  (`--weight-classes 1 -w -p`). The settings are globals, and the wrapper
  resets them on every call.
- lt-merge (`wrappers/lt_merge.cpp`) makes the same calls as
  `lt_merge.cc`: `FSTProcessor::quoteMerge`, or `quoteUnmerge` for
  `--unmerge`, with no dictionary. `merge-quotes.rlx` only tags
  MERGE_BEG/MERGE_END when the CG variable `sitat.lastå` is set, which
  the app never does, so in the app lt-merge just re-serializes the
  stream.
- apertium-transfer, -interchunk and -postchunk get the rules XML that
  their `.bin` was compiled from: when `X.t1x.bin`'s source `X.t1x` sits
  in the pair dir, `rules_xml_for_bin()` uses it in place of the mode's
  XML. The .bin's matcher returns rule numbers that index the XML's
  `<rule>`s. Pairs with rule variants (`alt="oci@aran"`) ship both the
  variant-filtered `X.t1x` and the unfiltered `apertium-<pkg>.X.t1x`. The
  2022 Debian build of apertium-oci-cat (357b2f07) passes the unfiltered
  files (t1x 155 rules vs 132, t2x 23 vs 22, t3x 12 vs 7), so every
  oci→cat sentence ran the wrong rules' actions. Some segfaulted (see the
  1.0.6 entry in "Known issues"). Upstream fixed `modes.xml` in a81f6fd1
  (2025-03). Among the 49 directions only oci→cat's three stages hit
  this case.
- cg-proc output loses CG-3 dependency tags (`<#1→2>`,
  `strip_dependency_tags()`). CG-3 prints one on every cohort a
  SETPARENT/SETCHILD rule touched, in the Apertium format since cg3
  f5d37748 (2022-01). apertium-pretransfer reads the tag's `#` as a
  multiword split (`^Dobar#1→2><adj>…<$`) and apertium-transfer then
  segfaults. Only `hbs-mkd.rlx` (experimental SETPARENT rules, last
  edited 2017) prints them among the 49 directions. nob-nno's
  `merge-names.rlx.bin` has the grammar's dependency flag from
  MERGECOHORTS but prints no tags. Escaped text and `[superblanks]` are
  left alone, so a typed `<#1→2>` still comes through.
- Upstream `exit()` calls are not patched to throw (the plan under "The
  core iOS blocker" was never carried out), so an lttoolbox exit such as
  "Unexpected trailing backslash" still ends the app. Input escaping keeps
  user text away from the known ones. Fed malformed streams directly,
  which no stage of an offered direction produces, apertium-pretransfer
  exits on an unterminated `^…` LU, cg-proc exits on an unescaped `$`, and
  apertium-interchunk and -postchunk loop forever, allocating memory, on
  an unterminated `[` superblank (found 2026-10-07).
- Reference output: the native build tree also has every upstream CLI
  built for the simulator (`out/ios-arm64-sim/bin/lt-proc`,
  `apertium/apertium/apertium-transfer`,
  `apertium-separable/src/lsx-proc`,
  `apertium-recursive/src/rtx-proc`,
  `out/ios-arm64-sim/bin/hfst-apertium-proc`, ...). The simulator's
  `/bin/sh` can pipe a whole mode line through them in one
  `xcrun simctl spawn <udid> /bin/sh -c '...'`; substitute `$1` with `-g`
  and drop `$2` first. Export `DYLD_ROOT_PATH` (the iOS runtime's
  `runtimeRoot` from `xcrun simctl list runtimes -j`) at the start of the
  `sh -c` string, or every child fails with "DYLD_ROOT_PATH not set for
  simulator program". oci→cat and hbs→mkd differ from it on purpose (the
  two items above).

### Threading, safety, and crash recovery

- Translation calls are serialized on a dedicated serial
  `DispatchQueue` in `ApertiumCore.swift`. Apertium globals make
  concurrent calls unsafe.
- Every wrapper runs its stage inside `aix::run_wrapper`
  (`native/wrappers/wrapper_common.h`), which turns any exception into
  the `ApertiumResult` error string, `std::exception` or not, and
  `run_stage()` and `apertium_translate()` end in `catch (...)`. Nothing
  may cross the extern "C" API into Swift: an exception there terminates
  the app. HFST's `HfstException` doesn't derive from `std::exception`,
  and through 1.0.6 a corrupt `.hfst` (sme→nob) threw
  `TransducerHasWrongTypeException` past every catch and ended the app.
  `hfst_proc.cpp` now names it in the error ("HFST
  TransducerHasWrongTypeException (transducer.h:148)"), and its header
  check refuses a transducer that isn't in optimized-lookup format
  (HFST_OL, HFST_OLW), as `hfst-proc.cc` does.
- Wrappers check only that their data files exist (`ensure_exists()`;
  lttoolbox's `openInBinFile` exits the app on a missing file, and
  lt-proc, lrx-proc and lsx-proc skipped the check through 1.0.6). Most
  truncated or corrupt files make the upstream reader throw ("Failed to
  read uint64_t") and fail just that translation. Some don't; see the
  next item.
- **A corrupt pair can still crash the app** via segfault inside
  Apertium's C++. We do NOT try to catch `SIGSEGV` in-process on iOS
  (it fights CrashReporter and Apple discourages it). Mitigation for
  v1 is "don't ship corrupt pairs". If this becomes a real problem
  post-launch, move translation to an XPC service — out of scope now.
  It happened in 1.0.6 with two pairs whose data doesn't fit current
  Apertium tools (hbs→mkd, oci→cat; see "Mode-file tools and flags").
  Android runs each stage as a subprocess, so the same segfault (exit
  code 139 under `adb shell`) fails only that translation there:
  `NativePipeline.checkStages` reports the apertium-transfer stage as
  failed. That is how hbs→mkd and oci→cat failed on Android through
  1.0.12; `NativePipeline` now has the same two workarounds
  (`android/README.md`, "Pair-data workarounds in `NativePipeline`").
  Forced on purpose (2026-10-07): an `X.autolex.bin` cut to 6 bytes
  (lrx-proc) and an `X.prob` cut to 10 bytes (apertium-tagger) segfault
  in the upstream readers.
- Every stage runs inside the app's one long-lived process, so a file a
  stage leaves open stays open for the rest of the session. Once open()
  fails, lttoolbox's `openOutTextFile` exits the app with "Cannot open
  file '…/apertium_…_out_…' for writing" (a simulator process tops out at
  256 descriptors). Two sources, both fixed in 1.0.7:
  - Upstream readers. apertium's `TransferBase::read()` opens the
    compiled rules (`X.t1x.bin`, ...) and never closes them: through 1.0.6
    every apertium-transfer, -interchunk and -postchunk stage leaked a
    descriptor, and a simulator test process died after 137 translations
    (eng→spa runs three such stages per translation).
    `Transfer::readBil()` and apertium-recursive's `RTXProcessor::read()`
    close theirs only if nothing throws. `patch_close_on_throw` in
    `native/build.sh` gives all three a scope guard that closes the file
    however the function ends. It also initializes `RTXProcessor::mx`,
    which `~RTXProcessor()` deleted uninitialized when `read()` threw, so
    a truncated `.rtx.bin` crashed the app. It matches each edit exactly,
    as upstream has it or as patched, and stops the build when upstream
    changes one of these functions (the clones are unpinned).
  - Failed stages. Through 1.0.6 a wrapper closed its files and deleted
    its tmp files only on success. A stage that threw (malformed stream,
    truncated `.bin`) left a `FILE*` or `UFILE*` open, so about 250 failed
    translations in one session brought the exit back. The wrappers now
    hold their files in `aix::FilePtr`, `aix::UFilePtr` or lttoolbox's
    `InputFile`, and their tmp files in `aix::TmpFile`, which release them
    on success and failure alike. A new wrapper should do the same.

  After a natives change, check for leaks: run many directions in one
  process and count open descriptors (`fcntl(fd, F_GETFD)`) around each
  `apertium_translate()` call, and force the failure paths (the
  2026-10-07 release-log entry lists the set). Android starts a fresh
  process per stage and isn't affected.

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

iPad size classes work out of the box with SwiftUI. Dynamic Type is on
by default. Accessibility labels mirror the Android
`contentDescription` set.

Colors follow the Android translator screen (`Translate/Theme.swift`,
since 2026-10-07): pale_brown `#FFECC0` background, nav bar included,
and dark_red `#CC0000` as the accent. The accent covers the Translate
button, the focused source field's outline and label, toggles and links;
the `AccentColor` asset carries the same red for UIKit-presented alerts
and menus. The pair picker, gear and icons stay black, as on Android.
The app is light-only (`UIUserInterfaceStyle: Light` in `project.yml`),
like Android's `Theme.MaterialComponents.Light` with no night resources:
dark mode's white text would be unreadable on the pale brown.

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
- **UI snapshot tests**: `TranslatorView` on iPhone/iPad (light only).
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

`Translate/PrivacyInfo.xcprivacy` (added 2026-10-06, on origin; first
ships in 1.0.7). xcodegen's `Translate` source glob
puts it in Copy Bundle Resources at the root of the `.app`. It declares:
- No tracking, no tracking domains, no collected data types (fully
  offline, no analytics; ODR downloads come from Apple).
- **UserDefaults `CA92.1`**: last pair, direction, the display-marks
  toggle and the review-prompt counters (`AppStorageKey`, `ReviewPrompt`).
- **FileTimestamp `C617.1`**: `stat()` is a file-timestamp API. It's
  called by our own `native/wrappers/wrapper_common.h` (`ensure_exists`)
  and by the statically linked CG-3, ICU (`umapfile`) and libxml2 code in
  `ApertiumCore.a`. Those libraries ship no manifest of their own. All the
  stat targets are pair data, ICU data or temp files inside the app's own
  bundle/container.
- No DiskSpace or SystemBootTime: `nm -u` on `ApertiumCore.a` and the app
  binary shows no `statfs`/`statvfs`/`mach_absolute_time` imports. Re-check
  with `nm -u native/ApertiumCore.xcframework/ios-arm64/ApertiumCore.a | grep -E '_(f?stat|statv?fs|mach_absolute_time)'`
  whenever the native libraries change.

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
- Jobs: `natives` (both xcframework slices) → `pairs` (prep-pair.sh
  unchanged, then `check-pair-tools.py --ios`) → `build` (Xcode archive)
  → `deploy` (App Store Connect API upload).
- `natives` is cached by the tree SHA of `ios/native/`. Any change there
  (a wrapper, `build.sh`) is a cache miss: `build.sh all` re-clones
  lttoolbox, apertium, cg3, HFST, ... at upstream HEAD, so every tool
  changes, and the job takes ~27 min (2026-09-29 run). Re-QA the
  translations after such a release.
- Manual runs (`gh workflow run release-ios.yml -f force_publish=true`)
  ship app-code-only changes; add `-f stock_notes=true` to post the stock
  "Behind-the-scenes changes…" line instead of the pair-inventory diff.
  `release-android.yml` takes the same two inputs.
- Per project CLAUDE.md: "Always use the App Store Connect API directly
  (via PyJWT + requests) for any ASC operations." Never Fastlane.
- ASC credentials: check `~/Documents/keystore/` for an existing API
  key `.p8`; otherwise generate a new App Store Connect API key. Store
  as `APP_STORE_CONNECT_API_KEY_P8`, `APP_STORE_CONNECT_API_KEY_ID`,
  `APP_STORE_CONNECT_ISSUER_ID` in GitHub secrets.

### App Store screenshots

- `scripts/screenshots-ios.sh` (`KIND=iphone`, the default, or
  `KIND=ipad`) writes `screenshots/appstore-iphone-69/` (iPhone 16 Pro
  Max, 1320×2868) and `screenshots/appstore-ipad-13/` (iPad Pro 13-inch
  (M4), 2064×2752). Run it from a worktree: it rewrites
  `ios/PairResources/` and needs `ios/native/ApertiumCore.xcframework`.
  Use the CI artifacts (`apertium-core-xcframework`, `ios-pairs` →
  `scripts/stage-pair-odrs.sh`), not stale local copies. It temporarily
  strips the ODR tags from `project.yml` and restores them on exit.
- It erases a simulator of its own, "Translate screenshots (<device
  type>)", created on the newest iOS runtime. Never pass it a shared
  device: other sessions use the same simulator set.
- Xcode 27 workarounds in the script: no Simulator.app (it captures
  headless); `status_bar --time` takes only ISO 8601 with fractional
  seconds; `--batteryState charged` draws a green bolt, so it uses
  `discharging` at 100%; the Dynamic Island is missing from default and
  `--mask=ignored` captures, so it's pasted in from a `--mask=black`
  capture (needs ImageMagick).
- iPadOS 26/27 simulators start in Windowed Apps mode: a resize grabber
  in the bottom-right corner and, on 27, the app name in the status bar.
  The mode isn't a defaults key (SpringBoard's MultitaskingModeManager
  switches it), so the script can't change it. The iPad status-bar date
  can show the wrong weekday: Wed Oct 7, 2026 came out as "Sat Oct 7"
  in the app, the weekday of Oct 7, 2000.
- CI never uploads screenshots. ASC copies the previous version's
  screenshots into a new version, so new ones go up through the API to
  the editable version before it's submitted. The release workflow's
  deploy job creates the version and submits it in one run, so:
  1. `ASC_VERSION_STRING=<next> python3 scripts/asc_create_version.py`.
     `<next>` is the patch bump of `CFBundleShortVersionString` in
     `project.yml`, which is what the workflow will build and look up.
  2. `python3 scripts/asc_upload_screenshots.py --version <next>`
     (`--dry-run` first). It replaces the 6.9" and 13" sets of every
     localization that has one (today only en-US), in filename order, and
     waits until ASC reports each file COMPLETE. It refuses a version that
     isn't editable.
  3. Dispatch the release. The workflow reuses the editable version.

  Both scripts read `ASC_KEY_ID`, `ASC_ISSUER_ID` and `ASC_P8` (the .p8
  contents; locally the App Manager key in
  `~/.appstoreconnect/private_keys/`).
- Through 1.0.6 the sets were in a scrambled order (iPhone led with
  02_cat_srd, iPad with 06_sme_nob). From 1.0.7 they are 01–08.

## Known issues

- 1.0.6 and earlier crash the app (SIGSEGV in `apertium-transfer`) on
  Serbo-Croatian → Macedonian and Occitan → Catalan input such as "Dobar
  dan.", "Ja sam student.", "L'ostal es grand." and "Lo gat dormís sus la
  cadièra vièlha.". Both are pair-data problems: Android's real binaries
  segfault on the same streams (the translation fails there through
  1.0.12). Fixed in iOS 1.0.7 and Android 1.0.13 (see "Mode-file tools
  and flags" and the release log).
- Occitan → Catalan pair data is the 2022 Debian nightly (357b2f07,
  still the current package on 2026-10-07). Its analyzer misses common
  words, so "L'ostal es grand." comes out as "El *ostal *es *grand.".
  In cat→oci the bilingual dictionary gives Aranese forms the generator
  can't produce ("La casa és gran." → "*Eth casa *èster granda."), the
  same on Android. Upstream apertium-oci-cat has commits up to 2026-02
  that the nightly doesn't include.

## Release log

- **1.0.7** (build 202610072025; submitted to App Review 2026-10-07 by
  release-ios.yml run 37678901292 with `force_publish` + `stock_notes`,
  AFTER_APPROVAL; natives built on CI at the same upstream commits as the
  QA below: lttoolbox ed9b682, apertium c0a91d8, lex-tools 1ccefa6,
  recursive f48e2f3, separable 18045e4, anaphora 55b1778, cg3 7b7ff6d,
  hfst d1128ce): adds the `lt-merge`
  wrapper and the `lt-proc -b -g` dispatch fix (see "Mode-file tools and
  flags"). Norwegian Bokmål → Nynorsk failed in every iOS release with
  `stage 8 (lt-merge): unknown tool: lt-merge`. This changes
  `ios/native/`, so the natives job rebuilds from upstream HEAD (see "CI
  / release"). QA 2026-10-06 on an iPhone 17 / iOS 27.0 simulator, with
  the 1.0.6 CI pair JARs and natives built locally at that day's upstream
  HEAD (lttoolbox ed9b682, apertium c0a91d8, cg3 7b7ff6d, hfst fcfb18e):
  - nob→nno: 9/9 sentences translate (all failed on the 1.0.6 natives),
    e.g. "Jeg har ikke lest boka ennå." → "Eg har ikkje lese boka enno.".
  - The other 48 directions are byte-identical to the 1.0.6 natives
    (130 sentences, eng→spa and nno→nob included).
  - The `lt-merge`, `lt-merge --unmerge` and `lt-proc -g -b` stages are
    byte-identical to host-built lttoolbox binaries.
  - `nm -u` required-reason APIs are unchanged (`_stat` only).
  - The "byte-identical" count includes hbs→mkd and oci→cat, which
    crashed on the first sentence with both natives (see the next item).
- **1.0.7, continued** (committed 2026-10-07): fixes the hbs→mkd
  and oci→cat crashes in `apertium_core.cpp` (`rules_xml_for_bin()`,
  `strip_dependency_tags()`; see "Mode-file tools and flags"). Also under
  `ios/native/`, so it needs the same natives rebuild. QA 2026-10-07 on
  an iPhone 17 / iOS 27.0 simulator, with the CI pair JARs from
  release-ios.yml run 36962949842 and natives built locally at upstream
  HEAD (lttoolbox ed9b682, apertium c0a91d8, cg3 7b7ff6d, hfst fcfb18e,
  same as 2026-10-06):
  - 49 directions, 151 sentences: no crashes. 47 directions are
    byte-identical to the same natives without the fix. hbs→mkd and
    oci→cat now translate 8/8 each (both crashed on the first sentence
    before), e.g. "Dobar dan." → "Добар даден." and "Lo gat dormís sus la
    cadièra vièlha." → "El gat dorm sobre la *cadièra *vièlha.". A
    further 28 hbs→mkd and 25 oci→cat sentences (punctuation, caps,
    email, `$`/`€`, typed `<#1→2>`) translate without a crash.
  - Android (the 1.0.12 CI arm64 binaries, run from `adb shell` on an
    API 36 arm64 emulator, same JARs) segfaults in apertium-transfer on
    the same inputs. With the two fixes applied by hand there (dependency
    tags stripped after cg-proc, filtered t1x/t2x/t3x in the mode), its
    output matches iOS on all 16 sentences.
  - The real app (ODR tags stripped, as `verify-ios-translate.sh` does)
    translates all four crash inputs plus mkd→hbs and cat→oci and stays
    running; an unsigned Release device build links.
  - `nm -u` required-reason APIs are unchanged (`_stat` only; the new
    `access()` call isn't one).
- **1.0.7, continued** (committed 2026-10-07): Android's colors
  (see "UI — SwiftUI"), light-only. App code only. Screenshots retaken
  with the new colors (8 iPhone 6.9", 8 iPad 13"; same scenes and
  translations, CI 1.0.6 natives + run 36962949842 pair JARs, iOS 27.0
  simulators). 2026-10-07: version 1.0.7 created in ASC
  (PREPARE_FOR_SUBMISSION, AFTER_APPROVAL) and all 16 uploaded with
  `asc_upload_screenshots.py`; the served files are pixel-identical to
  `screenshots/`. The 8 scene sentences translate byte-identically with
  master's natives (through `0b7e0c3`, upstream as on 2026-10-06), so the
  shots match what 1.0.7 will show.
- **1.0.7, continued** (committed 2026-10-07): every mode-file
  option now reaches the wrappers and works as in the upstream CLI (see
  "Mode-file tools and flags"). That covers lt-proc `-w`/`-c`/`-N1`,
  cg-proc `-g` and grammar `CMDARGS`, and hfst-proc's defaults, and
  `check-pair-tools.py --ios` now checks options. Also under
  `ios/native/`. QA 2026-10-07 on an iPhone 17 / iOS 27.0 simulator, with
  pair JARs matching the 1.0.6 pair inventory, natives at the same
  upstream commits as above and 172 test sentences:
  - Stage by stage, 47 directions are byte-identical to the real CLIs
    from the same build tree, run in the simulator (418 sentence ×
    direction runs). Before the change, lt-proc `-w` differed in all 42
    `-w` directions (lemma case: `^LIVRO/LIVRO<n>` instead of
    `^LIVRO/livro<n>`). hbs→mkd and oci→cat differ on purpose: those are
    the crash fixes above, and the real apertium-transfer segfaults there.
  - Final output changed in 5 of 426 translations, each now matching the
    real tools: por→cat "A Maria tem um cão…" gives "La Maria té un gos…"
    (was "A Maria"); nno→nob "Eg las avisa…" gives "Jeg leste avisen…"
    (was "aviste"); nob→nno "Vi kastet stener i vannet." gives "Me kasta
    steinar i vatnet." (was "Vi kasta"); nob→swe "Mye av arbeidet er
    gjort allerede." gives "…är gjort redan." (was "gjorda"). In nob→swe,
    "Vi kastet stener i vannet." now gives "Ägna kasten stenar i
    vattnet." (was "Ägna kastade…"). That's worse Swedish, but it's what
    the real tools produce.
  - Crafted stage inputs cover the options the sentences don't reach:
    lt-proc `-N1` keeps one generator alternative ("enno", not
    "enno/ennå<v:…>"), cg-proc `-g` drops reading tags, and hfst-proc
    `-e`/`-k`/`-N`/`-W`. All match the CLIs.
  - `nm -u` required-reason APIs are unchanged (`_stat` only).
- **1.0.7, continued** (committed 2026-10-07): fixes a file
  descriptor leak in apertium-transfer, -interchunk and -postchunk (see
  "Threading, safety, and crash recovery"). It aborted the app after
  enough translations in one session, in every iOS release so far.
  `native/build.sh` changes, so this needs the natives rebuild too. QA
  2026-10-07, same simulator, JARs and upstream commits as the previous
  item: all 426 translations (49 directions) run in one process, with no
  descriptor left open by any of the 14 tools over about 5,800 stage
  runs. Before, that process died after 137 translations. Output is
  byte-identical to the same code without the patch.
- **1.0.7, continued** (committed 2026-10-07): failure paths,
  from a review of 8beea8d..0b7e0c3 (see "Threading, safety, and crash
  recovery"). A stage that threw left its files open, so about 250 failed
  translations brought back the "Cannot open file … for writing" exit; a
  corrupt `.hfst` ended the app through an uncaught `HfstException`; the
  build.sh fclose patch counted any `fclose(in);` in `read()` as already
  applied. Under `ios/native/` (wrappers and `build.sh`), so this needs the
  natives rebuild too. QA 2026-10-07 on an iPhone 17 / iOS 27.0
  simulator, with the pair JARs from release-ios.yml run 36962949842 and a
  clean `build.sh` run of both slices plus `xcframework` at upstream HEAD
  (lttoolbox ed9b682, apertium c0a91d8, apertium-recursive f48e2f3, cg3
  7b7ff6d, hfst d1128ce; hfst is newer than in the entries above):
  - 49 directions, 426 translations through `apertium_translate()` in one
    process: byte-identical to the same build with master's wrappers and
    fclose patch. Three passes (1,278 translations) leave 4 open
    descriptors, as at the start, and no tmp files.
  - 22 forced failures, 300 runs each in one process: truncated `.bin`s
    for lt-proc, apertium-transfer (rules and bilingual), -interchunk,
    -postchunk, lrx-proc, lsx-proc and rtx-proc; a truncated `.rlx.bin`;
    missing `.bin`s; a broken `.arx`; four corrupt copies of sme-nob's
    `.hfst` (payload, truncated, wrong type, bad header); eng→spa with its
    `t1x.bin` truncated (fails at stage 7); malformed streams into lt-proc
    and hfst-proc. 20 return an error string every time, with descriptors
    at 4 → 4 and no tmp files left. With master's code, descriptors
    climbed to the 256 limit in 7 cases and 3 ended in "Cannot open file …
    for writing", the missing `.bin`s exited, three corrupt `.hfst`s
    terminated on the uncaught exception, and the truncated `.rtx.bin`
    crashed in `~RTXProcessor()`.
  - The other 2 crash as on master: an `X.autolex.bin` cut to 6 bytes and
    an `X.prob` cut to 10 bytes segfault in the upstream readers.
  - Changed on purpose: an `.hfst` whose header names a type other than
    HFST_OL/HFST_OLW now fails (hfst-proc refuses it too); master read it
    anyway. The shipped sme-nob transducers are HFST_OLW.
  - The real app (ODR tags stripped) translates sme→nob, eng→spa and
    nob→nno. With a corrupt `sme-nob.automorf.hfst` planted in the
    installed app, sme→nob shows "Translation error … HFST
    TransducerHasWrongTypeException" and the app keeps running. An
    unsigned Release device build links.
  - Follow-up (same day): rtx-proc's input FILE was closed twice (the
    wrapper's owner, then RTXProcessor's own `InputFile`, which
    `process()` wraps it in); the wrapper now hands ownership over. 49
    directions byte-identical; 300 nob→swe runs in one process: no
    errors, descriptors 5 → 5.
  - `patch_close_on_throw` applied on fresh clones, did nothing on patched
    ones, and stopped the build on simulated upstream changes (an extra
    fclose on one path, the old end-of-`read()` fclose, a reshaped
    `readBil()`, `mx` initialized upstream).
  - `nm -u` required-reason APIs are unchanged (`_stat` only).
- **1.0.6** (released 2026-09-29): natives from the 2026-09-29 CI build.

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
11. Ship `PrivacyInfo.xcprivacy` with accurate declarations. (Done
    2026-10-06 — see "Privacy manifest" above.)
12. Write the GitHub Actions release workflow (natives → pairs → build
    → deploy).
13. First TestFlight build via the App Store Connect API.
14. Inventory-diff release notes (reuse Python scripts verbatim);
    store listing; privacy policy HTML on `qvyshift.website` (clone of
    the Android page with iOS-specific swaps).
15. Submit to the App Store for end users (not just TestFlight): the
    deploy job creates the App Store version (`asc_create_version.py` —
    Apple does NOT auto-create it on build upload), sets notes +
    description, then `asc_resubmit.py` attaches the build and submits
    for review with `releaseType=AFTER_APPROVAL` (auto-release on
    approval). Apple review is still mandatory.

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
