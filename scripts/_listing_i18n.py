"""Localized store-listing text shared by asc_upload_listings.py and
play_upload_listings.py (the one-off uploads) and by asc_release_notes.py,
update-appstore-description.py and update-store-description.py (the release
workflows' per-release refresh).

A listing file (ios/appstore/listings/<locale>.json, android/play/listings/<lang>.json)
holds the human-written parts of one localization. The pair list is never written
by hand: it is rendered here from the pair inventory, with the language names
from scripts/language-names.json (CLDR, via gen-language-names.py), so a Catalan
description lists "Català ↔ Espanyol", not the English names.

Description layout, App Store (mirrors the en-US description, whose preamble
lives in App Store Connect and whose anchor is "Language pairs:"):

    <description>\n\n<pairsHeading>\n<appstore_pair_block()>
    where appstore_pair_block() = \n<pairsSummary>\n\n• A ↔ B\n• ...

update-appstore-description.py keeps everything after "<pairsHeading>\n" fresh
after a pair change; it never touches the preamble.

Play (mirrors the en-US full description; the markers are what
update-store-description.py splices between at every release):

    <fullDescription>\n\n<!-- AUTO-GENERATED LANGUAGES START -->\n<play_pair_block()>\n<!-- AUTO-GENERATED LANGUAGES END -->
    where play_pair_block() = <pairsHeader>\n\n• A ↔ B\n• ...
"""
from __future__ import annotations

import json
import pathlib
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _pair_catalog import load as load_catalog  # noqa: E402

NAMES_PATH = HERE / "language-names.json"
PLAY_START = "<!-- AUTO-GENERATED LANGUAGES START -->"
PLAY_END = "<!-- AUTO-GENERATED LANGUAGES END -->"


def load_names() -> dict[str, dict[str, str]]:
    return json.loads(NAMES_PATH.read_text())["names"]


def english_locale(tag: str) -> bool:
    """en-US, en-GB, en-AU, en-CA, ...: the store locales whose text is English.
    The release scripts post English release notes and the English pair list
    to these only; every other locale gets its own listing's text or nothing."""
    return tag.split("-")[0].split("_")[0].lower() == "en"


def language_name(iso3: str, locale: str, names: dict[str, dict[str, str]]) -> str:
    """CLDR name of an ISO 639-3 code in `locale`, first letter capitalized.
    A code the table doesn't know is an error: add it to gen-language-names.py."""
    table = names.get(locale)
    if table is None:
        sys.exit(f"ERROR: no language names for listing locale {locale!r} in {NAMES_PATH.name}; "
                 f"add it to LISTING_LOCALES in gen-language-names.py and regenerate")
    name = table.get(iso3.split("_")[0])
    if not name:
        sys.exit(f"ERROR: no {locale} name for language {iso3!r} in {NAMES_PATH.name}; "
                 f"add it to ISO3_TO_CLDR in gen-language-names.py and regenerate")
    return name[0].upper() + name[1:]


def pair_lines(inventory: list[dict], locale: str, names: dict[str, dict[str, str]],
               catalog: dict | None = None) -> list[str]:
    """One "• Source ↔ Target" line per pair, sorted by the localized label."""
    catalog = catalog if catalog is not None else load_catalog()
    labels = set()
    for entry in inventory:
        pkg = entry["pair"]
        parts = pkg.removeprefix("apertium-").split("-", 1)
        if len(parts) != 2:
            labels.add(pkg)
            continue
        left, right = (language_name(p, locale, names) for p in parts)
        one_way = (catalog.get(pkg) or {}).get("backward") is None and pkg in catalog
        labels.add(f"{left} {'→' if one_way else '↔'} {right}")
    return [f"• {label}" for label in sorted_for(locale, labels)]


