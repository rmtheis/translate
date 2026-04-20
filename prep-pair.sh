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

# Pull the Package block for this pair out of the Debian Packages index so we can
# capture both the download URL and the upstream Version field in one hop.
PKG_BLOCK=$(curl -sL "http://apertium.projectjj.com/apt/nightly/dists/bookworm/main/binary-amd64/Packages" \
  | awk "/^Package: $PKG\$/,/^\$/")
URL_SUFFIX=$(echo "$PKG_BLOCK" | awk '/^Filename:/ {print $2}')
VERSION=$(echo "$PKG_BLOCK" | awk '/^Version:/ {print $2}')

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

# Sidecar file read by scripts/pair-inventory.py to record the upstream Debian
# version alongside the content hash, so release-notes can show e.g.
# "Catalan ↔ Italian (2.1.0~r1234 → 2.1.0~r1245)".
echo -n "$VERSION" > "$PAIRS_DIR/$PKG.version"

# stat(1) takes different format flags on macOS vs. Linux; try each.
size_bytes=$(stat -c %s "$OUT" 2>/dev/null || stat -f %z "$OUT")
echo "packed: $OUT  ($size_bytes bytes, $(ls | wc -l | tr -d ' ') files, version=$VERSION)"
