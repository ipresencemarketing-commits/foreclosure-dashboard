#!/usr/bin/env python3
"""
MWC Law (McCabe, Weisberg & Conway) — Virginia Foreclosure Sales Scraper
------------------------------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://apps.mwc-law.com/SalesLists/VA.html

Static HTML table — requests + BeautifulSoup, no Playwright needed.

Table structure (7 columns, after title row + header row):
  Sale Date | Sale Time | County | City | Address | State | File No

County field quirks:
  - "Prince WiIliam County"  — typo (capital I), strip " County" suffix
  - "Montgomery-VA"           — strip "-VA" suffix
  - "City of X"              — normalise to "X City"
  - "Alexandria"             — bare city name → "Alexandria City"

Fields provided:
  ✅ Address (street + city + state from separate columns)
  ✅ County (explicit column — normalised)
  ✅ Sale Date (M/D/YYYY)
  ✅ Sale Time (H:MM:SS AM/PM)
  ✅ File Number
  ❌ Bid deposit / opening bid
  ❌ Lender / full notice text
  🔄 Owner / property details (GIS backfill)
"""

import json
import os
import re
import sys
import logging
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

SOURCE_URL  = "https://apps.mwc-law.com/SalesLists/VA.html"
SOURCE_TAG  = "mwclaw"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_mwclaw.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ---------------------------------------------------------------------------
# County normalisation
# ---------------------------------------------------------------------------

# Explicit overrides for MWC's non-standard county strings
COUNTY_OVERRIDES = {
    "prince william county": "Prince William",   # typo: "WiIliam" with capital I
    "prince william":        "Prince William",
    "montgomery-va":         "Montgomery",
    "montgomery":            "Montgomery",
    "alexandria":            "Alexandria City",
    "danville":              "Danville City",
    "norfolk":               "Norfolk City",
}


def resolve_county(raw: str) -> str:
    key = raw.strip().lower()
    # Strip common suffixes
    key_clean = re.sub(r'\s+county$', '', key).strip()
    key_clean = re.sub(r'-va$', '', key_clean).strip()
    # Replace capital I typo: "wiIliam" → "william"
    key_clean = key_clean.replace('wiIliam', 'william').replace('wiiliam', 'william')

    if key_clean in COUNTY_OVERRIDES:
        return COUNTY_OVERRIDES[key_clean]
    if key in COUNTY_OVERRIDES:
        return COUNTY_OVERRIDES[key]

    # "City of X" → try county_display("X") → "X City"
    m = re.match(r'^city of\s+(.+)$', key_clean, re.IGNORECASE)
    if m:
        city = m.group(1).strip()
        cd = county_display(city)
        return cd if cd else f"{city.title()} City"

    # Try county_display on cleaned key
    cd = county_display(key_clean.title())
    if cd:
        return cd

    return raw.strip().title()


# ---------------------------------------------------------------------------
# Date / time parsing
# ---------------------------------------------------------------------------

def parse_date(raw: str):
    """'6/5/2026' → '2026-06-05'"""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_time(raw: str) -> str:
    """'9:15:00 AM' → '9:15 AM'"""
    raw = raw.strip()
    m = re.match(r'(\d+):(\d+)(?::\d+)?\s*(AM|PM)', raw, re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}:{m.group(2)} {m.group(3).upper()}"
    return raw


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting MWC Law scraper (since {since_date})")

    try:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.error(f"  Fetch error: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    all_rows = soup.find_all("tr")

    # Row 0 = title ("VA Sales List"), Row 1 = column headers, Row 2+ = data
    data_rows = all_rows[2:]
    log.info(f"  {len(data_rows)} data rows found")

    listings  = []
    seen_ids  = set()
    skipped   = 0

    for row in data_rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 6:
            skipped += 1
            continue

        sale_date_raw = cells[0]
        sale_time_raw = cells[1]
        county_raw    = cells[2]
        city          = cells[3].strip()
        street        = cells[4].strip()
        state         = cells[5].strip() if len(cells) > 5 else "VA"
        file_no       = cells[6].strip() if len(cells) > 6 else ""

        if state != "VA":
            skipped += 1
            continue

        sale_date = parse_date(sale_date_raw)
        if not sale_date or not street:
            skipped += 1
            continue
        if sale_date < since_date.isoformat():
            skipped += 1
            continue

        county     = resolve_county(county_raw)
        sale_time  = parse_time(sale_time_raw)
        address    = f"{street}, {city}, VA"
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
            "zip":             None,
            "property_type":   "single-family",
            "stage":           "auction",
            "sale_date":       sale_date,
            "sale_time":       sale_time,
            "sale_location":   courthouse_location(county),
            "days_until_sale": days_until,
            "asking_price":    None,
            "lender":          None,
            "trustee":         "McCabe, Weisberg & Conway, LLC",
            "notice_text":     f"File #: {file_no}" if file_no else None,
            "source":          SOURCE_TAG,
            "source_url":      SOURCE_URL,
            "first_seen":      date.today().isoformat(),
            "is_new":          True,
        })

    log.info(f"  {len(listings)} listings kept | {skipped} skipped")
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

    log.info(f"Saved → {OUTPUT_FILE}  ({added} added, {updated} updated, {len(out['listings'])} total)")


if __name__ == "__main__":
    listings = scrape()
    save(listings)
    log.info("Done.")
