#!/usr/bin/env python3
"""
Upload a signed iOS .ipa to App Store Connect.

Authenticates with an ASC API key (.p8) and invokes `xcrun altool`
under the hood — altool is pre-installed on macOS runners and handles
the multi-chunk upload + processing handshake for us, which keeps
this script short. We only implement the bits altool doesn't: JWT
auth preflight (so we fail fast if creds are bad) and writing the
.p8 to the path altool expects.

Environment (matches the iOS release workflow):
  ASC_KEY_ID     — App Store Connect API key ID (e.g. "ABC123DEF4")
  ASC_ISSUER_ID  — Issuer ID from App Store Connect → Users & Access
  ASC_P8         — Full PEM contents of the .p8 private key

Usage:
  python3 scripts/asc_upload.py path/to/Translate.ipa
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import jwt  # PyJWT
except ImportError:
    sys.exit("ERROR: PyJWT not installed. Run `pip install pyjwt cryptography`.")


def _env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"ERROR: ${name} not set")
    return val


def mint_jwt(key_id: str, issuer_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    # 20-minute validity window (App Store Connect's maximum).
    return jwt.encode(
        {
            "iss": issuer_id,
            "iat": now,
            "exp": now + 20 * 60,
            "aud": "appstoreconnect-v1",
        },
        private_key_pem,
        algorithm="ES256",
        headers={"kid": key_id, "typ": "JWT"},
    )


def preflight(token: str) -> None:
    """Hit a trivial ASC API endpoint to confirm the key is accepted
    before spending ten minutes uploading a ~200 MB IPA."""
    req = urllib.request.Request(
        "https://api.appstoreconnect.apple.com/v1/apps?limit=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status != 200:
                sys.exit(f"ERROR: ASC preflight returned HTTP {r.status}")
    except urllib.error.HTTPError as e:
        sys.exit(f"ERROR: ASC preflight failed: {e.code} {e.reason}")


def stage_p8(key_id: str, private_key_pem: str) -> pathlib.Path:
    """altool expects the .p8 at ~/.appstoreconnect/private_keys/ —
    plant it there and return the path for logging."""
    dst_dir = pathlib.Path.home() / ".appstoreconnect/private_keys"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"AuthKey_{key_id}.p8"
    dst.write_text(private_key_pem, encoding="utf-8")
    dst.chmod(0o600)
    return dst


def upload_with_altool(ipa_path: pathlib.Path, key_id: str, issuer_id: str) -> None:
    cmd = [
        "xcrun", "altool", "--upload-app",
        "-f", str(ipa_path),
        "-t", "ios",
        "--apiKey", key_id,
        "--apiIssuer", issuer_id,
        "--output-format", "normal",
    ]
    print(">", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        sys.exit(f"altool upload failed (exit {result.returncode})")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: asc_upload.py <path-to-ipa>")
    ipa = pathlib.Path(sys.argv[1]).resolve()
    if not ipa.is_file():
        sys.exit(f"ERROR: IPA not found: {ipa}")

    key_id    = _env("ASC_KEY_ID")
    issuer_id = _env("ASC_ISSUER_ID")
    p8        = _env("ASC_P8")

    token = mint_jwt(key_id, issuer_id, p8)
    preflight(token)
    stage_p8(key_id, p8)
    upload_with_altool(ipa, key_id, issuer_id)
    print("Upload complete — TestFlight will process the build in a few minutes.")


if __name__ == "__main__":
    main()
