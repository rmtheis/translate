#!/usr/bin/env python3
"""Refresh the pair list in the Play full description of every listing language.

The Play Developer API has no partial update, so each listing is round-tripped
inside one edit: GET, replace the text between the marker comments

    <!-- AUTO-GENERATED LANGUAGES START -->
    <!-- AUTO-GENERATED LANGUAGES END -->

PUT; then one commit for all of them. Which language gets what:

  * the default language (en-US): the English block scripts/store-listing.py
    rendered into listing-languages.txt. If its description has no markers
    yet, the block is appended (the original bootstrap).
  * every other language: the block scripts/_listing_i18n.py renders from
    android/play/listings/<language>.json (its `pairsHeader`) and the CLDR
    names in scripts/language-names.json, so the Catalan listing says
    "Català ↔ Espanyol". The English block never goes into another language.
  * a language with no listing JSON, or whose description has no markers,
    is skipped with a warning: upload it with scripts/play_upload_listings.py
    first.

Titles, short descriptions and the text before the markers are not touched.

Usage:
    ./scripts/update-store-description.py listing-languages.txt pair-inventory.json
        [--render-dir DIR] [--dry-run]

--render-dir writes the composed full description of every drafted language
(<language>.txt; for en-US the markers plus block, since its preamble isn't in
the repo) before anything is fetched. --dry-run opens an edit, shows the planned
PUTs and deletes the edit instead of committing it.

Env:
    SA_JSON               Service-account JSON contents (PLAY_SERVICE_ACCOUNT_JSON in CI), or
    SA_JSON_FILE          path to that JSON (locally)
    PACKAGE_NAME          App package (defaults to com.qvyshift.translate)
    STORE_LANG            Default listing language that takes listing-languages.txt (en-US)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _listing_i18n import (PLAY_END as END, PLAY_START as START,  # noqa: E402
                           inventory_mb, load_listings, load_names,
                           play_full_description, play_pair_block)
from _pair_catalog import load as load_catalog  # noqa: E402

PLAY_API = "https://androidpublisher.googleapis.com/androidpublisher/v3"
MAX_DESC = 4000
REPO = Path(__file__).resolve().parent.parent
LISTINGS = REPO / "android/play/listings"


def warn(msg: str) -> None:
    """A GitHub Actions annotation on the runner, a plain WARNING elsewhere."""
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "WARNING: "
    print(prefix + msg, flush=True)


def sa_creds() -> dict:
    raw = os.environ.get("SA_JSON")
    path = os.environ.get("SA_JSON_FILE")
    if raw:
        return json.loads(raw)
    if path:
        return json.loads(Path(path).expanduser().read_text())
    sys.exit("ERROR: set SA_JSON (contents) or SA_JSON_FILE (path)")


def access_token(sa: dict) -> str:
    # JWT-based Google service-account auth. Avoid the full google-auth dep by
    # building the JWT inline.
    import base64
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        sys.exit("pip install cryptography")

    header = {"alg": "RS256", "typ": "JWT"}
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/androidpublisher",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=")
    signing_input = b64(header) + b"." + b64(claims)
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")

    resp = urllib.request.urlopen(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt.decode(),
        }).encode(),
    )
    return json.loads(resp.read())["access_token"]


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{PLAY_API}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method} {path}\n{e.read().decode()}")


# --- composing ---------------------------------------------------------------

def block_for(lang: str, default_lang: str, default_block: str, by_lang: dict[str, dict],
              inventory: list[dict], names, catalog) -> str | None:
    """The block between the markers for `lang`: the English block for the
    default language, the localized block for a drafted language, None (write
    nothing) for any other language."""
    if lang == default_lang:
        return default_block
    listing = by_lang.get(lang)
    if listing:
        return play_pair_block(listing, inventory, names, catalog)
    return None


def splice(existing: str, block: str, append: bool = False) -> str | None:
    """Replace the text between the markers with `block`. Without markers,
    append them (default language only, the original bootstrap) or return
    None so the caller skips the language."""
    if START in existing and END in existing:
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
        return pattern.sub(lambda _m: f"{START}\n{block}\n{END}", existing, count=1)
    if not append:
        return None
    sep = "\n\n" if existing.strip() else ""
    return f"{existing.rstrip()}{sep}{START}\n{block}\n{END}"


def render(render_dir: Path, default_lang: str, default_block: str, listings: list[dict],
           inventory: list[dict], names, catalog) -> None:
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / f"{default_lang}.txt").write_text(
        f"{START}\n{default_block}\n{END}\n", encoding="utf-8")
    for listing in listings:
        (render_dir / f"{listing['language']}.txt").write_text(
            play_full_description(listing, inventory, names, catalog) + "\n", encoding="utf-8")
    print(f"rendered {default_lang} and {len(listings)} drafted language(s) to {render_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("languages_block", type=Path,
                    help="the English block from scripts/store-listing.py (listing-languages.txt)")
    ap.add_argument("inventory", type=Path, help="pair-inventory.json of this build")
    ap.add_argument("--render-dir", type=Path,
                    help="write the composed full description of every language here")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the planned PUTs; delete the edit instead of committing")
    args = ap.parse_args()

    default_block = args.languages_block.read_text(encoding="utf-8").strip()
    if not default_block:
        sys.exit(f"ERROR: {args.languages_block} is empty")
    inventory = json.loads(args.inventory.read_text())
    pkg = os.environ.get("PACKAGE_NAME", "com.qvyshift.translate")
    default_lang = os.environ.get("STORE_LANG", "en-US")

    names, catalog = load_names(), load_catalog()
    listings = load_listings(LISTINGS, "language", required=False)
    by_lang = {l["language"]: l for l in listings if l["language"] != default_lang}
    # Render every drafted language up front: a missing language name in
    # language-names.json fails here, before the edit is opened.
    for listing in by_lang.values():
        play_pair_block(listing, inventory, names, catalog)
    print(f"{len(inventory)} pairs, {inventory_mb(inventory)} MB; {default_lang} plus "
          f"{len(by_lang)} drafted language(s)")
    if args.render_dir:
        render(args.render_dir, default_lang, default_block, list(by_lang.values()),
               inventory, names, catalog)

    token = access_token(sa_creds())
    edit_id = api("POST", f"/applications/{pkg}/edits", token, {})["id"]
    try:
        existing = {l["language"]: l for l in
                    api("GET", f"/applications/{pkg}/edits/{edit_id}/listings", token)
                    .get("listings", [])}
        print(f"Play listing languages: {sorted(existing)}")
        if default_lang not in existing:
            sys.exit(f"ERROR: no {default_lang} listing on {pkg}")

        updated = unchanged = skipped = 0
        for lang in sorted(existing):
            listing = existing[lang]
            block = block_for(lang, default_lang, default_block, by_lang, inventory, names, catalog)
            if block is None:
                warn(f"{lang}: no {LISTINGS.name}/{lang}.json — the English pair list never "
                     f"goes to another language; full description left as is")
                skipped += 1
                continue
            current = listing.get("fullDescription", "")
            new_description = splice(current, block, append=(lang == default_lang))
            if new_description is None:
                warn(f"{lang}: no AUTO-GENERATED LANGUAGES markers in the full description — "
                     f"upload the listing with play_upload_listings.py first; left as is")
                skipped += 1
                continue
            if len(new_description) > MAX_DESC:
                sys.exit(f"ERROR: {lang} full description would be {len(new_description)} chars "
                         f"(cap {MAX_DESC})")
            if new_description == current:
                print(f"  {lang}: pair list unchanged")
                unchanged += 1
                continue
            if args.dry_run:
                print(f"  {lang}: would PUT full description ({len(current)} → "
                      f"{len(new_description)} chars)")
                updated += 1
                continue
            listing["fullDescription"] = new_description
            api("PUT", f"/applications/{pkg}/edits/{edit_id}/listings/{lang}", token, listing)
            print(f"  {lang}: full description updated ({len(new_description)} chars)")
            updated += 1

        verb = "would update" if args.dry_run else "updated"
        print(f"{verb} the pair list of {updated} listing(s); "
              f"{unchanged} unchanged, {skipped} skipped")
        if args.dry_run:
            print("dry run — edit deleted, nothing published.")
        elif updated:
            api("POST", f"/applications/{pkg}/edits/{edit_id}:validate", token)
            api("POST", f"/applications/{pkg}/edits/{edit_id}:commit", token)
            print(f"committed edit {edit_id} on {pkg}")
        else:
            print("nothing to commit")
    finally:
        if args.dry_run:
            api("DELETE", f"/applications/{pkg}/edits/{edit_id}", token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
