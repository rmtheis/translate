#!/usr/bin/env python3
"""
Refresh the App Store description's language-pair list on the latest
app version, leaving the human-written preamble alone.

The description is expected to contain a single anchor line

    Language pairs:

followed by a newline. Everything after that newline is considered
auto-generated and gets replaced with fresh content derived from the
current pair-inventory.json.

Environment (same keys as scripts/asc_release_notes.py):
  ASC_KEY_ID     — App Store Connect API key ID
  ASC_ISSUER_ID  — Issuer ID
  ASC_P8         — PEM contents of the .p8 private key
  ASC_BUNDLE_ID  — defaults to com.qvyshift.translate

Usage:
  python3 scripts/update-appstore-description.py pair-inventory.json
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

# scripts/ is on sys.path by virtue of running from the repo root in CI;
# in ad-hoc local invocations (`python3 scripts/update-…`) it isn't, so
# prepend explicitly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _pair_catalog import load as load_catalog, pair_label  # type: ignore

ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
MAX_DESC = 4000  # App Store description character cap.
ANCHOR = "Language pairs:\n"


# --- helpers -----------------------------------------------------------------

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


# --- pair list formatting ----------------------------------------------------

def format_pair_list(inventory_path: pathlib.Path) -> str:
    """Return the block that replaces everything after the anchor.

    Mirrors the Android store-listing.py output but tailored for the
    iOS description (no redundant "Included language pairs" header —
    the anchor "Language pairs:" already serves that role).
    """
    inventory = json.loads(inventory_path.read_text())
    total_kb = sum(e.get("sizeKb", 0) for e in inventory)
    total_mb = round(total_kb / 1024)
    catalog = load_catalog()
    labels = sorted({pair_label(e["pair"], catalog) for e in inventory})
    lines = [
        "",  # blank line after the anchor
        f"{len(labels)} pairs, {total_mb} MB on demand",
        "",
    ]
    lines.extend(f"• {label}" for label in labels)
    return "\n".join(lines)


def splice(description: str, new_list: str) -> str:
    idx = description.rfind(ANCHOR)
    if idx < 0:
        sys.exit(
            "ERROR: anchor 'Language pairs:\\n' not found in the current "
            "App Store description. Set the description manually in ASC first "
            "so this script has a seam to splice against."
        )
    head = description[: idx + len(ANCHOR)]
    return head + new_list


# --- ASC traversal -----------------------------------------------------------

def find_app_id(token: str, bundle_id: str) -> str:
    data = _request("GET", token, "/apps",
                    params={"filter[bundleId]": bundle_id, "limit": "1"})
    rows = data.get("data", [])
    if not rows:
        sys.exit(f"ERROR: no App Store Connect app with bundleId={bundle_id}")
    return rows[0]["id"]


def latest_version_id(token: str, app_id: str) -> str:
    data = _request("GET", token, f"/apps/{app_id}/appStoreVersions",
                    params={"limit": "1", "sort": "-createdDate"})
    rows = data.get("data", [])
    if not rows:
        sys.exit(f"ERROR: app {app_id} has no app store versions")
    return rows[0]["id"]


def version_localizations(token: str, version_id: str) -> list[dict]:
    data = _request("GET", token,
                    f"/appStoreVersions/{version_id}/appStoreVersionLocalizations",
                    params={"limit": "200"})
    return data.get("data", [])


def patch_description(token: str, localization_id: str, text: str) -> None:
    body = {
        "data": {
            "type": "appStoreVersionLocalizations",
            "id": localization_id,
            "attributes": {"description": text},
        }
    }
    _request("PATCH", token,
             f"/appStoreVersionLocalizations/{localization_id}", body=body)


# --- main --------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: update-appstore-description.py <pair-inventory.json>")
    inv = pathlib.Path(sys.argv[1])
    if not inv.is_file():
        sys.exit(f"ERROR: inventory not found: {inv}")

    new_list = format_pair_list(inv)

    token = mint_jwt(_env("ASC_KEY_ID"), _env("ASC_ISSUER_ID"), _env("ASC_P8"))
    bundle_id = _env("ASC_BUNDLE_ID", default="com.qvyshift.translate")
    app_id = find_app_id(token, bundle_id)
    vid    = latest_version_id(token, app_id)
    locs   = version_localizations(token, vid)
    if not locs:
        sys.exit(f"ERROR: app version {vid} has no localizations")

    updated = 0
    for loc in locs:
        attrs = loc.get("attributes", {})
        locale = attrs.get("locale", "?")
        current = attrs.get("description") or ""
        if ANCHOR not in current:
            print(f"  skip {locale}: no 'Language pairs:' anchor in description")
            continue
        new_desc = splice(current, new_list)
        if len(new_desc) > MAX_DESC:
            sys.exit(f"ERROR: new description is {len(new_desc)} chars "
                     f"(> ASC cap {MAX_DESC}) for locale {locale}")
        if new_desc == current:
            print(f"  {locale}: pair list unchanged — skipping PATCH")
            continue
        patch_description(token, loc["id"], new_desc)
        print(f"  updated description for {locale} ({len(new_desc)} chars)")
        updated += 1
    print(f"updated description on {updated} localization(s)")


if __name__ == "__main__":
    main()
