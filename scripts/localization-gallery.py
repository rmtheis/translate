#!/usr/bin/env python3
"""Render screenshots/localization-sample/index.html: one row per locale, the
Android and iOS captures side by side (main screen, then the open pair picker).

Reads whatever <locale>_main.png / <locale>_picker.png exist under
screenshots/localization-sample/{android,ios}/ and names each locale from
scripts/language-names.json (its own language, then English). Re-run after
adding captures; open the page with `open -a "Brave Browser" <path>`.

Usage: python3 scripts/localization-gallery.py
"""
from __future__ import annotations

import html
import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
ROOT = REPO / "screenshots/localization-sample"
NAMES = json.loads((REPO / "scripts/language-names.json").read_text())["names"]

# App locale → (language name in that language, English name, ISO 639-3 of the
# language, store codes). Codes: in-app (Android / iOS), App Store, Play.
LOCALES = {
    "ca":    ("català", "Catalan", "cat", "ca", "ca"),
    "da":    ("dansk", "Danish", "dan", "da", "da-DK"),
    "es-MX": ("español (México)", "Spanish (Mexico)", "spa", "es-MX", "es-419"),
    "es":    ("español (España)", "Spanish (Spain)", "spa", "es-ES", "es-ES"),
    "fr-CA": ("français (Canada)", "French (Canada)", "fra", "fr-CA", "fr-CA"),
    "fr":    ("français", "French", "fra", "fr-FR", "fr-FR"),
    "hr":    ("hrvatski", "Croatian", "hbs", "hr", "hr"),
    "it":    ("italiano", "Italian", "ita", "it", "it-IT"),
    "nb":    ("norsk bokmål", "Norwegian Bokmål", "nob", "no", "no-NO"),
    "pt-BR": ("português (Brasil)", "Portuguese (Brazil)", "por", "pt-BR", "pt-BR"),
    "pt-PT": ("português (Portugal)", "Portuguese (Portugal)", "por", "pt-PT", "pt-PT"),
    "ro":    ("română", "Romanian", "ron", "ro", "ro"),
    "ru":    ("русский", "Russian", "rus", "ru", "ru-RU"),
    "sv":    ("svenska", "Swedish", "swe", "sv", "sv-SE"),
    "uk":    ("українська", "Ukrainian", "ukr", "uk", "uk"),
    "en-GB": ("English (UK)", "English (UK)", "eng", "en-GB", "en-GB"),
    "en-AU": ("English (Australia)", "English (Australia)", "eng", "en-AU", "en-AU"),
    "en-CA": ("English (Canada)", "English (Canada)", "eng", "en-CA", "en-CA"),
}


def shots(platform: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for png in sorted((ROOT / platform).glob("*.png")):
        m = re.fullmatch(r"(.+)_(main|picker)", png.stem)
        if m:
            out.setdefault(m.group(1), {})[m.group(2)] = f"{platform}/{png.name}"
    return out


def main() -> None:
    android, ios = shots("android"), shots("ios")
    locales = [l for l in LOCALES if l in android or l in ios]
    locales += sorted((set(android) | set(ios)) - set(LOCALES))
    rows = []
    for loc in locales:
        native, english, iso3, asc, play = LOCALES.get(loc, (loc, loc, "", "", ""))
        cells = []
        for platform, table in (("Android", android), ("iOS", ios)):
            for scene, label in (("main", "translate screen"), ("picker", "pair picker")):
                src = table.get(loc, {}).get(scene)
                if src:
                    cells.append(f'<figure><a href="{src}"><img src="{src}" loading="lazy" '
                                 f'alt="{html.escape(english)} {platform} {label}"></a>'
                                 f'<figcaption>{platform} · {label}</figcaption></figure>')
                else:
                    cells.append(f'<figure class="missing"><div>no {platform} {label}</div></figure>')
        rows.append(
            f'<section id="{html.escape(loc)}"><h2><code>{html.escape(loc)}</code> '
            f'{html.escape(native)} <span>{html.escape(english)}'
            + (f' · App Store <code>{asc}</code> · Play <code>{play}</code>' if asc else '')
            + f'</span></h2><div class="row">{"".join(cells)}</div></section>')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Translate — localization sample</title>
<style>
  body {{ font: 15px/1.4 -apple-system, system-ui, sans-serif; margin: 0; padding: 24px; background: #f6f3ee; color: #222; }}
  h1 {{ margin: 0 0 4px; }} p.lead {{ margin: 0 0 24px; color: #555; }}
  section {{ margin-bottom: 36px; }}
  h2 {{ font-size: 18px; margin: 0 0 8px; }} h2 span {{ font-weight: normal; color: #666; font-size: 14px; }}
  code {{ background: #e9e4dc; padding: 1px 5px; border-radius: 4px; }}
  .row {{ display: flex; gap: 14px; overflow-x: auto; }}
  figure {{ margin: 0; flex: 0 0 auto; text-align: center; }}
  figure img {{ height: 560px; width: auto; border-radius: 14px; box-shadow: 0 2px 10px rgba(0,0,0,.18); background: #fff; }}
  figcaption {{ font-size: 12px; color: #666; margin-top: 4px; }}
  figure.missing div {{ height: 560px; width: 258px; border: 1px dashed #bbb; border-radius: 14px; display: grid; place-items: center; color: #999; font-size: 12px; }}
  nav a {{ margin-right: 10px; }}
</style></head><body>
<h1>Translate (Experimental) — localization sample</h1>
<p class="lead">Android: Medium Phone API 36 emulator, per-app locale, SysUI demo status bar. iOS: iPhone 16 Pro Max simulator (iOS 26.5), launched with <code>-AppleLanguages</code>. Click an image for full size.</p>
<nav>{" ".join(f'<a href="#{html.escape(l)}">{html.escape(l)}</a>' for l in locales)}</nav>
{"".join(rows)}
</body></html>
"""
    (ROOT / "index.html").write_text(page)
    print(f"wrote {ROOT / 'index.html'}: {len(locales)} locale rows "
          f"({sum(len(v) for v in android.values())} Android, {sum(len(v) for v in ios.values())} iOS captures)")


if __name__ == "__main__":
    main()
