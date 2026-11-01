#!/usr/bin/env python3
"""
Refresh the pair list in the App Store description of every localization of
the editable app version, leaving the human-written preamble alone.

Each description ends with an anchor line followed by a newline:

    Language pairs:              en-US (the live description, kept in App Store Connect)
    <pairsHeading>               the locales drafted in ios/appstore/listings/<locale>.json

Everything after that newline is auto-generated and is replaced with a block
rendered from pair-inventory.json:

  * en-US: the English block — "<n> pairs, <mb> MB on demand" and one
    "• Catalan ↔ Italian" line per pair, with the names scripts/_pair_catalog.py
    gives the Android listing.
  * a drafted locale: the block scripts/_listing_i18n.py renders from the
    listing's `pairsSummary` and the CLDR names in scripts/language-names.json,
    so the Catalan description lists "Català ↔ Espanyol". The English block
    never goes into a non-English locale.

The preambles of the drafted locales live in their JSONs and go up with
scripts/asc_upload_listings.py; this script never rewrites them. A localization
whose description has no anchor is skipped with a warning (upload the listing
first), and so is a non-English localization that has no listing JSON.

Environment (same keys as scripts/asc_release_notes.py):
  ASC_KEY_ID     — App Store Connect API key ID
  ASC_ISSUER_ID  — Issuer ID
  ASC_P8         — PEM contents of the .p8 private key
  ASC_BUNDLE_ID  — defaults to com.qvyshift.translate

Usage:
  python3 scripts/update-appstore-description.py pair-inventory.json
      [--render-dir DIR] [--dry-run]

--render-dir writes the composed text of every locale (<locale>.txt; for en-US
the anchor plus block, since its preamble isn't in the repo) before anything is
fetched. --dry-run lists the version's localizations with the planned PATCH of
each and writes nothing (and doesn't wait for an editable version).
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
    import jwt  # PyJWT
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")

# scripts/ is on sys.path by virtue of running from the repo root in CI;
# in ad-hoc local invocations (`python3 scripts/update-…`) it isn't, so
# prepend explicitly.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _listing_i18n import (appstore_description, appstore_pair_block,  # noqa: E402
                           english_locale, inventory_mb, load_listings, load_names)
from _pair_catalog import load as load_catalog, pair_label  # noqa: E402

ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
MAX_DESC = 4000  # App Store description character cap.
REPO = pathlib.Path(__file__).resolve().parent.parent
LISTINGS = REPO / "ios/appstore/listings"
ANCHOR_EN = "Language pairs:\n"   # the en-US description's own heading
SUMMARY_EN = "{n} pairs, {mb} MB on demand"


# --- helpers -----------------------------------------------------------------

def _env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        sys.exit(f"ERROR: ${name} not set")
    return val


def warn(msg: str) -> None:
    """A GitHub Actions annotation on the runner, a plain WARNING elsewhere."""
    prefix = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "WARNING: "
    print(prefix + msg, flush=True)


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

def english_block(inventory: list[dict], catalog: dict | None = None) -> str:
    """The block after the en-US anchor: a blank line, the summary, a blank
    line, one bullet per pair. English names from _pair_catalog (the same
    names the Android listing uses); size from "bytes" (older inventories
    had "sizeKb" — the source of the "0 MB" the live description showed)."""
    catalog = catalog if catalog is not None else load_catalog()
    labels = sorted({pair_label(e["pair"], catalog) for e in inventory})
    summary = SUMMARY_EN.format(n=len(labels), mb=inventory_mb(inventory))
    return f"\n{summary}\n\n" + "\n".join(f"• {label}" for label in labels)


def anchor_and_block(locale: str, by_locale: dict[str, dict], inventory: list[dict],
                     names, catalog) -> tuple[str, str] | None:
    """(anchor including its newline, replacement block) for a localization,
    or None when the locale is neither English nor drafted in
    ios/appstore/listings/ — then nothing may be written to it."""
    listing = by_locale.get(locale)
    if listing:
        return listing["pairsHeading"] + "\n", appstore_pair_block(listing, inventory, names, catalog)
    if english_locale(locale):
        return ANCHOR_EN, english_block(inventory, catalog)
    return None


def splice(description: str, anchor: str, block: str) -> str | None:
    """Replace everything after the last `anchor` with `block`; None when
    the description has no anchor to splice against."""
    idx = description.rfind(anchor)
    if idx < 0:
        return None
    return description[: idx + len(anchor)] + block


def render(render_dir: pathlib.Path, listings: list[dict], inventory: list[dict],
           names, catalog) -> None:
    render_dir.mkdir(parents=True, exist_ok=True)
    (render_dir / "en-US.txt").write_text(ANCHOR_EN + english_block(inventory, catalog) + "\n",
                                          encoding="utf-8")
    for listing in listings:
        (render_dir / f"{listing['locale']}.txt").write_text(
            appstore_description(listing, inventory, names, catalog) + "\n", encoding="utf-8")
    print(f"rendered en-US and {len(listings)} drafted locale(s) to {render_dir}")


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


def latest_editable_version_id(token: str, app_id: str, wait: bool = True) -> str | None:
    """Pick the newest version whose state still accepts metadata
    edits, retrying in case the build we just uploaded hasn't yet
    materialized as an ASC version row. Returns None if ASC has no
    editable version — the caller warns and exits cleanly. wait=False
    (dry runs) looks once and settles for the newest version."""
    delays = [0, 15, 30, 45, 60, 90, 120, 120, 120, 120] if wait else [0]
    last_states: list[tuple[str, str]] = []
    rows: list[dict] = []
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
    if not wait and rows:
        picked = rows[0]
        vs = picked["attributes"].get("versionString")
        st = picked["attributes"].get("appStoreState")
        print(f"  no editable version; dry run against the newest one, {vs} ({st}, "
              f"id={picked['id']})", flush=True)
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inventory", type=pathlib.Path, help="pair-inventory.json of this build")
    ap.add_argument("--render-dir", type=pathlib.Path,
                    help="write the composed description of every locale here")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the planned PATCHes; write nothing to App Store Connect")
    args = ap.parse_args()
    if not args.inventory.is_file():
        sys.exit(f"ERROR: inventory not found: {args.inventory}")

    inventory = json.loads(args.inventory.read_text())
    names, catalog = load_names(), load_catalog()
    listings = load_listings(LISTINGS, "locale", required=False)
    by_locale = {l["locale"]: l for l in listings}
    # Render every drafted locale up front: a missing language name in
    # language-names.json fails here, before anything is fetched.
    for listing in listings:
        appstore_pair_block(listing, inventory, names, catalog)
    print(f"{len(inventory)} pairs, {inventory_mb(inventory)} MB; en-US plus "
          f"{len(listings)} drafted locale(s)")
    if args.render_dir:
        render(args.render_dir, listings, inventory, names, catalog)

    token = mint_jwt(_env("ASC_KEY_ID"), _env("ASC_ISSUER_ID"), _env("ASC_P8"))
    bundle_id = _env("ASC_BUNDLE_ID", default="com.qvyshift.translate")
    app_id = find_app_id(token, bundle_id)
    vid    = latest_editable_version_id(token, app_id, wait=not args.dry_run)
    if vid is None:
        return  # warning already printed; let the workflow continue
    locs   = version_localizations(token, vid)
    if not locs:
        sys.exit(f"ERROR: app version {vid} has no localizations")

    updated = unchanged = skipped = 0
    for loc in sorted(locs, key=lambda l: l.get("attributes", {}).get("locale", "")):
        attrs = loc.get("attributes", {})
        locale = attrs.get("locale", "?")
        current = attrs.get("description") or ""
        pick = anchor_and_block(locale, by_locale, inventory, names, catalog)
        if pick is None:
            warn(f"{locale}: not English and no {LISTINGS.name}/{locale}.json — the English "
                 f"pair list never goes to a non-English locale; description left as is")
            skipped += 1
            continue
        anchor, block = pick
        new_desc = splice(current, anchor, block)
        if new_desc is None:
            warn(f"{locale}: anchor {anchor.rstrip()!r} not in the description — upload the "
                 f"listing with asc_upload_listings.py first; description left as is")
            skipped += 1
            continue
        if len(new_desc) > MAX_DESC:
            sys.exit(f"ERROR: new description is {len(new_desc)} chars "
                     f"(> ASC cap {MAX_DESC}) for locale {locale}")
        if new_desc == current:
            print(f"  {locale}: pair list unchanged")
            unchanged += 1
            continue
        if args.dry_run:
            print(f"  {locale}: would PATCH description ({len(current)} → {len(new_desc)} chars)")
            updated += 1
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
    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} description on {updated} localization(s); "
          f"{unchanged} unchanged, {skipped} skipped")
    if args.dry_run:
        print("dry run — nothing written.")


if __name__ == "__main__":
    main()
