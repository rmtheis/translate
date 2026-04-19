#!/usr/bin/env python3
"""Splice the generated pair list into the Play Console "full description".

The Play Developer API doesn't let us patch just a section of the description,
so we round-trip: fetch the current listing, replace text between the marker
comments (or append if they're absent), and PUT the whole description back.

Usage:
    ./scripts/update-store-description.py listing-languages.txt

Env:
    SA_JSON               Service-account JSON from PLAY_SERVICE_ACCOUNT_JSON
    PACKAGE_NAME          App package (defaults to com.qvyshift.translate)
    STORE_LANG            Play listing language code (default en-US)

The initial Play listing must either contain the markers

    <!-- AUTO-GENERATED LANGUAGES START -->
    <!-- AUTO-GENERATED LANGUAGES END -->

or have fewer than 4000 - section chars of existing body so we can safely append.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


START = "<!-- AUTO-GENERATED LANGUAGES START -->"
END = "<!-- AUTO-GENERATED LANGUAGES END -->"
PLAY_API = "https://androidpublisher.googleapis.com/androidpublisher/v3"


def sa_creds() -> dict:
    raw = os.environ.get("SA_JSON")
    if not raw:
        sys.exit("SA_JSON env var not set")
    return json.loads(raw)


def access_token(sa: dict) -> str:
    # JWT-based Google service-account auth. Avoid the full google-auth dep by
    # building the JWT inline.
    import base64, hashlib, hmac
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        sys.exit("pip install cryptography")

    header = {"alg": "RS256", "typ": "JWT"}
    now = int(time.time())
    claims = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/androidpublisher",
        "aud": "https://oauth2.googleapis.com/token",
        "exp": now + 3600,
        "iat": now,
    }
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()).rstrip(b"=")
    signing_input = b64(header) + b"." + b64(claims)
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    jwt = signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")

    resp = urllib.request.urlopen(
        "https://oauth2.googleapis.com/token",
        data=urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt.decode(),
        }).encode(),
    )
    return json.loads(resp.read())["access_token"]


def api(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{PLAY_API}{path}",
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {method} {path}\n{e.read().decode()}")


def splice(existing: str, block: str) -> str:
    if START in existing and END in existing:
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
        return pattern.sub(f"{START}\n{block}\n{END}", existing)
    # No markers yet — append.
    sep = "\n\n" if existing.strip() else ""
    return f"{existing.rstrip()}{sep}{START}\n{block}\n{END}"


def main() -> int:
    languages_block = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
    pkg = os.environ.get("PACKAGE_NAME", "com.qvyshift.translate")
    lang = os.environ.get("STORE_LANG", "en-US")

    sa = sa_creds()
    token = access_token(sa)

    edit = api("POST", f"/applications/{pkg}/edits", token, {})
    edit_id = edit["id"]
    listing = api("GET", f"/applications/{pkg}/edits/{edit_id}/listings/{lang}", token)
    existing = listing.get("fullDescription", "")

    new_description = splice(existing, languages_block.strip())
    listing["fullDescription"] = new_description

    api("PUT", f"/applications/{pkg}/edits/{edit_id}/listings/{lang}", token, listing)
    api("POST", f"/applications/{pkg}/edits/{edit_id}:commit", token)

    print(f"store listing full description updated ({lang}, {len(new_description)} chars)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
