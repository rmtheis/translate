#!/usr/bin/env python3
"""
Create the App Store version row that a release is submitted against.

Apple does NOT auto-create an App Store version when a build is uploaded —
altool/Transporter only make the build available (it shows up under
TestFlight). So the release pipeline must create the version explicitly;
otherwise asc_release_notes.py / update-appstore-description.py find nothing
editable to patch (they skip with a warning) and asc_resubmit.py has no
version to submit (it errors). That gap is why iOS releases never reached the
App Store.

Idempotent:
  * If an editable iOS version already exists (a prior run created one and it
    hasn't been submitted yet), it's reused — printed, not duplicated.
  * If a version with the target versionString already exists in any state
    (e.g. already submitted or live), we leave it alone.
  * Otherwise we POST a new appStoreVersion. Apple creates it in
    PREPARE_FOR_SUBMISSION and copies metadata forward from the prior version.

Environment:
  ASC_KEY_ID
  ASC_ISSUER_ID
  ASC_P8
  ASC_BUNDLE_ID         — defaults to com.qvyshift.translate
  ASC_VERSION_STRING    — required: CFBundleShortVersionString to create; must
                          match the uploaded build's marketing version (e.g. "1.0.2")
  ASC_RELEASE_TYPE      — AFTER_APPROVAL (default) | MANUAL | SCHEDULED

Usage:
  python3 scripts/asc_create_version.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import jwt
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")


ASC_BASE = "https://api.appstoreconnect.apple.com/v1"

# States in which a version still accepts edits (and so can be reused rather
# than creating a duplicate). Matches asc_resubmit.py.
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


def mint_jwt(key_id: str, issuer_id: str, pem: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer_id, "iat": now, "exp": now + 20 * 60,
         "aud": "appstoreconnect-v1"},
        pem, algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"})


def _request(method: str, token: str, path: str,
             params: dict | None = None, body: dict | None = None,
             expect_json: bool = True) -> dict:
    url = ASC_BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True, safe=",[]")
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw and expect_json else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        sys.exit(f"HTTP {e.code} {e.reason} on {method} {path}\n{detail}")


def find_app_id(token: str, bundle_id: str) -> str:
    data = _request("GET", token, "/apps",
                    params={"filter[bundleId]": bundle_id, "limit": "1"})
    rows = data.get("data", [])
    if not rows:
        sys.exit(f"ERROR: no App Store Connect app with bundleId={bundle_id}")
    return rows[0]["id"]


def list_ios_versions(token: str, app_id: str) -> list[dict]:
    data = _request("GET", token, f"/apps/{app_id}/appStoreVersions",
                    params={"limit": "200",
                            "fields[appStoreVersions]":
                                "versionString,appStoreState,platform"})
    return [r for r in data.get("data", [])
            if r.get("attributes", {}).get("platform") == "IOS"]


def create_version(token: str, app_id: str, version_string: str,
                   release_type: str) -> str:
    body = {
        "data": {
            "type": "appStoreVersions",
            "attributes": {
                "platform": "IOS",
                "versionString": version_string,
                "releaseType": release_type,
            },
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            },
        }
    }
    resp = _request("POST", token, "/appStoreVersions", body=body)
    return resp["data"]["id"]


def main() -> None:
    token = mint_jwt(_env("ASC_KEY_ID"), _env("ASC_ISSUER_ID"), _env("ASC_P8"))
    bundle_id = _env("ASC_BUNDLE_ID", "com.qvyshift.translate")
    version_string = _env("ASC_VERSION_STRING")
    release_type = (os.environ.get("ASC_RELEASE_TYPE") or "AFTER_APPROVAL").upper()

    app_id = find_app_id(token, bundle_id)
    versions = list_ios_versions(token, app_id)

    editable = [v for v in versions
                if v["attributes"].get("appStoreState") in EDITABLE_STATES]
    if editable:
        v = editable[0]
        print(f"editable iOS version already exists: "
              f"{v['attributes'].get('versionString')} "
              f"({v['attributes'].get('appStoreState')}, id={v['id']}); "
              f"reusing it, not creating {version_string}")
        return

    same = [v for v in versions
            if v["attributes"].get("versionString") == version_string]
    if same:
        v = same[0]
        print(f"version {version_string} already exists in state "
              f"{v['attributes'].get('appStoreState')} (id={v['id']}); "
              f"not creating")
        return

    vid = create_version(token, app_id, version_string, release_type)
    print(f"created App Store version {version_string} "
          f"(IOS, releaseType={release_type}, id={vid})")


if __name__ == "__main__":
    main()
