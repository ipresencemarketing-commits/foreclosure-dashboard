#!/usr/bin/env python3
"""
ServiceLink Auction — Virginia Foreclosure Sales Scraper
---------------------------------------------------------
Scrapes upcoming trustee sale listings from the ServiceLink REST API:
  https://www.servicelinkauction.com/api/listingsvc/v1/listings?state=VA&...

Site URL (for reference):
  https://www.servicelinkauction.com/foreclosures/virginia

The site is an Angular SPA backed by a public JSON REST API. No Playwright
needed — a plain requests.get() returns the full dataset.

Fields provided (richest source in the pipeline):
  ✅ Address (street, city, state, ZIP)
  ✅ County (explicit from API)
  ✅ Sale Date (ISO datetime)
  ✅ Sale Time (H:MM AM/PM)
  ✅ Sale Location (full courthouse address from tpsSaleLocation)
  ✅ Property Type (Single family, Town House, Condo, etc.)
  ✅ Beds / Baths / SqFt (from propertyInfo)
  ✅ Year Built
  ✅ Lot Size
  ✅ Occupancy Status (Occupied / Vacant)
  ✅ Foreclosure Attorney / Trustee (e.g. Aldridge Pite, LLP)
  ✅ Attorney Reference # (case identifier)
  ✅ Listing URL (individual property detail page)
  ✅ Cash Only flag
  ❌ Opening bid / asking price (not in API)
  ❌ Lender name
  🔄 Owner info (GIS backfill — property details already present)
"""

import json
import os
import re
import sys
import logging
from datetime import date, datetime

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

API_URL     = "https://www.servicelinkauction.com/api/listingsvc/v1/listings"
SOURCE_URL  = "https://www.servicelinkauction.com/foreclosures/virginia"
SOURCE_TAG  = "servicelink"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_servicelink.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":   "application/json",
    "Referer":  "https://www.servicelinkauction.com/",
}

API_PARAMS = {
    "state":                  "VA",
    "limit":                  "100",   # API max is 100
    "sortByEndingSoonest":    "true",
    "listingProgramWebsite":  "Foreclosure Sale",
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sale_date(raw: str):
    """'2026-06-03T00:00:00' → '2026-06-03'"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:19]).date().isoformat()
    except ValueError:
        return None


def resolve_county(raw_county: str) -> str:
    """Normalise API county string → sheet display name."""
    if not raw_county:
        return None
    # API sometimes returns "Fairfax County" — strip trailing " County"
    cleaned = re.sub(r"\s+County$", "", raw_county.strip(), flags=re.IGNORECASE)
    cd = county_display(cleaned)
    if cd:
        return cd
    # Independent cities: "Newport News City County" → "Newport News City"
    cleaned2 = re.sub(r"\s+County$", "", raw_county.strip(), flags=re.IGNORECASE)
    return cleaned2.strip().title()


def build_beds_baths_sqft(prop: dict):
    """Build a 'Xbd / Xba / X sqft' summary string."""
    parts = []
    beds = prop.get("bedrooms")
    baths = prop.get("fullBathrooms")
    sqft = prop.get("interiorSqFt")
    if beds is not None:
        parts.append(f"{int(beds)}bd")
    if baths is not None:
        parts.append(f"{int(baths)}ba")
    if sqft is not None:
        parts.append(f"{int(sqft):,} sqft")
    return " / ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting ServiceLink Auction scraper (VA, since {since_date})")

    try:
        r = requests.get(API_URL, params=API_PARAMS, headers=HEADERS, timeout=20)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        log.error(f"  API fetch error: {e}")
        return []

    raw_listings = payload.get("data", [])
    total = payload.get("searchResultCount", len(raw_listings))
    log.info(f"  API returned {len(raw_listings)} of {total} listings")

    listings  = []
    seen_ids  = set()
    skipped_status = 0
    skipped_date   = 0

    for item in raw_listings:
        # Only active listings
        status = item.get("foreclosureSaleStatusWebsite", "")
        if status.lower() not in ("active", "on website", ""):
            skipped_status += 1
            continue

        sale_date = parse_sale_date(item.get("foreclosureSaleDate", ""))
        if not sale_date:
            skipped_date += 1
            continue
        if sale_date < since_date.isoformat():
            skipped_date += 1
            continue

        prop      = item.get("propertyInfo", {})
        status_info = item.get("listingStatus", {})

        street    = prop.get("address", "").strip()
        city      = prop.get("city", "").strip()
        zipcode   = prop.get("postalCode", "").strip()
        state     = prop.get("state", "VA")
        raw_county = prop.get("county", "")

        if state != "VA":
            continue
        if not street:
            continue

        address  = f"{street}, {city}, VA {zipcode}".strip(", ")
        county   = resolve_county(raw_county)
        if not county:
            county = raw_county or "Unknown"

        sale_time    = item.get("tpsSaleTime", "")
        sale_location = item.get("tpsSaleLocation") or courthouse_location(county)
        attorney     = item.get("foreclosureAttorneyName", "")
        attorney_ref = item.get("foreclosureAttorneyReference", "")
        listing_url  = prop.get("websiteUrl", "") or item.get("canonicalUrl", "")
        prop_type    = prop.get("propertyType", "single-family")
        year_built   = prop.get("yearBuilt")
        lot_size     = prop.get("lotSize")
        occupancy    = prop.get("occupancyStatus", "")
        beds_baths   = build_beds_baths_sqft(prop)
        days_until   = (date.fromisoformat(sale_date) - date.today()).days
        is_cash_only = item.get("isCashOnly", False)

        # Build notice text
        notice_parts = []
        if attorney_ref:
            notice_parts.append(f"Case #: {attorney_ref}")
        if occupancy:
            notice_parts.append(f"Occupancy: {occupancy}")
        if is_cash_only:
            notice_parts.append("Cash only")
        notice_text = " | ".join(notice_parts) if notice_parts else None

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
            "property_type":   prop_type,
            "stage":           "auction",
            "sale_date":       sale_date,
            "sale_time":       sale_time,
            "sale_location":   sale_location,
            "days_until_sale": days_until,
            "asking_price":    None,
            "lender":          None,
            "trustee":         attorney or "ServiceLink Auction",
            "beds_baths_sqft": beds_baths,
            "year_built":      int(year_built) if year_built else None,
            "lot_size":        str(int(lot_size)) if lot_size else None,
            "notice_text":     notice_text,
            "source":          SOURCE_TAG,
            "source_url":      listing_url or SOURCE_URL,
            "first_seen":      date.today().isoformat(),
            "is_new":          True,
        })

    log.info(
        f"  {len(listings)} active VA listings | "
        f"{skipped_status} wrong status | {skipped_date} date-filtered"
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
