#!/usr/bin/env bash
# Cross-compile Apertium's C++ toolchain for Android arm64-v8a.
# Outputs go into $PREFIX which we bundle into the app under jniLibs/arm64-v8a/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Toolchain
# -----------------------------------------------------------------------------
: "${NDK:=/Users/theis/Library/Android/sdk/ndk/28.2.13676358}"
: "${ANDROID_API:=21}"
: "${ABI:=arm64-v8a}"

case "$ABI" in
  arm64-v8a)   TRIPLE=aarch64-linux-android ;;
  armeabi-v7a) TRIPLE=armv7a-linux-androideabi ;;
  *) echo "unknown ABI: $ABI"; exit 1 ;;
esac

case "$(uname -s)" in
  Darwin) HOST_OS=darwin-x86_64 ;;
  Linux)  HOST_OS=linux-x86_64 ;;
  *) echo "unknown host OS: $(uname -s)"; exit 1 ;;
esac
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/$HOST_OS"
SYSROOT="$TOOLCHAIN/sysroot"
PREFIX="$SCRIPT_DIR/out/$ABI"
BUILD="$SCRIPT_DIR/build/$ABI"
mkdir -p "$PREFIX" "$BUILD"

export CC="$TOOLCHAIN/bin/${TRIPLE}${ANDROID_API}-clang"
export CXX="$TOOLCHAIN/bin/${TRIPLE}${ANDROID_API}-clang++"
export AR="$TOOLCHAIN/bin/llvm-ar"
export RANLIB="$TOOLCHAIN/bin/llvm-ranlib"
export STRIP="$TOOLCHAIN/bin/llvm-strip"
export CFLAGS="-fPIC -O2"
export CXXFLAGS="-fPIC -O2 -std=c++17"
export LDFLAGS="-Wl,--build-id=sha1 -Wl,--hash-style=gnu"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
# pkg-config must not see host's /usr paths
export PKG_CONFIG_SYSROOT_DIR=""

CMAKE="$NDK/../../cmake/3.22.1/bin/cmake"
NINJA="$NDK/../../cmake/3.22.1/bin/ninja"
CMAKE_COMMON=(
  -DCMAKE_TOOLCHAIN_FILE="$NDK/build/cmake/android.toolchain.cmake"
  -DANDROID_ABI="$ABI"
  -DANDROID_PLATFORM="android-$ANDROID_API"
  -DCMAKE_INSTALL_PREFIX="$PREFIX"
  -DCMAKE_PREFIX_PATH="$PREFIX"
  -DCMAKE_FIND_ROOT_PATH="$PREFIX"
  -DCMAKE_MAKE_PROGRAM="$NINJA"
  -DBUILD_SHARED_LIBS=ON
  -GNinja
)

banner() { echo; echo "========== $* =========="; }

# Cross-platform CPU count, capped so low-memory CI runners don't OOM linking ICU/boost/OpenFST.
: "${JOBS:=$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2) )}"
JOBS="${MAX_JOBS:-$JOBS}"

# -----------------------------------------------------------------------------
# Deps
# -----------------------------------------------------------------------------

build_utfcpp() {
  banner "utfcpp (header-only)"
  local src="$SCRIPT_DIR/deps/utfcpp"
  [ -d "$src" ] || git clone --depth 1 https://github.com/nemtrif/utfcpp.git "$src"
  mkdir -p "$BUILD/utfcpp"
  "$CMAKE" -S "$src" -B "$BUILD/utfcpp" "${CMAKE_COMMON[@]}" \
    -DUTF8_TESTS=OFF -DUTF8_SAMPLES=OFF
  "$NINJA" -C "$BUILD/utfcpp" install
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
  "$NINJA" -C "$BUILD/pcre2" install
}

build_libxml2() {
  banner "libxml2"
  local src="$SCRIPT_DIR/deps/libxml2"
  if [ ! -d "$src" ]; then
    git clone --depth 1 --branch v2.13.5 https://github.com/GNOME/libxml2.git "$src"
  fi
  mkdir -p "$BUILD/libxml2"
  "$CMAKE" -S "$src" -B "$BUILD/libxml2" "${CMAKE_COMMON[@]}" \
    -DLIBXML2_WITH_ICONV=OFF -DLIBXML2_WITH_LZMA=OFF -DLIBXML2_WITH_PYTHON=OFF \
    -DLIBXML2_WITH_ZLIB=OFF -DLIBXML2_WITH_TESTS=OFF -DLIBXML2_WITH_PROGRAMS=OFF
  "$NINJA" -C "$BUILD/libxml2" install
}

