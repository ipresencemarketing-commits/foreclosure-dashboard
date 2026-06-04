#!/usr/bin/env python3
"""
Auction Network — Virginia Foreclosure Sales Scraper
-----------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://bid.auctionnetwork.com/Home/Auctions?auctionTypes=Foreclosure/Trustee

The site is a JS-rendered SPA with no URL-based state filter.
Strategy:
  1. Load all paginated listing pages in a single Playwright session
  2. Collect cards where address contains ", VA " — filter Virginia only
  3. Deduplicate by listing ID (same VA listings may appear on multiple pages)
  4. For each unique VA listing, fetch the detail page to get exact sale
     date/time, county, and sale location

Fields provided:
  ✅ Address (street + city + ZIP from card)
  ✅ County (from detail page, e.g. "Prince William County")
  ✅ Sale Date + Time (from detail page: "LIVE Auction Jun 16 at 1:00 PM")
  ✅ Sale Location (from detail page: "Sale Location: ...")
  ✅ Listing URL (individual detail page)
  ✅ Property ID / Listing ID
  ❌ Opening bid (not shown pre-auction)
  ❌ Lender / notice text
  🔄 Owner / property details (GIS backfill)

Note: Volume is low (typically 2–10 VA listings) but covers properties
not appearing in other sources.
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

BASE_URL    = "https://bid.auctionnetwork.com"
LIST_URL    = f"{BASE_URL}/Home/Auctions?auctionTypes=Foreclosure/Trustee"
SOURCE_TAG  = "auctionnetwork"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_auctionnetwork.json")

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,  "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sale_date_from_detail(text: str):
    """
    Find "LIVE Auction Jun 16 at 1:00 PM" or "Jun 16 at 1:00 PM" in detail text.
    Returns (date_iso, time_str) or (None, None).
    """
    m = re.search(
        r'(?:LIVE\s+Auction\s+)?(\w{3,9})\s+(\d{1,2})\s+at\s+(\d{1,2}:\d{2}\s*[AP]M)',
        text, re.IGNORECASE
    )
    if m:
        month_str = m.group(1).lower()[:3]
        day       = int(m.group(2))
        time_str  = m.group(3).strip()
        month     = MONTHS.get(month_str)
        if month:
            today = date.today()
            year  = today.year
            # If the month/day is in the past, assume next year
            candidate = date(year, month, day)
            if candidate < today:
                candidate = date(year + 1, month, day)
            return candidate.isoformat(), time_str
    return None, None


def parse_county_from_detail(text: str):
    """Extract county from detail page text."""
    m = re.search(r'([A-Z][A-Za-z ]+(?:County|City))', text)
    if m:
        raw = m.group(1).strip()
        # Normalise "KING WILLIAM County" → "King William"
        raw = re.sub(r'\s+County$', '', raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r'\s+City$',   '', raw, flags=re.IGNORECASE).strip()
        cd = county_display(raw.title())
        return cd if cd else raw.title()
    return None


def parse_sale_location(text: str, county: str = None):
    """Extract sale location from detail page."""
    m = re.search(r'Sale Location:\s*([^\n]+)', text)
    if m:
        loc = m.group(1).strip()
        # Sanity check: if it doesn't mention VA, fall back to courthouse lookup
        if 'VA' in loc or 'Virginia' in loc:
            return loc
    return courthouse_location(county) if county else None


def parse_address_from_lines(lines: list):
    """
    Lines from <br/>-separated h1 text:
      ["5133 CURRAN CREEK DR", "Haymarket, VA 20169"]
    → ("5133 Curran Creek Dr, Haymarket, VA 20169", "Haymarket", "20169")
    Falls back to regex split if only one line.
    """
    if len(lines) >= 2:
        street   = lines[0].strip().title()
        cityline = lines[1].strip()
        m = re.match(r'^([^,]+),\s*VA\s+(\d{5})', cityline)
        if m:
            city    = m.group(1).strip().title()
            zipcode = m.group(2)
            return f"{street}, {city}, VA {zipcode}", city, zipcode
        return f"{street}, {cityline}", None, None
    elif lines:
        # Single line: try to split on ", VA "
        text = lines[0].strip()
        m = re.search(r'^(.+),\s*([^,]+),\s*VA\s+(\d{5})', text)
        if m:
            return f"{m.group(1).title()}, {m.group(2).title()}, VA {m.group(3)}", m.group(2).strip().title(), m.group(3)
    return " ".join(lines).title(), None, None


def resolve_county(raw: str):
    if not raw:
        return None
    cleaned = re.sub(r'\s+County$', '', raw.strip(), flags=re.IGNORECASE).strip()
    cd = county_display(cleaned)
    return cd if cd else cleaned.title()


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting Auction Network scraper (VA only, since {since_date})")

    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError as e:
        log.error(f"  Missing dependency: {e}")
        return []

    va_cards = {}  # listing_id → {address, href}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])

        # ── Step 1: Collect VA listing IDs from all pages ──────────────
        for page_num in range(1, 20):  # safety cap at 20 pages
            url = LIST_URL if page_num == 1 else f"{LIST_URL}&page={page_num}"
            page = browser.new_page()
            try:
                page.goto(url, wait_until="load", timeout=30000)
                page.wait_for_timeout(5000)
                html = page.content()
            except Exception as e:
                log.warning(f"  Page {page_num} load error: {e}")
                page.close()
                break
            page.close()

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.panel.listing")

            if not cards:
                log.info(f"  Page {page_num}: no cards — stopping")
                break

            new_found = 0
            for card in cards:
                row = card.select_one("[data-listingid]")
                h1  = card.select_one("h1.title a")
                if not row or not h1:
                    continue
                lid  = row["data-listingid"]
                text = card.get_text()
                # Only Virginia listings
                if ", VA " not in text and "VA 2" not in text:
                    continue
                if lid not in va_cards:
                    # Extract street and city from <br/>-separated lines in h1
                    lines = [s.strip() for s in h1.strings if s.strip()]
                    va_cards[lid] = {
                        "lines": lines,   # ["5133 CURRAN CREEK DR", "Haymarket, VA 20169"]
                        "href":  h1.get("href", ""),
                    }
                    new_found += 1

            log.info(f"  Page {page_num}: {len(cards)} total cards, {new_found} new VA listings")

            # Stop if no new VA listings found and we've seen at least 1 page
            if new_found == 0 and page_num > 1:
                break

        log.info(f"  Total unique VA listings found: {len(va_cards)}")

        # ── Step 2: Fetch each VA detail page ──────────────────────────
        listings  = []
        seen_ids  = set()

        for lid, info in va_cards.items():
            detail_url = f"{BASE_URL}{info['href']}"
            dpage = browser.new_page()
            try:
                dpage.goto(detail_url, wait_until="load", timeout=30000)
                dpage.wait_for_timeout(4000)
                detail_text = dpage.inner_text("body")
            except Exception as e:
                log.warning(f"  Detail page error for {lid}: {e}")
                detail_text = ""
            dpage.close()

            address, city, zipcode = parse_address_from_lines(info.get("lines", []))
            sale_date, sale_time   = parse_sale_date_from_detail(detail_text)
            county_raw             = parse_county_from_detail(detail_text)
            county                 = resolve_county(county_raw)
            sale_location          = parse_sale_location(detail_text, county)

            if not sale_date:
                log.debug(f"  {lid}: no sale date found — skipping")
                continue
            if sale_date < since_date.isoformat():
                continue

            if not county:
                county = "Unknown"

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
                "asking_price":    None,
                "lender":          None,
                "trustee":         "Auction Network",
                "notice_text":     f"Listing ID: {lid}",
                "source":          SOURCE_TAG,
                "source_url":      detail_url,
                "first_seen":      date.today().isoformat(),
                "is_new":          True,
            })
            log.info(f"  Added: {address} | {sale_date} {sale_time} | {county}")

        browser.close()

    log.info(f"  {len(listings)} VA listings kept")
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
        "meta":     {"source": SOURCE_TAG, "updated": today, "url": LIST_URL},
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
