# native/

Cross-compile scripts for Apertium's C++ toolchain against Android NDK.
Produces arm64-v8a binaries + shared libs that the parent Android app
(`app/` at the repo root) invokes via `ProcessBuilder` in `NativePipeline.java`.

This directory was originally the separate `rmtheis/translate-native` repo;
it was folded into `rmtheis/translate` via `git subtree` so the toolchain
and the app ship from a single history.

## Build

Requires:
- Android NDK r28+ (set `NDK=...` or use `/Users/theis/Library/Android/sdk/ndk/28.2.13676358`)
- Android CMake 3.22 (bundled with the SDK)
- `brew install autoconf automake libtool pkg-config patchelf`
- Xcode command-line tools (for the ICU host build)

Full build:

```sh
./build.sh all
./install-to-app.sh     # copies to ../app/src/main/jniLibs/arm64-v8a/
```

Individual targets: `utfcpp`, `pcre2`, `xml2`, `icu`, `lttoolbox`,
`apertium`, `lex-tools`, `recursive`, `separable`, `cg3`.

## Output layout

- `build/arm64-v8a/...` — per-component build dirs
- `build/icu-host-build/` + `build/icu-host-install/` — ICU host stage
  (needed for cross-compile; ICU's codegen tools run on the build host)
- `out/arm64-v8a/` — final install prefix, autotools-style tree
- `shims/` — manual shims for bionic gaps (`wordexp.h`)

## Gotchas

- **`long double` soft-float**: Android's NDK doesn't export `__floatunditf`
  etc. from shared libs. Apertium is built `--disable-shared --enable-static`
  so tools statically link the helpers rather than pulling them from a DSO.
- **libxml2 `AM_CPPFLAGS`** only has `-I$(top_srcdir)`, no `$(top_builddir)`.
  Apertium and its sibling autotools projects are therefore built in-tree
  (`cd $src && ./configure && make`) instead of out-of-tree.
- **bionic missing `wordexp`** until API 28. cg3's `TextualParser.cpp`
  `#include <wordexp.h>` — covered by `shims/wordexp.h` which returns
  `WRDE_BADCHAR` so the (dead) shell-expansion path fails loudly.
- **cg3 needs Boost**. Its `get-boost.sh` fetches 1.65.1 into
  `cg3/include/boost/` at configure time; we pass `BOOST_ROOT=cg3/include`
  to cmake so it finds the local copy rather than hunting system paths.
- **cg3 needs RapidJSON**. We build `deps/rapidjson` (header-only) first
  and point `RapidJSON_DIR` at the installed cmake config.
- **ICU versioning**: ICU ships `.so.76.1` libraries. Android's APK
  packaging pattern (`lib*.so`) rejects versioned names, and each binary's
  `DT_NEEDED` points at the versioned soname. `install-to-app.sh` runs
  `patchelf --set-soname` on the libs and `patchelf --replace-needed` on
  each binary to rewrite to plain `libicuuc.so` etc.
- **Binary naming** for jniLibs: each tool (`lt-proc`, `apertium-transfer`,
  ...) must become `lib<tool>.so` with hyphens → underscores so Android
  extracts it executable. The Java-side `NativePipeline` maps back from
  mode-file friendly names (`lt-proc`) to these filenames.

## Missing / future

- armeabi-v7a is supported (`ABI=armeabi-v7a ./build.sh all`); arm64-v8a is the default.
- GH Actions workflow that runs the whole stack on Ubuntu runners (in progress, see repo root `.github/workflows/`).

## HFST

`apertium-sme-nob` is the only Trunk pair that needs HFST (plus ~40 Nursery/Incubator
pairs). HFST builds against upstream **OpenFST 1.8.5** and ships `hfst-apertium-proc`
as `libhfst_proc.so`. `build.sh hfst` applies three in-tree patches automatically:

- **OpenFST `configure.ac`**: cross-compile fallback for the `AC_RUN_IFELSE`
  float-equality check (can't execute target binaries during configure).
- **HFST `HfstInputStream.h`**: `TropicalWeightInputStream`'s forward-declaration
  guards were swapped with `LogWeightInputStream`'s, breaking
  `--without-openfst-log` builds. Python-patched after clone.
- **`shims/glob.h`**: bionic lacks `glob(3)`; HFST's `XfstCompiler` only calls
  it from the interactive "print dir" command, which Android never exercises.

HFST's `.yy` grammars need bison 3.x; `build_hfst` prefers Homebrew's bison
over macOS's built-in bison 2.3. The `AX_CHECK_ICU` macro needs `ICU_CONFIG`
pointed at our ICU's `icu-config` so the link line picks up `-licuuc -licudata`
(pkg-config's icu-i18n.pc marks them `Requires.private`).
