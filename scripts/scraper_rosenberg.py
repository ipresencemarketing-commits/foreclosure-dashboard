#!/usr/bin/env python3
"""
Rosenberg & Associates — Virginia Foreclosure Sales Scraper
------------------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://rosenberg-assoc.com/foreclosure-sales/

Structure:
  - Static HTML table — requests + BeautifulSoup (no Playwright needed)
  - Single page, 142 rows (VA + MD + DC mixed; filtered to VA only)
  - Columns: Case #, Sale Date, Sale Time, Address, City, Jurisdiction,
             State, ZIP, Deposit, soldid, cancelled, cur_case_stat_id

Status logic:
  - cur_case_stat_id = 1 → Active (keep)
  - cur_case_stat_id = 2 → Sold  (skip)
  - cur_case_stat_id = 3 → Cancelled (skip)
  - cancelled = 'Y'       → skip (belt and suspenders)
  - soldid populated       → skip

Fields provided:
  ✅ Address (street + city + ZIP assembled)
  ✅ County / Jurisdiction (explicit — "Fairfax", "City of Chesapeake", etc.)
  ✅ Sale Date (MM-DD-YYYY)
  ✅ Sale Time (H:MM AM/PM)
  ✅ Deposit amount
  ✅ Case Number
  ✅ State filter (VA only — site also lists MD and DC)
  ❌ Lender / Trustee / Opening bid / Notice text
  🔄 Owner / property details (GIS backfill)
"""

import re
import json
import os
import sys
import logging
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, city_to_county, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

SOURCE_URL  = "https://rosenberg-assoc.com/foreclosure-sales/"
SOURCE_TAG  = "rosenberg"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_rosenberg.json")

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
# Rosenberg uses various formats for independent cities.
# Map them to standard display names used in the sheet.

JURISDICTION_MAP = {
    # "City of X" → "X City"
    "city of alexandria":        "Alexandria City",
    "city of bristol":           "Bristol City",
    "city of buena vista":       "Buena Vista City",
    "city of charlottesville":   "Charlottesville City",
    "city of chesapeake":        "Chesapeake City",
    "city of colonial heights":  "Colonial Heights City",
    "city of covington":         "Covington City",
    "city of danville":          "Danville City",
    "city of emporia":           "Emporia City",
    "city of fairfax":           "Fairfax City",
    "city of falls church":      "Falls Church City",
    "city of franklin":          "Franklin City",
    "city of fredericksburg":    "Fredericksburg City",
    "city of galax":             "Galax City",
    "city of hampton":           "Hampton City",
    "city of harrisonburg":      "Harrisonburg City",
    "city of hopewell":          "Hopewell City",
    "city of lexington":         "Lexington City",
    "city of lynchburg":         "Lynchburg City",
    "city of manassas":          "Manassas City",
    "city of manassas park":     "Manassas Park City",
    "city of martinsville":      "Martinsville City",
    "city of newport news":      "Newport News City",
    "city of norfolk":           "Norfolk City",
    "city of norton":            "Norton City",
    "city of petersburg":        "Petersburg City",
    "city of poquoson":          "Poquoson City",
    "city of portsmouth":        "Portsmouth City",
    "city of radford":           "Radford City",
    "city of richmond":          "Richmond City",
    "city of roanoke":           "Roanoke City",
    "city of salem":             "Salem City",
    "city of staunton":          "Staunton City",
    "city of suffolk":           "Suffolk City",
    "city of virginia beach":    "Virginia Beach City",
    "city of waynesboro":        "Waynesboro City",
    "city of williamsburg":      "Williamsburg City",
    "city of winchester":        "Winchester City",
    # Bare city names without "City of" prefix or "City" suffix
    "alexandria":     "Alexandria City",
    "bristol":        "Bristol City",
    "chesapeake":     "Chesapeake City",
    "danville":       "Danville City",
    "hampton":        "Hampton City",
    "harrisonburg":   "Harrisonburg City",
    "hopewell":       "Hopewell City",
    "lynchburg":      "Lynchburg City",
    "manassas":       "Manassas City",
    "martinsville":   "Martinsville City",
    "newport news":   "Newport News City",
    "petersburg":     "Petersburg City",
    "portsmouth":     "Portsmouth City",
    "radford":        "Radford City",
    "roanoke":        "Roanoke City",
    "salem":          "Salem City",
    "staunton":       "Staunton City",
    "suffolk":        "Suffolk City",
    "virginia beach": "Virginia Beach City",
    "waynesboro":     "Waynesboro City",
    "williamsburg":   "Williamsburg City",
    "winchester":     "Winchester City",
}


