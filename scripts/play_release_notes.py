#!/usr/bin/env python3
"""Write the Play "What's new" file of every listing language from the English notes.

    python3 scripts/play_release_notes.py whatsnew/whatsnew-en-US whatsnew [--dry-run]

release-android.yml writes the English notes first (the pair-inventory diff from
scripts/release-notes.py, or the stock "Behind-the-scenes changes to keep things
running smoothly." line with stock_notes=true) and then runs this, so that the
whatsNewDirectory r0adkll/upload-google-play reads holds one `whatsnew-<language>`
file per listing language. Play shows the default language's notes to every
language WITHOUT its own file, which is how 1.0.13 and 1.0.14 went out to the 18
other languages (back-filled on the track by hand on 2026-11-01). Same policy as
scripts/asc_release_notes.py on the iOS side:

  * en-US and the other English languages (en-GB, en-AU, en-CA): the English
    notes, verbatim;
  * every other language in android/play/listings/: its own stock line, the
    `whatsNew` of its listing JSON. The pair diff is never translated — that
    would be release-note wording nobody approved;
  * a non-English listing without `whatsNew` gets NO file and a warning: Play
    will show it English until the listing JSON is fixed. English text never
    goes into a non-English file; the script exits if it would.

Files are named `whatsnew-<language>` with no extension: the action reads the
whole suffix as the language code. Play caps release notes at 500 characters.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _listing_i18n import english_locale, load_listings  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
LISTINGS = REPO / "android/play/listings"
MAX_NOTES = 500  # Play's cap on a release's notes, per language.


def warn(msg: str) -> None:
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "WARNING: "
    print(prefix + msg, flush=True)


def text_for_language(language: str, english: str, by_language: dict[str, dict]) -> str | None:
    """The notes `language` gets: the English notes for an English language, the
    listing's own stock line otherwise, None when the listing has none."""
    if english_locale(language):
        return english
    listing = by_language.get(language)
    if listing is None:
        return None
    return (listing.get("whatsNew") or "").strip() or None


def english_texts(english: str, listings: list[dict]) -> set[str]:
    """Every text known to be English: the notes file and the English listings'
    stock line. No non-English language may receive one of these."""
    texts = {english}
    for listing in listings:
        if english_locale(listing["language"]) and listing.get("whatsNew"):
            texts.add(listing["whatsNew"].strip())
    return texts


def check_text(language: str, text: str, english: set[str]) -> None:
    if not english_locale(language) and text in english:
        sys.exit(f"ERROR: {language} would get English release notes ({text[:60]!r}). "
                 f"Fix whatsNew in {LISTINGS / (language + '.json')}.")
    if len(text) > MAX_NOTES:
        sys.exit(f"ERROR: {language} notes are {len(text)} chars (> Play cap {MAX_NOTES})")


def plan_texts(english: str, listings: list[dict]) -> dict[str, str]:
    """Language → text for en-US and every listing language that has a text.
    A non-English listing without whatsNew is left out, with a warning."""
    by_language = {l["language"]: l for l in listings}
    known_english = english_texts(english, listings)
    plan = {"en-US": english}
    for language in by_language:
        text = text_for_language(language, english, by_language)
        if text is None:
            warn(f"{language}: no whatsNew in {LISTINGS / (language + '.json')}; no notes "
                 f"file written, so Play will show it the en-US notes. Add the stock line.")
            continue
        check_text(language, text, known_english)
        plan[language] = text
    return plan


def write_files(plan: dict[str, str], out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for language, text in plan.items():
        path = out_dir / f"whatsnew-{language}"
        path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("notes_file", type=pathlib.Path, help="the English notes (whatsnew-en-US)")
    ap.add_argument("out_dir", type=pathlib.Path, help="the whatsNewDirectory to fill")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()

    english = args.notes_file.read_text(encoding="utf-8").strip()
    if not english:
        sys.exit(f"ERROR: {args.notes_file} is empty")
    listings = load_listings(LISTINGS, "language", required=False)
    plan = plan_texts(english, listings)
    for language, text in plan.items():
        print(f"{language:7s} {text.splitlines()[0][:90]}")
    if args.dry_run:
        print(f"(dry run) would write {len(plan)} files to {args.out_dir}")
        return
    written = write_files(plan, args.out_dir)
    print(f"wrote {len(written)} notes files to {args.out_dir}")


if __name__ == "__main__":
    main()
