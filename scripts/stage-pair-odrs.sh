#!/usr/bin/env bash
# Materialize On-Demand Resources pair folders for the Xcode build.
#
# For every apertium-<pair>.jar in $1, unzip into
#   TranslateIOS/PairResources/pair_<snake>/
# Xcode picks these up via project.yml, which tags each non-eng-spa
# folder with resourceTags: [pair_<snake>] for ODR delivery.
#
# Usage:
#   ./scripts/stage-pair-odrs.sh <dir-of-jars>
#
# Idempotent: existing directories are rewritten.
set -euo pipefail

SRC="${1:?usage: $0 <dir-of-jars>}"
# Resolve $SRC to an absolute path — the per-pair loop cd's into each
# destination dir before invoking unzip, which breaks relative jar paths.
SRC="$(cd "$SRC" && pwd)"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$REPO_ROOT/ios/PairResources"

mkdir -p "$OUT"

count=0
for jar in "$SRC"/apertium-*.jar; do
  [ -f "$jar" ] || continue
  pair=$(basename "$jar" .jar)      # apertium-eng-spa
  pkg="${pair#apertium-}"            # eng-spa
  snake="${pkg//-/_}"                # eng_spa
  dst="$OUT/pair_${snake}"
  rm -rf "$dst"
  mkdir -p "$dst"
  (cd "$dst" && unzip -oq "$jar")
  count=$((count + 1))
done

echo "staged $count pair folders under $OUT"
