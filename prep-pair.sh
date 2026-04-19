#!/usr/bin/env bash
# prep-pair.sh <pair-name>
#
# Fetch the apertium-<pair>.deb from apertium.projectjj.com (bookworm), extract the
# pair's data files + mode definitions, and pack them into a flat JAR under
# apertium-android/app/src/main/assets/pairs/ so installBundledPairs() picks it up
# on next launch. Mode files reference /usr/share/apertium/... absolute paths which
# NativePipeline rewrites to the on-device pair base dir at runtime.
set -euo pipefail

PAIR="${1:?usage: $0 <pair> e.g. spa-cat}"
PKG="apertium-$PAIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Default output is a flat staging dir shared with CI; override with PAIRS_DIR env.
PAIRS_DIR="${PAIRS_DIR:-$SCRIPT_DIR/../pair-jars}"
WORK="$SCRIPT_DIR/build/pairs/$PAIR"

mkdir -p "$WORK" "$PAIRS_DIR"

URL_SUFFIX=$(curl -sL "http://apertium.projectjj.com/apt/nightly/dists/bookworm/main/binary-amd64/Packages" \
  | awk "/^Package: $PKG\$/,/^\$/" | grep '^Filename:' | awk '{print $2}')

if [ -z "$URL_SUFFIX" ]; then
  echo "no Debian package found for $PKG" >&2
  exit 1
fi

echo "fetching $URL_SUFFIX"
curl -sSL -o "$WORK/pair.deb" "http://apertium.projectjj.com/apt/nightly/$URL_SUFFIX"

cd "$WORK"
rm -rf usr control.tar.* data.tar.* debian-binary
ar x pair.deb
tar xf data.tar.*

rm -rf jar
mkdir jar
cp -a "usr/share/apertium/$PKG/." jar/
# Modes live under /usr/share/apertium/modes/, named by the mode id; grab anything that
# references this package's data dir (cheap and deterministic: every .mode from the deb
# belongs to this pair).
if compgen -G "usr/share/apertium/modes/*.mode" > /dev/null; then
  cp usr/share/apertium/modes/*.mode jar/
fi

cd jar
OUT="$PAIRS_DIR/$PKG.jar"
rm -f "$OUT"
zip -qr "$OUT" .

echo "packed: $OUT  ($(stat -f %z "$OUT") bytes, $(ls | wc -l | tr -d ' ') files)"
