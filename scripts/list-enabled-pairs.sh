#!/usr/bin/env bash
# Extract the set of ENABLED pair package names from PairCatalog.java, honoring the
# HFST_EXCLUDED set so we don't try to prep pairs whose binaries can't be built yet.
#
# Output: one pair per line, bare mode name (e.g. "eng-spa"), suitable for
#   while read pair; do apertium-native/prep-pair.sh "$pair"; done
set -euo pipefail

CATALOG="${1:-app/src/main/java/com/qvyshift/translate/PairCatalog.java}"

# Read HFST_EXCLUDED set (currently a single-element singleton) to filter.
excluded=$(grep -oE 'HFST_EXCLUDED = [^;]*;' "$CATALOG" \
  | grep -oE '"apertium-[a-z]+-[a-z]+"' \
  | tr -d '"' \
  | sort -u)

# Every trunk/staging pair literal in the file, minus the excluded ones.
grep -oE 'new Pair\("apertium-[a-z]+-[a-z]+"[^)]*Tier\.(TRUNK|STAGING)' "$CATALOG" \
  | grep -oE 'apertium-[a-z]+-[a-z]+' \
  | sort -u \
  | comm -23 - <(echo "$excluded") \
  | sed 's/^apertium-//'
