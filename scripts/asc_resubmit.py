#!/usr/bin/env python3
"""
Submit the freshly-uploaded build for App Store review.

Run this AFTER asc_upload.py has uploaded a new build. The script:
  1. Polls App Store Connect until the build's processingState becomes
     VALID (altool returns before Apple finishes processing).
  2. Finds the App Store version row matching the build's
     versionString — typically the row ASC auto-creates after a
     successful upload, in PREPARE_FOR_SUBMISSION state.
  3. Attaches the build to that version (PATCH the build relationship).
  4. Creates a reviewSubmission for the app, adds the version as an
     item, and PATCHes submitted=true to send it to Apple's review
     queue.

Use sparingly: this is the irreversible "submit for review" click —
once submitted, Apple will queue the version for review. There's a
cancel endpoint, but treat each successful run as a real submission.

Environment:
  ASC_KEY_ID
  ASC_ISSUER_ID
  ASC_P8
  ASC_BUNDLE_ID         — defaults to com.qvyshift.translate
  ASC_BUILD_VERSION     — optional: CFBundleVersion of the new build
                          (e.g. "202604261325"). If unset, picks the
                          most-recently-uploaded build that's already
                          processed.
  ASC_VERSION_STRING    — optional: CFBundleShortVersionString to
                          target. Defaults to the version row that has
                          createdDate descending and matches one of
                          the editable states.

Usage:
  python3 scripts/asc_resubmit.py
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

# States where we can edit a version (attach build, set release notes)
# and submit it for review. Apple's docs claim REJECTED is editable but
# the API rejects PATCHes against it — for re-submission after a
# rejection, ASC auto-creates a new version row in
# PREPARE_FOR_SUBMISSION when the new build is uploaded, and we target
# that one.
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
             params: dict | None = None,
             body: dict | None = None,
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


def wait_for_build(token: str, app_id: str, build_version: str | None,
                   max_wait_min: int = 30) -> dict:
    """Poll until the target build is PROCESSED. If `build_version` is
    set, find by CFBundleVersion; otherwise pick the most recently
    uploaded build for this app. Returns the build's full row."""
    delays = [0, 30, 30, 30, 60, 60, 60, 90, 120, 120, 180, 180, 180, 180]
    deadline = time.time() + max_wait_min * 60
    for delay in delays:
        if time.time() > deadline:
            break
        if delay:
            print(f"  build not ready, waiting {delay}s...", flush=True)
            time.sleep(delay)
        params = {"fields[builds]": "version,processingState,uploadedDate",
                  "limit": "10"}
        if build_version:
            params["filter[version]"] = build_version
        data = _request("GET", token, f"/apps/{app_id}/builds", params=params)
        rows = data.get("data", [])
        if not rows:
            label = build_version or "(any)"
            print(f"  no build matching version={label} yet")
            continue
        rows.sort(key=lambda r: r.get("attributes", {}).get("uploadedDate", ""),
                  reverse=True)
        b = rows[0]
        state = b["attributes"].get("processingState")
        ver   = b["attributes"].get("version")
        print(f"  latest build version={ver} processingState={state} (id={b['id']})")
        if state == "VALID":
            return b
        if state in {"FAILED", "INVALID"}:
            sys.exit(f"ERROR: build {ver} processingState={state}")
    sys.exit(f"ERROR: build did not reach VALID within {max_wait_min} min")


def find_target_version(token: str, app_id: str,
                        version_string: str | None) -> dict:
    """Pick the editable version row to submit. Prefer one matching
    `version_string` if supplied; otherwise return the most recently
    created editable version."""
    data = _request("GET", token, f"/apps/{app_id}/appStoreVersions",
                    params={"limit": "200",
                            "fields[appStoreVersions]":
                                "versionString,createdDate,appStoreState,platform"})
    rows = data.get("data", [])
    rows.sort(key=lambda r: r.get("attributes", {}).get("createdDate", ""),
              reverse=True)
    editable = [r for r in rows
                if r.get("attributes", {}).get("appStoreState") in EDITABLE_STATES
                and r.get("attributes", {}).get("platform") == "IOS"]
    if version_string:
        for r in editable:
            if r["attributes"].get("versionString") == version_string:
                return r
        sys.exit(
            f"ERROR: no editable version with versionString={version_string}. "
            f"Available editable versions: "
            + ", ".join(f"{r['attributes'].get('versionString')}"
                        f" ({r['attributes'].get('appStoreState')})"
                        for r in editable))
    if not editable:
        sys.exit("ERROR: no editable App Store version found "
                 "(states: PREPARE_FOR_SUBMISSION / *_REJECTED / INVALID_BINARY)")
    return editable[0]