build_icu() {
  banner "icu"
  local src="$SCRIPT_DIR/deps/icu"
  local version="76-1"
  if [ ! -d "$src/source" ]; then
    curl -sL -o /tmp/icu4c.tgz "https://github.com/unicode-org/icu/releases/download/release-${version}/icu4c-${version//-/_}-src.tgz"
    mkdir -p "$src" && tar -xzf /tmp/icu4c.tgz -C "$src" --strip-components=1
  fi

  # Stage 1 — host build to get pkgdata / genrb / genbrk codegen tools. The cross
  # stage (--with-cross-build) reuses the host build dir, so this must match the
  # runner's platform (MacOSX on darwin, Linux on linux). Build and install dirs
  # MUST be separate; ICU's install breaks if prefix overlaps build.
  case "$(uname -s)" in
    Darwin) ICU_HOST_PLATFORM=MacOSX ;;
    Linux)  ICU_HOST_PLATFORM=Linux ;;
  esac
  local host_build="$SCRIPT_DIR/build/icu-host-build"
  local host_install="$SCRIPT_DIR/build/icu-host-install"
  if [ ! -x "$host_install/bin/icupkg" ]; then
    banner "icu — host stage ($ICU_HOST_PLATFORM)"
    rm -rf "$host_build" "$host_install"
    mkdir -p "$host_build" "$host_install"
    pushd "$host_build" >/dev/null
    env -i PATH=/usr/bin:/bin HOME="$HOME" \
      "$src/source/runConfigureICU" "$ICU_HOST_PLATFORM" --prefix="$host_install" \
      --disable-samples --disable-tests --disable-extras
    env -i PATH=/usr/bin:/bin HOME="$HOME" make -j"$JOBS"
    env -i PATH=/usr/bin:/bin HOME="$HOME" make install
    popd >/dev/null
  fi

  # Stage 2 — cross-compile for Android. --with-cross-build wants the host BUILD dir.
  banner "icu — cross stage ($ABI)"
  local cross_build="$BUILD/icu"
  rm -rf "$cross_build"
  mkdir -p "$cross_build"
  pushd "$cross_build" >/dev/null
  "$src/source/configure" \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --with-cross-build="$host_build" \
    --enable-static --enable-shared \
    --disable-samples --disable-tests --disable-extras --disable-layoutex \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS"
  make -j"$JOBS" install
  popd >/dev/null
}

