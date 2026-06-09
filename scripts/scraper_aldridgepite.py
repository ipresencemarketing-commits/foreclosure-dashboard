#!/usr/bin/env python3
"""
Aldridge Pite, LLP — Virginia Foreclosure Sales Scraper
--------------------------------------------------------
Scrapes upcoming trustee sale listings from:
  https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-virginia/

The page shows a disclaimer on first visit; clicking "I agree" reloads the same
URL with a session cookie and renders the actual listings table.  Playwright is
required to handle the cookie gate.

Table columns (0-indexed):
  0: File Number
  1: Address
  2: City
  3: State
  4: ZIP
  5: County
  6: Date Listed   ← auction sale date + time, e.g. "August 19, 2026 2:00 PM"
  7: Original Loan Amount

Fields provided:
  ✅ Address (street + city + state + zip)
  ✅ County
  ✅ ZIP
  ✅ City
  ✅ File Number
  ✅ Original Loan Amount
  ✅ Sale Date (parsed from "Date Listed" column)
  ✅ Sale Time (parsed from "Date Listed" column)
  ❌ Bid deposit / opening bid
  ❌ Lender / trustee name
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

SOURCE_URL  = "https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-virginia/"
SOURCE_TAG  = "aldridgepite"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_aldridgepite.json")

# Column indices (0-based)
COL_FILE_NUMBER   = 0
COL_ADDRESS       = 1
COL_CITY          = 2
COL_STATE         = 3
COL_ZIP           = 4
COL_COUNTY        = 5
COL_DATE_LISTED   = 6
COL_LOAN_AMOUNT   = 7


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sale_datetime(raw: str):
    """
    Parse combined sale date+time string.
    'August 19, 2026 2:00 PM' → ('2026-08-19', '2:00 PM')
    Falls back to date-only formats if no time present.
    Returns (sale_date_iso, sale_time_str) — either may be None.
    """
    if not raw:
        return None, None
    raw = raw.strip()
    # Full datetime: "August 19, 2026 2:00 PM"
    m = re.match(
        r'^(\w+ \d{1,2},\s*\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?\s*[AP]M)$',
        raw, re.IGNORECASE
    )
    if m:
        try:
            d = datetime.strptime(m.group(1).strip(), "%B %d, %Y").date().isoformat()
        except ValueError:
            d = None
        t_raw = m.group(2).strip()
        t_m = re.match(r'(\d+):(\d+)(?::\d+)?\s*(AM|PM)', t_raw, re.IGNORECASE)
        t = f"{int(t_m.group(1))}:{t_m.group(2)} {t_m.group(3).upper()}" if t_m else t_raw
        return d, t
    # Date-only fallbacks
    for fmt in ("%B %d, %Y", "%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat(), None
        except ValueError:
            pass
    return None, None


def parse_money(raw: str):
    """'$125,000.00' → 125000"""
    if not raw:
        return None
    m = re.search(r'[\d,]+(?:\.\d+)?', raw.replace(" ", ""))
    if m:
        try:
            return int(float(m.group().replace(",", "")))
        except ValueError:
            pass
    return None


def resolve_county(raw: str) -> str:
    """Normalise raw county string to display name."""
    if not raw:
        return None
    raw = raw.strip()
    clean = re.sub(r'\s+county$', '', raw, flags=re.IGNORECASE).strip()
    m = re.match(r'^city of\s+(.+)$', clean, re.IGNORECASE)
    if m:
        city = m.group(1).strip()
        cd = county_display(city)
        return cd if cd else f"{city.title()} City"
    cd = county_display(clean)
    return cd if cd else raw.title()


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting Aldridge Pite scraper (since {since_date})")

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

            # Step 1 — load disclaimer page
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Step 2 — click "I agree" to bypass disclaimer cookie gate
            try:
                agree = page.locator("a", has_text=re.compile(r"i\s+agree", re.IGNORECASE)).first
                if agree.count():
                    agree.click()
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(3000)
                    log.info("  Clicked 'I agree' — disclaimer bypassed")
                else:
                    log.info("  No disclaimer found — listings may already be visible")
            except Exception as e:
                log.warning(f"  Could not click agree: {e}")

            # Step 3 — set "Show entries" dropdown to All so every row is visible
            try:
                all_selects = page.locator("select").all()

                # Target the row-count select specifically: the one preceded by a "Show" label.
                # select[0] is the county filter; select[1] is the row-count dropdown.
                selected = False
                for sel in all_selects:
                    options = sel.locator("option").all()
                    opt_texts = [o.text_content().strip() for o in options]
                    # Only touch selects whose options look like row counts (numbers + All)
                    if not any(t.lower() == "all" for t in opt_texts):
                        continue
                    if any(len(t) > 6 for t in opt_texts if t.lower() != "all"):
                        # Options contain long strings (county names etc.) — skip
                        continue
                    for opt in options:
                        txt = opt.text_content().strip().lower()
                        val = opt.get_attribute("value") or ""
                        if txt == "all" or val == "-1":
                            sel.select_option(value=val if val else "All")
                            page.wait_for_timeout(2000)
                            log.info(f"  Set 'Show entries' to All (value='{val or txt}')")
                            selected = True
                            break
                    if selected:
                        break
                if not selected:
                    log.warning("  No row-count select found — will scrape visible rows only")
            except Exception as e:
                log.warning(f"  Could not set 'Show All': {e}")

            html = page.content()
            browser.close()
    except Exception as e:
        log.error(f"  Playwright error: {e}")
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Find the listings table — it has 8 columns starting with "File Number".
    # There may be other tables on the page (e.g. county→courthouse map); skip those.
    table = None
    for t in soup.find_all("table"):
        header_row = t.find("tr")
        if not header_row:
            continue
        headers = [c.get_text(strip=True).lower() for c in header_row.find_all(["th", "td"])]
        if any("file" in h for h in headers) and any("address" in h for h in headers):
            table = t
            break

    if not table:
        log.warning("  Listings table (File Number / Address columns) not found on page")
        return []

    rows = table.find_all("tr")
    if len(rows) < 2:
        log.warning("  Listings table found but no data rows")
        return []

    data_rows = rows[1:]  # skip header row
    log.info(f"  {len(data_rows)} data rows found")


    listings  = []
    seen_ids  = set()
    skipped   = 0

    for row in data_rows:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) <= COL_COUNTY:
            skipped += 1
            continue

        file_number     = cells[COL_FILE_NUMBER].strip()
        address_raw     = cells[COL_ADDRESS].strip()
        city            = cells[COL_CITY].strip()
        state           = cells[COL_STATE].strip().upper()
        zipcode         = cells[COL_ZIP].strip()
        county_raw      = cells[COL_COUNTY].strip()
        sale_datetime   = cells[COL_DATE_LISTED].strip() if len(cells) > COL_DATE_LISTED else ""
        loan_raw        = cells[COL_LOAN_AMOUNT].strip() if len(cells) > COL_LOAN_AMOUNT else ""

        if state != "VA":
            skipped += 1
            continue
        if not address_raw:
            skipped += 1
            continue

        sale_date, sale_time = parse_sale_datetime(sale_datetime)
        if not sale_date:
            skipped += 1
            continue
        if sale_date < since_date.isoformat():
            skipped += 1
            continue

        # Build full address
        parts = [p for p in [address_raw, city, f"VA {zipcode}" if zipcode else "VA"] if p]
        address = ", ".join(parts)

        county      = resolve_county(county_raw)
        loan_amount = parse_money(loan_raw)
        days_until  = (date.fromisoformat(sale_date) - date.today()).days
        listing_id  = make_id(address, sale_date)

        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        notice_parts = []
        if file_number:
            notice_parts.append(f"File #: {file_number}")
        if loan_amount:
            notice_parts.append(f"Original Loan: ${loan_amount:,}")

        listings.append({
            "id":                 listing_id,
            "address":            address,
            "city":               city,
            "county":             county,
            "state":              "VA",
            "zip":                zipcode or None,
            "property_type":      "single-family",
            "stage":              "auction",
            "sale_date":          sale_date,
            "sale_time":          sale_time,
            "sale_location":      courthouse_location(county),
            "days_until_sale":    days_until,
            "asking_price":       None,
            "original_principal": loan_amount,
            "lender":             None,
            "trustee":            "Aldridge Pite, LLP",
            "notice_text":        " | ".join(notice_parts) if notice_parts else None,
            "source":             SOURCE_TAG,
            "source_url":         SOURCE_URL,
            "first_seen":         date.today().isoformat(),
            "is_new":             True,
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
