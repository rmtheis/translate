#!/usr/bin/env bash
# Cross-compile Apertium's C++ toolchain for Apple iOS.
#
# Produces a static-lib slice per target (arm64 device, arm64 simulator,
# optional x86_64 simulator) and then combines them into
# ApertiumCore.xcframework for the iOS app target to consume.
#
# Mirrors android/native/build.sh step-for-step; the main differences are
# toolchain selection (xcrun-based Xcode clang instead of the Android NDK),
# static-only libs (no .dylib shipping — everything links into the
# xcframework), and the per-slice / xcframework packaging at the end.
#
# Usage:
#   SLICE=ios-arm64     ./build.sh <target>    # device arm64  (default)
#   SLICE=ios-arm64-sim ./build.sh <target>    # simulator arm64 (Apple Silicon Mac)
#   SLICE=ios-x86_64-sim ./build.sh <target>   # simulator x86_64 (Intel Mac / Rosetta)
#                       ./build.sh xcframework # build all slices + wrap

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Toolchain
# -----------------------------------------------------------------------------
: "${SLICE:=ios-arm64}"
: "${IOS_MIN:=16.0}"

case "$SLICE" in
  ios-arm64)
    SDK=iphoneos
    ARCH=arm64
    MIN_FLAG="-miphoneos-version-min=$IOS_MIN"
    # Triple must be one the bundled autotools config.sub accepts as
    # *cross-compile* from the build host (arm64-apple-darwin). Older
    # ICU/Apertium config.sub copies don't recognize `-simulator`, so
    # we keep just `-apple-ios`; the actual device/simulator split is
    # entirely driven by CFLAGS (-miphoneos-version-min vs
    # -mios-simulator-version-min) and the sysroot.
    HOST_TRIPLE="aarch64-apple-ios"
    ;;
  ios-arm64-sim)
    SDK=iphonesimulator
    ARCH=arm64
    MIN_FLAG="-mios-simulator-version-min=$IOS_MIN"
    HOST_TRIPLE="aarch64-apple-ios"
    ;;
  ios-x86_64-sim)
    SDK=iphonesimulator
    ARCH=x86_64
    MIN_FLAG="-mios-simulator-version-min=$IOS_MIN"
    HOST_TRIPLE="x86_64-apple-ios"
    ;;
  *) echo "unknown SLICE: $SLICE (expected ios-arm64 | ios-arm64-sim | ios-x86_64-sim)"; exit 1 ;;
esac

SDK_PATH="$(xcrun --sdk $SDK --show-sdk-path)"
DEVELOPER_DIR="$(xcode-select -p)"

PREFIX="$SCRIPT_DIR/out/$SLICE"
BUILD="$SCRIPT_DIR/build/$SLICE"
mkdir -p "$PREFIX" "$BUILD"

export CC="$(xcrun --sdk $SDK --find clang)"
export CXX="$(xcrun --sdk $SDK --find clang++)"
export AR="$(xcrun --sdk $SDK --find ar)"
export RANLIB="$(xcrun --sdk $SDK --find ranlib)"
export STRIP="$(xcrun --sdk $SDK --find strip)"
export CFLAGS="-arch $ARCH -isysroot $SDK_PATH $MIN_FLAG -fPIC -O2"
export CXXFLAGS="-arch $ARCH -isysroot $SDK_PATH $MIN_FLAG -fPIC -O2 -std=c++17"
export LDFLAGS="-arch $ARCH -isysroot $SDK_PATH $MIN_FLAG -L$PREFIX/lib"
# Static ICU: libicuuc.a references _icudt76_dat (defined in libicudata.a),
# but CMake's FindICU only exports the i18n/io/uc components. Inject
# libicudata explicitly on the executable link line so every Apertium
# tool's link resolves the data symbol.
CMAKE_ICUDATA_FIX=(
  -DCMAKE_EXE_LINKER_FLAGS="-L$PREFIX/lib -licudata"
)
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_SYSROOT_DIR=""

CMAKE="$(command -v cmake)"
NINJA="$(command -v ninja || true)"

CMAKE_COMMON=(
  -DCMAKE_SYSTEM_NAME=iOS
  -DCMAKE_OSX_SYSROOT="$SDK"
  -DCMAKE_OSX_ARCHITECTURES="$ARCH"
  -DCMAKE_OSX_DEPLOYMENT_TARGET="$IOS_MIN"
  -DCMAKE_INSTALL_PREFIX="$PREFIX"
  -DCMAKE_PREFIX_PATH="$PREFIX"
  -DCMAKE_FIND_ROOT_PATH="$PREFIX"
  -DBUILD_SHARED_LIBS=OFF
  # CMAKE_SYSTEM_NAME=iOS flips executables to MACOSX_BUNDLE=TRUE, which
  # requires a BUNDLE DESTINATION on install(). We don't ship any
  # Apertium executable at runtime — the xcframework exposes callable
  # library functions instead — but CMake still builds them, so keep
  # them as plain CLI-style Mach-O binaries in the build tree.
  -DCMAKE_MACOSX_BUNDLE=OFF
)
if [ -n "$NINJA" ]; then
  CMAKE_COMMON+=(-GNinja -DCMAKE_MAKE_PROGRAM="$NINJA")
  BUILDER=(ninja)
