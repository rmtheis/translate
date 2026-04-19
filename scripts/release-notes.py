#!/usr/bin/env python3
"""Generate Play Store release notes from a pair-inventory diff.

Inputs:
    prior.json    — inventory from the previous release (or {} on first run)
    current.json  — inventory from this build

Outputs (stdout): plain-text release notes <= 500 chars (Play's soft cap).
If the diff exceeds the cap, the note is abbreviated.
"""
import json
import sys
from pathlib import Path

from _pair_catalog import load as load_catalog, pair_label


MAX_CHARS = 500


def load(path: Path) -> dict[str, dict]:
    try:
        raw = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return {e["pair"]: e for e in raw}


def diff(prior: dict[str, dict], current: dict[str, dict]) -> dict[str, list]:
    added = sorted(p for p in current if p not in prior)
    removed = sorted(p for p in prior if p not in current)
    changed = sorted(
        p for p in current
        if p in prior and prior[p]["sha256"] != current[p]["sha256"]
    )
    return {"added": added, "removed": removed, "changed": changed}


def format_notes(d: dict[str, list], current: dict[str, dict], prior: dict[str, dict]) -> str:
    catalog = load_catalog()
    lines = []
    if d["added"]:
        lines.append("New: " + ", ".join(pair_label(p, catalog) for p in d["added"]))
    if d["removed"]:
        lines.append("Removed: " + ", ".join(pair_label(p, catalog) for p in d["removed"]))
    if d["changed"]:
        entries = []
        for p in d["changed"]:
            delta = current[p]["bytes"] - prior[p]["bytes"]
            sign = "+" if delta >= 0 else "-"
            entries.append(f"{pair_label(p, catalog)} ({sign}{abs(delta) // 1024}KB)")
        lines.append("Updated: " + ", ".join(entries))
    if not lines:
        lines.append("Internal improvements.")
    return "\n".join(lines)


def abbreviate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


if __name__ == "__main__":
    prior = load(Path(sys.argv[1])) if len(sys.argv) > 1 else {}
    current = load(Path(sys.argv[2])) if len(sys.argv) > 2 else {}
    notes = format_notes(diff(prior, current), current, prior)
    print(abbreviate(notes, MAX_CHARS))
