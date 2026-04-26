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


class _ApiError(Exception):
    """Raised by _request when raise_http_error=True. Carries the
    status code and parsed response body so callers can decide whether
    the error is recoverable (e.g. Apple's documented STATE_ERROR for
    fields locked on first-version submissions)."""

    def __init__(self, code: int, reason: str, method: str, path: str, body: str):
        self.code = code
        self.reason = reason
        self.method = method
        self.path = path
        self.body = body
        super().__init__(f"HTTP {code} {reason} on {method} {path}\n{body}")


def _request(method: str, token: str, path: str,
             params: dict | None = None, body: dict | None = None,
             raise_http_error: bool = False) -> dict:
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
        if raise_http_error:
            raise _ApiError(e.code, e.reason, method, path, detail) from e
        sys.exit(f"HTTP {e.code} {e.reason} on {method} {path}\n{detail}")


def _is_attribute_locked_error(body: str, attribute: str) -> bool:
    """Apple returns 409 STATE_ERROR with detail
    "Attribute '<name>' cannot be edited at this time" when the
    current version state doesn't accept edits to that field. Mirrors
    the helper in asc_release_notes.py — same Apple error shape applies
    to any localization attribute."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False
    for err in parsed.get("errors", []):
        if err.get("status") != "409" or err.get("code") != "STATE_ERROR":
            continue
        detail = (err.get("detail") or "").lower()
        if attribute.lower() in detail and "cannot be edited" in detail:
            return True
    return False


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


# Same editable-state set as asc_release_notes.py — Apple's docs claim
# REJECTED + WAITING_FOR_REVIEW are editable, but the API returns 409
# in practice, so stay conservative.
_EDITABLE_STATES = {
    "PREPARE_FOR_SUBMISSION",
    "DEVELOPER_REJECTED",
    "METADATA_REJECTED",
    "INVALID_BINARY",
}


def latest_editable_version_id(token: str, app_id: str) -> str | None:
    """Pick the newest version whose state still accepts metadata
    edits, retrying in case the build we just uploaded hasn't yet
    materialized as an ASC version row. Returns None if ASC has no
    editable version — the caller warns and exits cleanly."""
    delays = [0, 15, 30, 45, 60, 90, 120, 120, 120, 120]
    last_states: list[tuple[str, str]] = []
    for delay in delays:
        if delay:
            print(f"  no editable version yet, waiting {delay}s...", flush=True)
            time.sleep(delay)
        data = _request("GET", token, f"/apps/{app_id}/appStoreVersions",
                        params={"limit": "200",
                                "fields[appStoreVersions]":
                                    "versionString,createdDate,appStoreState"})
        rows = data.get("data", [])
        rows.sort(key=lambda r: r.get("attributes", {}).get("createdDate", ""),
                  reverse=True)
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
        f"  Skipping description splice (not fatal — description stays "
        f"at its current value).",
        flush=True,
    )
    return None


def version_localizations(token: str, version_id: str) -> list[dict]:
    data = _request("GET", token,
                    f"/appStoreVersions/{version_id}/appStoreVersionLocalizations",
                    params={"limit": "200"})
    return data.get("data", [])


def patch_description(token: str, localization_id: str, text: str) -> bool:
    """Patch description. Returns True on success, False if Apple
    rejected the edit with the documented "attribute locked"
    STATE_ERROR. Description is normally editable on first-version
    submissions (it's required), but the same guard is applied as for
    whatsNew so any analogous state-driven rejection skips cleanly
    instead of failing the workflow."""
    body = {
        "data": {
            "type": "appStoreVersionLocalizations",
            "id": localization_id,
            "attributes": {"description": text},
        }
    }
    try:
        _request("PATCH", token,
                 f"/appStoreVersionLocalizations/{localization_id}",
                 body=body, raise_http_error=True)
        return True
    except _ApiError as e:
        if e.code == 409 and _is_attribute_locked_error(e.body, "description"):
            return False
        sys.exit(str(e))


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
    vid    = latest_editable_version_id(token, app_id)
    if vid is None:
        return  # warning already printed; let the workflow continue
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
        if not patch_description(token, loc["id"], new_desc):
            # Same per-version lockout pattern as whatsNew: every
            # locale would fail with the same STATE_ERROR. Stop early
            # so the workflow continues (project.yml commit-back still
            # needs to run after this step).
            print(
                f"WARNING: ASC won't accept description edits on this "
                f"version (STATE_ERROR for 'description').\n"
                f"  Triggered on locale={locale}; skipping remaining locales.\n"
                f"  Not fatal — pair list stays at its current value.",
                flush=True,
            )
            return
        print(f"  updated description for {locale} ({len(new_desc)} chars)")
        updated += 1
    print(f"updated description on {updated} localization(s)")


if __name__ == "__main__":
    main()
