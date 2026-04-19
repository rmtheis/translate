# apertium-native

Cross-compile scripts for Apertium's C++ toolchain against Android NDK.
Produces arm64-v8a binaries + shared libs that the `apertium-android` app
invokes via `ProcessBuilder` in `NativePipeline.java`.

## Build

Requires:
- Android NDK r28+ (set `NDK=...` or use `/Users/theis/Library/Android/sdk/ndk/28.2.13676358`)
- Android CMake 3.22 (bundled with the SDK)
- `brew install autoconf automake libtool pkg-config patchelf`
- Xcode command-line tools (for the ICU host build)

Full build:

```sh
./build.sh all
./install-to-app.sh     # copies to ../apertium-android/app/src/main/jniLibs/arm64-v8a/
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
- HFST (see below).

## HFST retry plan

`apertium-sme-nob` is the only Trunk pair that needs HFST, plus ~40 Nursery/Incubator
pairs if we ever expand beyond Trunk+Staging. The cross-compile is partly done:

- **OpenFST 1.7.2** (kkm000 fork) cross-compiles cleanly via `build_openfst`. One
  patch to `configure.ac` was needed to supply a cross-compile fallback for its
  `AC_RUN_IFELSE` float-equality check. Libs install at `out/<abi>/lib/libfst.a` +
  `out/<abi>/include/fst/`.
- **HFST itself** doesn't build. Blocker: HFST's `libhfst/src/implementations/`
  calls `SymbolTable::begin()/end()` — the iterator API OpenFST replaced with
  `SymbolTableIterator` in 1.7.x. Removing `convert.cc` from the build clears one
  site; `ConvertTropicalWeightTransducer.cc` and `TropicalWeightTransducer.cc`
  fail the same way and aren't optional.

### When picking this up next session

**First try** pinning OpenFST to a version that still has `begin()/end()`:

```sh
cd openfst
git clone https://github.com/kkm000/openfst.git .   # or fetch tarball
# find a tag or commit from 2017 or earlier; 1.6.9 is the documented last version
git checkout openfst-1.6.9           # or equivalent commit hash
# re-apply the configure.ac cross-compile patch:
python3 - <<'PY'
import re
with open('configure.ac') as f: c = f.read()
needle = 'Test float equality failed!'
if needle in c:
    c = c.replace('Compile with -msse -mfpmath=sse if using g++.\n              ]))])',
                  'Compile with -msse -mfpmath=sse if using g++.\n              ]))],\n              [echo \"Cross-compiling; assuming float equality is good on target\"])')
    open('configure.ac','w').write(c)
PY
autoreconf -fi
cd ..
./build.sh openfst
./build.sh hfst
```

www.openfst.org was 522ing during the initial attempt; the kkm000 fork may not
have a 1.6.x tag, in which case either vendor a tarball into `deps/openfst-1.6.9/`
or check out the right commit (`git log --before=2018` in kkm000's main branch).

**If 1.6.9 still doesn't work** (e.g. won't compile under modern clang), the
fallback is to patch HFST to use `SymbolTableIterator`. That's upstream-PR-scope
work — many call sites, loop bodies need restructuring (the iterator is stateful).

**If neither works**, accept HFST is a v2 milestone and leave `sme-nob` excluded.
`PairCatalog.HFST_EXCLUDED` is the single on-switch to flip once HFST is working.
