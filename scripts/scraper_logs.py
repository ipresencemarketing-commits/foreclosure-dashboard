#!/usr/bin/env python3
"""
LOGS Legal Group LLP — Virginia Foreclosure Sales Scraper
----------------------------------------------------------
Scrapes upcoming trustee sale listings from the PowerBI embed on:
  https://www.logs.com/va-sales-report.html

Approach:
  The page embeds a public PowerBI report. We use Playwright to load the
  iframe, intercept the querydata POST response, then decode the PowerBI
  DSR (Data Shape Result) format directly — no DOM scraping needed.

  This gives us ALL rows (114+ as of June 2026) without PowerBI's
  virtualised table truncation.

Fields provided:
  ✅ Address (full — "4634 Catterton Road, Free Union, Virginia 22940")
  ✅ County (explicit county name)
  ✅ Sale Date (YYYY-MM-DD)
  ✅ Sale Time (H:MM AM/PM)
  ✅ Auctioneer (NFPDS-VA LLC or AUCTION.COM)
  ✅ Foreclosure Status (Active or On Hold)
  ❌ Opening bid amount (not in this report)
  ❌ Lender / Trustee (not in this report)
  🔄 Owner / property details (GIS backfill)

Architecture notes:
  - DSR ValueDicts (D0–D5) are string lookup tables.
  - D0 = county names, D1 = state ("VA"), D2 = addresses (first 100),
    D3 = auctioneer names, D4 = phone (empty), D5 = status values.
  - Addresses beyond 100 are inlined as raw strings in C arrays.
  - The R bitmask (repeat mask) indicates which columns carry over from
    the previous row; C provides new values for non-repeat columns in order.
  - Empty-dict columns (D4/phone) are skipped entirely.
"""

import json
import os
import re
import sys
import logging
import time
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, city_to_county, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

SOURCE_URL  = "https://www.logs.com/va-sales-report.html"
IFRAME_URL  = (
    "https://app.powerbi.com/view?r="
    "eyJrIjoiNjJkZGIzZGUtYzk4OC00ODEyLThhNjUtNGJjNzBkOGMxMzJiIiwidCI6"
    "ImRmZmRlOTRmLTcyZmItNDlhZS1hY2IyLTBiOTYxYWJkNWI0MSIsImMiOjN9"
)
SOURCE_TAG  = "logs_legal"
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "data", "foreclosures_logs.json")


# ---------------------------------------------------------------------------
# DSR decoder
# ---------------------------------------------------------------------------

def decode_dsr(dsr_resp: dict) -> list[dict]:
    """
    Decode a PowerBI DSR (Data Shape Result) querydata response into a list
    of plain dicts, one per listing row.
    """
    results = dsr_resp.get("results", [])
    if not results:
        return []

    data = results[0]["result"]["data"]
    desc = data["descriptor"]["Select"]
    dsr  = data["dsr"]
    ds   = dsr["DS"][0]
    rows = ds["PH"][0]["DM0"]
    vd   = ds.get("ValueDicts", {})

    # Column schema from the first row's S array
    schema = rows[0]["S"]

    # Column names from the descriptor (G0 → COUNTY_NAME, etc.)
    col_names = {
        s["Value"]: s["Name"].split(".")[-1]
        for s in desc if s
    }

    # Columns whose dict is empty → always None, never written to C
    skip_cols = {
        i for i, col in enumerate(schema)
        if col.get("DN") and len(vd.get(col["DN"], [])) == 0
    }

    def decode_val(col_idx: int, raw):
        col = schema[col_idx]
        t   = col.get("T", 0)
        if t == 1:  # string type
            if isinstance(raw, str):
                return raw  # inlined string (overflows dict)
            dn  = col.get("DN", "")
            lst = vd.get(dn, [])
            return lst[raw] if isinstance(raw, int) and raw < len(lst) else None
        elif t == 7:  # numeric — date (epoch ms) or time (ms since midnight)
            if not isinstance(raw, (int, float)):
                return None
            if raw > 86_400_000:  # date: > 1 day in ms
                return datetime.utcfromtimestamp(raw / 1000).strftime("%Y-%m-%d")
            else:                  # time of day in ms
                total_s = int(raw) // 1000
                h, rem  = divmod(total_s, 3600)
                m       = rem // 60
                ampm    = "AM" if h < 12 else "PM"
                return f"{h % 12 or 12}:{m:02d} {ampm}"
        return raw

    prev  = [None] * len(schema)
    rows_out = []

    for row in rows:
        r_mask = row.get("R", 0)
        c_vals = row.get("C", [])
        cur    = list(prev)
        c_i    = 0

        for col_i in range(len(schema)):
            if col_i in skip_cols:
                cur[col_i] = None
                continue
            if r_mask & (1 << col_i):
                pass  # carry forward
            else:
                if c_i < len(c_vals):
                    cur[col_i] = decode_val(col_i, c_vals[c_i])
                    c_i += 1

        prev = cur
        row_dict = {col_names.get(schema[i]["N"], schema[i]["N"]): cur[i]
                    for i in range(len(schema))}
        rows_out.append(row_dict)

    return rows_out