def attach_build(token: str, version_id: str, build_id: str) -> None:
    """PATCH /v1/appStoreVersions/{vid}/relationships/build."""
    body = {"data": {"type": "builds", "id": build_id}}
    _request("PATCH", token,
             f"/appStoreVersions/{version_id}/relationships/build",
             body=body, expect_json=False)


def create_review_submission(token: str, app_id: str,
                             platform: str = "IOS") -> str:
    """Find an existing open reviewSubmission for this app+platform, or
    POST a new one. Apple permits only one open reviewSubmission per
    platform; trying to create a second returns 409. Returns the
    reviewSubmission id."""
    data = _request("GET", token, "/reviewSubmissions",
                    params={"filter[app]": app_id,
                            "filter[platform]": platform,
                            "filter[state]": "READY_FOR_REVIEW,IN_REVIEW,UNRESOLVED_ISSUES,WAITING_FOR_REVIEW",
                            "limit": "5"})
    rows = data.get("data", [])
    if rows:
        rs_id = rows[0]["id"]
        st = rows[0]["attributes"].get("state")
        print(f"  reusing existing reviewSubmission {rs_id} (state={st})")
        return rs_id
    body = {
        "data": {
            "type": "reviewSubmissions",
            "attributes": {"platform": platform},
            "relationships": {
                "app": {"data": {"type": "apps", "id": app_id}}
            }
        }
    }
    resp = _request("POST", token, "/reviewSubmissions", body=body)
    rs_id = resp["data"]["id"]
    print(f"  created reviewSubmission {rs_id}")
    return rs_id


def add_version_to_submission(token: str, rs_id: str, version_id: str) -> None:
    """POST a reviewSubmissionItem linking the version to the
    reviewSubmission. If one already exists for this version, ASC
    returns 409 — treat that as success."""
    body = {
        "data": {
            "type": "reviewSubmissionItems",
            "relationships": {
                "reviewSubmission": {
                    "data": {"type": "reviewSubmissions", "id": rs_id}
                },
                "appStoreVersion": {
                    "data": {"type": "appStoreVersions", "id": version_id}
                }
            }
        }
    }
    url = ASC_BASE + "/reviewSubmissionItems"
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}
    req = urllib.request.Request(url, method="POST", headers=headers,
                                 data=json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  added version {version_id} as submission item")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        if e.code == 409 and "already" in detail.lower():
            print(f"  version {version_id} already in submission (continuing)")
            return
        sys.exit(f"HTTP {e.code} {e.reason} on POST /reviewSubmissionItems\n{detail}")


def submit_for_review(token: str, rs_id: str) -> None:
    """PATCH /v1/reviewSubmissions/{id} with submitted=true."""
    body = {
        "data": {
            "type": "reviewSubmissions",
            "id": rs_id,
            "attributes": {"submitted": True}
        }
    }
    _request("PATCH", token, f"/reviewSubmissions/{rs_id}", body=body,
             expect_json=False)


def main() -> None:
    key_id    = _env("ASC_KEY_ID")
    issuer_id = _env("ASC_ISSUER_ID")
    p8        = _env("ASC_P8")
    bundle_id = _env("ASC_BUNDLE_ID", "com.qvyshift.translate")
    build_ver = os.environ.get("ASC_BUILD_VERSION") or None
    version_string = os.environ.get("ASC_VERSION_STRING") or None

    token = mint_jwt(key_id, issuer_id, p8)

    print(f"[1/5] Find app for bundleId={bundle_id}")
    app_id = find_app_id(token, bundle_id)
    print(f"  app_id={app_id}")

    label = f"CFBundleVersion={build_ver}" if build_ver else "(latest uploaded)"
    print(f"[2/5] Wait for build {label} to be VALID")
    build = wait_for_build(token, app_id, build_ver)
    build_id = build["id"]
    build_ver_actual = build["attributes"].get("version")
    print(f"  build_id={build_id} version={build_ver_actual}")

    print(f"[3/5] Find target version row "
          f"(versionString={version_string or '<latest editable>'})")
    version = find_target_version(token, app_id, version_string)
    version_id = version["id"]
    vs = version["attributes"].get("versionString")
    st = version["attributes"].get("appStoreState")
    print(f"  version_id={version_id} versionString={vs} state={st}")

    print(f"[4/5] Attach build {build_id} to version {version_id}")
    attach_build(token, version_id, build_id)

    print(f"[5/5] Create reviewSubmission and submit")
    rs_id = create_review_submission(token, app_id)
    add_version_to_submission(token, rs_id, version_id)
    submit_for_review(token, rs_id)
    print(f"\nSubmitted for review: app={bundle_id} version={vs} "
          f"build={build_ver_actual}")
    print(f"reviewSubmission id={rs_id}")


if __name__ == "__main__":
    main()
