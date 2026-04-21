#!/usr/bin/env bash
# Extract the set of ENABLED pair package names from PairCatalog.java.
#
# Output: one pair per line, bare mode name (e.g. "eng-spa"), suitable for
#   while read pair; do apertium-native/prep-pair.sh "$pair"; done
set -euo pipefail

CATALOG="${1:-app/src/main/java/com/qvyshift/translate/PairCatalog.java}"

# Every trunk/staging pair literal in the file.
grep -oE 'new Pair\("apertium-[a-z]+-[a-z]+"[^)]*Tier\.(TRUNK|STAGING)' "$CATALOG" \
  | grep -oE 'apertium-[a-z]+-[a-z]+' \
  | sort -u \
  | sed 's/^apertium-//'
