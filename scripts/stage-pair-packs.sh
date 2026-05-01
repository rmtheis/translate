#!/usr/bin/env bash
# Materialize one on-demand asset-pack Gradle module per enabled pair, laying out
#
#   android/pair_<code>/
#     build.gradle
#     src/main/AndroidManifest.xml
#     src/main/assets/apertium-<pair>.jar   ← from $1 (source dir of prepped JARs)
#
# Usage: ./scripts/stage-pair-packs.sh <jar-source-dir>
#
# The JAR source dir is the artifact download path populated by
# android/native/prep-pair.sh; in CI that's <repo>/pair-jars/, in local dev
# it's wherever you ran prep-pair against. The path is resolved to an
# absolute path up front so this script can safely cd into android/ for
# its own work without affecting argv interpretation.
#
# Emits:
#   /tmp/pack-modules.txt — one ':pair_<code>' gradle coord per line, used to
#                           rewrite android/settings.gradle and
#                           android/app/build.gradle.
set -euo pipefail

SRC="${1:?usage: $0 <jar-source-dir>}"
# Resolve $SRC to an absolute path BEFORE cd-ing into android/ — otherwise a
# relative pair-jars/ argv (the CI default, with the artifact downloaded to
# the repo root) would resolve as android/pair-jars/ after the cd and every
# JAR lookup would miss. This regressed in the April 2026 monorepo reorg
# when this script gained the `cd "$REPO_ROOT/android"` below; the May 1
# scheduled run was the first failure.
if [ ! -d "$SRC" ]; then
  echo "stage-pair-packs.sh: source dir not found: $SRC" >&2
  exit 1
fi
SRC="$(cd "$SRC" && pwd)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/android"

../scripts/list-enabled-pairs.sh > /tmp/pairs.txt

: > /tmp/pack-modules.txt

while read pair; do
  jar="$SRC/apertium-${pair}.jar"
  if [ ! -f "$jar" ]; then
    echo "missing $jar"; exit 1
  fi
  pack_name="pair_${pair//-/_}"
  mod_dir="$pack_name"

  mkdir -p "$mod_dir/src/main/assets"
  cp "$jar" "$mod_dir/src/main/assets/apertium-${pair}.jar"

  cat > "$mod_dir/build.gradle" <<GRADLE
apply plugin: 'com.android.asset-pack'

assetPack {
    packName = "${pack_name}"
    dynamicDelivery {
        deliveryType = "on-demand"
    }
}
GRADLE

  cat > "$mod_dir/src/main/AndroidManifest.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:dist="http://schemas.android.com/apk/distribution"
    split="${pack_name}">
    <dist:module dist:type="asset-pack">
        <dist:fusing dist:include="true" />
        <dist:delivery>
            <dist:on-demand />
        </dist:delivery>
    </dist:module>
</manifest>
XML

  echo ":${pack_name}" >> /tmp/pack-modules.txt
done < /tmp/pairs.txt

echo "staged $(wc -l < /tmp/pack-modules.txt | tr -d ' ') asset-pack modules"
