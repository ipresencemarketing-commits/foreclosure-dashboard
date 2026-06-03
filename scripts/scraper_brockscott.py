#!/usr/bin/env python3
"""
Brock & Scott PLLC — Virginia Foreclosure Sales Scraper
---------------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va

Structure:
  - Static HTML, server-rendered WordPress (no Playwright needed)
  - 10 listings per page, paginated via ?sf_paged=N
  - Each <article class="type-foreclosure_search"> contains one listing
  - Fields: County, Sale Date, State, Court SP #, Case #, Address,
            Opening Bid Amount, Book Page

Fields provided:
  ✅ Address (city + ZIP embedded in address string)
  ✅ County (from article CSS class + field text)
  ✅ Sale Date (MM/DD/YYYY)
  ✅ Sale Time (HH:MM:SS AM/PM)
  ✅ Opening Bid Amount (numeric — unique among notice sources)
  ✅ Case # (trustee reference)
  ❌ Lender (not in listing)
  ❌ Notice Text (no full notice — summary table only)
  🔄 Owner / Property Details (GIS backfill)
"""

import re
import json
import os
import sys
import logging
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, city_to_county, county_display, courthouse_location, valid_va_county

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

BASE_URL = "https://www.brockandscott.com/foreclosure-sales/"
PARAMS   = {"_sft_foreclosure_state": "va"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SOURCE_TAG  = "brockandscott"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_brockscott.json")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_fields(article) -> dict:
    """Extract key→value pairs from a listing <article> element.
    Also reads county directly from the article CSS class as a fallback."""
    fields = {}
    for col in article.select("div.forecol"):
        texts = [p.get_text(strip=True) for p in col.find_all("p") if p.get_text(strip=True)]
        if len(texts) >= 2:
            key   = texts[0].rstrip(":").strip().lower()
            value = texts[1].strip()
            fields[key] = value

    # Extract county from CSS class (e.g. "foreclosure_county-poquoson-city")
    # This is reliable even when city_to_county() doesn't know the city
    if "county" not in fields or not fields["county"]:
        for cls in article.get("class", []):
            m = re.match(r"foreclosure_county-(.+)", cls)
            if m:
                # "poquoson-city" → "Poquoson City", "grayson" → "Grayson"
                raw = m.group(1).replace("-", " ").title()
                fields["county_from_class"] = raw
                break

    return fields


def parse_sale_date_time(raw: str):
    """
    Parse "06/02/2026 - 01:15:00 PM" → ("2026-06-02", "1:15PM")
    Returns (sale_date_iso, sale_time_str) or (None, None).
    """
    m = re.match(
        r'(\d{1,2})/(\d{1,2})/(\d{4})\s*-\s*(\d{1,2}):(\d{2}):\d{2}\s*(AM|PM)',
        raw.strip(), re.IGNORECASE
    )
    if not m:
        return None, None
    month, day, year = m.group(1), m.group(2), m.group(3)
    hour, minute, ampm = m.group(4), m.group(5), m.group(6).upper()
    try:
        sale_date = date(int(year), int(month), int(day)).isoformat()
        sale_time = f"{int(hour)}:{minute}{ampm}"
        return sale_date, sale_time
    except ValueError:
        return None, None


def parse_address(raw: str):
    """
    Parse "4511 Riverside Dr   Independence, Virginia 24348"
    → ("4511 Riverside Dr, Independence, VA 24348", "Independence", "24348")

    Brock & Scott uses 2+ spaces as the separator between street and city.
    Falls back to comma-based split if no multi-space separator is found.
    """
    # Primary: split on 2+ spaces (B&S address format)
    m = re.match(
        r'^(.+?)\s{2,}([A-Za-z][A-Za-z\s]+?),\s*(?:Virginia|VA)\s+(\d{5}(?:-\d{4})?)',
        raw.strip()
    )
    if m:
        street  = m.group(1).strip()
        city    = m.group(2).strip()
        zipcode = m.group(3).strip()
        return f"{street}, {city}, VA {zipcode}", city, zipcode

    # Fallback: comma-separated "Street, City, VA ZIP"
    m = re.match(
        r'^(.+),\s+([A-Za-z][A-Za-z\s]+?),\s*(?:Virginia|VA)\s+(\d{5}(?:-\d{4})?)',
        raw.strip()
    )
    if m:
        street  = m.group(1).strip()
        city    = m.group(2).strip()
        zipcode = m.group(3).strip()
        return f"{street}, {city}, VA {zipcode}", city, zipcode

    return raw.strip(), None, None


def parse_opening_bid(raw: str):
    """Parse "125000.00" or "0.00" → int or None."""
    try:
        val = float(raw.replace(',', '').strip())
        return int(val) if val > 0 else None
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    listings = []
    seen_ids = set()
    page = 1

    log.info(f"Starting Brock & Scott scraper (VA, since {since_date})")

    while True:
        params = dict(PARAMS)
        if page > 1:
            params["sf_paged"] = page

        try:
            r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
            r.raise_for_status()
        except Exception as e:
            log.error(f"  Page {page} fetch error: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("article.type-foreclosure_search")

        if not articles:
            log.info(f"  Page {page}: no listings found — stopping")
            break

        log.info(f"  Page {page}: {len(articles)} listings")

        for article in articles:
            fields = parse_fields(article)

            raw_date   = fields.get("sale date", "")
            raw_addr   = fields.get("address", "")
            raw_county = fields.get("county", "")
            raw_bid    = fields.get("opening bid amount", "")
            case_num   = fields.get("case #", "")

            sale_date, sale_time = parse_sale_date_time(raw_date)

            # Date filter — skip past sales
            if sale_date and sale_date < since_date.isoformat():
                continue

            address, city, zipcode = parse_address(raw_addr)

            # County resolution — B&S always lists county explicitly in the field.
            # The field value (e.g. "Poquoson City", "Grayson") is already the correct
            # display name. county_display() only normalises bare city names, so we
            # try the field value directly first, then fall through to helpers.
            county = None
            if raw_county:
                # Use field value directly if it's a recognisable VA county/city name
                cd = county_display(raw_county)
                if cd:
                    county = cd
                else:
                    # county_display() failed — raw_county might already be the display name
                    # (e.g. "Poquoson City", "Hopewell City") or bare name without "City"
                    # Try stripping " City" and re-checking, then fall back to raw value
                    stripped = re.sub(r'\s+City$', '', raw_county, flags=re.IGNORECASE).strip()
                    cd2 = county_display(stripped)
                    county = cd2 if cd2 else raw_county.title()

            if not county and city:
                county = city_to_county(city)

            if not county:
                log.debug(f"  Skipping — unresolved county: raw={raw_county!r} addr={raw_addr!r}")
                continue

            opening_bid = parse_opening_bid(raw_bid)
            days_until  = (date.fromisoformat(sale_date) - date.today()).days if sale_date else None

            listing_id = make_id(address, sale_date or "")
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            listing = {
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
                "sale_location":   courthouse_location(county),
                "days_until_sale": days_until,
                "asking_price":    opening_bid,
                "lender":          None,
                "trustee":         "Brock & Scott, PLLC",
                "notice_text":     f"Case #: {case_num}" if case_num else None,
                "source":          SOURCE_TAG,
                "source_url":      f"{BASE_URL}?_sft_foreclosure_state=va",
                "first_seen":      date.today().isoformat(),
                "is_new":          True,
            }
            listings.append(listing)

        # Check for next page
        next_link = soup.select_one("div.nav-previous a, a[href*='sf_paged']")
        if next_link and f"sf_paged={page + 1}" in next_link.get("href", ""):
            page += 1
            time.sleep(0.5)
        else:
            break

    log.info(f"Brock & Scott: {len(listings)} listings scraped across {page} page(s)")
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

    # Dedup: merge new into existing by ID
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
        "meta":     {"source": "brockandscott", "updated": today, "url": BASE_URL},
        "listings": list(existing_map.values()),
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2, default=str)

    log.info(f"Saved → {OUTPUT_FILE}  ({added} added, {updated} updated, {len(out['listings'])} total)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    listings = scrape()
    save(listings)
    log.info("Done.")