else
  CMAKE_COMMON+=(-G"Unix Makefiles")
  BUILDER=(make)
fi

banner() { echo; echo "========== $* =========="; }

: "${JOBS:=$( (sysctl -n hw.ncpu 2>/dev/null || echo 2) )}"
JOBS="${MAX_JOBS:-$JOBS}"

# -----------------------------------------------------------------------------
# Sanity check: compile a trivial C++ program for $SLICE and verify platform.
# -----------------------------------------------------------------------------

test_toolchain() {
  banner "toolchain sanity check ($SLICE, IOS_MIN=$IOS_MIN)"
  mkdir -p "$BUILD"
  local src="$BUILD/test_toolchain.cpp"
  cat > "$src" <<'EOF'
#include <iostream>
#include <string>
int main() {
  std::string s = "hello from apertium-ios";
  std::cout << s << std::endl;
  return 0;
}
EOF
  "$CXX" $CXXFLAGS $LDFLAGS "$src" -o "$BUILD/test_toolchain"
  echo
  echo "--- file(1):"
  file "$BUILD/test_toolchain"
  echo
  echo "--- vtool -show-build:"
  vtool -show-build "$BUILD/test_toolchain" 2>&1 | sed -n '1,20p'
  echo
  echo "OK: toolchain produces $SLICE binaries into $PREFIX"
}

# -----------------------------------------------------------------------------
# Deps (to be filled in as we progress through the plan)
# -----------------------------------------------------------------------------

build_utfcpp() {
  banner "utfcpp (header-only)"
  local src="$SCRIPT_DIR/deps/utfcpp"
  [ -d "$src" ] || git clone --depth 1 https://github.com/nemtrif/utfcpp.git "$src"
  mkdir -p "$BUILD/utfcpp"
  "$CMAKE" -S "$src" -B "$BUILD/utfcpp" "${CMAKE_COMMON[@]}" \
    -DUTF8_TESTS=OFF -DUTF8_SAMPLES=OFF
  "${BUILDER[@]}" -C "$BUILD/utfcpp" install
}

build_pcre2() {
  banner "pcre2"
  local src="$SCRIPT_DIR/deps/pcre2"
  if [ ! -d "$src" ]; then
    curl -sL -o /tmp/pcre2.tar.bz2 "https://github.com/PCRE2Project/pcre2/releases/download/pcre2-10.44/pcre2-10.44.tar.bz2"
    mkdir -p "$src" && tar -xjf /tmp/pcre2.tar.bz2 -C "$src" --strip-components=1
  fi
  mkdir -p "$BUILD/pcre2"
  "$CMAKE" -S "$src" -B "$BUILD/pcre2" "${CMAKE_COMMON[@]}" \
    -DPCRE2_BUILD_PCRE2_8=ON -DPCRE2_BUILD_PCRE2_16=OFF -DPCRE2_BUILD_PCRE2_32=OFF \
    -DPCRE2_BUILD_TESTS=OFF -DPCRE2_BUILD_PCRE2GREP=OFF
  "${BUILDER[@]}" -C "$BUILD/pcre2" install
}

build_libxml2() {
  banner "libxml2"
  local src="$SCRIPT_DIR/deps/libxml2"
  if [ ! -d "$src" ]; then
    git clone --depth 1 --branch v2.13.5 https://github.com/GNOME/libxml2.git "$src"
  fi
  mkdir -p "$BUILD/libxml2"
  # HAVE_GETENTROPY=0: iOS libSystem has the symbol at link time (CMake's
  # check_function_exists resolves it), but <sys/random.h> isn't public on
  # iOS, so dict.c fails to compile with an implicit-function-declaration
  # error. Pre-populate the cache to short-circuit the check and fall back
  # to the time()-seeded PRNG — fine for libxml2's hash randomization.
  "$CMAKE" -S "$src" -B "$BUILD/libxml2" "${CMAKE_COMMON[@]}" \
    -DLIBXML2_WITH_ICONV=OFF -DLIBXML2_WITH_LZMA=OFF -DLIBXML2_WITH_PYTHON=OFF \
    -DLIBXML2_WITH_ZLIB=OFF -DLIBXML2_WITH_TESTS=OFF -DLIBXML2_WITH_PROGRAMS=OFF \
    -DHAVE_GETENTROPY=0
  "${BUILDER[@]}" -C "$BUILD/libxml2" install
}

