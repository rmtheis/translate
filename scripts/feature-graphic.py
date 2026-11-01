#!/usr/bin/env python3
"""Render the Play feature graphics (1024x500) for every listing language.

The text-free base (background, faded 文A watermark, red logo) is
android/play/feature_graphic_base.png, reconstructed on 2026-11-01 from the
designer's en-US graphic. On top of it two lines are set in Helvetica Neue
with CoreText (ct_text.py from app-store-optimization/tools/feature-graphic,
so Cyrillic and any fallback script render with real fonts): the title in the
app's red, the subtitle in dark brown, both fitted into the Play safe box
x 100..924 (shrunk when a translation is longer than the English), baselines
where the original had them (y 376 and y 447).

Writes android/play/feature_graphic.png (en-US) and
android/play/feature_graphic_<language>.png for every other language in
TEXTS. en-GB/en-AU/en-CA reuse en-US's file (play_upload_images.py). Keep
the pair count in TEXTS in step with PairCatalog (27 pairs since 1.0.13).

Usage: /usr/local/bin/python3 scripts/feature-graphic.py [--check]
       (--check also writes the 16:9 crop Play web shows, next to each file,
        as feature_graphic_<language>.preview.png — look, then delete)
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from PIL import Image

sys.path.insert(0, str(pathlib.Path.home() / "Documents/app-store-optimization/tools/feature-graphic"))
import ct_text  # noqa: E402
import safe_zone  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
PLAY = REPO / "android/play"
BASE = PLAY / "feature_graphic_base.png"

FONT = "HelveticaNeue"
RED = (204, 0, 0)
BROWN = (52, 17, 0)
TITLE_SIZE, TITLE_BASELINE = 104, 376
SUB_SIZE, SUB_BASELINE = 46, 447
LEFT = safe_zone.SAFE_X          # 100
MAX_WIDTH = safe_zone.SAFE_BOX[2] - safe_zone.SAFE_X - 4   # 820: ink can overhang the advance width by a pixel or two

# Play language -> (title, subtitle). The subtitle counts the shipped pairs.
TEXTS = {
    "en-US": ("Offline Translation", "27 lesser-known language pairs"),
    "ca":    ("Traducció sense connexió", "27 parells de llengües poc coneguts"),
    "da-DK": ("Offline oversættelse", "27 mindre kendte sprogpar"),
    "es-ES": ("Traducción sin conexión", "27 pares de idiomas poco conocidos"),
    "es-419": ("Traducción sin conexión", "27 pares de idiomas poco conocidos"),
    "fr-FR": ("Traduction hors ligne", "27 paires de langues peu connues"),
    "fr-CA": ("Traduction hors ligne", "27 paires de langues peu connues"),
    "hr":    ("Prijevod bez interneta", "27 manje poznatih jezičnih parova"),
    "it-IT": ("Traduzione offline", "27 coppie di lingue poco conosciute"),
    "no-NO": ("Frakoblet oversettelse", "27 mindre kjente språkpar"),
    "pt-BR": ("Tradução off-line", "27 pares de idiomas pouco conhecidos"),
    "pt-PT": ("Tradução offline", "27 pares de línguas pouco conhecidos"),
    "ro":    ("Traducere offline", "27 de perechi de limbi mai puțin cunoscute"),
    "ru-RU": ("Офлайн-перевод", "27 малоизвестных языковых пар"),
    "sv-SE": ("Offlineöversättning", "27 mindre kända språkpar"),
    "uk":    ("Офлайн-переклад", "27 маловідомих мовних пар"),
}


def draw_line(canvas: Image.Image, text: str, max_size: int, baseline: int, color) -> int:
    size = ct_text.fit(text, FONT, max_size=max_size, max_width=MAX_WIDTH)
    img, base = ct_text.render(text, FONT, size, color)
    canvas.alpha_composite(img, (LEFT, int(round(baseline - base))))
    return size


def render(language: str, title: str, subtitle: str) -> pathlib.Path:
    canvas = Image.open(BASE).convert("RGBA")
    ts = draw_line(canvas, title, TITLE_SIZE, TITLE_BASELINE, RED)
    ss = draw_line(canvas, subtitle, SUB_SIZE, SUB_BASELINE, BROWN)
    out = PLAY / ("feature_graphic.png" if language == "en-US" else f"feature_graphic_{language}.png")
    canvas.convert("RGB").save(out, optimize=True)
    print(f"{language:7} title {ts:3}px  subtitle {ss:2}px  -> {out.relative_to(REPO)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="also write the 16:9 preview crops")
    ap.add_argument("--languages", help="comma-separated subset of TEXTS")
    args = ap.parse_args()
    langs = args.languages.split(",") if args.languages else list(TEXTS)
    for language in langs:
        title, subtitle = TEXTS[language]
        out = render(language, title, subtitle)
        if args.check:
            safe_zone.preview(str(out), str(out.with_suffix(".preview.png")))


if __name__ == "__main__":
    main()
