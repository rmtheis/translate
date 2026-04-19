#!/usr/bin/env python3
"""Regenerate the "Languages" section of the Play Store listing's full description.

Reads the current pair inventory, resolves each pair's modes + display titles from
the app's PairCatalog, and prints a block suitable for splicing into the Play
listing under a "Included language pairs" heading.

Usage:
    ./scripts/store-listing.py current.json > listing.txt
"""
import json
import re
import sys
from pathlib import Path


ISO_NAMES = {
    "afr": "Afrikaans", "ara": "Arabic", "arg": "Aragonese", "ast": "Asturian",
    "bel": "Belarusian", "bul": "Bulgarian", "cat": "Catalan", "ces": "Czech",
    "crh": "Crimean Tatar", "dan": "Danish", "deu": "German", "ell": "Greek",
    "eng": "English", "epo": "Esperanto", "est": "Estonian", "eus": "Basque",
    "fao": "Faroese", "fin": "Finnish", "fra": "French", "gle": "Irish",
    "glg": "Galician", "haw": "Hawaiian", "hbs": "Serbo-Croatian", "heb": "Hebrew",
    "hin": "Hindi", "hrv": "Croatian", "hun": "Hungarian", "ind": "Indonesian",
    "isl": "Icelandic", "ita": "Italian", "jpn": "Japanese", "kat": "Georgian",
    "kaz": "Kazakh", "kir": "Kyrgyz", "kor": "Korean", "lat": "Latin",
    "lav": "Latvian", "lit": "Lithuanian", "mkd": "Macedonian", "mlt": "Maltese",
    "nld": "Dutch", "nno": "Norwegian Nynorsk", "nob": "Norwegian Bokmål",
    "nor": "Norwegian",
    "oci": "Occitan", "pol": "Polish", "por": "Portuguese", "ron": "Romanian",
    "rus": "Russian", "sco": "Scots", "slk": "Slovak", "slv": "Slovenian",
    "sme": "Northern Sami", "smn": "Inari Sami", "sma": "Southern Sami",
    "smj": "Lule Sami", "spa": "Spanish", "srd": "Sardinian", "swe": "Swedish",
    "tat": "Tatar", "tur": "Turkish", "ukr": "Ukrainian", "uzb": "Uzbek",
    "vie": "Vietnamese", "zho": "Chinese",
}


def language_name(iso: str) -> str:
    base = iso.split("_")[0]
    return ISO_NAMES.get(base, base)


def pair_label(pkg_name: str) -> str:
    # "apertium-eng-spa" → "English ↔ Spanish"
    parts = pkg_name.removeprefix("apertium-").split("-", 1)
    if len(parts) != 2:
        return pkg_name
    left, right = parts
    return f"{language_name(left)} ↔ {language_name(right)}"


def render(inventory: list[dict]) -> str:
    labels = sorted({pair_label(e["pair"]) for e in inventory})
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
