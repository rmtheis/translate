#!/usr/bin/env python3
"""
update_ios_signing_secrets.py

Refreshes the three code-signing secrets .github/workflows/release-ios.yml
reads:

  IOS_DISTRIBUTION_CERT_P12        base64 .p12 holding the distribution cert + key
  IOS_DISTRIBUTION_CERT_PASSWORD   password of that .p12
  IOS_PROVISIONING_PROFILE         base64 of the "Translate App Store" profile

The secrets are copies. Nothing refreshes them when the distribution
certificate is rotated or the profile is recreated in the Apple developer
account, so run this after either. See "CI / release" in ios/README.md.

Usage (needs `gh` signed in with access to this repo):

  ASC_KEY_ID=... ASC_ISSUER_ID=... \\
    python3 scripts/update_ios_signing_secrets.py --signing-dir DIR [--dry-run]

DIR holds the current distribution certificate and its private key as
`dist.cer` and `dist.key`. The App Store Connect key is read from ASC_P8 (PEM
text) or, when that is unset, from
~/.appstoreconnect/private_keys/AuthKey_<ASC_KEY_ID>.p8.

What it does:
  1. Checks that dist.key belongs to dist.cer and that the cert has not expired.
  2. Downloads the one ACTIVE App Store profile of com.qvyshift.translate from
     the App Store Connect API and checks that it lists that certificate and
     still has the name the workflow signs with.
  3. Builds a .p12 with a random throwaway password and imports it into a
     scratch keychain, the way the workflow does, to prove it is readable.
  4. Unless --dry-run: sets the three secrets.
"""

import argparse
import base64
import datetime
import hashlib
import os
import plistlib
import secrets
import ssl
import subprocess
import sys
import tempfile
import time

import jwt
import requests

# Named explicitly: this checkout has two remotes (the fork and its upstream),
# and `gh secret set` refuses to guess between them.
REPO = "rmtheis/translate"
BUNDLE_ID = "com.qvyshift.translate"
# release-ios.yml passes this name as PROVISIONING_PROFILE_SPECIFIER and in
# ExportOptions.plist, so a profile under another name would not be picked up.
PROFILE_NAME = "Translate App Store"

# macOS's own LibreSSL. It writes the older .p12 encryption that `security
# import` reads on every runner image; OpenSSL 3 (Homebrew) defaults to a newer
# one that `security import` has rejected with "MAC verification failed".
OPENSSL = "/usr/bin/openssl"


def run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, capture_output=True, **kwargs)


def die(message):
    sys.exit(f"ERROR: {message}")


def asc_token():
    key_id = os.environ.get("ASC_KEY_ID") or die("ASC_KEY_ID is not set")
    issuer_id = os.environ.get("ASC_ISSUER_ID") or die("ASC_ISSUER_ID is not set")
    key = os.environ.get("ASC_P8")
    if not key:
        path = os.path.expanduser(f"~/.appstoreconnect/private_keys/AuthKey_{key_id}.p8")
        if not os.path.exists(path):
            die(f"ASC_P8 is not set and {path} does not exist")
        with open(path) as f:
            key = f.read()
    now = int(time.time())
    return jwt.encode(
        {"iss": issuer_id, "iat": now, "exp": now + 900, "aud": "appstoreconnect-v1"},
        key,
        algorithm="ES256",
        headers={"kid": key_id},
    )


def load_certificate(signing_dir):
    """Returns (DER bytes, SHA-1 hex, subject common name) after checking key and expiry."""
    cer_path = os.path.join(signing_dir, "dist.cer")
    key_path = os.path.join(signing_dir, "dist.key")
    for path in (cer_path, key_path):
        if not os.path.exists(path):
            die(f"{path} not found")
    with open(cer_path, "rb") as f:
        raw = f.read()
    der = ssl.PEM_cert_to_DER_cert(raw.decode()) if raw.lstrip().startswith(b"-----BEGIN") else raw

    def x509(*args):
        return run([OPENSSL, "x509", "-inform", "DER", *args], input=der).stdout

    cert_pub = x509("-noout", "-pubkey")
    key_pub = run([OPENSSL, "pkey", "-in", key_path, "-pubout"]).stdout
    if cert_pub.strip() != key_pub.strip():
        die("dist.key is not the private key of dist.cer")
    if subprocess.run([OPENSSL, "x509", "-inform", "DER", "-noout", "-checkend", "0"],
                      input=der, capture_output=True).returncode != 0:
        die("dist.cer has expired; rotate the certificate first")
    end = x509("-noout", "-enddate").decode().strip().split("=", 1)[1]
    subject = x509("-noout", "-subject").decode()
    name = subject.split("CN=", 1)[1].split("/", 1)[0].strip() if "CN=" in subject else "Apple Distribution"
    sha1 = hashlib.sha1(der).hexdigest().upper()
    print(f"Certificate: {name}\n  SHA-1 {sha1}, expires {end}")
    return der, sha1, name