build_icu() {
  banner "icu"
  local src="$SCRIPT_DIR/deps/icu"
  local version="76-1"
  if [ ! -d "$src/source" ]; then
    curl -sL -o /tmp/icu4c.tgz "https://github.com/unicode-org/icu/releases/download/release-${version}/icu4c-${version//-/_}-src.tgz"
    mkdir -p "$src" && tar -xzf /tmp/icu4c.tgz -C "$src" --strip-components=1
  fi

  # Stage 1 — host build for pkgdata/genrb/etc. Reused across iOS slices.
  local host_build="$SCRIPT_DIR/build/icu-host-build"
  local host_install="$SCRIPT_DIR/build/icu-host-install"
  if [ ! -x "$host_install/bin/icupkg" ]; then
    banner "icu — host stage (MacOSX)"
    rm -rf "$host_build" "$host_install"
    mkdir -p "$host_build" "$host_install"
    pushd "$host_build" >/dev/null
    env -i PATH=/usr/bin:/bin HOME="$HOME" \
      "$src/source/runConfigureICU" MacOSX --prefix="$host_install" \
      --disable-samples --disable-tests --disable-extras
    env -i PATH=/usr/bin:/bin HOME="$HOME" make -j"$JOBS"
    env -i PATH=/usr/bin:/bin HOME="$HOME" make install
    popd >/dev/null
  fi

  # Stage 2 — cross-compile for iOS $SLICE.
  # icu_cv_host_frag=mh-darwin: ICU's configure only matches *-apple-darwin*
  # → mh-darwin, not *-apple-ios*; pre-set the cache variable so the host
  # triple can stay ios-flavored while the makefile template is darwin.
  banner "icu — cross stage ($SLICE)"
  local cross_build="$BUILD/icu"
  rm -rf "$cross_build"
  mkdir -p "$cross_build"
  pushd "$cross_build" >/dev/null
  # --disable-tools: the cross stage would otherwise try to compile pkgdata
  # et al. for iOS — pkgdata.cpp uses system(3) which is
  # __DARWIN_ALIAS_C-marked unavailable on iOS. We only need those tools
  # on the host (already built in Stage 1); iOS runtime uses the static
  # ICU libs directly.
  icu_cv_host_frag=mh-darwin \
  "$src/source/configure" \
    --host="$HOST_TRIPLE" \
    --prefix="$PREFIX" \
    --with-cross-build="$host_build" \
    --enable-static --disable-shared \
    --disable-samples --disable-tests --disable-extras --disable-layoutex \
    --disable-tools \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS"
  make -j"$JOBS" install
  popd >/dev/null
}

# -----------------------------------------------------------------------------
# Apertium stack (to be filled in)
# -----------------------------------------------------------------------------

