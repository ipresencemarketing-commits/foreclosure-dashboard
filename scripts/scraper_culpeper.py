#!/usr/bin/env python3
from __future__ import annotations
"""
Culpeper Star-Exponent Column.us Foreclosure Scraper
-----------------------------------------------------
Pulls trustee sale notices from starexponent.column.us.

Covers: Culpeper County (also approved paper for Fauquier County notices)

Separate pipeline from Fredericksburg/Richmond — do NOT merge.
Writes to: data/foreclosures_culpeper.json

Run:   python3 scripts/scraper_culpeper.py
Then:  python3 scripts/sheets_sync.py --file data/foreclosures_culpeper.json
Or:    bash scripts/update_culpeper.sh
"""

import re
import json
import os
import sys
import logging
from datetime import date, datetime
from itertools import zip_longest

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Import shared parsing helpers from scraper.py ──────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import (
    make_id, days_until,
    parse_sale_datetime, parse_original_principal,
    parse_deposit, parse_deed_of_trust_date,
    parse_lender, parse_trustee,
    city_to_county, county_display, courthouse_location,
)

# ── Config ──────────────────────────────────────────────────────────────────
COLUMN_US_URL = "https://starexponent.column.us/search?noticeType=Foreclosure+Sale"
PAPER_HEADER  = "CULPEPER STAR EXPONENT"
SOURCE_TAG    = "column_us_culpeper"

SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT  = os.path.join(SCRIPT_DIR, "..")
DATA_FILE     = os.path.join(PROJECT_ROOT, "data", "foreclosures_culpeper.json")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(listings: list) -> None:
    today = date.today().isoformat()
    existing = {"meta": {}, "listings": []}
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            existing = json.load(f)
    existing_ids = {l["id"]: l for l in existing.get("listings", [])}

    for listing in listings:
        lid = listing["id"]
        if lid in existing_ids:
            listing["first_seen"] = existing_ids[lid].get("first_seen", today)
        else:
            listing["first_seen"] = today
        listing["is_new"] = listing["first_seen"] == today
        listing["days_until_sale"] = days_until(listing.get("sale_date"))

    data = {
        "meta": {
            "last_updated": datetime.now().isoformat(timespec="seconds"),
            "source": "starexponent.column.us",
            "total_count": len(listings),
            "new_today": sum(1 for l in listings if l.get("is_new")),
        },
        "listings": listings,
    }
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Saved {len(listings)} listings to {DATA_FILE}")


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def scrape() -> list:
    """Scrape starexponent.column.us for Foreclosure Sale notices."""
    listings = []

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning(
            "  playwright not installed — skipping.\n"
            "    Install with:  pip3 install playwright --break-system-packages\n"
            "                   playwright install chromium"
        )
        return listings

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                java_script_enabled=True,
            )
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            log.info(f"  Culpeper: loading {COLUMN_US_URL}")
            page.goto(COLUMN_US_URL, wait_until="load", timeout=40_000)
            page.wait_for_timeout(8_000)

            # Wait until notice cards are rendered
            try:
                page.wait_for_function(
                    f"document.body.innerText.toUpperCase().includes('{PAPER_HEADER}')",
                    timeout=20_000
                )
            except PWTimeout:
                log.warning(
                    f"  Culpeper: page never showed '{PAPER_HEADER}' after 20s "
                    "— may be 0 notices or site structure changed"
                )
                browser.close()
                return listings

            # Click "Load more" until exhausted
            load_more_clicks = 0
            while True:
                try:
                    clicked = page.evaluate("""
                        () => {
                            const buttons = Array.from(document.querySelectorAll('button'));
                            const btn = buttons.find(b =>
                                b.innerText && b.innerText.trim().toLowerCase().includes('load more')
                            );
                            if (btn) {
                                btn.scrollIntoView({block: 'center'});
                                btn.click();
                                return true;
                            }
                            return false;
                        }
                    """)
                    if clicked:
                        load_more_clicks += 1
                        log.info(f"  Culpeper: clicked 'Load more' ({load_more_clicks}x)")
                        page.wait_for_timeout(2500)
                    else:
                        log.info(f"  Culpeper: 'Load more' exhausted after {load_more_clicks} click(s)")
                        break
                except Exception as ex:
                    log.debug(f"  Culpeper: 'Load more' loop ended: {ex}")
                    break

            # Extract individual notice URLs from DOM
            try:
                notice_urls: list = page.evaluate("""
                    () => {
                        const seen  = new Set();
                        const links = document.querySelectorAll('a[href]');
                        const out   = [];
                        for (const a of links) {
                            const h = a.href || '';
                            if (/\\/notice[s]?\\/[\\w-]+/i.test(h) && !seen.has(h)) {
                                seen.add(h);
                                out.push(h);
                            }
                        }
                        return out;
                    }
                """)
            except Exception as e:
                log.debug(f"  Culpeper: could not extract notice URLs: {e}")
                notice_urls = []

            log.info(f"  Culpeper: {len(notice_urls)} individual notice URL(s) found")

            # Split body text into per-notice blocks by newspaper header line
            body_text     = page.inner_text("body")
            raw_blocks    = re.split(PAPER_HEADER, body_text, flags=re.I)
            notice_blocks = raw_blocks[1:]   # first element is page chrome — drop it
            total_blocks  = len(notice_blocks)
            log.info(f"  Culpeper: {total_blocks} total listings found")

            kept = skipped_addr = 0
            listing_num = 0

            for block_text, notice_url in zip_longest(notice_blocks, notice_urls, fillvalue=None):
                if not block_text:
                    continue
                listing_num += 1
                text = block_text.strip()

                # ── Address extraction ─────────────────────────────────────
                # Same 4-pattern logic as the Fredericksburg scraper.
                addr_raw = None

                # Primary: house number + street + city + VA/Virginia + ZIP
                direct_m = re.search(
                    r"(\d+\s+[A-Z0-9][^,\n]{4,60},\s*[A-Z][^,\n]{1,35},\s*(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
                    text, re.I
                )
                if direct_m:
                    addr_raw = re.sub(r"\s+", " ", direct_m.group(1)).strip()

                # Fallback A: TRUSTEE'S SALE OF {address}
                if not addr_raw:
                    addr_m = re.search(
                        r"TRUSTEE.{0,3}S\s+SALE\s+OF\s+([\w\d].*?)(?=\n\n|\n?In\s+execution|\nDefault|\(Parcel)",
                        text, re.I | re.S
                    )
                    if addr_m:
                        addr_raw = re.sub(r"\s+", " ", addr_m.group(1)).strip()

                # Fallback B: SUBSTITUTE TRUSTEE SALE {address}
                if not addr_raw:
                    sub_m = re.search(
                        r"(?:NOTICE OF )?SUBSTITUTE TRUSTEE.{0,10}SALE\s+([\w\d].*?)(?=\n\n|\n?In\s+execution|\nBy virtue)",
                        text, re.I | re.S
                    )
                    if sub_m:
                        addr_raw = re.sub(r"\s+", " ", sub_m.group(1)).strip()

                # Fallback C: Trustee's Sale\n{address} — address on its own line
                if not addr_raw:
                    newline_m = re.search(
                        r"TRUSTEE.{0,3}S\s+SALE\s*\n\s*(\d+\s+[A-Z0-9][^,\n]{4,60},\s*[A-Z][^,\n]{1,35},\s*(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
                        text, re.I
                    )
                    if newline_m:
                        addr_raw = re.sub(r"\s+", " ", newline_m.group(1)).strip()

                if not addr_raw:
                    snippet = re.sub(r'\s+', ' ', text[:100]).strip()
                    log.info(f"  [{listing_num}/{total_blocks}] SKIPPED — no address | snippet: {snippet!r}")
                    skipped_addr += 1
                    continue

                # Parse street / city / ZIP from address line
                parsed = re.match(
                    r"^(.*?),\s*([^,]+),\s*(?:VA|Virginia)\s+(\d{5}(?:-\d{4})?)",
                    addr_raw, re.I
                )
                if parsed:
                    street   = parsed.group(1).strip()
                    city     = parsed.group(2).strip()
                    zip_code = parsed.group(3)
                else:
                    street   = addr_raw[:80]
                    city     = ""
                    zip_code = None

                # Derive county from city; fall back to Circuit Court mention in text
                county = city_to_county(city)
                if county == "Unknown":
                    county_m = re.search(
                        r"Circuit Court(?:\s+for)?\s+(?:the\s+)?"
                        r"(?:(?:City|County)\s+of\s+)?([A-Za-z][A-Za-z ]{1,25}?)"
                        r"(?:\s+County(?:\s+City)?)?,\s+(?:Main|Courthouse|\d)",
                        text, re.I
                    )
                    if county_m:
                        raw_county = county_m.group(1).strip()
                        raw_county = re.sub(r'^(?:of|the|county|city)\s+', '', raw_county, flags=re.I).strip()
                        raw_county = " ".join(raw_county.split()[:2])
                        county = county_display(raw_county.lower())
                    else:
                        county = ""

                kept += 1
                sale_date, sale_time  = parse_sale_datetime(text)
                lender                = parse_lender(text)
                trustee               = parse_trustee(text)
                original_principal    = parse_original_principal(text)
                deposit               = parse_deposit(text)
                deed_of_trust_date    = parse_deed_of_trust_date(text)
                county_key = county.lower().replace(" city", "").replace(" county", "").strip()

                log.info(
                    f"  [{listing_num}/{total_blocks}] ADDED — {street}, {city} | "
                    f"county: {county or 'unknown'} | sale: {sale_date or 'TBD'}"
                )
                listings.append({
                    "id":                  make_id(street, sale_date),
                    "address":             street,
                    "city":                city.title(),
                    "county":              county,
                    "zip":                 zip_code,
                    "stage":               "auction" if sale_date else "pre-fc",
                    "property_type":       "single-family",
                    "assessed_value":      None,
                    "asking_price":        None,
                    "sale_date":           sale_date,
                    "sale_time":           sale_time,
                    "sale_location":       courthouse_location(county_key) if county_key else "",
                    "days_until_sale":     None,
                    "notice_date":         date.today().isoformat(),
                    "days_in_foreclosure": 0,
                    "lender":              lender,
                    "trustee":             trustee,
                    "original_principal":  original_principal,
                    "deposit":             deposit,
                    "deed_of_trust_date":  deed_of_trust_date,
                    "notice_text":         re.sub(r'\s+', ' ', text).strip()[:5000],
                    "source":              SOURCE_TAG,
                    "source_url":          notice_url or COLUMN_US_URL,
                })

            log.info(
                f"  Culpeper summary: {kept} added | "
                f"{skipped_addr} skipped (no address) | "
                f"{total_blocks} total blocks"
            )
            browser.close()

    except Exception as e:
        log.error(f"  Culpeper error: {e}", exc_info=True)

    log.info(f"  Culpeper: found {len(listings)} listings total")
    return listings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    log.info("Starting Culpeper Star-Exponent (starexponent.column.us) scraper…")
    listings = scrape()
    save(listings)
    log.info("Done.")


if __name__ == "__main__":
    run()
