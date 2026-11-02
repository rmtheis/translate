#!/usr/bin/env python3
"""
Create the one-time donation in-app purchase on App Store Connect, idempotently.

A consumable: a tip with nothing to restore. Each step is skipped when already done:
the product, one localization per store listing language (_donation_i18n.py), the US$
base price (Apple equalizes the other territories), availability in every territory,
and the App Review screenshot. A new IAP stays READY_TO_SUBMIT until a version carries
it: asc_resubmit.py adds it to that version's review submission.

The product id must match SupportPurchase.productID in ios/Translate/SupportPurchase.swift.

Dry run by default: prints what is missing. --create creates it.

Environment:
  ASC_KEY_ID, ASC_ISSUER_ID, ASC_P8 (the .p8 contents)
  ASC_BUNDLE_ID — defaults to com.qvyshift.translate

Usage:
  python3 scripts/asc_create_donation_iap.py [--create]
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import os
import sys
import time

try:
    import jwt
    import requests
except ImportError:
    sys.exit("ERROR: pip install pyjwt cryptography requests")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _donation_i18n import ENGLISH, TEXT  # noqa: E402

BASE = "https://api.appstoreconnect.apple.com"
PRODUCT_ID = "com.qvyshift.translate.support_2026"
PRICE_USD = "2.99"
REVIEW_SCREENSHOT = (pathlib.Path(__file__).resolve().parent.parent
                     / "ios/appstore/iap/support_review.png")
REVIEW_NOTE = ("An optional one-time donation to support development of the app. It unlocks "
               "nothing and every feature stays free. To find it: gear icon at the top right "
               "of the main screen, then the Donate row. After a purchase that row becomes a "
               "thank-you line.")


def token() -> str:
    now = int(time.time())
    return jwt.encode({"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 1200,
                       "aud": "appstoreconnect-v1"},
                      os.environ["ASC_P8"], algorithm="ES256",
                      headers={"kid": os.environ["ASC_KEY_ID"], "typ": "JWT"})


def api(method: str, path: str, body: dict | None = None, params: dict | None = None,
        ok_missing: bool = False) -> dict:
    r = requests.request(method, BASE + path, params=params, json=body, timeout=60,
                         headers={"Authorization": f"Bearer {token()}"})
    if ok_missing and r.status_code == 404:
        return {}
    if not r.ok:
        sys.exit(f"{method} {path} -> {r.status_code}\n{r.text[:1500]}")
    return r.json() if r.text else {}


def find_app(bundle_id: str) -> str:
    # filter[bundleId] is a prefix match, so pick the exact row.
    rows = api("GET", "/v1/apps", params={"filter[bundleId]": bundle_id, "limit": 200})["data"]
    for row in rows:
        if row["attributes"]["bundleId"] == bundle_id:
            return row["id"]
    sys.exit(f"ERROR: no App Store Connect app with bundleId={bundle_id}")


def all_territories() -> list[str]:
    return [t["id"] for t in api("GET", "/v1/territories", params={"limit": 200})["data"]]


def upload_review_screenshot(iap_id: str) -> None:
    data = REVIEW_SCREENSHOT.read_bytes()
    res = api("POST", "/v1/inAppPurchaseAppStoreReviewScreenshots", {"data": {
        "type": "inAppPurchaseAppStoreReviewScreenshots",
        "attributes": {"fileName": REVIEW_SCREENSHOT.name, "fileSize": len(data)},
        "relationships": {"inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": iap_id}}},
    }})["data"]
    for op in res["attributes"]["uploadOperations"]:
        chunk = data[op["offset"]:op["offset"] + op["length"]]
        requests.request(op["method"], op["url"], data=chunk, timeout=120,
                         headers={h["name"]: h["value"] for h in op["requestHeaders"]}
                         ).raise_for_status()
    api("PATCH", f"/v1/inAppPurchaseAppStoreReviewScreenshots/{res['id']}", {"data": {
        "type": "inAppPurchaseAppStoreReviewScreenshots", "id": res["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()},
    }})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--create", action="store_true", help="create what is missing")
    args = ap.parse_args()

    app_id = find_app(os.environ.get("ASC_BUNDLE_ID", "com.qvyshift.translate"))
    found = api("GET", f"/v1/apps/{app_id}/inAppPurchasesV2",
                params={"filter[productId]": PRODUCT_ID})["data"]
    if found:
        iap_id = found[0]["id"]
        print(f"IAP exists ({found[0]['attributes']['inAppPurchaseType']}, "
              f"{found[0]['attributes']['state']})")
    elif not args.create:
        print(f"DRY RUN: would create CONSUMABLE {PRODUCT_ID} at US$ {PRICE_USD}, "
              f"{len(TEXT)} localizations, all territories, review screenshot "
              f"{REVIEW_SCREENSHOT.name}. Re-run with --create.")
        return
    else:
        iap_id = api("POST", "/v2/inAppPurchases", {"data": {
            "type": "inAppPurchases",
            "attributes": {"name": ENGLISH[0], "productId": PRODUCT_ID,
                           "inAppPurchaseType": "CONSUMABLE", "reviewNote": REVIEW_NOTE},
            "relationships": {"app": {"data": {"type": "apps", "id": app_id}}},
        }})["data"]["id"]
        print("IAP created")

    have = {row["attributes"]["locale"] for row in api(
        "GET", f"/v2/inAppPurchases/{iap_id}/inAppPurchaseLocalizations",
        params={"limit": 200})["data"]}
    missing = [locale for locale in TEXT if locale not in have]
    if missing and not args.create:
        print(f"DRY RUN: would add localizations {missing}")
    elif missing:
        for locale in missing:
            name, description = TEXT[locale]
            api("POST", "/v1/inAppPurchaseLocalizations", {"data": {
                "type": "inAppPurchaseLocalizations",
                "attributes": {"locale": locale, "name": name, "description": description},
                "relationships": {"inAppPurchaseV2": {"data": {"type": "inAppPurchases", "id": iap_id}}},
            }})
        print(f"{len(missing)} localizations added")

    prices = api("GET", f"/v1/inAppPurchasePriceSchedules/{iap_id}/manualPrices", ok_missing=True)
    if not prices.get("data") and args.create:
        points = api("GET", f"/v2/inAppPurchases/{iap_id}/pricePoints",
                     params={"filter[territory]": "USA", "limit": 8000})["data"]
        point = [p for p in points if p["attributes"]["customerPrice"] == PRICE_USD][0]
        api("POST", "/v1/inAppPurchasePriceSchedules", {
            "data": {"type": "inAppPurchasePriceSchedules", "relationships": {
                "inAppPurchase": {"data": {"type": "inAppPurchases", "id": iap_id}},
                "baseTerritory": {"data": {"type": "territories", "id": "USA"}},
                "manualPrices": {"data": [{"type": "inAppPurchasePrices", "id": "${p}"}]}}},
            "included": [{"type": "inAppPurchasePrices", "id": "${p}", "attributes": {"startDate": None},
                          "relationships": {"inAppPurchasePricePoint": {
                              "data": {"type": "inAppPurchasePricePoints", "id": point["id"]}}}}]})
        print(f"Price US$ {PRICE_USD} (USA base, others equalized by Apple)")

    availability = api("GET", f"/v2/inAppPurchases/{iap_id}/inAppPurchaseAvailability", ok_missing=True)
    if not availability.get("data") and args.create:
        territories = all_territories()
        api("POST", "/v1/inAppPurchaseAvailabilities", {"data": {
            "type": "inAppPurchaseAvailabilities",
            "attributes": {"availableInNewTerritories": True},
            "relationships": {
                "inAppPurchase": {"data": {"type": "inAppPurchases", "id": iap_id}},
                "availableTerritories": {"data": [{"type": "territories", "id": t} for t in territories]},
            }}})
        print(f"Available in {len(territories)} territories")

    shot = api("GET", f"/v2/inAppPurchases/{iap_id}/appStoreReviewScreenshot", ok_missing=True)
    if not shot.get("data") and args.create:
        upload_review_screenshot(iap_id)
        print("Review screenshot uploaded")

    state = api("GET", f"/v2/inAppPurchases/{iap_id}")["data"]["attributes"]["state"]
    print(f"IAP state: {state}")


if __name__ == "__main__":
    main()
