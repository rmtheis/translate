#!/usr/bin/env python3
"""Regenerate scripts/language-names.json: CLDR language names for the Apertium
languages the app ships, in every store-listing locale.

The committed JSON is what the listing scripts read (CI has no Babel). Re-run
after adding a pair whose language is missing from the table, or a listing
locale: `/usr/local/bin/python3 scripts/gen-language-names.py` (needs Babel:
`pip install babel`). Names come as CLDR gives them (lowercase in Romance and
Slavic languages); the renderer capitalizes the first letter of each name.
"""
from __future__ import annotations

import json
import pathlib
import sys

try:
    from babel import Locale
    import babel
except ImportError:
    sys.exit("pip install babel")

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "language-names.json"

# ISO 639-3 (pair package codes) → CLDR language subtag.
ISO3_TO_CLDR = {
    "arg": "an", "ast": "ast", "bel": "be", "cat": "ca", "dan": "da", "eng": "en",
    "fra": "fr", "glg": "gl", "hbs": "sh", "ita": "it", "mkd": "mk", "nno": "nn",
    "nob": "nb", "nor": "no", "oci": "oc", "por": "pt", "ron": "ro", "rus": "ru",
    "sme": "se", "spa": "es", "srd": "sc", "swe": "sv", "ukr": "uk",
}

# Store-listing locales (App Store and Play codes) → CLDR locale.
LISTING_LOCALES = {
    "en-US": "en", "en-GB": "en_GB", "en-AU": "en_AU", "en-CA": "en_CA",
    "ca": "ca", "da": "da", "da-DK": "da", "fr-FR": "fr", "fr-CA": "fr_CA",
    "hr": "hr", "it": "it", "it-IT": "it", "no": "nb", "no-NO": "nb",
    "pt-BR": "pt_BR", "pt-PT": "pt_PT", "ro": "ro", "ru": "ru", "ru-RU": "ru",
    "es-ES": "es", "es-MX": "es_MX", "es-419": "es_419", "sv": "sv", "sv-SE": "sv",
    "uk": "uk",
}


def main() -> None:
    table: dict[str, dict[str, str]] = {}
    for listing, cldr in LISTING_LOCALES.items():
        loc = Locale.parse(cldr)
        names = {}
        for iso3, sub in ISO3_TO_CLDR.items():
            name = loc.languages.get(sub)
            if not name:
                sys.exit(f"no CLDR name for {iso3} ({sub}) in {listing}")
            names[iso3] = name
        table[listing] = names
    OUT.write_text(json.dumps(
        {"_generated_by": "scripts/gen-language-names.py",
         "_cldr_source": f"Babel {babel.__version__}",
         "names": table},
        indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {OUT.relative_to(HERE.parent)}: {len(table)} locales × {len(ISO3_TO_CLDR)} languages")


if __name__ == "__main__":
    main()