# Collation of the pair lists. Platform-independent on purpose: the release
# workflows render the lists on ubuntu (Play) and macOS (App Store) runners and
# the upload scripts on a Mac, and locale.strxfrm gave each OS its own order —
# ubuntu runners have no fr_FR.UTF-8-style locales (code-point fallback: Ukrainian
# "І" before "А"), and macOS sorts Croatian Š between O and P. Letters compare
# case-insensitively with accents stripped, except the letters a language's
# alphabet treats as letters of their own, which _TAILORING places after the base
# letter they follow (and in order among themselves); the arrows are ignored.
# Checked 2026-11-01 against the Mac's order for every drafted locale: identical
# except hr, whose Š now follows S as Croatian sorts it. English locales keep the
# plain case-insensitive order of the live en-US list.
_AFTER = "\uffff"  # sorts after every letter
_TAILORING = {
    "uk": {"ґ": "г" + _AFTER, "є": "е" + _AFTER, "і": "и" + _AFTER, "ї": "и" + _AFTER * 2},
    "ru": {"ё": "е" + _AFTER},
    "hr": {"č": "c" + _AFTER, "ć": "c" + _AFTER * 2, "đ": "d" + _AFTER,
           "š": "s" + _AFTER, "ž": "z" + _AFTER},
    "ro": {"ă": "a" + _AFTER, "â": "a" + _AFTER * 2, "î": "i" + _AFTER,
           "ș": "s" + _AFTER, "ş": "s" + _AFTER, "ț": "t" + _AFTER, "ţ": "t" + _AFTER},
    "es": {"ñ": "n" + _AFTER},
    "da": {"æ": "z" + _AFTER, "ø": "z" + _AFTER * 2, "å": "z" + _AFTER * 3},
    "no": {"æ": "z" + _AFTER, "ø": "z" + _AFTER * 2, "å": "z" + _AFTER * 3},
    "sv": {"å": "z" + _AFTER, "ä": "z" + _AFTER * 2, "ö": "z" + _AFTER * 3},
}
_IGNORED = set("↔→•")


def collation_key(listing_locale: str):
    """Sort key for one label ("Català ↔ Italià") in the language of `listing_locale`."""
    tailoring = _TAILORING.get(listing_locale.split("-")[0].split("_")[0].lower(), {})

    def key(label: str) -> tuple[str, str]:
        out = []
        for ch in label.casefold():
            if ch in _IGNORED:
                continue
            if ch in tailoring:
                out.append(tailoring[ch])
                continue
            out.append("".join(c for c in unicodedata.normalize("NFD", ch)
                               if unicodedata.category(c) != "Mn"))
        return " ".join("".join(out).split()), label

    return key


def sorted_for(listing_locale: str, labels) -> list[str]:
    """Sort pair labels the way the locale's readers expect, the same on every OS."""
    if english_locale(listing_locale):
        return sorted(labels, key=str.casefold)
    return sorted(labels, key=collation_key(listing_locale))


def inventory_mb(inventory: list[dict]) -> int:
    # Both platforms' pair-inventory.py output carries "bytes". "sizeKb" is
    # what update-appstore-description.py summed until 2026-11-01 — the field
    # never existed, hence the "27 pairs, 0 MB on demand" in 1.0.7's live
    # en-US description.
    total = sum(e.get("bytes") or e.get("sizeKb", 0) * 1024 for e in inventory)
    return round(total / (1024 * 1024))


def appstore_pair_block(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    """Everything after the "<pairsHeading>\\n" anchor of an App Store description:
    a blank line, the localized summary, a blank line, the pair lines."""
    lines = pair_lines(inventory, listing["locale"], names, catalog)
    summary = listing["pairsSummary"].format(n=len(lines), mb=inventory_mb(inventory))
    return f"\n{summary}\n\n" + "\n".join(lines)


def appstore_description(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    return (f"{listing['description'].rstrip()}\n\n{listing['pairsHeading']}\n"
            + appstore_pair_block(listing, inventory, names, catalog))


def play_pair_block(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    """What sits between the Play markers: the localized header, a blank line,
    the pair lines."""
    lines = pair_lines(inventory, listing["language"], names, catalog)
    header = listing["pairsHeader"].format(n=len(lines), mb=inventory_mb(inventory))
    return f"{header}\n\n" + "\n".join(lines)


def play_full_description(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    block = play_pair_block(listing, inventory, names, catalog)
    return f"{listing['fullDescription'].rstrip()}\n\n{PLAY_START}\n{block}\n{PLAY_END}"


def load_listings(directory: pathlib.Path, key: str, required: bool = True) -> list[dict]:
    """Every <locale>.json in `directory`, each checked to name its own locale.
    The upload scripts need listings (required=True); the release scripts take
    an empty or missing directory as "no drafted locales" and then only serve
    the English localizations."""
    out = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        data = json.loads(path.read_text())
        if data.get(key) != path.stem:
            sys.exit(f"ERROR: {path} has {key}={data.get(key)!r}, expected {path.stem!r}")
        out.append(data)
    if not out and required:
        sys.exit(f"ERROR: no listings in {directory}")
    return out


def check_lengths(where: str, fields: dict[str, int], data: dict) -> None:
    for field, cap in fields.items():
        value = data.get(field)
        if value and len(value) > cap:
            sys.exit(f"ERROR: {where}: {field} is {len(value)} chars (cap {cap})")
