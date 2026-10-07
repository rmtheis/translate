#!/usr/bin/env python3
"""
Replace the App Store screenshots of an EDITABLE iOS version with the PNGs in
screenshots/ (written by scripts/screenshots-ios.sh):

  screenshots/appstore-iphone-69/*.png  -> APP_IPHONE_67          (6.9", 1320x2868)
  screenshots/appstore-ipad-13/*.png    -> APP_IPAD_PRO_3GEN_129  (13", 2064x2752)

CI never uploads screenshots, and ASC copies the previous version's sets into
a new version, so new screenshots must reach the editable version before it's
submitted: create it with asc_create_version.py (the release workflow reuses
an editable version with the same versionString), run this, then dispatch.

For each localization of the version that already has a set of a display
type, plus the app's primary locale, the set's screenshots are deleted and
the new files uploaded in filename order. Other display types and other
locales are left alone. Each upload is reserved, PUT in the chunks ASC asks
for, committed with its MD5, and polled until ASC reports it COMPLETE. Never
touches a version that isn't editable.

Environment (same as asc_create_version.py):
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_P8 (the .p8 contents)
  ASC_BUNDLE_ID   — defaults to com.qvyshift.translate

Usage:
  python3 scripts/asc_upload_screenshots.py --version 1.0.7 [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    import jwt
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")

ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
REPO = Path(__file__).resolve().parent.parent
SETS = {
    "APP_IPHONE_67": REPO / "screenshots/appstore-iphone-69",
    "APP_IPAD_PRO_3GEN_129": REPO / "screenshots/appstore-ipad-13",
}
# Matches asc_create_version.py / asc_resubmit.py.
EDITABLE_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"ERROR: ${name} not set")
    return val


class Asc:
    def __init__(self, key_id: str, issuer_id: str, pem: str):
        now = int(time.time())
        self.token = jwt.encode(
            {"iss": issuer_id, "iat": now, "exp": now + 20 * 60,
             "aud": "appstoreconnect-v1"},
            pem, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"})

    def call(self, method: str, path: str, params: dict | None = None,
             body: dict | None = None) -> dict:
        url = ASC_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",[]")
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            sys.exit(f"HTTP {e.code} {e.reason} on {method} {path}\n{detail}")


def find_app(asc: Asc, bundle_id: str) -> dict:
    # filter[bundleId] is a prefix match, so check the exact id.
    rows = asc.call("GET", "/apps", {"filter[bundleId]": bundle_id, "limit": "50"})["data"]
    rows = [r for r in rows if r["attributes"]["bundleId"] == bundle_id]
    if not rows:
        sys.exit(f"ERROR: no App Store Connect app with bundleId={bundle_id}")
    return rows[0]


def find_version(asc: Asc, app_id: str, version_string: str) -> dict:
    rows = asc.call("GET", f"/apps/{app_id}/appStoreVersions",
                    {"filter[platform]": "IOS",
                     "filter[versionString]": version_string, "limit": "5"})["data"]
    if not rows:
        sys.exit(f"ERROR: no iOS version {version_string}; create it with "
                 f"ASC_VERSION_STRING={version_string} scripts/asc_create_version.py")
    version = rows[0]
    state = version["attributes"]["appStoreState"]
    if state not in EDITABLE_STATES:
        sys.exit(f"ERROR: version {version_string} is {state}, not editable")
    return version


def put_chunks(operations: list[dict], data: bytes) -> None:
    for op in operations:
        chunk = data[op["offset"]:op["offset"] + op["length"]]
        headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
        req = urllib.request.Request(op["url"], method=op["method"],
                                     headers=headers, data=chunk)
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()


def upload(asc: Asc, set_id: str, path: Path) -> str:
    data = path.read_bytes()
    shot = asc.call("POST", "/appScreenshots", body={"data": {
        "type": "appScreenshots",
        "attributes": {"fileName": path.name, "fileSize": len(data)},
        "relationships": {"appScreenshotSet": {
            "data": {"type": "appScreenshotSets", "id": set_id}}}}})["data"]
    put_chunks(shot["attributes"]["uploadOperations"], data)
    asc.call("PATCH", f"/appScreenshots/{shot['id']}", body={"data": {
        "type": "appScreenshots", "id": shot["id"],
        "attributes": {"uploaded": True,
                       "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
    return shot["id"]


def wait_complete(asc: Asc, shot_ids: list[str], timeout: int = 600) -> None:
    pending = set(shot_ids)
    deadline = time.time() + timeout
    while pending:
        for sid in sorted(pending):
            attrs = asc.call("GET", f"/appScreenshots/{sid}",
                             {"fields[appScreenshots]": "assetDeliveryState,fileName"}
                             )["data"]["attributes"]
            state = (attrs.get("assetDeliveryState") or {}).get("state")
            if state == "COMPLETE":
                pending.discard(sid)
            elif state == "FAILED":
                errors = attrs["assetDeliveryState"].get("errors")
                sys.exit(f"ERROR: ASC rejected {attrs.get('fileName')}: {errors}")
        if pending:
            if time.time() > deadline:
                sys.exit(f"ERROR: {len(pending)} screenshot(s) still processing "
                         f"after {timeout}s")
            time.sleep(5)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", required=True, help="versionString, e.g. 1.0.7")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be replaced; change nothing")
    args = ap.parse_args()

    files = {t: sorted(d.glob("*.png")) for t, d in SETS.items()}
    for display_type, paths in files.items():
        if not paths:
            sys.exit(f"ERROR: no PNGs in {SETS[display_type]}")

    asc = Asc(_env("ASC_KEY_ID"), _env("ASC_ISSUER_ID"), _env("ASC_P8"))
    app = find_app(asc, _env("ASC_BUNDLE_ID", "com.qvyshift.translate"))
    version = find_version(asc, app["id"], args.version)
    primary = app["attributes"]["primaryLocale"]
    print(f"{app['attributes']['name']} {args.version} "
          f"({version['attributes']['appStoreState']})")

    locs = asc.call("GET", f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations",
                    {"limit": "200"})["data"]
    for loc in locs:
        locale = loc["attributes"]["locale"]
        existing = {s["attributes"]["screenshotDisplayType"]: s for s in asc.call(
            "GET", f"/appStoreVersionLocalizations/{loc['id']}/appScreenshotSets",
            {"limit": "50", "include": "appScreenshots"})["data"]}
        for display_type, paths in files.items():
            st = existing.get(display_type)
            if st is None and locale != primary:
                continue
            old = [r["id"] for r in (st or {}).get("relationships", {})
                   .get("appScreenshots", {}).get("data") or []]
            print(f"  {locale} {display_type}: replace {len(old)} with {len(paths)}")
            if args.dry_run:
                continue
            if st is None:
                st = asc.call("POST", "/appScreenshotSets", body={"data": {
                    "type": "appScreenshotSets",
                    "attributes": {"screenshotDisplayType": display_type},
                    "relationships": {"appStoreVersionLocalization": {
                        "data": {"type": "appStoreVersionLocalizations",
                                 "id": loc["id"]}}}}})["data"]
            for sid in old:
                asc.call("DELETE", f"/appScreenshots/{sid}")
            new_ids = [upload(asc, st["id"], p) for p in paths]
            wait_complete(asc, new_ids)
            order = [r["id"] for r in asc.call(
                "GET", f"/appScreenshotSets/{st['id']}/relationships/appScreenshots",
                {"limit": "50"})["data"]]
            if order != new_ids:
                sys.exit(f"ERROR: {locale} {display_type} set holds {order}, "
                         f"expected {new_ids}")
            print(f"    uploaded {len(new_ids)}, all COMPLETE, in filename order")


if __name__ == "__main__":
    main()
