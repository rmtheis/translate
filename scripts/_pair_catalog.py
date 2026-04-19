"""Shared parser for PairCatalog.java → {pkg: {"forward": "...", "backward": "..." | None}}.

Source-of-truth is the Java catalog; keeps release-notes.py and store-listing.py
from disagreeing on which pairs are one-way. A `null` backwardMode means the pair
only ships the forward direction — so we render it with `→`, not `↔`.
"""
from pathlib import Path
import re


CATALOG_PATH = Path(__file__).resolve().parent.parent / "app/src/main/java/com/qvyshift/translate/PairCatalog.java"

_PAIR_RE = re.compile(
    r'new Pair\('
    r'\s*"(?P<pkg>apertium-[a-z]+-[a-z]+)"\s*,'
    r'\s*"(?P<forward>[^"]+)"\s*,'
    r'\s*(?:"(?P<backward>[^"]+)"|null)\s*,',
)


def load(catalog_path: Path = CATALOG_PATH) -> dict[str, dict]:
    text = catalog_path.read_text()
    out: dict[str, dict] = {}
    for m in _PAIR_RE.finditer(text):
        out[m.group("pkg")] = {
            "forward": m.group("forward"),
            "backward": m.group("backward"),  # None when the regex matched `null`
        }
    return out


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
    return ISO_NAMES.get(iso.split("_")[0], iso)


def pair_label(pkg: str, catalog: dict[str, dict] | None = None) -> str:
    """Render a pair as "Foo ↔ Bar" if bidirectional, "Foo → Bar" if one-way."""
    c = catalog if catalog is not None else load()
    entry = c.get(pkg)
    parts = pkg.removeprefix("apertium-").split("-", 1)
    if len(parts) != 2:
        return pkg
    left_iso, right_iso = parts
    left, right = language_name(left_iso), language_name(right_iso)
    arrow = "→" if entry and entry.get("backward") is None else "↔"
    return f"{left} {arrow} {right}"