build_lttoolbox() {
  banner "lttoolbox"
  local src="$SCRIPT_DIR/lttoolbox"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/lttoolbox.git "$src"
  mkdir -p "$BUILD/lttoolbox"
  "$CMAKE" -S "$src" -B "$BUILD/lttoolbox" "${CMAKE_COMMON[@]}" \
    -DBUILD_TESTING=OFF
  "$NINJA" -C "$BUILD/lttoolbox" install
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
  # Apertium's Makefile.am only adds -I$(top_srcdir) to AM_CPPFLAGS, not $(top_builddir),
  # so out-of-tree builds can't find the generated apertium/apertium_config.h. Build in-tree.
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-docs \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_lex_tools() {
  banner "apertium-lex-tools (lrx-proc, lsx-proc)"
  local src="$SCRIPT_DIR/apertium-lex-tools"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/apertium-lex-tools.git "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_recursive() {
  banner "apertium-recursive (rtx-proc)"
  local src="$SCRIPT_DIR/apertium-recursive"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/apertium-recursive.git "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_anaphora() {
  banner "apertium-anaphora"
  local src="$SCRIPT_DIR/apertium-anaphora"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/apertium-anaphora.git "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_separable() {
  banner "apertium-separable (lsx-proc)"
  local src="$SCRIPT_DIR/apertium-separable"
  [ -d "$src" ] || git clone --depth 1 https://github.com/apertium/apertium-separable.git "$src"
  if [ ! -f "$src/configure" ]; then
    pushd "$src" >/dev/null
    autoreconf -fi
    popd >/dev/null
  fi
  pushd "$src" >/dev/null
  make distclean 2>/dev/null || true
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$PREFIX/include/libxml2 -I$PREFIX/include/utf8cpp" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_rapidjson() {
  banner "rapidjson (header-only, for cg3)"
  local src="$SCRIPT_DIR/deps/rapidjson"
  [ -d "$src" ] || git clone --depth 1 https://github.com/Tencent/rapidjson.git "$src"
  mkdir -p "$BUILD/rapidjson"
  "$CMAKE" -S "$src" -B "$BUILD/rapidjson" "${CMAKE_COMMON[@]}" \
    -DRAPIDJSON_BUILD_DOC=OFF -DRAPIDJSON_BUILD_EXAMPLES=OFF \
    -DRAPIDJSON_BUILD_TESTS=OFF -DRAPIDJSON_BUILD_THIRDPARTY_GTEST=OFF
  "$NINJA" -C "$BUILD/rapidjson" install
}

build_openfst() {
  banner "openfst (HFST backend)"
  local src="$SCRIPT_DIR/openfst"
  local version="1.8.5"
  if [ ! -d "$src" ]; then
    # Our rmtheis/translate-native GitHub release is primary — openfst.org
    # intermittently 5xx's on GitHub Actions runners (saw `gzip: stdin: not in
    # gzip format` on 2026-04-21: curl -s masked an HTTP error page). Upstream
    # is kept as a fallback so a clean laptop build still works if the mirror
    # tag ever goes missing.
    local urls=(
      "https://github.com/rmtheis/translate-native/releases/download/vendor-openfst-${version}/openfst-${version}.tar.gz"
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
      || { echo "ERROR: could not fetch openfst-${version} from any mirror"; exit 1; }
    mkdir -p "$src"
    tar -xzf /tmp/openfst.tar.gz -C "$src" --strip-components=1
    # Patch configure.ac: the float-equality check uses AC_RUN_IFELSE which aborts
    # under cross-compile because it can't execute target binaries. Supply a
    # cross-compile fallback that assumes the check passes on arm64.
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
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    --disable-bin \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_hfst() {
  banner "hfst"
  local src="$SCRIPT_DIR/hfst"
  [ -d "$src" ] || git clone --depth 1 https://github.com/hfst/hfst.git "$src"
  [ -f "$PREFIX/include/fst/fst.h" ] || build_openfst
  # HFST's HfstInputStream.h has the Tropical/Log forward-declaration guards
  # swapped: TropicalWeightInputStream is declared only under HAVE_OPENFST_LOG,
  # but used under HAVE_OPENFST alone — so --without-openfst-log builds fail
  # to find the type. Swap the two class names. Idempotent.
  python3 - "$src/libhfst/src/HfstInputStream.h" <<'PY'
import sys
p = sys.argv[1]
with open(p) as f: c = f.read()
bad = ('#if HAVE_OPENFST\n    class LogWeightInputStream;\n'
       '#if HAVE_OPENFST_LOG || HAVE_LEAN_OPENFST_LOG\n'
       '    class TropicalWeightInputStream;\n#endif\n#endif')
good = ('#if HAVE_OPENFST\n    class TropicalWeightInputStream;\n'
        '#if HAVE_OPENFST_LOG || HAVE_LEAN_OPENFST_LOG\n'
        '    class LogWeightInputStream;\n#endif\n#endif')
if bad in c:
    open(p,'w').write(c.replace(bad, good, 1))
PY
  # HFST's .yy files use bison 3.x syntax. macOS ships bison 2.3 in /usr/bin.
  # Prefer Homebrew's bison if present; fall back to whatever's in PATH (Linux CI).
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
  # AX_CHECK_ICU prefers `icu-config` over pkg-config, and pkg-config's output
  # for icu-i18n doesn't include the transitive `icu-uc` dep (it's marked
  # Requires.private). Use the icu-config we installed with ICU — it returns
  # all three libs (`-licui18n -licuuc -licudata`).
  ./configure \
    --host="$TRIPLE" \
    --prefix="$PREFIX" \
    --disable-shared --enable-static \
    --without-sfst --with-openfst --without-openfst-log \
    --without-foma --without-xfsm --without-readline \
    --enable-proc \
    CC="$CC" CXX="$CXX" AR="$AR" RANLIB="$RANLIB" \
    CPPFLAGS="-I$PREFIX/include -I$SCRIPT_DIR/shims" \
    LDFLAGS="-L$PREFIX/lib $LDFLAGS" \
    PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig" \
    ICU_CONFIG="$PREFIX/bin/icu-config"
  make -j"$JOBS"
  make install
  popd >/dev/null
}

build_cg3() {
  banner "cg3 (GPLv3)"
  local src="$SCRIPT_DIR/cg3"
  [ -d "$src" ] || git clone --depth 1 https://github.com/GrammarSoft/cg3.git "$src"
  [ -f "$PREFIX/include/rapidjson/rapidjson.h" ] || build_rapidjson
  # cg3 doesn't vendor boost; its get-boost.sh fetches 1.65.1 into include/boost/.
  # CI starts from a clean clone, so run it if the headers aren't already there.
  if [ ! -f "$src/include/boost/version.hpp" ]; then
    banner "cg3 — fetching vendored Boost 1.65.1"
    (cd "$src" && sh ./get-boost.sh)
  fi
  mkdir -p "$BUILD/cg3"
  "$CMAKE" -S "$src" -B "$BUILD/cg3" "${CMAKE_COMMON[@]}" \
    -DUSE_TCMALLOC=OFF -DMASTER_PROJECT=ON \
    -DENABLE_PROFILING=OFF \
    -DRapidJSON_DIR="$PREFIX/lib/cmake/RapidJSON" \
    -DBOOST_ROOT="$src/include" \
    -DBoost_NO_SYSTEM_PATHS=ON \
    -DBoost_INCLUDE_DIR="$src/include" \
    -DICU_ROOT="$PREFIX" \
    -DCMAKE_CXX_FLAGS="$CXXFLAGS -I$SCRIPT_DIR/shims" \
    -DCMAKE_C_FLAGS="$CFLAGS -I$SCRIPT_DIR/shims"
  "$NINJA" -C "$BUILD/cg3" install
}

# -----------------------------------------------------------------------------
# Orchestration
# -----------------------------------------------------------------------------

case "${1:-all}" in
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
  deps)      build_utfcpp; build_pcre2; build_libxml2; build_icu ;;
  all)       build_utfcpp; build_pcre2; build_libxml2; build_icu
             build_lttoolbox; build_apertium; build_lex_tools
             build_recursive; build_separable; build_anaphora
             build_cg3; build_openfst; build_hfst ;;
  *)         echo "usage: $0 [utfcpp|pcre2|xml2|icu|lttoolbox|apertium|cg3|openfst|hfst|deps|all]"
             exit 1 ;;
esac
