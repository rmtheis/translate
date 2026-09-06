#!/usr/bin/env bash
# Populate app/src/main/jniLibs/<abi>/ with UNSTRIPPED Apertium tools + libs from a
# native build output tree (android/native/out/<abi>, or the `natives-<abi>` artifact of
# the monorepo's release-android workflow: `gh run download <run> -n natives-<abi>`).
#
# Same renames as ../../scripts/install-natives-android.sh (tool -> lib<tool>.so, ICU
# soname de-versioning) but WITHOUT llvm-strip: AGP strips the libs when it packages the
# APK/AAB and, with `ndk.debugSymbolLevel` set in app/build.gradle, stores the symbols
# in the bundle (BUNDLE-METADATA/com.android.tools.build.debugsymbols) so Play can
# symbolicate native crashes. Nothing here is committed (jniLibs/ is gitignored).
#
# Usage: scripts/install-natives-unstripped.sh <abi> <out-root>
set -euo pipefail
ABI="${1:?usage: $0 <abi> <out-root>}"; SRC="${2:?usage: $0 <abi> <out-root>}"
HERE="$(cd "$(dirname "$0")" && pwd)"; DST="$HERE/../app/src/main/jniLibs/$ABI"
NDK="${ANDROID_NDK_HOME:-${NDK:-$HOME/Library/Android/sdk/ndk/28.2.13676358}}"
case "$ABI" in arm64-v8a) NDK_ABI_DIR=aarch64-linux-android ;; armeabi-v7a) NDK_ABI_DIR=arm-linux-androideabi ;; *) echo "unsupported ABI: $ABI"; exit 1 ;; esac
HOST=$(uname | tr 'A-Z' 'a-z')-x86_64
rm -rf "$DST"; mkdir -p "$DST"
for spec in libicudata.so.76.1=libicudata.so libicuuc.so.76.1=libicuuc.so libicui18n.so.76.1=libicui18n.so libicuio.so.76.1=libicuio.so; do
  src="${spec%%=*}"; dst="${spec##*=}"; cp "$SRC/lib/$src" "$DST/$dst"
  patchelf --set-soname "$dst" "$DST/$dst"
  for icu in icudata icuuc icui18n icuio; do patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$DST/$dst" 2>/dev/null || true; done
done
for simple in libxml2.so libpcre2-8.so liblttoolbox.so libcg3.so; do
  cp "$SRC/lib/$simple" "$DST/$simple"
  for icu in icudata icuuc icui18n icuio; do patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$DST/$simple" 2>/dev/null || true; done
done
cp "$NDK/toolchains/llvm/prebuilt/$HOST/sysroot/usr/lib/$NDK_ABI_DIR/libc++_shared.so" "$DST/libc++_shared.so"
TOOLS=(lt-proc apertium-tagger apertium-pretransfer apertium-posttransfer apertium-transfer apertium-interchunk apertium-postchunk apertium-anaphora lrx-proc lsx-proc rtx-proc cg-proc)
for tool in "${TOOLS[@]}"; do
  src="$SRC/bin/$tool"; dst="$DST/lib${tool//-/_}.so"; [ -x "$src" ] || { echo "missing $src"; exit 1; }
  cp "$src" "$dst"
  for icu in icudata icuuc icui18n icuio; do patchelf --replace-needed "lib${icu}.so.76" "lib${icu}.so" "$dst" 2>/dev/null || true; done
done
# hfst-proc is part of the monorepo's tool set but srd-ita doesn't use it; skipped to keep the AAB small.
echo "installed $(ls "$DST" | wc -l | tr -d ' ') unstripped libs into $DST ($(du -sh "$DST" | cut -f1))"
