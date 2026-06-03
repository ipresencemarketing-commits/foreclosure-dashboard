#!/usr/bin/env python3
"""
Xome Auctions — Virginia Foreclosure Sales Scraper
---------------------------------------------------
Scrapes upcoming trustee sale listings from Xome's REST API:

  Step 1 — County/date/ID map:
    GET https://apis.xome.com/auctions/listing/v1/Foreclosures/VA/Assets
        ?auctionStartAfter=YYYY-MM-DD

  Step 2 — Batch property details (all IDs in one call):
    GET https://apis.xome.com/auctions/listing/v1/Foreclosures/Assets
        ?assetIds=P114A37,P113MIO,...&fetchListingInfo=true&fetchLocation=true

  Both calls require: Authorization: 8ec77f3db3ec43e4a62bb00c78b031e0

Site URL:
  https://www.xome.com/auctions/foreclosuresales?ss=virginia&cl=false

Fields provided:
  ✅ Address (street, city, state, ZIP from fCLTListingInfo)
  ✅ County (from county name in Assets map)
  ✅ Sale Date (saleStartDate MM/DD/YYYY)
  ✅ Sale Time (liveAuctionStartTime)
  ✅ Sale Location (liveAuctionLocationDescription — full courthouse address)
  ✅ Starting Bid (formattedStartingBid — may be "TBD")
  ✅ Listing URL (individual property page on xome.com)
  ✅ Property Image URL
  ❌ Beds/baths/sqft (not in this API)
  ❌ Lender / trustee / notice text
  🔄 Owner / property details (GIS backfill)
"""

import json
import os
import re
import sys
import logging
import time
from datetime import date, datetime

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

ASSETS_URL   = "https://apis.xome.com/auctions/listing/v1/Foreclosures/VA/Assets"
DETAILS_URL  = "https://apis.xome.com/auctions/listing/v1/Foreclosures/Assets"
SOURCE_URL   = "https://www.xome.com/auctions/foreclosuresales?ss=virginia&cl=false"
SOURCE_TAG   = "xome"
OUTPUT_FILE  = os.path.join(PROJECT_ROOT, "data", "foreclosures_xome.json")

# Public auth token embedded in the site's JS (not user-specific)
AUTH_TOKEN   = "8ec77f3db3ec43e4a62bb00c78b031e0"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Authorization": AUTH_TOKEN,
    "Accept":        "application/json",
    "Content-Type":  "application/json",
    "Referer":       "https://www.xome.com/",
}

# Xome county name format: "Fairfax County, Virginia" → "Fairfax"
def parse_county(xome_county: str) -> str:
    """
    "Fairfax County, Virginia"       → "Fairfax"
    "Chesapeake City County, Virginia" → "Chesapeake City"
    "Alexandria County, Virginia"    → "Alexandria City" (independent city)
    """
    # Strip ", Virginia" suffix
    name = re.sub(r",\s*Virginia\s*$", "", xome_county.strip(), flags=re.IGNORECASE)
    # Strip trailing "County" (but not "City County" — keep "City")
    name = re.sub(r"\s+County$", "", name.strip(), flags=re.IGNORECASE)
    name = name.strip()

    # Try county_display() to normalise
    cd = county_display(name)
    if cd:
        return cd

    # Fallback: title-case the cleaned name
    return name.title()


