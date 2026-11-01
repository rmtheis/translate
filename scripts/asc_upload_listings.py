#!/usr/bin/env python3
"""
Create or update the App Store localizations drafted in ios/appstore/listings/.

For every <locale>.json there:
  * appInfoLocalizations (name, subtitle, privacyPolicyUrl) on the app's EDITABLE
    appInfo — the one App Store Connect opens alongside an editable version;
  * appStoreVersionLocalizations (description, keywords, supportUrl, marketingUrl,
    promotionalText, whatsNew) on the editable version named by --version.
Existing localizations are PATCHed, missing ones POSTed; nothing is deleted. The
description is composed by _listing_i18n.py from the listing's text plus the
localized pair list rendered from the pair inventory (default
.ci/prior-pair-inventory-ios.json), so the list matches what the app ships.

Apple only accepts new localizations on a version that is still editable, so the
next version must exist first (ASC_VERSION_STRING=<next> scripts/asc_create_version.py,
<next> = the patch bump of CFBundleShortVersionString in ios/project.yml). The
localizations go live with that version.

Dry run by default: prints what would change and writes the composed texts to
--render-dir. Pass --commit to write to App Store Connect.

Environment (same as asc_create_version.py):
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_P8 (the .p8 contents)
  ASC_BUNDLE_ID — defaults to com.qvyshift.translate

Usage:
  python3 scripts/asc_upload_listings.py --version 1.0.8 [--inventory FILE]
      [--locales ca,da] [--render-dir DIR] [--commit]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import jwt
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _listing_i18n import (appstore_description, check_lengths, load_listings,  # noqa: E402
                           load_names)
from _pair_catalog import load as load_catalog  # noqa: E402

ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
REPO = pathlib.Path(__file__).resolve().parent.parent
LISTINGS = REPO / "ios/appstore/listings"
DEFAULT_INVENTORY = REPO / ".ci/prior-pair-inventory-ios.json"
EDITABLE_STATES = {"PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED",
                   "METADATA_REJECTED", "INVALID_BINARY"}
INFO_FIELDS = ("name", "subtitle", "privacyPolicyUrl")
VERSION_FIELDS = ("description", "keywords", "supportUrl", "marketingUrl",
                  "promotionalText", "whatsNew")
CAPS = {"name": 30, "subtitle": 30, "keywords": 100, "description": 4000,
        "promotionalText": 170, "whatsNew": 4000}


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"ERROR: ${name} not set")
    return val


class Asc:
    def __init__(self) -> None:
        now = int(time.time())
        self.token = jwt.encode(
            {"iss": _env("ASC_ISSUER_ID"), "iat": now, "exp": now + 20 * 60,
             "aud": "appstoreconnect-v1"},
            _env("ASC_P8"), algorithm="ES256",
            headers={"kid": _env("ASC_KEY_ID"), "typ": "JWT"})

    def call(self, method: str, path: str, params: dict | None = None,
             body: dict | None = None) -> dict:
        url = ASC_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params, safe=",[]")
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {self.token}"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            sys.exit(f"HTTP {e.code} {e.reason} on {method} {path}\n"
                     f"{e.read().decode('utf-8', 'replace')}")

    def paged(self, path: str, params: dict | None = None) -> list[dict]:
        params = dict(params or {}, limit="200")
        return self.call("GET", path, params).get("data", [])


def find_app(asc: Asc, bundle_id: str) -> dict:
    rows = asc.paged("/apps", {"filter[bundleId]": bundle_id})
    if not rows:
        sys.exit(f"ERROR: no app with bundleId {bundle_id}")
    return rows[0]


def find_version(asc: Asc, app_id: str, version_string: str) -> dict:
    rows = asc.paged(f"/apps/{app_id}/appStoreVersions",
                     {"filter[platform]": "IOS", "filter[versionString]": version_string})
    if not rows:
        sys.exit(f"ERROR: no App Store version {version_string}. Create it first:\n"
                 f"  ASC_VERSION_STRING={version_string} python3 scripts/asc_create_version.py")
    version = rows[0]
    state = version["attributes"].get("appStoreState")
    if state not in EDITABLE_STATES:
        sys.exit(f"ERROR: version {version_string} is {state}; localizations can only be "
                 f"added to an editable version ({', '.join(sorted(EDITABLE_STATES))})")
    return version


def editable_app_info(asc: Asc, app_id: str) -> dict:
    infos = asc.paged(f"/apps/{app_id}/appInfos")
    editable = [i for i in infos if i["attributes"].get("appStoreState") in EDITABLE_STATES]
    if not editable:
        states = [(i["id"], i["attributes"].get("appStoreState")) for i in infos]
        sys.exit(f"ERROR: no editable appInfo (name/subtitle are locked): {states}. "
                 f"Creating the next version with asc_create_version.py opens one.")
    return editable[0]


def changed_attrs(existing: dict | None, wanted: dict, fields: tuple[str, ...]) -> dict:
    current = (existing or {}).get("attributes", {})
    return {f: wanted[f] for f in fields
            if wanted.get(f) is not None and current.get(f) != wanted[f]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True, help="editable App Store versionString, e.g. 1.0.8")
    ap.add_argument("--inventory", type=pathlib.Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--locales", help="comma-separated subset of listing locales")
    ap.add_argument("--render-dir", type=pathlib.Path,
                    help="write the composed description of every locale here")
    ap.add_argument("--commit", action="store_true", help="write to App Store Connect")
    args = ap.parse_args()

    inventory = json.loads(args.inventory.read_text())
    names, catalog = load_names(), load_catalog()
    listings = load_listings(LISTINGS, "locale")
    if args.locales:
        want = set(args.locales.split(","))
        listings = [l for l in listings if l["locale"] in want]
    composed: dict[str, dict] = {}
    for listing in listings:
        desc = appstore_description(listing, inventory, names, catalog)
        wanted = {f: listing.get(f) for f in INFO_FIELDS + VERSION_FIELDS}
        wanted["description"] = desc
        check_lengths(f"{listing['locale']}", CAPS, wanted)
        composed[listing["locale"]] = wanted
        if args.render_dir:
            args.render_dir.mkdir(parents=True, exist_ok=True)
            (args.render_dir / f"{listing['locale']}.txt").write_text(
                "\n".join(f"{f}: {wanted[f]}" for f in INFO_FIELDS + VERSION_FIELDS
                          if f != "description" and wanted.get(f)) + "\n\n" + desc + "\n")
    print(f"{len(composed)} listing(s) composed from {args.inventory.name} "
          f"({len(inventory)} pairs)" + (f"; rendered to {args.render_dir}" if args.render_dir else ""))

    asc = Asc()
    app = find_app(asc, _env("ASC_BUNDLE_ID", "com.qvyshift.translate"))
    version = find_version(asc, app["id"], args.version)
    info = editable_app_info(asc, app["id"])
    info_locs = {l["attributes"]["locale"]: l
                 for l in asc.paged(f"/appInfos/{info['id']}/appInfoLocalizations")}
    ver_locs = {l["attributes"]["locale"]: l
                for l in asc.paged(f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations")}
    print(f"app {app['id']} ({app['attributes'].get('name')}), version {args.version} "
          f"{version['attributes'].get('appStoreState')}, appInfo {info['id']}")
    print(f"  existing appInfo locales:  {sorted(info_locs)}")
    print(f"  existing version locales:  {sorted(ver_locs)}")

    verb = "PATCH/POST" if args.commit else "would PATCH/POST"
    for locale, wanted in composed.items():
        info_delta = changed_attrs(info_locs.get(locale), wanted, INFO_FIELDS)
        ver_delta = changed_attrs(ver_locs.get(locale), wanted, VERSION_FIELDS)
        if not info_delta and not ver_delta:
            print(f"  {locale}: up to date")
            continue
        print(f"  {locale}: {verb} appInfo {sorted(info_delta)} / version {sorted(ver_delta)}")
        if not args.commit:
            continue
        if info_delta:
            if locale in info_locs:
                asc.call("PATCH", f"/appInfoLocalizations/{info_locs[locale]['id']}",
                         body={"data": {"type": "appInfoLocalizations",
                                        "id": info_locs[locale]["id"],
                                        "attributes": info_delta}})
            else:
                asc.call("POST", "/appInfoLocalizations",
                         body={"data": {"type": "appInfoLocalizations",
                                        "attributes": {"locale": locale, **info_delta},
                                        "relationships": {"appInfo": {"data": {
                                            "type": "appInfos", "id": info["id"]}}}}})
                # ASC creates the version localization of a new appInfo locale by
                # itself (POSTing it again is a 409 DUPLICATE), so re-read the list
                # and fall through to a PATCH.
                ver_locs = {l["attributes"]["locale"]: l for l in asc.paged(
                    f"/appStoreVersions/{version['id']}/appStoreVersionLocalizations")}
        if ver_delta:
            if locale in ver_locs:
                asc.call("PATCH", f"/appStoreVersionLocalizations/{ver_locs[locale]['id']}",
                         body={"data": {"type": "appStoreVersionLocalizations",
                                        "id": ver_locs[locale]["id"],
                                        "attributes": ver_delta}})
            else:
                asc.call("POST", "/appStoreVersionLocalizations",
                         body={"data": {"type": "appStoreVersionLocalizations",
                                        "attributes": {"locale": locale, **ver_delta},
                                        "relationships": {"appStoreVersion": {"data": {
                                            "type": "appStoreVersions", "id": version["id"]}}}}})
        print(f"  {locale}: done")
    if not args.commit:
        print("dry run — nothing written. Re-run with --commit to apply.")


if __name__ == "__main__":
    main()
