#!/usr/bin/env python3
"""
Replace the Google Play phone screenshots and feature graphic of the listing
languages that have their own images in the repo:

  screenshots/play-phone/<language>/*.png   -> phoneScreenshots (1080x2400, filename order)
  android/play/feature_graphic_<language>.png -> featureGraphic  (1024x500)
  android/play/feature_graphic.png            -> featureGraphic of en-US

A language without a screenshots folder reuses en-US's live phone screenshots
when it is English (en-GB, en-AU, en-CA: downloaded from the listing in the
same edit) and is skipped otherwise, with a warning. Play shows the default
language's images to a language without its own, which is exactly what this
script exists to end: a non-English listing must not show English screenshots.

Per language and image type the edit does images.deleteall, then uploads the
files in order; the icon is never touched. Dry run by default: the images are
uploaded into an edit that is validated and then deleted, so Play checks every
file without publishing anything. --commit commits the edit instead.

Environment (same as play_upload_listings.py):
  SA_JSON or SA_JSON_FILE — Play Developer API service-account credentials
  PACKAGE_NAME            — defaults to com.qvyshift.translate

Usage:
  python3 scripts/play_upload_images.py [--languages ca,da-DK] [--no-feature-graphic]
      [--no-screenshots] [--commit]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import sys
import tempfile
import urllib.request

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from PIL import Image

socket.setdefaulttimeout(300)
REPO = pathlib.Path(__file__).resolve().parent.parent
SHOTS = REPO / "screenshots/play-phone"
PLAY = REPO / "android/play"
PHONE_SIZE = (1080, 2400)
FG_SIZE = (1024, 500)


def _service():
    raw = os.environ.get("SA_JSON")
    path = os.environ.get("SA_JSON_FILE")
    if raw:
        info = json.loads(raw)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/androidpublisher"])
    elif path:
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=["https://www.googleapis.com/auth/androidpublisher"])
    else:
        sys.exit("ERROR: set SA_JSON or SA_JSON_FILE")
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def _check(path: pathlib.Path, size: tuple[int, int]) -> None:
    with Image.open(path) as im:
        if im.size != size:
            sys.exit(f"ERROR: {path} is {im.size}, expected {size}")


def _upload(images, pkg, edit, language, image_type, path: pathlib.Path):
    # Play wants PNG or JPEG without alpha for the feature graphic; screenshots
    # may carry alpha, the captures are opaque anyway.
    media = MediaFileUpload(str(path), mimetype="image/png", resumable=False)
    return images().upload(packageName=pkg, editId=edit, language=language,
                           imageType=image_type, media_body=media).execute()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--languages", help="comma-separated Play language codes; default: "
                    "every language with a screenshots folder or feature graphic, "
                    "plus en-GB/en-AU/en-CA (which copy en-US's screenshots)")
    ap.add_argument("--no-feature-graphic", action="store_true")
    ap.add_argument("--no-screenshots", action="store_true")
    ap.add_argument("--commit", action="store_true", help="publish; default is a validated dry run")
    args = ap.parse_args()

    pkg = os.environ.get("PACKAGE_NAME", "com.qvyshift.translate")
    svc = _service()
    edits, images = svc.edits(), svc.edits().images

    edit = edits.insert(packageName=pkg, body={}).execute()["id"]
    try:
        live = {l["language"] for l in edits.listings().list(
            packageName=pkg, editId=edit).execute().get("listings", [])}
        shot_dirs = {d.name: sorted(d.glob("*.png")) for d in SHOTS.iterdir() if d.is_dir()} if SHOTS.exists() else {}
        fgs = {p.stem.replace("feature_graphic_", ""): p for p in PLAY.glob("feature_graphic_*.png")
               if p.stem != "feature_graphic_base"}  # the text-free base is not a language
        fgs["en-US"] = PLAY / "feature_graphic.png"
        english_copies = ["en-GB", "en-AU", "en-CA"]
        languages = (args.languages.split(",") if args.languages
                     else sorted(set(shot_dirs) | set(fgs) | set(english_copies)))
        missing = [l for l in languages if l not in live]
        if missing:
            sys.exit(f"ERROR: no Play listing for {missing}; create the listing first")

        # en-GB/en-AU/en-CA reuse en-US's live phone screenshots: fetch them once.
        en_us_files: list[pathlib.Path] = []
        if not args.no_screenshots and any(l in english_copies and l not in shot_dirs for l in languages):
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="play-en-us-"))
            for n, img in enumerate(images().list(packageName=pkg, editId=edit, language="en-US",
                                                  imageType="phoneScreenshots").execute().get("images", []), 1):
                p = tmp / f"{n:02d}.png"
                urllib.request.urlretrieve(img["url"] + "=s0", p)
                en_us_files.append(p)
            print(f"en-US live phone screenshots: {len(en_us_files)} (reused for the English languages)")

        verb = "upload" if args.commit else "would upload"
        for language in languages:
            plan: list[tuple[str, list[pathlib.Path]]] = []
            if not args.no_screenshots:
                files = shot_dirs.get(language) or (en_us_files if language in english_copies else [])
                if files:
                    for f in files:
                        _check(f, PHONE_SIZE)
                    plan.append(("phoneScreenshots", files))
                elif language != "en-US":
                    print(f"  {language}: WARNING no phone screenshots for this language — left as is")
            if not args.no_feature_graphic:
                fg = fgs.get(language) or (fgs["en-US"] if language in english_copies else None)
                if fg and fg.exists():
                    _check(fg, FG_SIZE)
                    plan.append(("featureGraphic", [fg]))
                elif language != "en-US":
                    print(f"  {language}: WARNING no feature graphic for this language — left as is")
            if not plan:
                continue
            print(f"  {language}: " + ", ".join(f"{verb} {len(fs)} {t}" for t, fs in plan))
            for image_type, files in plan:
                images().deleteall(packageName=pkg, editId=edit, language=language,
                                   imageType=image_type).execute()
                for f in files:
                    r = _upload(images, pkg, edit, language, image_type, f)
                    print(f"      {image_type} {f.name} -> {r.get('image', {}).get('id', '?')[:12]}")

        edits.validate(packageName=pkg, editId=edit).execute()
        print("edit validated by Play")
        if args.commit:
            try:
                edits.commit(packageName=pkg, editId=edit).execute()
            except HttpError as e:
                if e.resp.status == 400 and b"changesNotSentForReview" in e.content:
                    edits.commit(packageName=pkg, editId=edit, changesNotSentForReview=True).execute()
                    print("committed with changesNotSentForReview=true — send the changes for "
                          "review in the Play Console (Publishing overview)")
                else:
                    raise
            else:
                print(f"committed: images for {len(languages)} language(s) on {pkg}")
        else:
            edits.delete(packageName=pkg, editId=edit).execute()
            print("dry run — edit deleted, nothing published. Re-run with --commit to apply.")
    except BaseException:
        try:
            edits.delete(packageName=pkg, editId=edit).execute()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
