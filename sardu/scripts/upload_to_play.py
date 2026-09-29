#!/usr/bin/env python3
"""Upload the Sardinian Translator release AAB to Google Play.

    python3 scripts/upload_to_play.py                    # DRAFT production release
    python3 scripts/upload_to_play.py --status completed \
        --release-notes-dir ~/Documents/app-store-optimization/stock-release-notes/behind-the-scenes
                                                         # straight to 100% (how sardu ships)
    python3 scripts/upload_to_play.py --rollout 0.05     # staged rollout instead

Build the AAB first (see README "Build / run" and "Google Play"). House rules:
production track only (no internal/staging); release notes are the stock
behind-the-scenes set or empty. Same shape as the other Qvyshift apps' uploaders
(e.g. ripcurrent/android/upload_to_play.py). Auth = the shared publisher OAuth
token at mines/android/.oauth_token.json.
"""

import argparse
import mimetypes
import pathlib
import sys
from pathlib import Path

PACKAGE = "com.qvyshift.sardu"
TRACK = "production"
AAB = Path(__file__).resolve().parent.parent / "app/build/outputs/bundle/release/app-release.aab"
TOKEN_FILE = Path.home() / "Documents/mines/android/.oauth_token.json"
SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]


def build_service():
    import json
    import socket
    socket.setdefaulttimeout(600)
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    with open(TOKEN_FILE) as f:
        creds = Credentials.from_authorized_user_info(json.load(f), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return build("androidpublisher", "v3", credentials=creds)


def _release_notes(dirname):
    """Read flat <locale>.txt files (the stock-release-notes layout) or
    <locale>/release_notes.txt subdirs into the API's releaseNotes list. Play
    ignores locales the listing doesn't have (sardu: en-US, it-IT)."""
    notes = []
    for entry in sorted(pathlib.Path(dirname).expanduser().iterdir()):
        sub = entry / "release_notes.txt"
        if entry.is_dir() and sub.exists():
            notes.append({"language": entry.name,
                          "text": sub.read_text(encoding="utf-8").strip()})
        elif entry.is_file() and entry.suffix == ".txt":
            notes.append({"language": entry.stem,
                          "text": entry.read_text(encoding="utf-8").strip()})
    if not notes:
        sys.exit(f"no release notes (<locale>.txt or <locale>/release_notes.txt) under {dirname}")
    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", default="draft", choices=["draft", "completed"],
                    help="release status to set on the track (default: draft)")
    ap.add_argument("--rollout", type=float, default=None, metavar="FRACTION",
                    help="publish as a staged rollout to this fraction of users "
                         "(e.g. 0.05). Overrides --status.")
    ap.add_argument("--release-notes-dir", default=None, metavar="DIR",
                    help="directory of <locale>.txt release notes (stock set)")
    args = ap.parse_args()

    if args.rollout is not None and not (0 < args.rollout <= 1):
        sys.exit(f"--rollout must be in (0, 1], got {args.rollout}")
    if not AAB.exists():
        sys.exit(f"AAB not found: {AAB} — run ./gradlew bundleRelease first")
    print(f"uploading {AAB.name} ({AAB.stat().st_size // 1024} KB) "
          f"to {PACKAGE} {TRACK} as {args.status if args.rollout is None else 'inProgress'}")

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    mimetypes.add_type("application/octet-stream", ".aab")
    service = build_service()
    eid = service.edits().insert(body={}, packageName=PACKAGE).execute()["id"]
    media = MediaFileUpload(str(AAB), mimetype="application/octet-stream", resumable=True)
    vc = service.edits().bundles().upload(
        editId=eid, packageName=PACKAGE, media_body=media).execute()["versionCode"]
    print(f"uploaded versionCode {vc}")

    release = {"versionCodes": [vc]}
    if args.rollout is not None:
        release["status"] = "inProgress"
        release["userFraction"] = args.rollout
    else:
        release["status"] = args.status
    if args.release_notes_dir:
        release["releaseNotes"] = _release_notes(args.release_notes_dir)
    service.edits().tracks().update(
        editId=eid, track=TRACK, packageName=PACKAGE,
        body={"releases": [release]}).execute()

    try:
        service.edits().commit(editId=eid, packageName=PACKAGE).execute()
    except HttpError as e:
        # Only when Play answers "Changes cannot be sent for review automatically"
        # (app in a rejected/review-hold state); then send for review in the console.
        if b"changesNotSentForReview" in e.content:
            service.edits().commit(editId=eid, packageName=PACKAGE,
                                   changesNotSentForReview=True).execute()
            print("committed with changesNotSentForReview=true — "
                  "send the changes for review from the Play Console")
        else:
            raise
    what = (f"inProgress @ {args.rollout:.0%}" if args.rollout is not None else args.status)
    print(f"done: {PACKAGE} versionCode {vc} on {TRACK} ({what})")


if __name__ == "__main__":
    main()