def fetch_profile(cert_sha1):
    """Returns the bytes of the app's one ACTIVE App Store profile."""
    headers = {"Authorization": f"Bearer {asc_token()}"}
    url = "https://api.appstoreconnect.apple.com/v1/profiles"
    params = {
        "filter[profileType]": "IOS_APP_STORE",
        "filter[profileState]": "ACTIVE",
        "include": "bundleId",
        "fields[bundleIds]": "identifier",
        "limit": 200,
    }
    found, bundle_ids = [], {}
    while url:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if not r.ok:
            die(f"App Store Connect answered {r.status_code}: {r.text[:500]}")
        page = r.json()
        for inc in page.get("included", []):
            if inc["type"] == "bundleIds":
                bundle_ids[inc["id"]] = inc["attributes"]["identifier"]
        for profile in page["data"]:
            rel = profile["relationships"]["bundleId"]["data"]
            if rel and bundle_ids.get(rel["id"]) == BUNDLE_ID:
                found.append(profile["attributes"])
        url, params = page.get("links", {}).get("next"), None

    if len(found) != 1:
        die(f"{BUNDLE_ID}: expected exactly one ACTIVE App Store profile, found "
            f"{[p['name'] for p in found]}")
    content = base64.b64decode(found[0]["profileContent"])
    plist = plistlib.loads(run(["security", "cms", "-D"], input=content).stdout)
    if plist["Name"] != PROFILE_NAME:
        die(f"the profile is named '{plist['Name']}', but release-ios.yml signs with '{PROFILE_NAME}'")
    cert_hashes = [hashlib.sha1(c).hexdigest().upper() for c in plist["DeveloperCertificates"]]
    if cert_sha1 not in cert_hashes:
        die(f"profile '{plist['Name']}' does not list this certificate; recreate the profile against it")
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if plist["ExpirationDate"] <= now:
        die(f"profile '{plist['Name']}' expired on {plist['ExpirationDate']:%Y-%m-%d}")
    print(f"Profile: '{plist['Name']}', expires {plist['ExpirationDate']:%Y-%m-%d}")
    return content


def build_p12(signing_dir, cert_der, cert_name, workdir):
    """Returns (p12 bytes, password) after a trial import into a scratch keychain."""
    password = secrets.token_urlsafe(24)
    pem_path = os.path.join(workdir, "dist.pem")
    p12_path = os.path.join(workdir, "dist.p12")
    with open(pem_path, "w") as f:
        f.write(ssl.DER_cert_to_PEM_cert(cert_der))
    run([OPENSSL, "pkcs12", "-export", "-inkey", os.path.join(signing_dir, "dist.key"),
         "-in", pem_path, "-name", cert_name, "-out", p12_path, "-passout", "env:P12_PASSWORD"],
        env={**os.environ, "P12_PASSWORD": password})

    # Same import the workflow's "Import signing cert" step does. A keychain
    # given by path is not added to the user's search list.
    keychain = os.path.join(workdir, "trial.keychain-db")
    keychain_password = secrets.token_urlsafe(16)
    run(["security", "create-keychain", "-p", keychain_password, keychain])
    try:
        run(["security", "unlock-keychain", "-p", keychain_password, keychain])
        run(["security", "import", p12_path, "-k", keychain, "-P", password,
             "-T", "/usr/bin/codesign", "-T", "/usr/bin/security"])
        identities = run(["security", "find-identity", "-v", "-p", "codesigning", keychain]).stdout.decode()
    finally:
        subprocess.run(["security", "delete-keychain", keychain], capture_output=True)
    if "1 valid identities found" not in identities:
        die(f"trial keychain import did not yield one valid signing identity:\n{identities}")
    print("Trial import of the .p12 into a scratch keychain: one valid signing identity")
    with open(p12_path, "rb") as f:
        return f.read(), password


def set_secret(name, value):
    # Value goes over stdin so it never appears in a process listing.
    result = subprocess.run(["gh", "secret", "set", name, "--repo", REPO],
                            input=value.encode(), capture_output=True)
    if result.returncode != 0:
        die(f"gh secret set {name} failed: {result.stderr.decode().strip()}")
    print(f"  set {name}")


def main():
    parser = argparse.ArgumentParser(
        description="Refresh the iOS signing secrets release-ios.yml reads.")
    parser.add_argument("--signing-dir", required=True,
                        help="folder holding dist.cer and dist.key")
    parser.add_argument("--dry-run", action="store_true",
                        help="run every check, change nothing")
    args = parser.parse_args()
    signing_dir = os.path.expanduser(args.signing_dir)

    cert_der, cert_sha1, cert_name = load_certificate(signing_dir)
    profile = fetch_profile(cert_sha1)
    with tempfile.TemporaryDirectory() as workdir:
        p12, password = build_p12(signing_dir, cert_der, cert_name, workdir)

    if args.dry_run:
        print("Dry run: all checks passed; no secret set.")
        return

    print("Setting secrets:")
    set_secret("IOS_DISTRIBUTION_CERT_P12", base64.b64encode(p12).decode())
    set_secret("IOS_DISTRIBUTION_CERT_PASSWORD", password)
    set_secret("IOS_PROVISIONING_PROFILE", base64.b64encode(profile).decode())
    print("Done.")


if __name__ == "__main__":
    main()
