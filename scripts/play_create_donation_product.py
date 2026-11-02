#!/usr/bin/env python3
"""
Create (or show) the one-time donation product on Google Play.

Pricing: a US$ base price converted to every Play region with Play's own converter
(monetization.convertRegionPrices, the same auto-conversion Play Console offers), plus a
new-regions config so future Play countries get a price too. Play converts once, on the
date the price is set; it does not follow exchange rates afterwards.

The product id must match support_product_id in android/app/src/main/res/values/strings.xml.

Dry run by default: converts the prices and prints the plan. --create upserts the product
and activates its purchase option. --create-if-missing does the same only when the product
doesn't exist yet, so its prices are never re-converted: release-android.yml runs this after
every upload, because Play refuses the product until an uploaded bundle declares BILLING.
--show prints the product as Play has it.

Environment:
  SA_JSON        — Play Developer API service-account JSON contents, or
  SA_JSON_FILE   — path to that JSON (locally: the androidpublisher key listed in
                   ~/.claude/CLAUDE.md under "Google Play / App Store reviews")
  PACKAGE_NAME   — defaults to com.qvyshift.translate

Usage:
  python3 scripts/play_create_donation_product.py
      [--create | --create-if-missing [--retries N] | --show]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _donation_i18n import PLAY, TEXT  # noqa: E402

PRODUCT_ID = "support_2026"
USD = 2.99
PURCHASE_OPTION_ID = "buy"
SHOW_REGIONS = ("US", "DE", "GB", "JP", "IN", "BR", "CA", "ES")
RETRY_SECONDS = 60


def service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("pip install google-auth google-api-python-client")
    raw = os.environ.get("SA_JSON")
    path = os.environ.get("SA_JSON_FILE")
    if raw:
        info = json.loads(raw)
    elif path:
        info = json.loads(pathlib.Path(path).expanduser().read_text())
    else:
        sys.exit("ERROR: set SA_JSON (contents) or SA_JSON_FILE (path)")
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/androidpublisher"])
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def money(currency: str, amount: float) -> dict:
    units = int(amount)
    return {"currencyCode": currency, "units": str(units),
            "nanos": int(round((amount - units) * 1e9))}


def fmt(m: dict) -> str:
    return f"{m.get('currencyCode')} {int(m.get('units', 0)) + int(m.get('nanos', 0)) / 1e9:.2f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--create", action="store_true", help="upsert and activate the product")
    ap.add_argument("--create-if-missing", action="store_true",
                    help="--create, but leave an existing product untouched")
    ap.add_argument("--retries", type=int, default=0,
                    help=f"retry a billing-permission refusal this many times, "
                         f"{RETRY_SECONDS} s apart (a fresh upload may need a moment)")
    ap.add_argument("--show", action="store_true", help="print the product as stored on Play")
    args = ap.parse_args()

    from googleapiclient.errors import HttpError

    package = os.environ.get("PACKAGE_NAME", "com.qvyshift.translate")
    svc = service()
    otp = svc.monetization().onetimeproducts()

    try:
        if args.show:
            print(json.dumps(otp.get(packageName=package, productId=PRODUCT_ID).execute(),
                             indent=1, ensure_ascii=False))
            return

        if args.create_if_missing:
            try:
                otp.get(packageName=package, productId=PRODUCT_ID).execute()
                print(f"Product {PRODUCT_ID} already exists on {package}; left untouched.")
                return
            except HttpError as e:
                if e.resp.status != 404:
                    raise

        conv = svc.monetization().convertRegionPrices(
            packageName=package, body={"price": money("USD", USD)}).execute()
        regions_version = conv["regionVersion"]["version"]
        prices = conv["convertedRegionPrices"]
        configs = []
        for region, entry in sorted(prices.items()):
            # US gets the base price itself, not a round trip through the converter.
            price = money("USD", USD) if region == "US" else entry["price"]
            configs.append({"regionCode": region, "price": price, "availability": "AVAILABLE"})
        other = conv["convertedOtherRegionsPrice"]
        product = {
            "packageName": package,
            "productId": PRODUCT_ID,
            "listings": [{"languageCode": PLAY[locale], "title": title, "description": description}
                         for locale, (title, description) in TEXT.items()],
            "purchaseOptions": [{
                "purchaseOptionId": PURCHASE_OPTION_ID,
                "buyOption": {"legacyCompatible": True, "multiQuantityEnabled": False},
                "regionalPricingAndAvailabilityConfigs": configs,
                "newRegionsConfig": {"usdPrice": other["usdPrice"], "eurPrice": other["eurPrice"],
                                     "availability": "AVAILABLE"},
            }],
            "taxAndComplianceSettings": {"isTokenizedDigitalAsset": False},
        }
        print(f"Product {PRODUCT_ID} on {package}: {len(product['listings'])} listing languages")
        print(f"Regions version {regions_version}; {len(configs)} regional prices from "
              f"US$ {USD:.2f}, e.g.")
        for code in SHOW_REGIONS:
            if code in prices:
                print(f"  {code}: {fmt(money('USD', USD) if code == 'US' else prices[code]['price'])}")
        print(f"  new regions: {fmt(other['usdPrice'])} / {fmt(other['eurPrice'])}")

        if not (args.create or args.create_if_missing):
            print("\nDRY RUN: nothing created. Re-run with --create to upsert and activate.")
            return

        body = {"requests": [{
            "oneTimeProduct": product,
            "updateMask": "listings,purchaseOptions,taxAndComplianceSettings",
            "regionsVersion": {"version": regions_version},
            "allowMissing": True,
            "latencyTolerance": "PRODUCT_UPDATE_LATENCY_TOLERANCE_LATENCY_SENSITIVE",
        }]}
        for attempt in range(args.retries + 1):
            try:
                created = otp.batchUpdate(packageName=package, body=body).execute()
                break
            except HttpError as e:
                if (attempt == args.retries or e.resp.status != 400
                        or b"billing permission" not in e.content):
                    raise
                print(f"Play refused the product for now (billing permission); "
                      f"retry {attempt + 1}/{args.retries} in {RETRY_SECONDS} s", flush=True)
                time.sleep(RETRY_SECONDS)
        state = created["oneTimeProducts"][0]["purchaseOptions"][0].get("state")
        print(f"\nUpserted {PRODUCT_ID}; purchase option '{PURCHASE_OPTION_ID}' state: {state}")
        if state != "ACTIVE":
            activated = otp.purchaseOptions().batchUpdateStates(
                packageName=package, productId=PRODUCT_ID,
                body={"requests": [{"activatePurchaseOptionRequest": {
                    "packageName": package, "productId": PRODUCT_ID,
                    "purchaseOptionId": PURCHASE_OPTION_ID,
                    "latencyTolerance": "PRODUCT_UPDATE_LATENCY_TOLERANCE_LATENCY_SENSITIVE"}}]}
            ).execute()
            state = activated["oneTimeProducts"][0]["purchaseOptions"][0].get("state")
            print(f"Activated; state now: {state}")
    except HttpError as e:
        sys.exit(f"Play API error {e.resp.status}: {e.content.decode(errors='replace')[:1200]}")


if __name__ == "__main__":
    main()
