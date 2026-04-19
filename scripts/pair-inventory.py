#!/usr/bin/env python3
"""Compute a deterministic inventory of bundled pair JARs.

Output: JSON sorted by pair name, one entry per JAR in the given directory:
    [{"pair": "apertium-eng-spa", "sha256": "...", "bytes": 12345}, ...]

Used by the CI workflow to detect which pairs changed between monthly runs
and to drive release-notes + store-listing generation.
"""
import hashlib
import json
import os
import sys
from pathlib import Path


def inventory(pairs_dir: Path) -> list[dict]:
    entries = []
    for jar in sorted(pairs_dir.glob("apertium-*.jar")):
        data = jar.read_bytes()
        entries.append({
            "pair": jar.stem,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        })
    return entries


if __name__ == "__main__":
    pairs_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("app/src/main/assets/pairs")
    print(json.dumps(inventory(pairs_dir), indent=2))
