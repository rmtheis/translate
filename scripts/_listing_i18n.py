"""Localized store-listing text shared by asc_upload_listings.py and
play_upload_listings.py.

A listing file (ios/appstore/listings/<locale>.json, android/play/listings/<lang>.json)
holds the human-written parts of one localization. The pair list is never written
by hand: it is rendered here from the pair inventory, with the language names
from scripts/language-names.json (CLDR, via gen-language-names.py), so a Catalan
description lists "Català ↔ Espanyol", not the English names.

Description layout, App Store (mirrors the en-US description that
update-appstore-description.py maintains):

    <description>\n\n<pairsHeading>\n\n<pairsSummary>\n\n• A ↔ B\n• ...

Play (mirrors the en-US full description that update-store-description.py maintains;
the markers are what that script splices between):

    <fullDescription>\n\n<!-- AUTO-GENERATED LANGUAGES START -->\n<pairsHeader>\n\n• A ↔ B\n• ...\n<!-- AUTO-GENERATED LANGUAGES END -->
"""
from __future__ import annotations

import json
import locale as _locale
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _pair_catalog import load as load_catalog  # noqa: E402

NAMES_PATH = HERE / "language-names.json"
PLAY_START = "<!-- AUTO-GENERATED LANGUAGES START -->"
PLAY_END = "<!-- AUTO-GENERATED LANGUAGES END -->"


def load_names() -> dict[str, dict[str, str]]:
    return json.loads(NAMES_PATH.read_text())["names"]


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


# Listing locale → POSIX locale for collation. Cyrillic "І" sorts before "А" in
# code-point order, so Ukrainian needs real collation; the others are close.
_COLLATE = {"ca": "ca_ES", "da": "da_DK", "da-DK": "da_DK", "fr-FR": "fr_FR", "fr-CA": "fr_CA",
            "hr": "hr_HR", "it": "it_IT", "it-IT": "it_IT", "no": "nb_NO", "no-NO": "nb_NO",
            "pt-BR": "pt_BR", "pt-PT": "pt_PT", "ro": "ro_RO", "ru": "ru_RU", "ru-RU": "ru_RU",
            "es-ES": "es_ES", "es-MX": "es_MX", "es-419": "es_MX", "sv": "sv_SE", "sv-SE": "sv_SE",
            "uk": "uk_UA"}


def sorted_for(listing_locale: str, labels) -> list[str]:
    """Sort with the locale's collation when the OS has it, else case-insensitively."""
    posix = _COLLATE.get(listing_locale)
    if posix:
        old = _locale.setlocale(_locale.LC_COLLATE)
        try:
            _locale.setlocale(_locale.LC_COLLATE, posix + ".UTF-8")
            return sorted(labels, key=_locale.strxfrm)
        except _locale.Error:
            pass
        finally:
            _locale.setlocale(_locale.LC_COLLATE, old)
    return sorted(labels, key=str.casefold)


def inventory_mb(inventory: list[dict]) -> int:
    # Android inventories carry "bytes"; the iOS pair-inventory.py output has
    # "bytes" too (the live en-US description's "0 MB" comes from a "sizeKb"
    # lookup in update-appstore-description.py).
    total = sum(e.get("bytes") or e.get("sizeKb", 0) * 1024 for e in inventory)
    return round(total / (1024 * 1024))


def appstore_description(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    lines = pair_lines(inventory, listing["locale"], names, catalog)
    summary = listing["pairsSummary"].format(n=len(lines), mb=inventory_mb(inventory))
    return (f"{listing['description'].rstrip()}\n\n{listing['pairsHeading']}\n\n"
            f"{summary}\n\n" + "\n".join(lines))


def play_full_description(listing: dict, inventory: list[dict], names, catalog=None) -> str:
    lines = pair_lines(inventory, listing["language"], names, catalog)
    header = listing["pairsHeader"].format(n=len(lines), mb=inventory_mb(inventory))
    block = f"{header}\n\n" + "\n".join(lines)
    return f"{listing['fullDescription'].rstrip()}\n\n{PLAY_START}\n{block}\n{PLAY_END}"


def load_listings(directory: pathlib.Path, key: str) -> list[dict]:
    out = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text())
        if data.get(key) != path.stem:
            sys.exit(f"ERROR: {path} has {key}={data.get(key)!r}, expected {path.stem!r}")
        out.append(data)
    if not out:
        sys.exit(f"ERROR: no listings in {directory}")
    return out


def check_lengths(where: str, fields: dict[str, int], data: dict) -> None:
    for field, cap in fields.items():
        value = data.get(field)
        if value and len(value) > cap:
            sys.exit(f"ERROR: {where}: {field} is {len(value)} chars (cap {cap})")
