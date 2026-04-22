#!/usr/bin/env python3
"""
Update the "What's New" release-notes text on the latest App Store
Connect app version via the REST API. Runs after asc_upload.py on the
iOS release workflow.

Environment:
  ASC_KEY_ID
  ASC_ISSUER_ID
  ASC_P8
  ASC_BUNDLE_ID   — bundle id of the app whose version to update
                    (defaults to com.qvyshift.translate)

Usage:
  python3 scripts/asc_release_notes.py <path-to-release-notes.txt>

The release-notes file is read as UTF-8 and posted verbatim. App Store
Connect caps the "What's New" field at 4000 characters; we fail loudly
if the supplied notes exceed that.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import jwt  # PyJWT
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")


ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
MAX_NOTES = 4000  # ASC character cap on the whatsNew field.


def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"ERROR: ${name} not set")
    return val


def mint_jwt(key_id: str, issuer_id: str, pem: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer_id,
            "iat": now,
            "exp": now + 20 * 60,
            "aud": "appstoreconnect-v1",
        },
        pem,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


def _request(method: str, token: str, path: str,
             params: dict | None = None, body: dict | None = None) -> dict:
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
            return json.loads(raw) if raw else {}
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


# States where whatsNew can actually be PATCHed. Apple's docs list
# REJECTED + WAITING_FOR_REVIEW as "editable" too, but empirically the
# API returns HTTP 409 ("Attribute 'whatsNew' cannot be edited at this
# time") for both — stay conservative and only target states that
# actually accept edits.
_EDITABLE_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}


def _fetch_versions(token: str, app_id: str) -> list[dict]:
    # This endpoint does not accept a `sort` query parameter (Apple
    # returns PARAMETER_ERROR.ILLEGAL). Fetch a batch with createdDate
    # in the response and sort locally. limit=200 is the API maximum.
    data = _request("GET", token, f"/apps/{app_id}/appStoreVersions",
                    params={"limit": "200",
                            "fields[appStoreVersions]": "versionString,createdDate,appStoreState"})
    rows = data.get("data", [])
    rows.sort(key=lambda r: r.get("attributes", {}).get("createdDate", ""),
              reverse=True)
    return rows


def latest_editable_version_id(token: str, app_id: str) -> str | None:
    """Return the most recently-created version in a state that still
    accepts whatsNew edits, or None if no such version appears within
    ~10 minutes. altool's upload returns well before Apple creates the
    ASC version row, so we retry with backoff. A None return means
    "ASC is in a state where this script can't safely patch" — the
    caller should warn and exit cleanly rather than fail the job."""
    delays = [0, 15, 30, 45, 60, 90, 120, 120, 120, 120]
    last_states: list[tuple[str, str]] = []
    for delay in delays:
        if delay:
            print(f"  no editable version yet, waiting {delay}s...", flush=True)
            time.sleep(delay)
        rows = _fetch_versions(token, app_id)
        last_states = [(r["id"], r["attributes"].get("appStoreState", "?"))
                       for r in rows]
        editable = [r for r in rows
                    if r.get("attributes", {}).get("appStoreState") in _EDITABLE_STATES]
        if editable:
            picked = editable[0]
            vs = picked["attributes"].get("versionString")
            st = picked["attributes"].get("appStoreState")
            print(f"  targeting version {vs} ({st}, id={picked['id']})", flush=True)
            return picked["id"]
    print(
        f"WARNING: no editable App Store version appeared within ~10 min.\n"
        f"  Versions seen (id, state): {last_states}\n"
        f"  Editable states we accept: {sorted(_EDITABLE_STATES)}\n"
        f"  Skipping whatsNew patch (not fatal — metadata stays at its "
        f"current value).",
        flush=True,
    )
    return None


def version_localizations(token: str, version_id: str) -> list[dict]:
    data = _request("GET", token,
                    f"/appStoreVersions/{version_id}/appStoreVersionLocalizations",
                    params={"limit": "200"})
    return data.get("data", [])


def patch_whats_new(token: str, localization_id: str, notes: str) -> None:
    body = {
        "data": {
            "type": "appStoreVersionLocalizations",
            "id": localization_id,
            "attributes": {"whatsNew": notes},
        }
    }
    _request("PATCH", token,
             f"/appStoreVersionLocalizations/{localization_id}", body=body)


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: asc_release_notes.py <path-to-notes-file>")
    notes_path = pathlib.Path(sys.argv[1])
    if not notes_path.is_file():
        sys.exit(f"ERROR: notes file not found: {notes_path}")
    notes = notes_path.read_text(encoding="utf-8").rstrip()
    if not notes:
        print("notes file is empty; nothing to update")
        return
    if len(notes) > MAX_NOTES:
        sys.exit(f"ERROR: notes are {len(notes)} chars (> ASC cap {MAX_NOTES})")

    token = mint_jwt(_env("ASC_KEY_ID"), _env("ASC_ISSUER_ID"), _env("ASC_P8"))
    bundle_id = _env("ASC_BUNDLE_ID", default="com.qvyshift.translate")
    app_id    = find_app_id(token, bundle_id)
    vid       = latest_editable_version_id(token, app_id)
    if vid is None:
        return  # warning already printed; let the workflow continue
    locs      = version_localizations(token, vid)
    if not locs:
        sys.exit(f"ERROR: app version {vid} has no localizations yet")

    # Update every locale — keeps parity with the Android store-listing
    # flow (which also pushes one block to every active locale).
    updated = 0
    for loc in locs:
        attrs = loc.get("attributes", {})
        locale = attrs.get("locale", "?")
        patch_whats_new(token, loc["id"], notes)
        print(f"  updated whatsNew for {locale}")
        updated += 1
    print(f"updated release notes on {updated} localization(s)")


if __name__ == "__main__":
    main()
