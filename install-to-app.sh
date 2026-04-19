#!/usr/bin/env bash
# Package the cross-compiled binaries + shared libs into the app's jniLibs dir.
#
# Android will only extract files matching lib*.so into the app's native-lib dir
# at install time, and only files in that dir are guaranteed executable. So we
# rename every binary to lib<name>.so (underscores replacing hyphens) and strip
# ICU's .so.X version suffixes via patchelf.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${ABI:=arm64-v8a}"
: "${APP_DIR:=$SCRIPT_DIR/../apertium-android}"
SRC="$SCRIPT_DIR/out/$ABI"
DST="$APP_DIR/app/src/main/jniLibs/$ABI"
STRIP="${STRIP:-$SCRIPT_DIR/../../../Library/Android/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip}"
# Fall back to NDK from env if path above is wrong
[ -x "$STRIP" ] || STRIP="/Users/theis/Library/Android/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip"

rm -rf "$DST"
mkdir -p "$DST"

# -----------------------------------------------------------------------------
# Shared libs (strip + rewrite SONAMEs where needed)
# -----------------------------------------------------------------------------
declare -a SOVER_MAP=(
  "libicudata.so.76.1=libicudata.so"
  "libicuuc.so.76.1=libicuuc.so"
  "libicui18n.so.76.1=libicui18n.so"
  "libicuio.so.76.1=libicuio.so"
)
for spec in "${SOVER_MAP[@]}"; do
  src="${spec%%=*}"
  dst="${spec##*=}"
  cp "$SRC/lib/$src" "$DST/$dst"
  patchelf --set-soname "$dst" "$DST/$dst"
  "$STRIP" -s "$DST/$dst"
done

for simple in libxml2.so libpcre2-8.so liblttoolbox.so libcg3.so; do
  cp "$SRC/lib/$simple" "$DST/$simple"
  "$STRIP" -s "$DST/$simple"
done

# -----------------------------------------------------------------------------
# C++ stdlib. Android's libc++_shared.so needs to ship with the app.
# -----------------------------------------------------------------------------
CXX_SHARED="/Users/theis/Library/Android/sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/darwin-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"
cp "$CXX_SHARED" "$DST/libc++_shared.so"
"$STRIP" -s "$DST/libc++_shared.so"

# -----------------------------------------------------------------------------
# Pipeline binaries (rename hyphens to underscores, prefix lib, suffix .so,
# rewrite ICU DT_NEEDED entries).
# -----------------------------------------------------------------------------
TOOLS=(
  lt-proc
  apertium-tagger
  apertium-pretransfer
  apertium-posttransfer
  apertium-transfer
  apertium-interchunk
  apertium-postchunk
  lrx-proc
  lsx-proc
  rtx-proc
  cg-proc
)
for tool in "${TOOLS[@]}"; do
  src="$SRC/bin/$tool"
  dst="$DST/lib${tool//-/_}.so"
  [ -x "$src" ] || { echo "missing $src"; exit 1; }
  cp "$src" "$dst"
  "$STRIP" -s "$dst"
  for icu in icudata icuuc icui18n icuio; do
    patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$dst" || true
  done
done

echo
echo "installed to: $DST"
ls -la "$DST"
du -sh "$DST"
