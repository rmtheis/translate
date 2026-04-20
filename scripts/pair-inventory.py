#!/usr/bin/env python3
"""Compute a deterministic inventory of bundled pair JARs.

Output: JSON sorted by pair name, one entry per JAR in the given directory:
    [{"pair": "apertium-eng-spa", "sha256": "...", "bytes": 12345,
      "version": "1.0.0~r12345"}, ...]

The "version" field comes from a sibling "<pair>.version" sidecar written by
apertium-native/prep-pair.sh when it repacks a Debian nightly. It's omitted
for JARs produced by older runs (or hand-built locally without the sidecar),
which lets scripts/release-notes.py distinguish real version bumps from
"we have no idea, just a hash change".

Used by the CI workflow to detect which pairs changed between monthly runs
and to drive release-notes + store-listing generation.
"""
import hashlib
import json
import sys
from pathlib import Path


def inventory(pairs_dir: Path) -> list[dict]:
    entries = []
    for jar in sorted(pairs_dir.glob("apertium-*.jar")):
        data = jar.read_bytes()
        entry = {
            "pair": jar.stem,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        version_file = jar.with_suffix(".version")
        if version_file.exists():
            v = version_file.read_text().strip()
            if v:
                entry["version"] = v
        entries.append(entry)
    return entries


if __name__ == "__main__":
    pairs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pair-jars")
    print(json.dumps(inventory(pairs_dir), indent=2))