def resolve_county(jurisdiction: str, city: str = None) -> str:
    """
    Normalise Rosenberg's jurisdiction field to a standard county display name.
    Tries JURISDICTION_MAP first, then county_display(), then city_to_county().
    """
    if not jurisdiction:
        return city_to_county(city) if city else None

    key = jurisdiction.strip().lower()

    # Check explicit map first
    if key in JURISDICTION_MAP:
        return JURISDICTION_MAP[key]

    # Handle "X City" suffix (e.g. "Norfolk City", "Roanoke City")
    if key.endswith(" city"):
        bare = key[:-5].strip()
        mapped = JURISDICTION_MAP.get(bare)
        if mapped:
            return mapped
        # Capitalise and return as-is (e.g. "Norfolk City")
        return jurisdiction.strip().title()

    # Try county_display() for plain county names (e.g. "Fairfax", "Chesterfield")
    cd = county_display(jurisdiction.strip())
    if cd:
        return cd

    # Last resort — city_to_county()
    return city_to_county(city) if city else jurisdiction.strip().title()


# ---------------------------------------------------------------------------
# Date / deposit parsing
# ---------------------------------------------------------------------------

def parse_date(raw: str):
    """MM-DD-YYYY → YYYY-MM-DD"""
    try:
        return datetime.strptime(raw.strip(), "%m-%d-%Y").date().isoformat()
    except ValueError:
        return None


def parse_deposit(raw: str):
    """'$ 20,000' → 20000"""
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

    log.info(f"Starting Rosenberg & Associates scraper (VA, since {since_date})")

    try:
        r = requests.get(SOURCE_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.error(f"  Fetch error: {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    data_rows = soup.select("table tr")[1:]  # skip header
    log.info(f"  {len(data_rows)} total rows fetched")

    listings    = []
    seen_ids    = set()
    skipped_state    = 0
    skipped_status   = 0
    skipped_date     = 0

    for row in data_rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 12:
            continue

        case_num   = cells[0]
        raw_date   = cells[1]
        raw_time   = cells[2]
        street     = cells[3].strip()
        city       = cells[4].strip()
        jurisdiction = cells[5].strip()
        state      = cells[6].strip()
        zipcode    = cells[7].strip()
        raw_deposit= cells[8]
        sold_id    = cells[9].strip()
        cancelled  = cells[10].strip()
        status_id  = cells[11].strip()

        # VA only
        if state != "VA":
            skipped_state += 1
            continue

        # Skip sold / cancelled
        if status_id in ("2", "3") or cancelled == "Y" or sold_id:
            skipped_status += 1
            continue

        sale_date = parse_date(raw_date)
        if not sale_date:
            continue
        if sale_date < since_date.isoformat():
            skipped_date += 1
            continue

        if not street:
            continue

        address = f"{street}, {city}, VA {zipcode}".strip(", ")
        county  = resolve_county(jurisdiction, city)
        if not county:
            county = jurisdiction or "Unknown"

        deposit    = parse_deposit(raw_deposit)
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
            "sale_time":       raw_time,
            "sale_location":   courthouse_location(county),
            "days_until_sale": days_until,
            "asking_price":    None,
            "deposit":         str(deposit) if deposit else None,
            "lender":          None,
            "trustee":         "Rosenberg & Associates",
            "notice_text":     f"Case #: {case_num}" if case_num else None,
            "source":          SOURCE_TAG,
            "source_url":      SOURCE_URL,
            "first_seen":      date.today().isoformat(),
            "is_new":          True,
        })

    log.info(
        f"  {len(listings)} VA active listings | "
        f"{skipped_state} non-VA | {skipped_status} sold/cancelled | "
        f"{skipped_date} date-filtered"
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