# ---------------------------------------------------------------------------
# Address / county parsing
# ---------------------------------------------------------------------------

def parse_address(full_addr: str):
    """
    "4634 Catterton Road, Free Union, Virginia 22940"
    → ("4634 Catterton Road, Free Union, VA 22940", "Free Union", "22940")
    """
    full_addr = re.sub(r"\s+", " ", full_addr).strip()
    m = re.match(
        r"^(.+),\s+([^,]+),\s+(?:Virginia|VA)\s+(\d{5}(?:-\d{4})?)",
        full_addr
    )
    if m:
        street  = m.group(1).strip()
        city    = m.group(2).strip()
        zipcode = m.group(3).strip()
        return f"{street}, {city}, VA {zipcode}", city, zipcode
    return full_addr, None, None


def resolve_county(raw_county: str, city: str = None) -> str:
    """Use raw_county from PowerBI (always populated), fallback to city lookup."""
    if raw_county:
        cd = county_display(raw_county)
        if cd:
            return cd
        # Try stripping " County" or " City" suffix variants
        stripped = re.sub(r"\s+(County|City)$", "", raw_county, flags=re.IGNORECASE).strip()
        cd2 = county_display(stripped)
        if cd2:
            return cd2
        return raw_county.title()
    if city:
        return city_to_county(city)
    return None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting LOGS Legal scraper (VA, since {since_date})")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("Playwright not installed. Run: pip3 install playwright && playwright install chromium")
        return []

    raw_rows = []

    def on_response(response):
        if "querydata" not in response.url:
            return
        try:
            body = response.json()
            results = body.get("results", [])
            for r in results:
                data = r.get("result", {}).get("data", {})
                desc = data.get("descriptor", {}).get("Select", [])
                names = [s.get("Name", "") for s in desc if s]
                if any("FULL_ADDRESS" in n for n in names):
                    raw_rows.append(body)
        except Exception:
            pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = browser.new_page()
        page.on("response", on_response)

        log.info("  Loading PowerBI embed...")
        page.goto(IFRAME_URL, wait_until="load", timeout=40_000)
        page.wait_for_timeout(18_000)
        browser.close()

    if not raw_rows:
        log.error("  No querydata response captured — PowerBI may have changed")
        return []

    log.info(f"  Decoding DSR response...")
    decoded = decode_dsr(raw_rows[0])
    log.info(f"  Decoded {len(decoded)} raw rows")

    listings = []
    seen_ids = set()
    skipped_date = skipped_addr = 0

    for row in decoded:
        sale_date  = row.get("SALE_DATE")
        full_addr  = row.get("FULL_ADDRESS", "")
        raw_county = row.get("COUNTY_NAME", "")
        sale_time  = row.get("SALE_TIME")
        auctioneer = row.get("CONTACT_COMP_NAME")
        status     = row.get("Foreclosure Status", "")

        if not sale_date:
            skipped_date += 1
            continue
        if sale_date < since_date.isoformat():
            skipped_date += 1
            continue
        if not full_addr:
            skipped_addr += 1
            continue

        # Skip "On Hold" sales
        if status and "hold" in status.lower():
            continue

        address, city, zipcode = parse_address(full_addr)
        county = resolve_county(raw_county, city)
        if not county:
            log.debug(f"  Unresolved county: {raw_county!r} / city={city!r}")
            county = raw_county or "Unknown"

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
            "sale_location":   courthouse_location(county),
            "days_until_sale": days_until,
            "asking_price":    None,
            "lender":          None,
            "trustee":         auctioneer or "LOGS Legal Group LLP",
            "notice_text":     f"Auctioneer: {auctioneer}" if auctioneer else None,
            "source":          SOURCE_TAG,
            "source_url":      SOURCE_URL,
            "first_seen":      date.today().isoformat(),
            "is_new":          True,
        })

    log.info(
        f"  {len(listings)} listings kept | "
        f"{skipped_date} date-filtered | {skipped_addr} no-address"
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

    log.info(f"Saved → {OUTPUT_FILE}  ({added} added, {updated} updated, {len(out['listings'])} total)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    listings = scrape()
    save(listings)
    log.info("Done.")