def parse_sale_date(raw: str):
    """'08/03/2026' → '2026-08-03'"""
    try:
        return datetime.strptime(raw.strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def parse_starting_bid(raw: str):
    """'$125,000' or 'TBD' → int or None"""
    if not raw or raw.strip().upper() in ("TBD", "N/A", ""):
        return None
    m = re.search(r"[\d,]+", raw.replace(" ", ""))
    if m:
        try:
            return int(m.group().replace(",", ""))
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting Xome Auction scraper (VA, since {since_date})")

    # ── Step 1: county → date → [id, ...] map ────────────────────────────
    try:
        r1 = requests.get(
            ASSETS_URL,
            params={"auctionStartAfter": since_date.isoformat()},
            headers=HEADERS,
            timeout=20,
        )
        r1.raise_for_status()
        counties_data = r1.json()["data"][0]["counties"]
    except Exception as e:
        log.error(f"  Assets API error: {e}")
        return []

    # Build flat list: [{id, county, date_str}, ...]
    props_meta = {}
    for xome_county, dates in counties_data.items():
        county = parse_county(xome_county)
        for date_str, ids in dates.items():
            for pid in ids:
                props_meta[pid] = {"county": county, "date_str": date_str}

    total_ids = len(props_meta)
    log.info(f"  Found {total_ids} property IDs")

    if not total_ids:
        log.info("  No properties found")
        return []

    # ── Step 2: batch fetch all property details ──────────────────────────
    try:
        r2 = requests.get(
            DETAILS_URL,
            params={
                "assetIds":        ",".join(props_meta.keys()),
                "fetchListingInfo": "true",
                "fetchLocation":    "true",
            },
            headers=HEADERS,
            timeout=30,
        )
        r2.raise_for_status()
        details = r2.json().get("data", [])
    except Exception as e:
        log.error(f"  Details API error: {e}")
        return []

    log.info(f"  Fetched details for {len(details)} properties")

    # ── Step 3: parse listings ────────────────────────────────────────────
    listings   = []
    seen_ids   = set()
    skipped    = 0

    for item in details:
        pid       = item.get("displayId", "")
        meta      = props_meta.get(pid, {})
        listing_info = item.get("fCLTListingInfo", {})

        sale_date = parse_sale_date(item.get("saleStartDate", ""))
        if not sale_date:
            skipped += 1
            continue
        if sale_date < since_date.isoformat():
            skipped += 1
            continue

        street    = listing_info.get("unstructuredAddress", "").strip()
        city      = listing_info.get("city", "").strip()
        zipcode   = listing_info.get("postalCode", "").strip()
        state     = listing_info.get("state", "VA")

        if state != "VA" or not street:
            skipped += 1
            continue

        address  = f"{street.title()}, {city}, VA {zipcode}"
        county   = meta.get("county") or ""

        sale_time     = item.get("liveAuctionStartTime", "")
        sale_location = item.get("liveAuctionLocationDescription") or courthouse_location(county)
        starting_bid  = parse_starting_bid(item.get("formattedStartingBid", ""))
        sale_status   = item.get("saleStatus", "")
        bid_increment = item.get("bidIncrement")

        listing_path = listing_info.get("listingURL", "")
        listing_url  = f"https://www.xome.com{listing_path}" if listing_path else SOURCE_URL

        days_until = (date.fromisoformat(sale_date) - date.today()).days

        listing_id = make_id(address, sale_date)
        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        listings.append({
            "id":              listing_id,
            "address":         address,
            "city":            city,
            "county":          county,
            "state":           "VA",
            "zip":             zipcode,
            "property_type":   "single-family",
            "stage":           "auction",
            "sale_date":       sale_date,
            "sale_time":       sale_time,
            "sale_location":   sale_location,
            "days_until_sale": days_until,
            "asking_price":    starting_bid,
            "lender":          None,
            "trustee":         "Xome Auctions",
            "notice_text":     (
                f"Xome ID: {pid}"
                + (f" | Status: {sale_status}" if sale_status else "")
                + (f" | Bid increment: ${int(bid_increment):,}" if bid_increment else "")
            ),
            "source":          SOURCE_TAG,
            "source_url":      listing_url,
            "first_seen":      date.today().isoformat(),
            "is_new":          True,
        })

    log.info(
        f"  {len(listings)} listings kept | {skipped} skipped"
    )
    return listings


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(listings: list):
    today = date.today().isoformat()
    existing = {"meta": {}, "listings": []}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            pass

    existing_map = {l["id"]: l for l in existing.get("listings", [])}
    added = updated = 0
    for l in listings:
        if l["id"] in existing_map:
            existing_map[l["id"]].update({k: v for k, v in l.items() if v is not None})
            updated += 1
        else:
            existing_map[l["id"]] = l
            added += 1

    out = {
        "meta":     {"source": SOURCE_TAG, "updated": today, "url": SOURCE_URL},
        "listings": list(existing_map.values()),
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2, default=str)

    log.info(
        f"Saved → {OUTPUT_FILE}  "
        f"({added} added, {updated} updated, {len(out['listings'])} total)"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    listings = scrape()
    save(listings)
    log.info("Done.")