build_lttoolbox() {
  banner "lttoolbox"
  local src="$SCRIPT_DIR/lttoolbox"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/lttoolbox.git "$src"
  # Remove -flto from the CMakeLists's CHECK_CXX_COMPILER_FLAG loop:
  # LTO generates LLVM bitcode objects (magic 0xb17c0de) that libtool
  # can merge but xcodebuild -create-xcframework rejects as "unknown
  # architecture". Idempotent — no-op if already stripped.
  /usr/bin/sed -i '' \
    's|foreach(flag "-Wno-unused-result" "-flto")|foreach(flag "-Wno-unused-result")|' \
    "$src/CMakeLists.txt"
  mkdir -p "$BUILD/lttoolbox"
  "$CMAKE" -S "$src" -B "$BUILD/lttoolbox" "${CMAKE_COMMON[@]}" \
    "${CMAKE_ICUDATA_FIX[@]}" \
    -DBUILD_TESTING=OFF
  "${BUILDER[@]}" -C "$BUILD/lttoolbox" install
}
build_apertium() {
  banner "apertium (autotools)"
  local src="$SCRIPT_DIR/apertium"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/apertium.git "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  # Apertium's Makefile.am adds -I$(top_srcdir) to AM_CPPFLAGS but not
  # $(top_builddir), so out-of-tree builds can't find apertium_config.h.
  # Build in-tree like android/native/ does; distclean between slices.
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  # cross_compiling=yes: triples may match build on Apple Silicon, and
  # AC_RUN_IFELSE without this would try to exec iOS binaries natively.
  cross_compiling=yes \
  ./configure \
    --host="$HOST_TRIPLE" \
    --prefix="$PREFIX" \
    --disable-docs \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CFLAGS="$CFLAGS" \
    CXXFLAGS="$CXXFLAGS" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="$LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}
# Shared helper for the three autotools-based Apertium sub-projects
# (lex-tools, recursive, separable, anaphora). They all:
#   - clone into $SCRIPT_DIR/<name>
#   - want in-tree builds (same AM_CPPFLAGS issue as apertium core)
#   - depend on lttoolbox + apertium
_apertium_autotools_build() {
  local name="$1" repo="$2"
  banner "$name (autotools)"
  local src="$SCRIPT_DIR/$name"
  [ -d "$src" ] || git clone --depth 1 "$repo" "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  cross_compiling=yes \
  ./configure \
    --host="$HOST_TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CFLAGS="$CFLAGS" \
    CXXFLAGS="$CXXFLAGS" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="$LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_lex_tools() {
  _apertium_autotools_build "apertium-lex-tools" \
    "https://github.com/apertium/apertium-lex-tools.git"
  # lex-tools's Makefile.am already installs libapertium-lex-tools.a via
  # libtool, so nothing to repackage.
}

# Recursive / separable / anaphora only install CLI binaries — their
# Makefiles don't declare an installed library. Repackage the in-tree
# .o files into a static .a so the iOS wrappers can link against them,
# and copy the public-ish headers into $PREFIX/include/<name>/.
_repack_static() {
  local name="$1"; shift
  local src_dir="$SCRIPT_DIR/$name/src"
  local archive="$PREFIX/lib/lib${name}.a"
  local inc_dir="$PREFIX/include/$name"
  mkdir -p "$inc_dir"
  # Copy every in-tree header — including the configure-generated
  # rtx_config.h / auto_config.h, since rtx_processor.h (and others)
  # `#include` them by quote form and the compile breaks without them.
  for h in "$src_dir"/*.h; do
    [ -f "$h" ] || continue
    cp "$h" "$inc_dir/"
  done
  rm -f "$archive"
  local objs=()
  for o in "$@"; do
    [ -f "$src_dir/$o" ] || { echo "missing $src_dir/$o"; exit 1; }
    objs+=("$src_dir/$o")
  done
  "$AR" rcs "$archive" "${objs[@]}"
  echo "repackaged: $archive"
}

build_recursive() {
  _apertium_autotools_build "apertium-recursive" \
    "https://github.com/apertium/apertium-recursive.git"
  # rtx_proc.o and rtx_comp.o / rtx_decomp.o hold binary-specific main()s;
  # skip them. The remaining objects back RTXProcessor and its deps.
  _repack_static apertium-recursive \
    chunk.o pattern.o rtx_processor.o trx_compiler.o rtx_compiler.o randpath.o
}

build_separable() {
  _apertium_autotools_build "apertium-separable" \
    "https://github.com/apertium/apertium-separable.git"
  # lsx_proc.o is the binary main; lsx_processor.o is the class.
  _repack_static apertium-separable \
    lsx_processor.o
}

build_anaphora() {
  _apertium_autotools_build "apertium-anaphora" \
    "https://github.com/apertium/apertium-anaphora.git"
  # anaphora doesn't have a Processor class — the logic is all in
  # anaphora.cc's main(). We library-ify main() in a dedicated wrapper;
  # archive the supporting .o files here so the wrapper can link.
  _repack_static apertium-anaphora \
    parse_arx.o parse_biltrans.o pattern_arx.o score.o
}

build_rapidjson() {
  banner "rapidjson (header-only, for cg3)"
  local src="$SCRIPT_DIR/deps/rapidjson"
  [ -d "$src" ] || git clone --depth 1 https://github.com/Tencent/rapidjson.git "$src"
  mkdir -p "$BUILD/rapidjson"
  "$CMAKE" -S "$src" -B "$BUILD/rapidjson" "${CMAKE_COMMON[@]}" \
    -DRAPIDJSON_BUILD_DOC=OFF -DRAPIDJSON_BUILD_EXAMPLES=OFF \
    -DRAPIDJSON_BUILD_TESTS=OFF -DRAPIDJSON_BUILD_THIRDPARTY_GTEST=OFF
  "${BUILDER[@]}" -C "$BUILD/rapidjson" install
}

build_cg3() {
  banner "cg3 (GPLv3)"
  local src="$SCRIPT_DIR/cg3"
  [ -d "$src" ] || git clone --depth 1 https://github.com/GrammarSoft/cg3.git "$src"
  [ -f "$PREFIX/include/rapidjson/rapidjson.h" ] || build_rapidjson
  # cg3 doesn't vendor Boost; its get-boost.sh fetches 1.65.1, which
  # trips clang two-phase-lookup bugs in flat_tree<> under modern libc++.
  # Use 1.86.0 instead — idempotent if already present.
  if [ ! -f "$src/include/boost/version.hpp" ]; then
    banner "cg3 — fetching Boost 1.86.0"
    curl -sL --max-redirs 10 -o /tmp/boost.tar.bz2 \
      "https://archives.boost.io/release/1.86.0/source/boost_1_86_0.tar.bz2"
    tar -jxf /tmp/boost.tar.bz2 -C /tmp boost_1_86_0/boost
    mv /tmp/boost_1_86_0/boost "$src/include/"
    rm -rf /tmp/boost_1_86_0 /tmp/boost.tar.bz2
  fi
  # iOS patches to the cg3 tree (idempotent — all skip on second run):
  #   - Top CMakeLists foreach std flag: pinned to c++17 (cg3's default
  #     c++26 fights Boost's flat_tree::insert under clang two-phase).
  #   - Top CMakeLists _FLAGS_COMMON foreach: drop -flto (generates LLVM
  #     IR objects with magic 0xb17c0de, which xcodebuild
  #     -create-xcframework rejects as "unknown architecture").
  #   - src/CMakeLists CMP0167: guard under if(POLICY …) — CMP0167 was
  #     added in CMake 3.30 and GHA runners / local CMake (we're on
  #     3.22) bail otherwise.
  #   - system()/wordexp()/popen_plus: iOS SDK marks all three
  #     __IPHONE_NA. Rewrite call sites to throw — they sit on
  #     grammar-compile paths (cg-comp, hunspell spawn) that a
  #     translation-only iOS build never exercises, and cg-proc itself
  #     doesn't touch them.
  python3 - "$src" <<'PY'
import sys, re
from pathlib import Path
root = Path(sys.argv[1])
edits = []

# Top CMakeLists: pin c++17 and drop -flto.
top = root / "CMakeLists.txt"
if top.is_file():
    c = top.read_text()
    orig = c
    c = c.replace(
        'foreach(flag "-std=c++26" "-std=c++2c" "-std=c++23" "-std=c++2b" "-std=c++20" "-std=c++2a" "-std=c++17")',
        'foreach(flag "-std=c++17")  # iOS: pinned; newer stds fight Boost 1.65.1 flat_tree')
    c = c.replace(
        'foreach(flag "-Wno-unused-result" "-flto")',
        'foreach(flag "-Wno-unused-result")  # iOS: -flto dropped — xcframework packager rejects LLVM IR')
    if c != orig:
        top.write_text(c); edits.append(str(top))

# src/CMakeLists: guard CMP0167.
sub = root / "src/CMakeLists.txt"
if sub.is_file():
    c = sub.read_text()
    # Lines in cg3 use tabs; look for the literal line.
    needle = "\t\tcmake_policy(SET CMP0167 OLD)"
    if needle in c and "if(POLICY CMP0167)" not in c:
        c = c.replace(needle,
                      "\t\tif(POLICY CMP0167)\n\t\t\tcmake_policy(SET CMP0167 OLD)\n\t\tendif()",
                      1)
        sub.write_text(c); edits.append(str(sub))

# popen_plus: stub system() calls.
pp = root / "include/posix/popen_plus.cpp"
if pp.is_file():
    c = pp.read_text()
    if 'system(command);' in c and 'IOS_STUB' not in c:
        c = c.replace(
            '#include <errno.h>',
            '#define IOS_STUB 1\n#include <stdexcept>\n#include <errno.h>',
            1)
        c = re.sub(r'int result = system\(command\);',
                   'int result = 0; (void)command; /* system() NA on iOS */',
                   c)
        c = re.sub(r'^\s*system\(command\);',
                   '    (void)command; /* system() NA on iOS */',
                   c, flags=re.MULTILINE)
        pp.write_text(c); edits.append(str(pp))

# TextualParser: stub wordexp().
tp = root / "src/TextualParser.cpp"
if tp.is_file():
    c = tp.read_text()
    if 'wordexp(' in c and 'IOS_STUB' not in c:
        stub = ('#include "TextualParser.hpp"\n#define IOS_STUB 1\n'
                '#include <stdexcept>\n'
                '#define WRDE_NOCMD 0\n#define WRDE_UNDEF 0\n'
                'typedef struct { char** we_wordv; size_t we_wordc; } wordexp_t;\n'
                'static int wordexp(const char*, wordexp_t*, int) { '
                'throw std::runtime_error("wordexp unavailable on iOS"); }\n'
                'static void wordfree(wordexp_t*) {}\n')
        c = c.replace('#include "TextualParser.hpp"', stub, 1)
        c = c.replace('#include <wordexp.h>',
                      '// #include <wordexp.h> — stubbed for iOS', 1)
        tp.write_text(c); edits.append(str(tp))

for p in edits: print("patched:", p)
PY
  mkdir -p "$BUILD/cg3"
  # -fno-lto overrides cg3's default -flto. Without this, libcg3.a
  # contains LLVM IR objects (magic 0xb17c0de) instead of Mach-O; the
  # xcframework packager rejects that with "Unknown header" when it
  # tries to sniff the arch of the combined library.
  "$CMAKE" -S "$src" -B "$BUILD/cg3" "${CMAKE_COMMON[@]}" \
    "${CMAKE_ICUDATA_FIX[@]}" \
    -DUSE_TCMALLOC=OFF -DMASTER_PROJECT=ON \
    -DENABLE_PROFILING=OFF \
    -DRapidJSON_DIR="$PREFIX/lib/cmake/RapidJSON" \
    -DBOOST_ROOT="$src/include" \
    -DBoost_NO_SYSTEM_PATHS=ON \
    -DBoost_INCLUDE_DIR="$src/include" \
    -DICU_ROOT="$PREFIX" \
    -DCMAKE_CXX_FLAGS="$CXXFLAGS -fno-lto" \
    -DCMAKE_C_FLAGS="$CFLAGS -fno-lto"
  "${BUILDER[@]}" -C "$BUILD/cg3" install
}
build_openfst() {
  banner "openfst (HFST backend)"
  local src="$SCRIPT_DIR/openfst"
  local version="1.8.5"
  if [ ! -d "$src" ]; then
    # Mirror-first: openfst.org 5xx/403's from GitHub Actions runners.
    # rmtheis/translate (this repo) hosts a vendored tarball as a release
    # asset; fall back to the upstream site if the mirror is unreachable.
    # The mirror originally lived on rmtheis/translate-native, which was
    # folded into this repo in April 2026 — update in lock-step with
    # android/native/build.sh.
    local urls=(
      "https://github.com/rmtheis/translate/releases/download/vendor-openfst-${version}/openfst-${version}.tar.gz"
      "https://www.openfst.org/twiki/pub/FST/FstDownload/openfst-${version}.tar.gz"
    )
    for url in "${urls[@]}"; do
      if curl -fsSL --retry 3 --retry-delay 5 --retry-all-errors \
           -o /tmp/openfst.tar.gz "$url" \
         && file /tmp/openfst.tar.gz | grep -q "gzip compressed"; then
        echo "fetched openfst from $url"
        break
      fi
      echo "fetch failed: $url"
    done
    file /tmp/openfst.tar.gz | grep -q "gzip compressed" \
      || { echo "ERROR: could not fetch openfst-${version}"; exit 1; }
    mkdir -p "$src"
    tar -xzf /tmp/openfst.tar.gz -C "$src" --strip-components=1
    # Patch configure.ac: the float-equality AC_RUN_IFELSE aborts under
    # cross-compile (can't execute iOS target binaries on the build host).
    # Supply a cross-compile fallback that assumes the check passes.
    python3 - "$src/configure.ac" <<'PY'
import sys
p = sys.argv[1]
with open(p) as f: c = f.read()
if 'Compile with -msse' in c and 'Cross-compiling; assuming float equality' not in c:
    needle = 'Compile with -msse -mfpmath=sse if using g++."\n              ]))])'
    repl   = ('Compile with -msse -mfpmath=sse if using g++."\n              ]))],\n'
              '              [echo "Cross-compiling; assuming float equality is good on target"])')
    c = c.replace(needle, repl, 1)
    open(p,'w').write(c)
PY
    (cd "$src" && autoreconf -fi)
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  cross_compiling=yes \
  ./configure \
    --host="$HOST_TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    --disable-bin \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include" \
    LDFLAGS="$LDFLAGS"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_hfst() {
  banner "hfst"
  local src="$SCRIPT_DIR/hfst"
  [ -d "$src" ] || git clone --depth 1 https://github.com/hfst/hfst.git "$src"
  [ -f "$PREFIX/include/fst/fst.h" ] || build_openfst
  # HFST's HfstInputStream.h has the Tropical/Log forward-declaration
  # guards swapped: TropicalWeightInputStream is only declared under
  # HAVE_OPENFST_LOG, but used under HAVE_OPENFST alone — so
  # --without-openfst-log builds fail to find the type. Idempotent.
  python3 - "$src" <<'PY'
import sys, re
from pathlib import Path
root = Path(sys.argv[1])
# Swap Tropical/Log forward-declaration guards.
p = root / "libhfst/src/HfstInputStream.h"
c = p.read_text()
bad = ('#if HAVE_OPENFST\n    class LogWeightInputStream;\n'
       '#if HAVE_OPENFST_LOG || HAVE_LEAN_OPENFST_LOG\n'
       '    class TropicalWeightInputStream;\n#endif\n#endif')
good = ('#if HAVE_OPENFST\n    class TropicalWeightInputStream;\n'
        '#if HAVE_OPENFST_LOG || HAVE_LEAN_OPENFST_LOG\n'
        '    class LogWeightInputStream;\n#endif\n#endif')
if bad in c:
    p.write_text(c.replace(bad, good, 1))
    print("patched:", p)
# Stub XfstCompiler's three system() calls — interactive-shell paths
# that hfst-apertium-proc never exercises. iOS marks system() as
# __IPHONE_NA; replace with a throwing no-op.
xc = root / "libhfst/src/parsers/XfstCompiler.cc"
if xc.is_file():
    c = xc.read_text()
    if 'IOS_STUB' not in c and 'system(' in c:
        # Inject stub once near the top of the file.
        c = c.replace('#include "XfstCompiler.h"',
                      '#include "XfstCompiler.h"\n'
                      '#define IOS_STUB 1\n#include <stdexcept>\n'
                      'static int ios_system_stub(const char*) { '
                      'throw std::runtime_error("system(3) unavailable on iOS"); }\n',
                      1)
        # The XfstCompiler has its own method `XfstCompiler::system(...)`
        # that forwards to the POSIX `::system(...)`. Only the forward
        # call sites (leading `::` with no identifier before it) hit the
        # __IPHONE_NA deprecation — leave method definition/invocations
        # like `XfstCompiler::system(` alone.
        c = re.sub(r'(?<![A-Za-z0-9_])::system\s*\(', 'ios_system_stub(', c)
        xc.write_text(c)
        print("patched:", xc)
PY
  # HFST's .yy parsers use bison 3.x syntax; macOS ships bison 2.3 at
  # /usr/bin. Prefer Homebrew's bison when present; fall back to $PATH
  # (CI runners usually have 3.x).
  local bison_path=""
  for d in /usr/local/opt/bison/bin /opt/homebrew/opt/bison/bin; do
    [ -x "$d/bison" ] && bison_path="$d"
  done
  if [ -n "$bison_path" ]; then
    export PATH="$bison_path:$PATH"
  fi
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  # AX_CHECK_ICU prefers icu-config over pkg-config; pkg-config's
  # icu-i18n.pc doesn't list icu-uc/data in public Libs (marked private).
  # Point ICU_CONFIG at our cross-compiled icu-config so the link line
  # picks up -licui18n -licuuc -licudata.
  cross_compiling=yes \
  ./configure \
    --host="$HOST_TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    --without-sfst --with-openfst --without-openfst-log \
    --without-foma --without-xfsm --without-readline \
    --enable-proc \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include" \
    LDFLAGS="$LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig" \
    ICU_CONFIG="$PREFIX/bin/icu-config"
  make -j"$JOBS"
  make install
  popd >/dev/null

  # HFST's Makefile installs libhfst.a + hfst-apertium-proc (binary) but
  # not the hfst-proc/*.o object files that back the binary. Our wrapper
  # links against the ProcTransducer/Applicator classes directly, so
  # repackage those objects into libhfst_proc.a and copy the headers.
  local hp="$src/tools/src/hfst-proc"
  if [ -f "$hp/transducer.o" ]; then
    local archive="$PREFIX/lib/libhfst_proc.a"
    rm -f "$archive"
    # Exclude hfst-proc.o — it holds the binary's main()/argv parsing.
    "$AR" rcs "$archive" \
      "$hp/alphabet.o" "$hp/applicators.o" "$hp/formatter.o" \
      "$hp/lookup-path.o" "$hp/lookup-state.o" "$hp/tokenizer.o" \
      "$hp/transducer.o"
    mkdir -p "$PREFIX/include/hfst-proc"
    cp "$hp"/*.h "$PREFIX/include/hfst-proc/"
    echo "repackaged: $archive"
  fi
}

# -----------------------------------------------------------------------------
# Wrappers — our C++ adapters that library-ify each Apertium CLI tool.
# -----------------------------------------------------------------------------

build_wrappers() {
  banner "apertium_core wrappers"
  local wsrc="$SCRIPT_DIR/wrappers"
  local wbuild="$BUILD/wrappers"
  mkdir -p "$wbuild"

  # Compile every wrapper .cpp into an object, then archive into one
  # libapertium_core.a. Header deps come from $PREFIX/include, icu + libxml2
  # come from the same prefix. Each wrapper stays self-contained so that
  # adding a new tool wrapper is just dropping wrappers/foo.cpp in place.
  local objs=()
  # apertium-core installs its public headers to $PREFIX/include/apertium
  # but NOT the configure-generated apertium_config.h — that stays in
  # the source tree. Several public headers (tagger.h in particular)
  # `#include "apertium_config.h"` by quote form, so we add the source
  # dir to the include path for the wrapper compile.
  for src in "$wsrc"/*.cpp; do
    [ -f "$src" ] || continue
    local obj="$wbuild/$(basename "${src%.cpp}.o")"
    "$CXX" $CXXFLAGS \
      -I"$wsrc" \
      -I"$PREFIX/include" \
      -I"$PREFIX/include/utf8cpp" \
      -I"$PREFIX/include/libxml2" \
      -I"$PREFIX/include/apertium-lex-tools" \
      -I"$PREFIX/include/apertium-recursive" \
      -I"$PREFIX/include/apertium-separable" \
      -I"$PREFIX/include/apertium-anaphora" \
      -I"$PREFIX/include/hfst" \
      -I"$SCRIPT_DIR/apertium/apertium" \
      -I"$SCRIPT_DIR/cg3/src" \
      -I"$SCRIPT_DIR/cg3/include" \
      -c "$src" -o "$obj"
    objs+=("$obj")
  done
  if [ ${#objs[@]} -eq 0 ]; then
    echo "no wrapper sources found in $wsrc"; return 1
  fi
  rm -f "$PREFIX/lib/libapertium_core.a"
  "$AR" rcs "$PREFIX/lib/libapertium_core.a" "${objs[@]}"
  mkdir -p "$PREFIX/include/apertium_core"
  cp "$wsrc/apertium_core.h" "$PREFIX/include/apertium_core/apertium_core.h"
  echo "OK: $PREFIX/lib/libapertium_core.a"
}

# -----------------------------------------------------------------------------
# xcframework packaging (to be filled in once the components build)
# -----------------------------------------------------------------------------

build_xcframework() {
  banner "ApertiumCore.xcframework"
  # Pre-flight: every slice we're bundling must have been built.
  local slices=(ios-arm64 ios-arm64-sim)
  for s in "${slices[@]}"; do
    if [ ! -f "$SCRIPT_DIR/out/$s/lib/libapertium_core.a" ]; then
      echo "ERROR: slice $s is not built (out/$s/lib/libapertium_core.a missing)"
      echo "       run: SLICE=$s ./build.sh all && SLICE=$s ./build.sh wrappers"
      exit 1
    fi
  done

  # Per-slice: merge all our static archives into one ApertiumCore.a so
  # consumers only link one library. `libtool -static` handles duplicate
  # symbols and foreign archive formats cleanly; `ar rcs` would just
  # concatenate and lose symbols.
  for s in "${slices[@]}"; do
    local lib_dir="$SCRIPT_DIR/out/$s/lib"
    local bundle="$SCRIPT_DIR/build/$s/ApertiumCore.a"
    mkdir -p "$(dirname "$bundle")"
    rm -f "$bundle"
    # shellcheck disable=SC2046
    /usr/bin/libtool -static -o "$bundle" \
      "$lib_dir/libapertium_core.a" \
      "$lib_dir/libapertium.a" \
      "$lib_dir/libapertium-lex-tools.a" \
      "$lib_dir/libapertium-recursive.a" \
      "$lib_dir/libapertium-separable.a" \
      "$lib_dir/libapertium-anaphora.a" \
      "$lib_dir/libcg3.a" \
      "$lib_dir/libhfst_proc.a" \
      "$lib_dir/libhfst.a" \
      "$lib_dir/libfst.a" \
      "$lib_dir/liblttoolbox.a" \
      "$lib_dir/libxml2.a" \
      "$lib_dir/libicui18n.a" \
      "$lib_dir/libicuio.a" \
      "$lib_dir/libicuuc.a" \
      "$lib_dir/libicudata.a" \
      "$lib_dir/libpcre2-8.a" 2>&1 | grep -v "same member name" || true
    echo "bundled: $bundle"
  done

  # Public headers that Swift imports via the bridging header.
  local public_hdr="$SCRIPT_DIR/build/public-headers"
  rm -rf "$public_hdr"; mkdir -p "$public_hdr"
  cp "$SCRIPT_DIR/wrappers/apertium_core.h" "$public_hdr/"

  # Final xcframework combining all slices.
  local out_xcf="$SCRIPT_DIR/ApertiumCore.xcframework"
  rm -rf "$out_xcf"
  xcodebuild -create-xcframework \
    -library "$SCRIPT_DIR/build/ios-arm64/ApertiumCore.a"     -headers "$public_hdr" \
    -library "$SCRIPT_DIR/build/ios-arm64-sim/ApertiumCore.a" -headers "$public_hdr" \
    -output  "$out_xcf"
  echo
  echo "wrote: $out_xcf"
}

# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

case "${1:-help}" in
  test-toolchain) test_toolchain ;;
  utfcpp)    build_utfcpp ;;
  pcre2)     build_pcre2 ;;
  xml2)      build_libxml2 ;;
  icu)       build_icu ;;
  lttoolbox) build_lttoolbox ;;
  apertium)  build_apertium ;;
  cg3)       build_cg3 ;;
  lex-tools) build_lex_tools ;;
  recursive) build_recursive ;;
  separable) build_separable ;;
  anaphora)  build_anaphora ;;
  hfst)      build_hfst ;;
  openfst)   build_openfst ;;
  rapidjson) build_rapidjson ;;
  wrappers)  build_wrappers ;;
  deps)      build_utfcpp; build_pcre2; build_libxml2; build_icu ;;
  all)       build_utfcpp; build_pcre2; build_libxml2; build_icu
             build_lttoolbox; build_apertium; build_lex_tools
             build_recursive; build_separable; build_anaphora
             build_cg3; build_openfst; build_hfst ;;
  xcframework) build_xcframework ;;
  help|*)
    cat <<EOF
usage: SLICE=<slice> $0 <target>

Slices:     ios-arm64 (default) | ios-arm64-sim | ios-x86_64-sim

Targets:
  test-toolchain     Verify the iOS toolchain by compiling a hello-world.
  utfcpp pcre2 xml2 icu
  lttoolbox apertium lex-tools recursive separable anaphora
  cg3 openfst hfst
  deps               utfcpp + pcre2 + xml2 + icu
  all                All components for the selected SLICE.
  xcframework        Build every slice and wrap into ApertiumCore.xcframework.

Env overrides:
  IOS_MIN=16.0       Minimum iOS version (affects -miphoneos-version-min).
  MAX_JOBS=<n>       Cap parallelism (default: number of CPU cores).
EOF
    ;;
esac
