#!/usr/bin/env bash
# Assemble app/src/main/jniLibs/<abi>/ from pre-built apertium-native out/ trees,
# mirroring apertium-native/install-to-app.sh but parameterized so CI can run it
# against artifacts downloaded from a prior workflow job.
#
# Usage:
#   ./scripts/install-natives.sh <abi> <path-to-apertium-native-out-root>
#
# where <path-to-apertium-native-out-root> contains bin/ and lib/ (the install
# prefix produced by build.sh).
set -euo pipefail

ABI="${1:?usage: $0 <abi> <out-root>}"
SRC="${2:?usage: $0 <abi> <out-root>}"
DST="app/src/main/jniLibs/$ABI"
NDK="${ANDROID_NDK_HOME:-$ANDROID_NDK_ROOT}"

case "$ABI" in
  arm64-v8a)   NDK_ABI_DIR=aarch64-linux-android ;;
  armeabi-v7a) NDK_ABI_DIR=arm-linux-androideabi ;;
  *) echo "unsupported ABI: $ABI"; exit 1 ;;
esac

STRIP="$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip"
[ -x "$STRIP" ] || STRIP="$NDK/toolchains/llvm/prebuilt/darwin-x86_64/bin/llvm-strip"

rm -rf "$DST"
mkdir -p "$DST"

# ICU libs: strip version suffix from SONAME + copy under plain lib*.so
for spec in \
  "libicudata.so.76.1=libicudata.so" \
  "libicuuc.so.76.1=libicuuc.so" \
  "libicui18n.so.76.1=libicui18n.so" \
  "libicuio.so.76.1=libicuio.so"; do
  src="${spec%%=*}"; dst="${spec##*=}"
  cp "$SRC/lib/$src" "$DST/$dst"
  patchelf --set-soname "$dst" "$DST/$dst"
  for icu in icudata icuuc icui18n icuio; do
    patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$DST/$dst" 2>/dev/null || true
  done
  "$STRIP" -s "$DST/$dst"
done

for simple in libxml2.so libpcre2-8.so liblttoolbox.so libcg3.so; do
  cp "$SRC/lib/$simple" "$DST/$simple"
  "$STRIP" -s "$DST/$simple"
  for icu in icudata icuuc icui18n icuio; do
    patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$DST/$simple" 2>/dev/null || true
  done
done

cp "$NDK/toolchains/llvm/prebuilt/$(uname | tr 'A-Z' 'a-z')-x86_64/sysroot/usr/lib/$NDK_ABI_DIR/libc++_shared.so" "$DST/libc++_shared.so"
"$STRIP" -s "$DST/libc++_shared.so"

TOOLS=(
  lt-proc apertium-tagger apertium-pretransfer apertium-posttransfer
  apertium-transfer apertium-interchunk apertium-postchunk apertium-anaphora
  lrx-proc lsx-proc rtx-proc cg-proc
)
for tool in "${TOOLS[@]}"; do
  src="$SRC/bin/$tool"
  dst="$DST/lib${tool//-/_}.so"
  [ -x "$src" ] || { echo "missing $src"; exit 1; }
  cp "$src" "$dst"
  "$STRIP" -s "$dst"
  for icu in icudata icuuc icui18n icuio; do
    patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$dst" 2>/dev/null || true
  done
done

echo "jniLibs populated at $DST"
du -sh "$DST"
