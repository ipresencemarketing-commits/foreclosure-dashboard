#!/usr/bin/env python3
"""
Glasser Law — Virginia Foreclosure Sales Scraper
-------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://www.glasserlaw.com/New%20Folder/Foreclosure%20Sales.html

The site is protected by Cloudflare so Playwright is required.

Table structure (8 columns):
  Jurisdiction | File Number | Bid Deposit | Property Address |
  Original Principal | Sale Date | Sale Time | Sale Location

Address and Sale Location cells use <br/> to separate lines:
  Address:  "706 Dooms Crossing Road<br/>Waynesboro, VA 22980"
  Location: "Augusta County Circuit Court<br/>1 East Johnson Street<br/>Staunton, VA 24402"

Fields provided:
  ✅ Address (street + city parsed from <br/> lines)
  ✅ County (Jurisdiction field: "County of Augusta" → "Augusta")
  ✅ Sale Date (M/D/YYYY)
  ✅ Sale Time (H:MM:SS AM/PM)
  ✅ Sale Location (full courthouse address)
  ✅ Bid Deposit amount
  ✅ Original Principal
  ✅ File Number
  ❌ Lender / full notice text
  🔄 Owner / property details (GIS backfill)
"""

import json
import os
import re
import sys
import logging
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

SOURCE_URL  = "https://www.glasserlaw.com/New%20Folder/Foreclosure%20Sales.html"
SOURCE_TAG  = "glasserlaw"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_glasserlaw.json")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_jurisdiction(raw: str) -> str:
    """
    "County of Augusta"      → "Augusta"
    "City of Hampton"        → "Hampton City"
    "County of Fairfax"      → "Fairfax"
    """
    raw = raw.strip()
    m = re.match(r'^City of\s+(.+)$', raw, re.IGNORECASE)
    if m:
        city = m.group(1).strip()
        cd = county_display(city)
        return cd if cd else f"{city} City"

    m = re.match(r'^County of\s+(.+)$', raw, re.IGNORECASE)
    if m:
        county = m.group(1).strip()
        cd = county_display(county)
        return cd if cd else county.title()

    # fallback — try direct lookup
    cd = county_display(raw)
    return cd if cd else raw.title()


def parse_cell_lines(td) -> list:
    """Extract text lines from a <td> that uses <br/> as line separator."""
    lines = []
    for item in td.descendants:
        from bs4 import NavigableString
        if isinstance(item, NavigableString):
            text = item.strip()
            if text:
                lines.append(text)
    return lines


def parse_address_cell(td):
    """
    <td>706 Dooms Crossing Road<br/>Waynesboro, VA 22980</td>
    → ("706 Dooms Crossing Road, Waynesboro, VA 22980", "Waynesboro", "22980")
    """
    lines = parse_cell_lines(td)
    if len(lines) >= 2:
        street  = lines[0].strip()
        cityline = lines[1].strip()  # "Waynesboro, VA 22980"
        m = re.match(r'^([^,]+),\s*VA\s+(\d{5})', cityline)
        if m:
            city    = m.group(1).strip()
            zipcode = m.group(2)
            return f"{street}, {city}, VA {zipcode}", city, zipcode
        return f"{street}, {cityline}", None, None
    elif lines:
        raw = lines[0]
        # Try regex split on ", VA XXXXX"
        m = re.match(r'^(.+?),\s*([^,]+),\s*VA\s+(\d{5})', raw)
        if m:
            return f"{m.group(1)}, {m.group(2)}, VA {m.group(3)}", m.group(2).strip(), m.group(3)
    return td.get_text(strip=True), None, None


def parse_location_cell(td) -> str:
    """
    <td>Augusta County Circuit Court<br/>1 East Johnson Street<br/>Staunton, VA 24402</td>
    → "Augusta County Circuit Court, 1 East Johnson Street, Staunton, VA 24402"
    """
    lines = parse_cell_lines(td)
    return ", ".join(l for l in lines if l) if lines else td.get_text(strip=True)


def parse_date(raw: str):
    """'6/5/2026' → '2026-06-05'"""
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_time(raw: str) -> str:
    """'10:00:00 AM' → '10:00 AM'"""
    raw = raw.strip()
    m = re.match(r'(\d+):(\d+)(?::\d+)?\s*(AM|PM)', raw, re.IGNORECASE)
    if m:
        return f"{int(m.group(1))}:{m.group(2)} {m.group(3).upper()}"
    return raw


def parse_money(raw: str):
    """'$7,000.00' → 7000"""
    m = re.search(r'[\d,]+', raw.replace(" ", ""))
    if m:
        try:
            return int(float(m.group().replace(",", "")))
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

    log.info(f"Starting Glasser Law scraper (since {since_date})")

    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError as e:
        log.error(f"Missing dependency: {e}")
        return []

    html = None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page()
            page.goto(SOURCE_URL, wait_until="load", timeout=30000)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
    except Exception as e:
        log.error(f"  Playwright error: {e}")
        return []

    from bs4 import BeautifulSoup, NavigableString
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.find_all("tr")
    data_rows = rows[1:]  # skip header
    log.info(f"  {len(data_rows)} data rows found")

    listings  = []
    seen_ids  = set()
    skipped   = 0

    for row in data_rows:
        cells = row.find_all("td")
        if len(cells) < 8:
            continue

        jurisdiction    = cells[0].get_text(strip=True)
        file_number     = cells[1].get_text(strip=True)
        bid_deposit_raw = cells[2].get_text(strip=True)
        sale_date_raw   = cells[5].get_text(strip=True)
        sale_time_raw   = cells[6].get_text(strip=True)
        principal_raw   = cells[4].get_text(strip=True)

        address, city, zipcode = parse_address_cell(cells[3])
        sale_location = parse_location_cell(cells[7])
        sale_date     = parse_date(sale_date_raw)
        sale_time     = parse_time(sale_time_raw)
        county        = parse_jurisdiction(jurisdiction)
        bid_deposit   = parse_money(bid_deposit_raw)
        principal     = parse_money(principal_raw)

        if not sale_date or not address:
            skipped += 1
            continue
        if sale_date < since_date.isoformat():
            skipped += 1
            continue

        days_until  = (date.fromisoformat(sale_date) - date.today()).days
        listing_id  = make_id(address, sale_date)

        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        notice_parts = []
        if file_number:
            notice_parts.append(f"File #: {file_number}")
        if principal:
            notice_parts.append(f"Original principal: ${principal:,}")

        listings.append({
            "id":                listing_id,
            "address":           address,
            "city":              city,
            "county":            county,
            "state":             "VA",
            "zip":               zipcode,
            "property_type":     "single-family",
            "stage":             "auction",
            "sale_date":         sale_date,
            "sale_time":         sale_time,
            "sale_location":     sale_location,
            "days_until_sale":   days_until,
            "asking_price":      None,
            "deposit":           str(bid_deposit) if bid_deposit else None,
            "original_principal": principal,
            "lender":            None,
            "trustee":           "Glasser & Glasser, P.L.C.",
            "notice_text":       " | ".join(notice_parts) if notice_parts else None,
            "source":            SOURCE_TAG,
            "source_url":        SOURCE_URL,
            "first_seen":        date.today().isoformat(),
            "is_new":            True,
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
