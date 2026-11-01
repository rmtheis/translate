#!/usr/bin/env python3
"""
Create or update the Google Play store listings drafted in android/play/listings/.

For every <language>.json there, the listing's title, short description and full
description are written to the Play listing for that language. The full
description is composed by _listing_i18n.py: the listing's text, then the
localized pair list rendered from the pair inventory (default
.ci/prior-pair-inventory-android.json) between the same
<!-- AUTO-GENERATED LANGUAGES --> markers the en-US listing uses. Graphics and
screenshots are not touched; Play serves the default language's (en-US) images
to languages without their own.

Dry run by default: opens an edit, stages the listings, runs Play's validation on
the edit and then deletes it, so the texts are checked by the API without being
published. Pass --commit to commit the edit instead.

Environment:
  SA_JSON        — Play Developer API service-account JSON contents (as in
                   update-store-description.py), or
  SA_JSON_FILE   — path to that JSON (locally: the androidpublisher key listed in
                   ~/.claude/CLAUDE.md under "Google Play / App Store reviews")
  PACKAGE_NAME   — defaults to com.qvyshift.translate

Usage:
  python3 scripts/play_upload_listings.py [--inventory FILE] [--languages ca,da-DK]
      [--render-dir DIR] [--commit]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _listing_i18n import check_lengths, load_listings, load_names, play_full_description  # noqa: E402
from _pair_catalog import load as load_catalog  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent
LISTINGS = REPO / "android/play/listings"
DEFAULT_INVENTORY = REPO / ".ci/prior-pair-inventory-android.json"
CAPS = {"title": 30, "shortDescription": 80, "fullDescription": 4000}


def service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-auth google-api-python-client")
    raw = os.environ.get("SA_JSON")
    path = os.environ.get("SA_JSON_FILE")
    if raw:
        info = json.loads(raw)
    elif path:
        info = json.loads(pathlib.Path(path).expanduser().read_text())
    else:
        sys.exit("ERROR: set SA_JSON (contents) or SA_JSON_FILE (path)")
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/androidpublisher"])
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inventory", type=pathlib.Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--languages", help="comma-separated subset of listing languages")
    ap.add_argument("--render-dir", type=pathlib.Path,
                    help="write the composed full description of every language here")
    ap.add_argument("--commit", action="store_true", help="commit the Play edit")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    names, catalog = load_names(), load_catalog()
    listings = load_listings(LISTINGS, "language")
    if args.languages:
        want = set(args.languages.split(","))
        listings = [l for l in listings if l["language"] in want]
    bodies: dict[str, dict] = {}
    for listing in listings:
        body = {"language": listing["language"], "title": listing["title"],
                "shortDescription": listing["shortDescription"],
                "fullDescription": play_full_description(listing, inventory, names, catalog)}
        check_lengths(listing["language"], CAPS, body)
        bodies[listing["language"]] = body
        if args.render_dir:
            args.render_dir.mkdir(parents=True, exist_ok=True)
            (args.render_dir / f"{listing['language']}.txt").write_text(
                f"title: {body['title']}\nshortDescription: {body['shortDescription']}\n\n"
                f"{body['fullDescription']}\n")
    print(f"{len(bodies)} listing(s) composed from {args.inventory.name} ({len(inventory)} pairs)"
          + (f"; rendered to {args.render_dir}" if args.render_dir else ""))

    pkg = os.environ.get("PACKAGE_NAME", "com.qvyshift.translate")
    svc = service()
    edit_id = svc.edits().insert(packageName=pkg, body={}).execute()["id"]
    try:
        existing = {l["language"]: l for l in
                    svc.edits().listings().list(packageName=pkg, editId=edit_id).execute()
                    .get("listings", [])}
        print(f"existing Play listing languages: {sorted(existing)}")
        for lang, body in bodies.items():
            cur = existing.get(lang)
            same = cur and all(cur.get(k) == body[k] for k in ("title", "shortDescription", "fullDescription"))
            if same:
                print(f"  {lang}: up to date")
                continue
            print(f"  {lang}: {'update' if cur else 'create'}")
            svc.edits().listings().update(packageName=pkg, editId=edit_id, language=lang,
                                          body=body).execute()
        svc.edits().validate(packageName=pkg, editId=edit_id).execute()
        print("edit validated by Play")
        if args.commit:
            svc.edits().commit(packageName=pkg, editId=edit_id).execute()
            print(f"committed: {len(bodies)} listing(s) on {pkg}")
        else:
            svc.edits().delete(packageName=pkg, editId=edit_id).execute()
            print("dry run — edit deleted, nothing published. Re-run with --commit to apply.")
    except Exception:
        try:
            svc.edits().delete(packageName=pkg, editId=edit_id).execute()
        finally:
            raise


if __name__ == "__main__":
    main()
