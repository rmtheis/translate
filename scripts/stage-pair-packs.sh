#!/usr/bin/env bash
# Materialize one on-demand asset-pack Gradle module per enabled pair, laying out
#
#   pair_<code>/
#     build.gradle
#     src/main/AndroidManifest.xml
#     src/main/assets/apertium-<pair>.jar   ← from $1 (source dir of prepped JARs)
#
# Usage: ./scripts/stage-pair-packs.sh <jar-source-dir>
#
# The JAR source dir is typically either:
#   - app/src/main/assets/pairs/  (historical flat layout — used for dev)
#   - a CI artifact download dir populated by apertium-native/prep-pair.sh
#
# Emits:
#   /tmp/pack-modules.txt — one ':pair_<code>' gradle coord per line, used to
#                           rewrite settings.gradle and app/build.gradle.
set -euo pipefail

SRC="${1:?usage: $0 <jar-source-dir>}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

./scripts/list-enabled-pairs.sh > /tmp/pairs.txt

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
