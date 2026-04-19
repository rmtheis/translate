#!/usr/bin/env python3
"""Regenerate the "Languages" section of the Play Store listing's full description.

Reads the current pair inventory and renders one line per pair with the proper
directional arrow (↔ for bidirectional, → for one-way-only pairs). Source of
truth for directionality is PairCatalog.java — see scripts/_pair_catalog.py.

Usage:
    ./scripts/store-listing.py current.json > listing.txt
"""
import json
import sys
from pathlib import Path

from _pair_catalog import load as load_catalog, pair_label


def render(inventory: list[dict]) -> str:
    catalog = load_catalog()
    labels = sorted({pair_label(e["pair"], catalog) for e in inventory})
    total_bytes = sum(e["bytes"] for e in inventory)
    header = (
        f"Included language pairs ({len(labels)} pairs, "
        f"{total_bytes // (1024 * 1024)} MB offline):"
    )
    body = "\n".join(f"• {label}" for label in labels)
    return f"{header}\n\n{body}"


if __name__ == "__main__":
    data = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else []
    print(render(data))
