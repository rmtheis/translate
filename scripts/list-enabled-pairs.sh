#!/usr/bin/env bash
# Extract the set of ENABLED pair package names from PairCatalog.java.
#
# Output: one pair per line, bare mode name (e.g. "eng-spa"), suitable for
#   while read pair; do android/native/prep-pair.sh "$pair"; done
set -euo pipefail

# Resolve the default catalog path relative to this script's location so
# callers from anywhere in the tree (or its parents) get a stable answer.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CATALOG="${1:-$REPO_ROOT/android/app/src/main/java/com/qvyshift/translate/PairCatalog.java}"

# Every trunk/staging pair literal in the file.
grep -oE 'new Pair\("apertium-[a-z]+-[a-z]+"[^)]*Tier\.(TRUNK|STAGING)' "$CATALOG" \
  | grep -oE 'apertium-[a-z]+-[a-z]+' \
  | sort -u \
  | sed 's/^apertium-//'
