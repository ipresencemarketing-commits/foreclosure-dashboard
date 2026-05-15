#!/usr/bin/env python3
from __future__ import annotations
"""
Fredericksburg Metro Foreclosure Scraper
-----------------------------------------
Pulls trustee sale notices from free public sources and saves to data/foreclosures.json.

Active source groups (controlled by scripts/config.py):
  Group 3  — PublicNoticeVirginia.com       (PNV, statewide — §55.1-321 required)
  Existing — fredericksburg.column.us       (Fredericksburg Free-Lance Star)
  Group 1  — richmond.column.us             (Richmond Times-Dispatch)
  Group 2  — logs.com/va-sales-report.html  (LOGS Legal Group / PFCVA)
  Group 4  — dailyprogress.column.us        (Charlottesville Daily Progress)

Search window: controlled by LOOKBACK_DAYS in scripts/config.py (default 30 days).

Run: python3 scripts/scraper.py
Requires: pip install requests beautifulsoup4 lxml playwright
          python3 -m playwright install chromium
"""

import re
import sys
import requests
import json
import hashlib
import os
import logging
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
from time import sleep

# Load pipeline config (scripts/config.py) — must come before any constant that
# references cfg.  sys.path is extended so the import works whether the script
# is invoked as "python3 scripts/scraper.py" (from repo root) or directly.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as cfg
from schema import normalize_listing

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "foreclosures.json")

# Use county list from config so there's a single source of truth.
TARGET_COUNTIES = cfg.TARGET_COUNTIES

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(address: str, sale_date: str) -> str:
    """Stable unique ID based on address + sale date."""
    raw = f"{address.lower().strip()}-{sale_date or 'nodate'}"
    return "fc-" + hashlib.md5(raw.encode()).hexdigest()[:8]


def days_until(sale_date_str: str) -> int | None:
    """Return integer days from today to sale_date_str (YYYY-MM-DD)."""
    if not sale_date_str:
        return None
    try:
        sale = date.fromisoformat(sale_date_str)
        return (sale - date.today()).days
    except ValueError:
        return None


def load_existing() -> dict:
    """Load the current data file so we can preserve first_seen dates."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"meta": {}, "listings": []}


def save(listings: list) -> None:
    today = date.today().isoformat()
    existing = load_existing()
    existing_ids = {l["id"]: l for l in existing.get("listings", [])}

    # Preserve first_seen; flag listings added today as new; stamp date_scraped
    for listing in listings:
        lid = listing["id"]
        if lid in existing_ids:
            listing["first_seen"] = existing_ids[lid].get("first_seen", today)
        else:
            listing["first_seen"] = today
        listing["is_new"]       = listing["first_seen"] == today
        listing["date_scraped"] = today

    # Normalize every listing to the canonical phone-app-ready schema
    normalized = [normalize_listing(l) for l in listings]

    data = {
        "meta": {
            "schema_version":  "2.0",
            "last_updated":    datetime.now().isoformat(timespec="seconds"),
            "lookback_days":   cfg.LOOKBACK_DAYS,
            "since_date":      cfg.SINCE_DATE.isoformat(),
            "target_counties": cfg.TARGET_COUNTIES_DISPLAY,
            "total_count":     len(normalized),
            "new_today":       sum(1 for l in normalized if l.get("is_new")),
        },
        "listings": normalized,
    }
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info(f"Saved {len(normalized)} listings to {DATA_FILE}")


# ---------------------------------------------------------------------------
# Source 1: PublicNoticeVirginia.com
# ---------------------------------------------------------------------------

def scrape_public_notice_va() -> list:
    """
    Scrapes trustee sale notices from publicnoticevirginia.com using Playwright.

    Page architecture (discovered via DOM inspection):
      - Grid ID: ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1
      - Notice IDs stored in hidden fields: input[id$="hdnPKValue"]  (e.g. value="470136")
      - VIEW buttons are form submits (NOT <a> links) — clicking them POSTs to Details.aspx
      - Detail URL pattern: Details.aspx?SID=<session_id>&ID=<notice_id>
      - Detail pages show a reCAPTCHA; we fall back to card text excerpt if blocked
      - Search mode must be "Any Words" (rdoType_1) for OR logic across keywords
      - Pagination: <a> links with text ">" in the grid footer row

    Approach:
      1. Open site in headless Chromium (spoof webdriver flag)
      2. Fill search box with popular-searches keyword set; select "Any Words" mode
      3. Submit and wait for results
      4. Loop pages: extract (notice_id, card_text) from hdnPKValue hidden fields → click ">" → repeat
      5. Construct detail URLs from session ID + notice IDs
      6. Navigate to each detail page; use full text if available, card excerpt as fallback
      7. Filter to target counties; build listing dict

    Virginia Code §55.1-321 requires all trustee sale notices on PNV.
    """
    listings = []

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning(
            "  PNV: playwright not installed — skipping.\n"
            "    Install with:  pip3 install playwright\n"
            "                   python3 -m playwright install chromium"
        )
        return listings

    # All three words appear in every Virginia trustee sale notice by statute.
    # "All Words" (AND) mode: trustee AND sale AND Virginia — filters to VA only.
    SEARCH_KEYWORDS = "trustee sale Virginia"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                java_script_enabled=True,
            )
            # Spoof navigator.webdriver so bot-detection JS doesn't flag us
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            log.info("  PNV: opening site with Playwright")
            page.goto("https://www.publicnoticevirginia.com/", wait_until="load", timeout=45_000)
            page.wait_for_timeout(3_000)

            # ── Fill search box ───────────────────────────────────────────────
            search_sel = 'input[id*="txtSearch"]'
            try:
                page.wait_for_selector(search_sel, timeout=15_000)
            except PWTimeout:
                log.error(
                    "  PNV: search box not found after 15 s — "
                    "site may be showing a CAPTCHA or has changed structure"
                )
                browser.close()
                return listings

            page.fill(search_sel, SEARCH_KEYWORDS)
            log.info("  PNV: search box filled")

            # ── Set date range from config (LOOKBACK_DAYS) ───────────────────
            # PNV's ASP.NET search form accepts M/D/YYYY dates.
            # SINCE_DATE comes from config.py — change LOOKBACK_DAYS there
            # to adjust the search window for all sources at once.
            from_date = cfg.SINCE_DATE.strftime("%-m/%-d/%Y")
            to_date   = cfg.TODAY.strftime("%-m/%-d/%Y")
            try:
                # Advanced search date inputs follow ASP.NET WebForms naming:
                # ctl00_ContentPlaceHolder1_as1_txt{From,To}Date
                for sel, val in [
                    ('[id*="txtFromDate"]', from_date),
                    ('[id*="txtToDate"]',   to_date),
                ]:
                    inp = page.query_selector(sel)
                    if inp:
                        inp.triple_click()
                        inp.fill(val)
                log.info(
                    f"  PNV: date range set to {from_date} → {to_date} "
                    f"({cfg.LOOKBACK_DAYS}-day window from config.py)"
                )
            except Exception as _e:
                log.debug(f"  PNV: could not set date range ({_e}) — using site default")

            # ── Submit ────────────────────────────────────────────────────────
            # "trustee sale" works with default "All Words" (AND) mode — both
            # words appear in every VA notice, so no radio button change needed.
            page.click('input[id*="btnGo"]')
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2_000)

            # Wait for the results grid to be present before evaluating DOM
            GRID_ID = "ctl00_ContentPlaceHolder1_WSExtendedGridNP1_GridView1"
            try:
                page.wait_for_selector(f"#{GRID_ID}", state="attached", timeout=15_000)
                page.wait_for_timeout(500)
            except PWTimeout:
                log.warning("  PNV: results grid not visible — search returned no results or page changed")
                browser.close()
                return listings

            # ── Paginate through all result pages ────────────────────────────
            # Each notice row has a hidden field id ending in "hdnPKValue" whose
            # value is the integer notice ID used in the detail URL.
            all_notice_items: list[dict] = []   # [{id, card_text}, ...]
            page_num = 1

            while True:
                log.info(f"  PNV: collecting notice IDs from results page {page_num}")

                items_on_page: list[dict] = page.evaluate(
                    """(gridId) => {
                        const out = [];
                        const grid = document.getElementById(gridId);
                        if (!grid) return out;
                        const fields = grid.querySelectorAll('input[id$="hdnPKValue"]');
                        fields.forEach(field => {
                            const nid = field.value;
                            if (!nid) return;
                            // PNV uses a nested table structure inside each grid cell:
                            //   outer TR → TD (card cell) → TABLE.nested → TR → TD.view → hdnPKValue
                            // field.closest('tr') stops at the INNER TR which only has the
                            // newspaper header ("Roanoke Times, The …").
                            // Instead: go up to the nested TABLE, then to its parent TD (the full card).
                            let container = field.closest('table');
                            if (container) container = container.closest('td');
                            if (!container) container = field.closest('tr'); // safe fallback
                            const text = container
                                ? container.textContent.replace(/\\s+/g, ' ').trim()
                                : '';
                            out.push({ id: nid, card_text: text });
                        });
                        return out;
                    }""",
                    GRID_ID,
                )

                all_notice_items.extend(items_on_page)
                log.info(f"  PNV: page {page_num} → {len(items_on_page)} notice(s)")

                # ── Advance to next page ──────────────────────────────────────
                # PNV pager uses input[type="image"] buttons, not <a> links.
                # The next-page button has id ending in "btnNext".
                next_btn = (
                    page.query_selector('input[id$="btnNext"]') or
                    page.query_selector('input[name$="btnNext"]')
                )
                if next_btn and next_btn.is_visible() and next_btn.is_enabled():
                    next_btn.click()
                    page.wait_for_load_state("networkidle", timeout=20_000)
                    page.wait_for_timeout(1_200)
                    page_num += 1
                else:
                    log.info(f"  PNV: no more pages (last page = {page_num})")
                    break

            # Deduplicate by notice ID
            seen_ids: set[str] = set()
            unique_items: list[dict] = []
            for item in all_notice_items:
                if item["id"] not in seen_ids:
                    seen_ids.add(item["id"])
                    unique_items.append(item)

            log.info(
                f"  PNV: {len(unique_items)} unique notices across {page_num} page(s)"
            )

            # ── Build detail URLs using the live session ID ──────────────────────
            # We keep the Playwright browser open and navigate to each detail
            # page directly — this guarantees the ASP.NET session cookie is
            # still valid.  The previous approach (close browser → HTTP requests)
            # caused the session to expire, so every fetch silently fell back to
            # the truncated card text, producing wrong sale_dates and blank times.
            session_match = re.search(r'\(S\(([^)]+)\)\)', page.url)
            session_id    = session_match.group(1) if session_match else ""
            log.info(f"  PNV: session_id = {session_id or '(not found)'}")
            log.info(f"  PNV: fetching {len(unique_items)} detail pages via Playwright…")

            for i, item in enumerate(unique_items, 1):
                nid       = item["id"]
                card_text = item["card_text"]

                if session_id:
                    detail_url = (
                        f"https://www.publicnoticevirginia.com"
                        f"/(S({session_id}))/Details.aspx?SID={session_id}&ID={nid}"
                    )
                else:
                    detail_url = (
                        f"https://www.publicnoticevirginia.com/Details.aspx?ID={nid}"
                    )

                full_text = card_text  # default; overwritten on successful fetch
                try:
                    page.goto(detail_url, wait_until="domcontentloaded", timeout=20_000)
                    page.wait_for_timeout(800)
                    # Extract visible text — strips scripts/styles automatically
                    raw_text = page.evaluate("() => document.body.innerText")
                    if raw_text:
                        full_text = re.sub(r'\s+', ' ', raw_text).strip()
                except Exception as e:
                    log.warning(f"  PNV: Playwright fetch failed for {nid}: {e} — using card text")

                # Verify we got actual notice content (not an error/redirect page)
                if not re.search(
                    r"trustee|deed of trust|sale of real property|foreclos|judicial sale",
                    full_text, re.I
                ):
                    log.debug(f"  PNV: notice {nid} — detail page lacked notice keywords, using card text")
                    full_text = card_text

                if i % 10 == 0:
                    log.info(f"  PNV: processed {i}/{len(unique_items)} detail pages…")

                address              = parse_address_from_notice(full_text)
                sale_date, sale_time = parse_sale_datetime(full_text)
                lender               = parse_lender(full_text)
                trustee              = parse_trustee(full_text)
                notice_text          = re.sub(r'\s+', ' ', full_text).strip()[:5000]

                # Derive county from notice text — critical for the county filter
                # that runs after all scrapers complete in main().
                county_key = None
                text_lower = full_text.lower()
                for c in TARGET_COUNTIES:
                    if c in text_lower:
                        county_key = c
                        break

                listings.append({
                    "id":                  make_id(address, sale_date),
                    "address":             address,
                    "city":                county_city(county_key) if county_key else "",
                    "county":              county_display(county_key) if county_key else "",
                    "zip":                 None,
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
                    "notice_text":         notice_text,
                    "source":              "publicnoticevirginia",
                    "source_url":          detail_url,
                })

                sleep(0.25)   # polite rate limit

            browser.close()

    except Exception as e:
        log.error(f"  PNV error: {e}", exc_info=True)

    log.info(f"  PublicNoticeVA: found {len(listings)} listings")
    return listings

# ---------------------------------------------------------------------------
# REMOVED SOURCES — see scripts/_archived_sources.py
# Auction.com, HUD Homes, Fannie Mae HomePath, Freddie Mac HomeSteps
# were removed 2026-05. Full implementations preserved in _archived_sources.py.
# ---------------------------------------------------------------------------

def scrape_auction_com() -> list:
    """
    Group 5: Auction.com — REO and trustee pre-sale listings.

    Uses Auction.com's XML sitemap hierarchy to discover active listing URLs
    without JavaScript, then fetches each detail page to extract address,
    auction date, and starting bid from embedded JSON.

    Sitemap index: https://www.auction.com/sitemaps/sitemapindex.xml
      → sitemap-pdp-active-tps-{N}.xml  (trustee/pre-foreclosure sales)
      → sitemap-pdp-active-reo-{N}.xml  (bank-owned REO)

    Covers REO properties that appear AFTER the trustee sale completes —
    a category not tracked by PNV or Column.us.  Complements trustee-sale
    sources rather than duplicating them.

    To tune: adjust SLUG_COUNTY keywords, sleep() delays, or the
    auction JSON field priority list.  Set ENABLE_AUCTION_COM=False in
    config.py to pause without touching this code.
    """
    listings = []

    # URL slug keyword → county display name.
    # Auction.com listing slugs contain city-state strings like "stafford-va".
    SLUG_COUNTY: dict[str, str] = {
        "stafford-va":          "Stafford",
        "fredericksburg-va":    "Fredericksburg City",
        "spotsylvania-va":      "Spotsylvania",
        "bowling-green-va":     "Caroline",
        "ruther-glen-va":       "Caroline",
        "milford-va":           "Caroline",
        "port-royal-va":        "Caroline",
        "woodford-va":          "Caroline",
        "penola-va":            "Caroline",
        "warrenton-va":         "Fauquier",
        "new-baltimore-va":     "Fauquier",
        "bealeton-va":          "Fauquier",
        "catlett-va":           "Fauquier",
        "remington-va":         "Fauquier",
        "midland-va":           "Fauquier",
        "culpeper-va":          "Culpeper",
        "jeffersonton-va":      "Culpeper",
        "woodville-va":         "Culpeper",
        "brandy-station-va":    "Culpeper",
        "king-george-va":       "King George",
        "dahlgren-va":          "King George",
        "ashland-va":           "Hanover",
        "mechanicsville-va":    "Hanover",
        "hanover-va":           "Hanover",
        "atlee-va":             "Hanover",
        "richmond-va":          "Richmond City",
        "chesterfield-va":      "Chesterfield",
        "midlothian-va":        "Chesterfield",
        "chester-va":           "Chesterfield",
        "bon-air-va":           "Chesterfield",
        "henrico-va":           "Henrico",
        "glen-allen-va":        "Henrico",
        "short-pump-va":        "Henrico",
        "sandston-va":          "Henrico",
        "highland-springs-va":  "Henrico",
        "louisa-va":            "Louisa",
        "mineral-va":           "Louisa",
    }

    try:
        # Step 1: Fetch the sitemap index
        idx_resp = requests.get(
            "https://www.auction.com/sitemaps/sitemapindex.xml",
            headers=HEADERS, timeout=15
        )
        idx_resp.raise_for_status()
        all_sm_urls = re.findall(r"<loc>(https://[^<]+)</loc>", idx_resp.text)

        # Keep only active PDP sitemaps for TPS (trustee pre-sale) and REO
        pdp_urls = [
            u for u in all_sm_urls
            if ("sitemap-pdp-active-tps" in u or "sitemap-pdp-active-reo" in u)
            and "image" not in u
        ]
        log.info(f"  Auction.com: scanning {len(pdp_urls)} sitemap file(s)")

        # Step 2: Scan each sitemap for target-county listing URLs
        target_detail_urls: list[str] = []
        for sm_url in pdp_urls:
            try:
                sm_resp = requests.get(sm_url, headers=HEADERS, timeout=20)
                sm_resp.raise_for_status()
                locs = re.findall(
                    r"<loc>(https://www\.auction\.com/details/[^<]+)</loc>",
                    sm_resp.text
                )
                for u in locs:
                    slug = u.split("/details/")[-1]
                    if any(kw in slug for kw in SLUG_COUNTY):
                        target_detail_urls.append(u)
                sleep(0.3)
            except Exception as e:
                log.warning(f"  Auction.com: sitemap error {sm_url}: {e}")

        # Deduplicate (a listing can appear in both TPS and REO sitemaps)
        target_detail_urls = list(dict.fromkeys(target_detail_urls))
        log.info(f"  Auction.com: {len(target_detail_urls)} target-county detail page(s)")

        # Step 3: Fetch each detail page and parse embedded auction JSON
        for detail_url in target_detail_urls:
            try:
                slug = detail_url.split("/details/")[-1]

                # Determine county from slug keyword
                county_name = next(
                    (cn for kw, cn in SLUG_COUNTY.items() if kw in slug), None
                )

                det_resp = requests.get(detail_url, headers=HEADERS, timeout=20)
                det_resp.raise_for_status()
                html = det_resp.text

                # Parse address from <title>
                # Format: "9 Plowshare Court, Stafford, VA 22554, Stafford County | SmartSale"
                title_m   = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                title_raw = title_m.group(1).strip() if title_m else ""
                addr_part = title_raw.split(" | ")[0].strip() if " | " in title_raw else title_raw
                am = re.match(
                    r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?),\s*(.+)$",
                    addr_part
                )
                if am:
                    street    = am.group(1).strip()
                    city_name = am.group(2).strip()
                    zip_code  = am.group(4).strip()
                    if not county_name:
                        county_name = (am.group(5)
                                       .replace(" County", "")
                                       .replace(" City", "")
                                       .strip())
                else:
                    # Fallback: derive from slug
                    slug_no_id = re.sub(r"-\d+$", "", slug)
                    parts = slug_no_id.split("-")
                    if len(parts) >= 3 and len(parts[-1]) == 2:
                        city_name = parts[-2].title()
                        street    = " ".join(parts[:-2]).title()
                    else:
                        street    = slug_no_id.replace("-", " ").title()
                        city_name = ""
                    zip_code = None

                # Parse auction data from embedded JSON
                sale_date    = None
                asking_price = None
                auction_m = re.search(
                    r'"auction"\s*:\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\})', html
                )
                if auction_m:
                    try:
                        auc = json.loads(auction_m.group(1))
                        raw_date = (
                            auc.get("auction_date") or
                            auc.get("visible_auction_start_date_time") or
                            auc.get("end_date") or
                            auc.get("start_date")
                        )
                        if raw_date:
                            sale_date = str(raw_date)[:10]
                        bid = auc.get("starting_bid")
                        if bid and int(bid) > 1:   # $1 = placeholder — skip
                            asking_price = int(bid)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

                # Property detail fields embedded in page JSON
                def _auc_int(keys):
                    for key in keys:
                        m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                        if m and int(m.group(1)) > 0:
                            return int(m.group(1))
                    return None

                def _auc_float(keys):
                    for key in keys:
                        m = re.search(rf'"{key}"\s*:\s*([\d.]+)', html)
                        if m and float(m.group(1)) > 0:
                            return float(m.group(1))
                    return None

                beds  = _auc_int(["bedrooms", "beds", "num_bedrooms", "bedroom_count"])
                baths = _auc_float(["bathrooms", "baths", "num_bathrooms", "bathroom_count"])
                sqft  = _auc_int(["square_feet", "sqft", "total_sqft", "living_sqft",
                                   "gross_area", "above_grade_sqft"])
                yr    = _auc_int(["year_built", "yearBuilt", "year_of_construction"])
                if yr and not (1800 < yr <= 2030):
                    yr = None

                lot_ac = _auc_float(["lot_size_acres", "lot_acres"])
                lot_sf = _auc_int(["lot_size_sqft", "lot_sqft", "lot_square_feet"])
                lot_size = (f"{lot_ac:.2f} ac" if lot_ac else
                            f"{lot_sf / 43560:.2f} ac" if lot_sf and lot_sf > 500 else None)

                full_addr = f"{street}, {city_name}, VA {zip_code}" if zip_code else street
                listings.append({
                    "id":            make_id(full_addr, sale_date),
                    "address":       street,
                    "city":          city_name,
                    "county":        county_name or "Unknown",
                    "zip":           zip_code,
                    "stage":         "auction" if sale_date else "reo",
                    "property_type": "single-family",
                    "asking_price":  asking_price,
                    "sale_date":     sale_date,
                    "sale_time":     None,
                    "sale_location": courthouse_for_address(county_name or ""),
                    "beds":          beds,
                    "baths":         baths,
                    "sqft":          sqft,
                    "year_built":    yr,
                    "lot_size":      lot_size,
                    "lender":        None,
                    "trustee":       None,
                    "notice_text":   None,
                    "source":        "auction_com",
                    "source_url":    detail_url,
                })
                sleep(0.4)

            except Exception as e:
                log.warning(f"  Auction.com: detail error {detail_url}: {e}")

    except Exception as e:
        log.error(f"  Auction.com error: {e}", exc_info=True)

    # Apply LOOKBACK_DAYS filter — drop listings whose auction is in the past
    # beyond the search window (keep unknowns and future dates)
    since_iso = cfg.SINCE_DATE.isoformat()
    listings = [
        l for l in listings
        if not l.get("sale_date") or l["sale_date"] >= since_iso
    ]
    log.info(f"  Auction.com: found {len(listings)} target-county listing(s)")
    return listings
    """
    Scrapes Auction.com for foreclosure listings near Fredericksburg, VA.

    As of 2026 Auction.com is fully client-side rendered — the search page HTML
    contains zero listing data before JavaScript runs.  Instead we use the site's
    XML sitemap (server-generated, no JS required) to discover active listing URLs,
    filter by target county keywords, then fetch each matching detail page to
    parse the embedded JSON auction data and the <title> tag for address/county.

    Sitemap hierarchy (from robots.txt):
      https://www.auction.com/sitemaps/sitemapindex.xml
        → sitemap-pdp-active-tps-{0..N}.xml  (trustee/pre-foreclosure sales)
        → sitemap-pdp-active-reo-{0..N}.xml  (bank-owned / REO)

    Detail page data format (server-rendered):
      <title>{address}, {city}, {state} {zip}, {county} County | Auction.com</title>
      ... embedded JSON ... "auction":{"auction_date":"YYYY-MM-DD","starting_bid":N,...}
    """
    listings = []

    # URL slug keywords → county display name
    SLUG_COUNTY: dict[str, str] = {
        # Fredericksburg metro (original)
        "stafford-va":          "Stafford",
        "fredericksburg-va":    "Fredericksburg City",
        "spotsylvania-va":      "Spotsylvania",
        "bowling-green-va":     "Caroline",
        "ruther-glen-va":       "Caroline",
        "milford-va":           "Caroline",
        "port-royal-va":        "Caroline",
        "woodford-va":          "Caroline",
        "penola-va":            "Caroline",
        # Fauquier
        "warrenton-va":         "Fauquier",
        "new-baltimore-va":     "Fauquier",
        "bealeton-va":          "Fauquier",
        "catlett-va":           "Fauquier",
        "remington-va":         "Fauquier",
        "midland-va":           "Fauquier",
        # Culpeper
        "culpeper-va":          "Culpeper",
        "jeffersonton-va":      "Culpeper",
        "woodville-va":         "Culpeper",
        "brandy-station-va":    "Culpeper",
        # King George
        "king-george-va":       "King George",
        "dahlgren-va":          "King George",
        # Hanover
        "ashland-va":           "Hanover",
        "mechanicsville-va":    "Hanover",
        "hanover-va":           "Hanover",
        "atlee-va":             "Hanover",
        # Richmond City
        "richmond-va":          "Richmond City",
        # Chesterfield
        "chesterfield-va":      "Chesterfield",
        "midlothian-va":        "Chesterfield",
        "chester-va":           "Chesterfield",
        "bon-air-va":           "Chesterfield",
        # Henrico
        "henrico-va":           "Henrico",
        "glen-allen-va":        "Henrico",
        "short-pump-va":        "Henrico",
        "sandston-va":          "Henrico",
        "highland-springs-va":  "Henrico",
        # Louisa
        "louisa-va":            "Louisa",
        "mineral-va":           "Louisa",
    }

    try:
        # Step 1: Fetch the sitemap index
        idx_resp = requests.get(
            "https://www.auction.com/sitemaps/sitemapindex.xml",
            headers=HEADERS, timeout=15
        )
        idx_resp.raise_for_status()
        all_sm_urls = re.findall(r"<loc>(https://[^<]+)</loc>", idx_resp.text)

        # Keep only PDP sitemaps for active TPS and REO (skip image sitemaps)
        pdp_urls = [
            u for u in all_sm_urls
            if ("sitemap-pdp-active-tps" in u or "sitemap-pdp-active-reo" in u)
            and "image" not in u
        ]
        log.info(f"  Auction.com: scanning {len(pdp_urls)} PDP sitemap files")

        # Step 2: Scan each sitemap for target-county listing URLs
        target_detail_urls: list[str] = []
        for sm_url in pdp_urls:
            try:
                sm_resp = requests.get(sm_url, headers=HEADERS, timeout=20)
                sm_resp.raise_for_status()
                locs = re.findall(
                    r"<loc>(https://www\.auction\.com/details/[^<]+)</loc>",
                    sm_resp.text
                )
                for u in locs:
                    slug = u.split("/details/")[-1]
                    if any(kw in slug for kw in SLUG_COUNTY):
                        target_detail_urls.append(u)
                sleep(0.3)
            except Exception as e:
                log.warning(f"  Auction.com: sitemap error {sm_url}: {e}")

        # Deduplicate (some listings appear in both TPS and REO sitemaps)
        target_detail_urls = list(dict.fromkeys(target_detail_urls))
        log.info(f"  Auction.com: {len(target_detail_urls)} target-county detail pages")

        # Step 3: Fetch each detail page and parse embedded data
        for detail_url in target_detail_urls:
            try:
                slug = detail_url.split("/details/")[-1]

                # Determine county from slug keyword
                county_name = None
                for kw, cn in SLUG_COUNTY.items():
                    if kw in slug:
                        county_name = cn
                        break

                det_resp = requests.get(detail_url, headers=HEADERS, timeout=20)
                det_resp.raise_for_status()
                html = det_resp.text

                # --- Parse address from <title> ---
                # Format: "9 Plowshare Court, Stafford, VA 22554, Stafford County | SmartSale"
                title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                title_raw = title_m.group(1).strip() if title_m else ""
                addr_part = title_raw.split(" | ")[0].strip() if " | " in title_raw else title_raw

                # Parse "street, city, ST zip, County County" → fields
                am = re.match(
                    r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?),\s*(.+)$",
                    addr_part
                )
                if am:
                    street    = am.group(1).strip()
                    city_name = am.group(2).strip()
                    zip_code  = am.group(4).strip()
                    county_from_title = (am.group(5)
                                         .replace(" County", "")
                                         .replace(" City", "")
                                         .strip())
                    if not county_name:
                        county_name = county_from_title
                else:
                    # Fallback: parse address from slug
                    slug_no_id = re.sub(r"-\d+$", "", slug)
                    parts = slug_no_id.split("-")
                    if len(parts) >= 3 and len(parts[-1]) == 2:
                        city_name = parts[-2].title()
                        street    = " ".join(parts[:-2]).title()
                    else:
                        street    = slug_no_id.replace("-", " ").title()
                        city_name = ""
                    zip_code = None

                # --- Parse auction data from embedded JSON blob ---
                sale_date    = None
                asking_price = None
                auction_m = re.search(
                    r'"auction"\s*:\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\})',
                    html
                )
                if auction_m:
                    try:
                        auc = json.loads(auction_m.group(1))
                        # Prefer auction_date, then visible start, then end_date
                        raw_date = (
                            auc.get("auction_date") or
                            auc.get("visible_auction_start_date_time") or
                            auc.get("end_date") or
                            auc.get("start_date")
                        )
                        if raw_date:
                            sale_date = str(raw_date)[:10]  # keep YYYY-MM-DD
                        bid = auc.get("starting_bid")
                        if bid and int(bid) > 1:  # $1 is placeholder
                            asking_price = int(bid)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

                # --- Parse property characteristics from the detail page ---
                # Auction.com embeds property data as JSON key-value pairs in
                # the page HTML (inside script tags / __NEXT_DATA__ / etc.).
                # We search for known field names directly rather than trying
                # to parse the full nested JSON, which is fragile.
                def _auc_int(pattern_keys):
                    for key in pattern_keys:
                        m = re.search(rf'"{key}"\s*:\s*(\d+)', html)
                        if m:
                            v = int(m.group(1))
                            if v > 0:
                                return v
                    return None

                def _auc_float(pattern_keys):
                    for key in pattern_keys:
                        m = re.search(rf'"{key}"\s*:\s*([\d.]+)', html)
                        if m:
                            v = float(m.group(1))
                            if v > 0:
                                return v
                    return None

                beds_val  = _auc_int(["bedrooms", "beds", "num_bedrooms", "bedroom_count"])
                baths_val = _auc_float(["bathrooms", "baths", "num_bathrooms", "bathroom_count", "full_baths"])
                sqft_val  = _auc_int(["square_feet", "sqft", "total_sqft", "living_sqft",
                                       "gross_area", "above_grade_sqft", "heated_area"])
                yr_val    = _auc_int(["year_built", "yearBuilt", "year_of_construction"])
                if yr_val and not (1800 < yr_val <= 2030):
                    yr_val = None   # reject placeholder values like 0 or 9999

                lot_sf_val  = _auc_int(["lot_size_sqft", "lot_sqft", "lot_square_feet"])
                lot_ac_val  = _auc_float(["lot_size_acres", "lot_acres"])
                lot_size_str = None
                if lot_ac_val:
                    lot_size_str = f"{lot_ac_val:.2f} ac"
                elif lot_sf_val and lot_sf_val > 500:
                    lot_size_str = f"{lot_sf_val / 43560:.2f} ac"

                listings.append({
                    "id":               make_id(detail_url, sale_date),
                    "address":          street,
                    "city":             city_name,
                    "county":           county_name or "Unknown",
                    "zip":              zip_code,
                    "stage":            "auction",
                    "property_type":    "single-family",
                    "assessed_value":   None,
                    "asking_price":     asking_price,
                    "sale_date":        sale_date,
                    "sale_time":        None,
                    "sale_location":    courthouse_for_address(county_name or ""),
                    "days_until_sale":  None,
                    "notice_date":      None,
                    "days_in_foreclosure": None,
                    "lender":           None,
                    "trustee":          None,
                    "source":           "auction.com",
                    "source_url":       detail_url,
                    # Property characteristics (may be None if not on the page)
                    "beds":             beds_val,
                    "baths":            baths_val,
                    "sqft":             sqft_val,
                    "year_built":       yr_val,
                    "lot_size":         lot_size_str,
                })
                sleep(0.4)

            except Exception as e:
                log.warning(f"  Auction.com: detail error {detail_url}: {e}")

    except Exception as e:
        log.error(f"  Auction.com error: {e}", exc_info=True)

    log.info(f"  Auction.com: found {len(listings)} target-county listings")
    return listings


# ---------------------------------------------------------------------------
# Source 3: HUD Homes
# ---------------------------------------------------------------------------

def scrape_hud_homes() -> list:
    """REMOVED 2026-05 — full implementation in _archived_sources.py."""
    return []
    """
    Scrapes HUD REO listings for Virginia from HUD Homestore.

    URL: https://www.hudhomestore.gov/searchresult?citystate=VA

    As of 2026 HUD Homestore is powered by Yardi and embeds ALL listing data
    as a JSON array inside a hidden <input type="hidden"> element with no
    'name' attribute.  The input value starts with '[{' and contains one
    object per property.

    Key JSON fields per listing:
      propertyCaseNumber, propertyAddress, propertyCity, propertyState,
      propertyZip, propertyCounty, listPrice, bedrooms, bathrooms,
      squareFootage, yearBuilt, bidOpenDate, periodDeadlineDate,
      listDate, listingPeriod, propertyStatus

    propertyCounty values for our targets (no "County" suffix):
      "Stafford", "Spotsylvania", "Caroline", "Fredericksburg"
    """
    listings = []
    url = "https://www.hudhomestore.gov/searchresult?citystate=VA"
    log.info(f"  HUD Homes: {url}")

    TARGET_COUNTIES_HUD = {
        "stafford", "spotsylvania", "caroline", "fredericksburg",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond", "chesterfield", "henrico", "louisa",
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Find the hidden input whose value is the JSON property array
        # It has no 'name' attribute and its value starts with '[{'
        json_input = None
        for inp in soup.find_all("input", type="hidden"):
            val = inp.get("value", "")
            if val.startswith("[{"):
                json_input = inp
                break

        if not json_input:
            # Fallback: search raw HTML for the JSON array pattern
            m = re.search(r'value="\s*(\[\{.*?\}])\s*"', resp.text, re.S)
            raw_json = m.group(1) if m else None
        else:
            raw_json = json_input.get("value", "")

        if not raw_json:
            log.warning("  HUD Homes: JSON property data not found in page — site may have changed")
            return listings

        try:
            properties = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            log.error(f"  HUD Homes: JSON parse error: {exc}")
            return listings

        log.info(f"  HUD Homes: {len(properties)} total VA properties in JSON")

        for prop in properties:
            county_raw = str(prop.get("propertyCounty", "")).strip()
            if county_raw.lower() not in TARGET_COUNTIES_HUD:
                continue

            address   = str(prop.get("propertyAddress", "")).strip()
            city_raw  = str(prop.get("propertyCity", "")).strip()
            state_raw = str(prop.get("propertyState", "")).strip()
            zip_raw   = str(prop.get("propertyZip", "")).strip()
            case_num  = str(prop.get("propertyCaseNumber", "")).strip()

            # Normalise county display name
            county_display_hud = {
                "stafford":       "Stafford",
                "spotsylvania":   "Spotsylvania",
                "caroline":       "Caroline",
                "fredericksburg": "Fredericksburg City",
                "fauquier":       "Fauquier",
                "culpeper":       "Culpeper",
                "king george":    "King George",
                "hanover":        "Hanover",
                "richmond":       "Richmond City",
                "chesterfield":   "Chesterfield",
                "henrico":        "Henrico",
                "louisa":         "Louisa",
            }.get(county_raw.lower(), county_raw.title())

            # Price
            price = None
            try:
                raw_price = prop.get("listPrice")
                if raw_price not in (None, "", "0"):
                    price = int(float(str(raw_price).replace(",", "")))
            except (ValueError, TypeError):
                pass

            # Bid-open date (format: "MM/DD/YYYY" or ISO)
            sale_date = None
            raw_date = prop.get("bidOpenDate") or prop.get("listDate")
            if raw_date:
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        sale_date = datetime.strptime(str(raw_date)[:19], fmt).date().isoformat()
                        break
                    except ValueError:
                        continue

            # Build a detail URL from the case number if available
            source_url = None
            if case_num:
                source_url = (
                    f"https://www.hudhomestore.gov/Listing/PropertyListing.aspx"
                    f"?caseNumber={case_num.replace('-', '')}"
                )

            listings.append({
                "id":               make_id(address or case_num, sale_date),
                "address":          address,
                "city":             city_raw or county_city(county_raw),
                "county":           county_display_hud,
                "zip":              zip_raw or None,
                "stage":            "reo",
                "property_type":    "single-family",
                "assessed_value":   None,
                "asking_price":     price,
                "sale_date":        sale_date,
                "sale_time":        None,
                "sale_location":    None,
                "days_until_sale":  None,
                "notice_date":      None,
                "days_in_foreclosure": None,
                "lender":           "HUD / FHA",
                "trustee":          None,
                "source":           "hud_homes",
                "source_url":       source_url,
            })

        sleep(1)

    except Exception as e:
        log.error(f"  HUD Homes error: {e}", exc_info=True)

    log.info(f"  HUD Homes: found {len(listings)} target-county listings")
    return listings


# ---------------------------------------------------------------------------
# Source 4: Fannie Mae HomePath
# ---------------------------------------------------------------------------

def scrape_homepath() -> list:
    """REMOVED 2026-05 — full implementation in _archived_sources.py."""
    return []
    """
    Fetches Fannie Mae REO listings from HomePath's JSON API.

    API endpoint (discovered via browser DevTools):
      GET https://homepath.fanniemae.com/cfl/property-inventory/search?bounds={s},{w},{n},{e}

    Bounding box for Fredericksburg metro (Fredericksburg City, Stafford,
    Spotsylvania, Caroline counties):
      South 37.85, West -77.80, North 38.60, East -77.10

    Response JSON: { "properties": [ {addressLine1, city, county, state,
                                       zipCode, price, mlsId, propertyType, ...} ] }
    """
    listings = []

    # Bounding box covering all 12 target counties
    # S=37.30 (Chesterfield), W=-78.30 (Culpeper/Louisa), N=38.90 (Fauquier), E=-77.10
    bounds = "37.30,-78.30,38.90,-77.10"
    url    = f"https://homepath.fanniemae.com/cfl/property-inventory/search?bounds={bounds}"
    log.info(f"  HomePath: {url}")

    TARGET_COUNTY_MAP = {
        "fredericksburg": "Fredericksburg City",
        "stafford":       "Stafford",
        "spotsylvania":   "Spotsylvania",
        "caroline":       "Caroline",
        "fauquier":       "Fauquier",
        "culpeper":       "Culpeper",
        "king george":    "King George",
        "hanover":        "Hanover",
        "richmond":       "Richmond City",
        "chesterfield":   "Chesterfield",
        "henrico":        "Henrico",
        "louisa":         "Louisa",
    }

    try:
        resp = requests.get(
            url,
            headers={
                **HEADERS,
                "Accept":  "application/json, text/plain, */*",
                "Referer": "https://homepath.fanniemae.com/",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data       = resp.json()
        properties = data.get("properties") or []
        log.info(f"  HomePath: {len(properties)} raw properties in bounding box")

        for item in properties:
            county_raw   = (item.get("county") or "").lower().strip()
            county_clean = TARGET_COUNTY_MAP.get(county_raw)
            if not county_clean:
                continue

            address  = (item.get("addressLine1") or "").title()
            city     = (item.get("city") or "").title()
            zip_code = item.get("zipCode") or ""
            price    = item.get("price")
            mls_id   = item.get("mlsId") or ""
            prop_uuid = item.get("propertyUuid") or ""

            # Capture property details HomePath already provides
            beds  = item.get("bedrooms")
            baths = item.get("bathrooms")
            sqft  = item.get("sqft")
            beds  = int(beds)  if beds  and float(beds)  > 0 else None
            baths = float(baths) if baths and float(baths) > 0 else None
            sqft  = int(sqft)  if sqft  and int(sqft)   > 0 else None

            # Geo coordinates (useful for future mapping)
            geo   = item.get("geoPoint") or {}
            lat   = geo.get("latitude")
            lon   = geo.get("longitude")

            # Listing flags
            just_added   = item.get("justAdded", False)
            ending_soon  = item.get("endingSoon", False)
            img_url      = item.get("primHiResImageUrl") or None

            listings.append({
                "id":               make_id(f"{address} {city}", None),
                "address":          address,
                "city":             city,
                "county":           county_clean,
                "zip":              zip_code,
                "stage":            "reo",
                "property_type":    normalize_property_type(item.get("propertyType") or ""),
                "assessed_value":   None,
                "asking_price":     price,
                "beds":             beds,
                "baths":            baths,
                "sqft":             sqft,
                "latitude":         lat,
                "longitude":        lon,
                "image_url":        img_url,
                "just_added":       just_added,
                "ending_soon":      ending_soon,
                "sale_date":        None,
                "sale_time":        None,
                "sale_location":    None,
                "days_until_sale":  None,
                "notice_date":      None,
                "days_in_foreclosure": None,
                "lender":              "Fannie Mae",
                "owner_name":          "Fannie Mae",
                "owner_mailing_address": "3900 Wisconsin Ave NW, Washington, DC 20016",
                "owner_mailing_differs": "Yes",
                "owner_phone":         "1-800-732-6643",
                "owner_email":         "",
                "trustee":             None,
                "source":           "homepath",
                "source_url":       (f"https://homepath.fanniemae.com/property-detail/{prop_uuid}"
                                     if prop_uuid else None),
            })

        sleep(1)

    except Exception as e:
        log.error(f"  HomePath error: {e}", exc_info=True)

    log.info(f"  HomePath: found {len(listings)} target-county listings")
    return listings


def scrape_homesteps() -> list:
    """REMOVED 2026-05 — full implementation in _archived_sources.py."""
    return []
    """
    Scrapes Freddie Mac HomeSteps REO listings for Virginia.

    URL: https://www.homesteps.com/listing/search?search=Virginia

    The site is server-rendered Drupal — Python requests gets full HTML with
    all listing data embedded. Each listing is a bare <li> element containing:

      .property-address   → "804 Carter St, Martinsville, VA 24112"
      .property-price     → "$34,900"
      .property-details   → "2 beds, 1 bath, 840 sq. ft."
      .property-status-value → "Active"
      a[href*=/listingdetails/] → "/listingdetails/804-carter-st-martinsville-va-24112"

    County is not present in the listing HTML — derived from city via city_to_county().
    """
    listings = []
    url = "https://www.homesteps.com/listing/search?search=Virginia"
    log.info(f"  HomeSteps: {url}")

    TARGET_COUNTIES_SET = {
        "fredericksburg city", "stafford", "spotsylvania", "caroline",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond city", "chesterfield", "henrico", "louisa",
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Each listing is a <li> containing a /listingdetails/ link
        items = [
            li for li in soup.find_all("li")
            if li.find("a", href=re.compile(r"/listingdetails/"))
        ]
        log.info(f"  HomeSteps: {len(items)} total listings on page")

        for item in items:
            # ── Address ────────────────────────────────────────────────────
            addr_el = item.find(class_="property-address")
            if not addr_el:
                continue
            addr_text = addr_el.get_text(" ", strip=True)
            # "804 Carter St, Martinsville, VA 24112"
            addr_m = re.match(
                r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                addr_text
            )
            if not addr_m:
                continue
            street   = addr_m.group(1).strip()
            city_raw = addr_m.group(2).strip()
            state    = addr_m.group(3)
            zip_code = addr_m.group(4)

            # Only Virginia — filter out "New Virginia, IA" etc.
            if state != "VA":
                continue

            # Derive county from city and check against target list
            county = city_to_county(city_raw)
            if county == "Unknown" or county.lower() not in TARGET_COUNTIES_SET:
                continue

            # ── Price ──────────────────────────────────────────────────────
            price = None
            price_el = item.find(class_="property-price")
            if price_el:
                price = parse_price(price_el.get_text())

            # ── Beds / baths / sqft ────────────────────────────────────────
            beds = baths = sqft = None
            details_el = item.find(class_="property-details")
            if details_el:
                dt = details_el.get_text()
                beds_m  = re.search(r"(\d+)\s*bed", dt)
                baths_m = re.search(r"([\d.]+)\s*bath", dt)
                sqft_m  = re.search(r"([\d,]+)\s*sq\.?\s*ft", dt, re.I)
                beds  = int(beds_m.group(1))                    if beds_m  else None
                baths = float(baths_m.group(1))                 if baths_m else None
                sqft  = int(sqft_m.group(1).replace(",", ""))   if sqft_m  else None

            # ── Detail URL ─────────────────────────────────────────────────
            link_el = item.find("a", href=re.compile(r"/listingdetails/"))
            href = link_el["href"] if link_el else None
            source_url = (
                ("https://www.homesteps.com" + href)
                if href and not href.startswith("http") else href
            )

            listings.append({
                "id":               make_id(f"{street} {city_raw}", None),
                "address":          street,
                "city":             city_raw.title(),
                "county":           county,
                "zip":              zip_code or None,
                "stage":            "reo",
                "property_type":    "single-family",
                "assessed_value":   None,
                "asking_price":     price,
                "beds":             beds,
                "baths":            baths,
                "sqft":             sqft,
                "sale_date":        None,
                "sale_time":        None,
                "sale_location":    None,
                "days_until_sale":  None,
                "notice_date":      None,
                "days_in_foreclosure": None,
                "lender":           "Freddie Mac",
                "owner_name":       "Freddie Mac",
                "owner_mailing_address": "8200 Jones Branch Dr, McLean, VA 22102",
                "owner_mailing_differs": "Yes",
                "owner_phone":      "1-800-FREDDIE",
                "owner_email":      "",
                "trustee":          None,
                "source":           "homesteps",
                "source_url":       source_url,
            })

        sleep(1)

    except Exception as e:
        log.error(f"  HomeSteps error: {e}", exc_info=True)

    log.info(f"  HomeSteps: found {len(listings)} target-county listings")
    return listings


# -- 5d: Virginia Gazette / Williamsburg (Group 6) ---------------------------

def _parse_date_flexible(text: str) -> str | None:
    """
    Try multiple date formats found on the LOGS sales report page and return
    an ISO date string (YYYY-MM-DD), or None if no date is found.

    Handles: "June 3, 2026", "Jun 3, 2026", "6/3/2026", "06/03/2026",
             "2026-06-03", "June 3 2026" (no comma).
    """
    if not text:
        return None
    text = text.strip()
    for fmt in (
        "%B %d, %Y", "%B %d %Y",
        "%b %d, %Y",  "%b %d %Y",
        "%m/%d/%Y",   "%m-%d-%Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # Try extracting a date fragment from a longer string and retry
    m = re.search(
        r'(\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
        r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
        r'Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})',
        text, re.I,
    )
    if m:
        return _parse_date_flexible(m.group(1))
    return None


def scrape_logs_legal() -> list:
    """
    Group 2: LOGS Legal Group / Professional Foreclosure Corporation of Virginia (PFCVA).

    URL: https://www.logs.com/va-sales-report.html

    DISABLED 2026-05: LOGS Legal migrated their sales report to a PowerBI embedded
    iframe.  BeautifulSoup cannot execute the PowerBI JavaScript or fetch data from
    the iframe's API endpoints, so no structured listing data is available without
    Playwright + PowerBI reverse-engineering.  The scraper is disabled until a
    replacement approach is implemented.

    To re-enable: set ENABLE_LOGS_LEGAL = True in config.py AND replace this
    function body with a Playwright-based approach that loads the PowerBI iframe.
    """
    log.error(
        "  LOGS Legal: DISABLED — site now uses a PowerBI embedded iframe "
        "(detected 2026-05-15). BS4 HTML table scraping returns 0 results. "
        "Set ENABLE_LOGS_LEGAL=False in config.py to suppress this message."
    )
    return []
    listings = []
    url      = "https://www.logs.com/va-sales-report.html"
    log.info(f"  LOGS Legal: {url}")

    TARGET_COUNTY_KEYS = {
        "fredericksburg", "stafford", "spotsylvania", "caroline",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond", "chesterfield", "henrico", "louisa",
    }

    COUNTY_DISPLAY_MAP = {
        "fredericksburg": "Fredericksburg City",
        "stafford":       "Stafford",
        "spotsylvania":   "Spotsylvania",
        "caroline":       "Caroline",
        "fauquier":       "Fauquier",
        "culpeper":       "Culpeper",
        "king george":    "King George",
        "hanover":        "Hanover",
        "richmond":       "Richmond City",
        "chesterfield":   "Chesterfield",
        "henrico":        "Henrico",
        "louisa":         "Louisa",
    }

    def _row_county(cells_lower: list[str]) -> str | None:
        """Return the first target county key found anywhere in a row's cell text."""
        joined = " ".join(cells_lower)
        for key in TARGET_COUNTY_KEYS:
            if key in joined:
                return key
        return None

    def _col_map(headers: list[str]) -> dict:
        """Map logical field names to column indices from a header row."""
        idx: dict = {}
        for i, h in enumerate(headers):
            h = h.lower()
            if any(k in h for k in ("address", "property", "location", "sale site")):
                idx.setdefault("address", i)
            if any(k in h for k in ("county", "jurisdiction", "city", "locality")):
                idx.setdefault("county", i)
            if "date" in h and "time" not in h:
                idx.setdefault("date", i)
            if "time" in h:
                idx.setdefault("time", i)
            if any(k in h for k in ("bid", "price", "amount", "opening")):
                idx.setdefault("price", i)
        return idx

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        processed_rows = 0

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            # Detect header row
            first_cells = [
                c.get_text(separator=" ", strip=True)
                for c in rows[0].find_all(["th", "td"])
            ]
            col_idx = _col_map(first_cells)

            # Skip tables with no recognisable address or date column
            if not col_idx.get("address") and not col_idx.get("date"):
                continue

            for row in rows[1:]:
                cells      = row.find_all(["td", "th"])
                cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                if len(cell_texts) < 2:
                    continue

                cells_lower = [t.lower() for t in cell_texts]
                county_key  = _row_county(cells_lower)
                if not county_key:
                    continue

                processed_rows += 1

                # ── Address ───────────────────────────────────────────────
                if "address" in col_idx and col_idx["address"] < len(cell_texts):
                    addr_raw = cell_texts[col_idx["address"]]
                else:
                    # Heuristic: pick the cell most likely to hold a street address
                    addr_raw = next(
                        (t for t in cell_texts if re.search(r'\d+\s+[A-Za-z]', t)),
                        " ".join(cell_texts),
                    )

                # ── Sale date ─────────────────────────────────────────────
                if "date" in col_idx and col_idx["date"] < len(cell_texts):
                    sale_date = _parse_date_flexible(cell_texts[col_idx["date"]])
                else:
                    sale_date = next(
                        filter(None, (_parse_date_flexible(t) for t in cell_texts)),
                        None,
                    )

                # ── Sale time ─────────────────────────────────────────────
                if "time" in col_idx and col_idx["time"] < len(cell_texts):
                    sale_time = cell_texts[col_idx["time"]]
                else:
                    tm = next(
                        (re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)', t, re.I) for t in cell_texts if re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)', t, re.I)),
                        None,
                    )
                    sale_time = tm.group(0).upper() if tm else None

                county_display_name = COUNTY_DISPLAY_MAP.get(county_key, county_key.title())
                addr_parsed, street, city, zip_code = extract_address(addr_raw)
                if not addr_parsed:
                    addr_parsed = addr_raw
                    street      = addr_raw

                full_row_text = " | ".join(cell_texts)

                listings.append({
                    "id":                  make_id(addr_parsed, sale_date),
                    "address":             addr_parsed,
                    "city":                city.title() if city else "",
                    "county":              county_display_name,
                    "zip":                 zip_code,
                    "stage":               "auction" if sale_date else "pre-fc",
                    "property_type":       "single-family",
                    "assessed_value":      None,
                    "asking_price":        None,
                    "sale_date":           sale_date,
                    "sale_time":           sale_time,
                    "sale_location":       courthouse_location(county_key),
                    "days_until_sale":     None,
                    "notice_date":         date.today().isoformat(),
                    "days_in_foreclosure": 0,
                    "lender":              None,
                    "trustee":             "LOGS Legal Group / PFCVA",
                    "notice_text":         full_row_text[:5000],
                    "source":              "logs_legal",
                    "source_url":          url,
                })
                log.info(
                    f"  LOGS Legal: ADDED — {addr_parsed} | "
                    f"county: {county_display_name} | sale: {sale_date or 'TBD'}"
                )

        # ── Fallback: no structured table found — text-based scan ─────────
        if not processed_rows:
            log.info("  LOGS Legal: no structured table rows found — trying text scan fallback")
            page_text = soup.get_text(separator="\n")
            for line in page_text.splitlines():
                line_lower = line.lower()
                county_key = next(
                    (k for k in TARGET_COUNTY_KEYS if k in line_lower), None
                )
                if not county_key:
                    continue
                addr_parsed, street, city, zip_code = extract_address(line)
                if not addr_parsed:
                    continue
                sale_date = _parse_date_flexible(line)
                county_display_name = COUNTY_DISPLAY_MAP.get(county_key, county_key.title())
                listings.append({
                    "id":                  make_id(addr_parsed, sale_date),
                    "address":             addr_parsed,
                    "city":                city.title() if city else "",
                    "county":              county_display_name,
                    "zip":                 zip_code,
                    "stage":               "auction" if sale_date else "pre-fc",
                    "property_type":       "single-family",
                    "assessed_value":      None,
                    "asking_price":        None,
                    "sale_date":           sale_date,
                    "sale_time":           None,
                    "sale_location":       courthouse_location(county_key),
                    "days_until_sale":     None,
                    "notice_date":         date.today().isoformat(),
                    "days_in_foreclosure": 0,
                    "lender":              None,
                    "trustee":             "LOGS Legal Group / PFCVA",
                    "notice_text":         line[:5000],
                    "source":              "logs_legal",
                    "source_url":          url,
                })
                log.info(
                    f"  LOGS Legal (text-scan): ADDED — {addr_parsed} | "
                    f"county: {county_display_name} | sale: {sale_date or 'TBD'}"
                )

    except Exception as e:
        log.error(f"  LOGS Legal error: {e}", exc_info=True)

    # Post-fetch date filter — drop listings whose sale has already passed
    # the LOOKBACK_DAYS window.  Listings with no parsed sale_date are kept
    # (unknown date is safer to include than silently drop).
    since_iso = cfg.SINCE_DATE.isoformat()
    before_filter = len(listings)
    listings = [
        l for l in listings
        if not l.get("sale_date") or l["sale_date"] >= since_iso
    ]
    dropped = before_filter - len(listings)
    if dropped:
        log.info(
            f"  LOGS Legal: dropped {dropped} listing(s) with sale_date "
            f"before {since_iso} ({cfg.LOOKBACK_DAYS}-day window)"
        )

    log.info(f"  LOGS Legal: found {len(listings)} target-county listing(s)")
    return listings


# ---------------------------------------------------------------------------
# Source 8: Samuel I. White, P.C. — Virginia Sales Report  (Group 8)
# ---------------------------------------------------------------------------

def scrape_siwpc() -> list:
    """
    Group 8: Samuel I. White, P.C. (SIWPC) — upcoming trustee sales.

    URL: https://www.siwpc.com/sales-report

    SIWPC is one of Virginia's highest-volume foreclosure law firms, handling
    trustee sales across the entire state.  Their sales report is server-rendered
    HTML (no JavaScript required) with a structured table of upcoming auctions.

    Strategy:
      1. Fetch the page with requests + BeautifulSoup.
      2. Parse the main sales table — columns typically include Property Address,
         County/City, Sale Date, Sale Time, and Opening Bid.
      3. Filter rows to target counties.
      4. Fallback: if no structured table matches, text-scan paragraphs for
         address + county + date patterns.

    Note: SIWPC often lists sales 2–4 weeks before they appear on PNV, giving
    early warning for high-volume counties like Henrico and Chesterfield.
    """
    listings = []
    url      = "https://www.siwpc.com/sales-report"
    log.info(f"  SIWPC: {url}")

    TARGET_COUNTY_KEYS = {
        "fredericksburg", "stafford", "spotsylvania", "caroline",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond", "chesterfield", "henrico", "louisa",
    }

    COUNTY_DISPLAY_MAP = {
        "fredericksburg": "Fredericksburg City",
        "stafford":       "Stafford",
        "spotsylvania":   "Spotsylvania",
        "caroline":       "Caroline",
        "fauquier":       "Fauquier",
        "culpeper":       "Culpeper",
        "king george":    "King George",
        "hanover":        "Hanover",
        "richmond":       "Richmond City",
        "chesterfield":   "Chesterfield",
        "henrico":        "Henrico",
        "louisa":         "Louisa",
    }

    def _row_county(cells_lower: list[str]) -> str | None:
        joined = " ".join(cells_lower)
        for key in TARGET_COUNTY_KEYS:
            if key in joined:
                return key
        return None

    def _col_map(headers: list[str]) -> dict:
        idx: dict = {}
        for i, h in enumerate(headers):
            h_l = h.lower()
            if any(k in h_l for k in ("address", "property", "location", "sale site", "street")):
                idx.setdefault("address", i)
            if any(k in h_l for k in ("county", "jurisdiction", "city", "locality")):
                idx.setdefault("county", i)
            if "date" in h_l and "time" not in h_l:
                idx.setdefault("date", i)
            if "time" in h_l:
                idx.setdefault("time", i)
            if any(k in h_l for k in ("bid", "price", "amount", "opening")):
                idx.setdefault("price", i)
        return idx

    def _parse_date_siwpc(text: str) -> str | None:
        """Try multiple date formats used on the SIWPC sales report."""
        if not text:
            return None
        text = text.strip()
        for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                    "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                continue
        # Extract date fragment from longer string
        m = re.search(
            r'(\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
            r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|'
            r'Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})',
            text, re.I,
        )
        if m:
            return _parse_date_siwpc(m.group(1))
        return None

    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        # verify=False: siwpc.com is served with a *.bizland.com wildcard cert that
        # doesn't cover the siwpc.com hostname — SSL handshake fails without this.
        resp = requests.get(url, headers=HEADERS, timeout=25, verify=False)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        processed_rows = 0

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue

            first_cells = [
                c.get_text(separator=" ", strip=True)
                for c in rows[0].find_all(["th", "td"])
            ]
            col_idx = _col_map(first_cells)

            if not col_idx.get("address") and not col_idx.get("date"):
                continue

            for row in rows[1:]:
                cells      = row.find_all(["td", "th"])
                cell_texts = [c.get_text(separator=" ", strip=True) for c in cells]
                if len(cell_texts) < 2:
                    continue

                cells_lower = [t.lower() for t in cell_texts]
                county_key  = _row_county(cells_lower)
                if not county_key:
                    continue

                processed_rows += 1

                addr_raw = (
                    cell_texts[col_idx["address"]]
                    if "address" in col_idx and col_idx["address"] < len(cell_texts)
                    else next(
                        (t for t in cell_texts if re.search(r'\d+\s+[A-Za-z]', t)),
                        " ".join(cell_texts)
                    )
                )

                sale_date = (
                    _parse_date_siwpc(cell_texts[col_idx["date"]])
                    if "date" in col_idx and col_idx["date"] < len(cell_texts)
                    else next(
                        filter(None, (_parse_date_siwpc(t) for t in cell_texts)), None
                    )
                )

                sale_time = None
                if "time" in col_idx and col_idx["time"] < len(cell_texts):
                    sale_time = cell_texts[col_idx["time"]]
                else:
                    tm = next(
                        (re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)', t, re.I)
                         for t in cell_texts if re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM)', t, re.I)),
                        None,
                    )
                    sale_time = tm.group(0).upper() if tm else None

                asking_price = None
                if "price" in col_idx and col_idx["price"] < len(cell_texts):
                    pm = re.search(r'\$([\d,]+)', cell_texts[col_idx["price"]])
                    if pm:
                        asking_price = int(pm.group(1).replace(",", ""))

                county_display_name = COUNTY_DISPLAY_MAP.get(county_key, county_key.title())
                addr_parsed, street, city, zip_code = extract_address(addr_raw)
                if not addr_parsed:
                    addr_parsed = addr_raw
                    street      = addr_raw

                full_row_text = " | ".join(cell_texts)
                listings.append({
                    "id":           make_id(addr_parsed, sale_date),
                    "address":      addr_parsed,
                    "city":         city.title() if city else "",
                    "county":       county_display_name,
                    "zip":          zip_code,
                    "stage":        "auction" if sale_date else "pre-fc",
                    "asking_price": asking_price,
                    "sale_date":    sale_date,
                    "sale_time":    sale_time,
                    "sale_location":courthouse_location(county_key),
                    "lender":       None,
                    "trustee":      "Samuel I. White, P.C.",
                    "notice_text":  full_row_text[:5000],
                    "source":       "siwpc",
                    "source_url":   url,
                })
                log.info(
                    f"  SIWPC: ADDED — {addr_parsed} | "
                    f"county: {county_display_name} | sale: {sale_date or 'TBD'}"
                )

        # Text-scan fallback if no structured table parsed
        if not processed_rows:
            log.info("  SIWPC: no table rows found — trying text-scan fallback")
            page_text = soup.get_text(separator="\n")
            for line in page_text.splitlines():
                line_lower = line.lower()
                county_key = next(
                    (k for k in TARGET_COUNTY_KEYS if k in line_lower), None
                )
                if not county_key:
                    continue
                addr_parsed, street, city, zip_code = extract_address(line)
                if not addr_parsed:
                    continue
                sale_date = _parse_date_siwpc(line)
                county_display_name = COUNTY_DISPLAY_MAP.get(county_key, county_key.title())
                listings.append({
                    "id":           make_id(addr_parsed, sale_date),
                    "address":      addr_parsed,
                    "city":         city.title() if city else "",
                    "county":       county_display_name,
                    "zip":          zip_code,
                    "stage":        "auction" if sale_date else "pre-fc",
                    "sale_date":    sale_date,
                    "sale_time":    None,
                    "sale_location":courthouse_location(county_key),
                    "trustee":      "Samuel I. White, P.C.",
                    "notice_text":  line[:5000],
                    "source":       "siwpc",
                    "source_url":   url,
                })

    except Exception as e:
        log.error(f"  SIWPC error: {e}", exc_info=True)

    # Post-fetch date filter (LOOKBACK_DAYS window)
    since_iso = cfg.SINCE_DATE.isoformat()
    before = len(listings)
    listings = [
        l for l in listings
        if not l.get("sale_date") or l["sale_date"] >= since_iso
    ]
    if before - len(listings):
        log.info(f"  SIWPC: dropped {before - len(listings)} listing(s) outside {cfg.LOOKBACK_DAYS}-day window")

    log.info(f"  SIWPC: found {len(listings)} target-county listing(s)")
    return listings


# -- 5c: Charlottesville Daily Progress (Group 4) ----------------------------

def scrape_va_courts() -> list:
    """
    Group 9: Virginia eCourts Circuit Court Case Information System.

    URL base: https://eapps.courts.state.va.us/circuitSearch/

    Searches each target county's circuit court for recently filed civil cases
    with "Trustee" or "Foreclosure" in the party or case description.  These
    filings typically precede PNV publication by 2–6 weeks, giving the earliest
    possible signal that a property is entering foreclosure.

    Case type searched: Civil — Deed of Trust / Lis Pendens filings.

    Data returned:
      - Case number and filing date
      - Plaintiff (usually the lender / trustee firm)
      - Defendant (the property owner — matches owner_name later)
      - Address (extracted from case description when available)

    Limitations:
      - The eCourts portal is rate-limited; each county is fetched with a
        CENSUS_DELAY_SECONDS pause to stay polite.
      - Not all counties have migrated to eCourts — Spotsylvania, Caroline,
        King George, and Louisa still use older Clerk systems.  Those counties
        fall back to scraping the individual clerk portal search pages.
      - Address extraction from case descriptions is best-effort; many filings
        only contain party names.  The GIS backfill pass (Pass 6) will attempt
        to find the property address from owner name + county.
      - Stage is always set to "pre-fc" since no auction date is known yet;
        backfill Pass 1 will attempt to find a date from the linked PNV notice.

    To tune: adjust COURT_FIPS or search parameters per county.
    Set ENABLE_VA_COURTS=False in config.py to pause without touching this code.
    """
    listings = []

    # Virginia FIPS codes and court identifiers for each target county.
    # eCourts uses a "courtId" parameter in the search URL.
    # Format: (court_id, display_name, county_key)
    COURT_MAP: list[tuple[str, str, str]] = [
        ("0630",  "Fredericksburg City",  "fredericksburg"),
        ("1790",  "Stafford",             "stafford"),
        ("1770",  "Spotsylvania",         "spotsylvania"),
        ("0190",  "Caroline",             "caroline"),
        ("0610",  "Fauquier",             "fauquier"),
        ("0220",  "Culpeper",             "culpeper"),
        ("0990",  "King George",          "king george"),
        ("0840",  "Hanover",              "hanover"),
        ("1600",  "Richmond City",        "richmond"),
        ("0200",  "Chesterfield",         "chesterfield"),
        ("0870",  "Henrico",              "henrico"),
        ("1040",  "Louisa",               "louisa"),
    ]

    BASE_URL = "https://eapps.courts.state.va.us/circuitSearch/courts/{court_id}/cases/search"

    # Search terms that identify trustee sale / lis pendens filings
    SEARCH_TERMS = ["trustee", "deed of trust", "lis pendens", "foreclosure"]

    for court_id, display_name, county_key in COURT_MAP:
        log.info(f"  VA Courts: querying {display_name} Circuit Court (id={court_id})")

        for term in SEARCH_TERMS[:1]:  # start with "trustee" — broadest match
            try:
                url = BASE_URL.format(court_id=court_id)
                params = {
                    "searchTerm":     term,
                    "caseType":       "civil",
                    "startDate":      cfg.SINCE_DATE.strftime("%m/%d/%Y"),
                    "endDate":        cfg.TODAY.strftime("%m/%d/%Y"),
                    "resultCount":    50,
                    "sortBy":         "filedDate",
                    "sortOrder":      "desc",
                }
                resp = requests.get(
                    url, params=params, headers={
                        **HEADERS,
                        "Accept":  "application/json, text/html, */*",
                        "Referer": "https://eapps.courts.state.va.us/circuitSearch/",
                    },
                    timeout=20,
                )

                # eCourts returns either JSON (if Accept header works) or HTML
                if "application/json" in resp.headers.get("Content-Type", ""):
                    cases = _parse_ecourts_json(resp.json(), display_name, county_key, court_id)
                else:
                    cases = _parse_ecourts_html(resp.text, display_name, county_key, court_id)

                listings.extend(cases)
                if cases:
                    log.info(f"  VA Courts: {len(cases)} filing(s) from {display_name}")
                break   # found results with first term — skip remaining terms

            except requests.exceptions.ConnectionError:
                log.debug(f"  VA Courts: {display_name} — connection error (portal may be down)")
            except Exception as e:
                log.debug(f"  VA Courts: {display_name} error — {e}")

        sleep(cfg.CENSUS_DELAY_SECONDS)   # polite rate limit

    since_iso = cfg.SINCE_DATE.isoformat()
    before = len(listings)
    listings = [
        l for l in listings
        if not l.get("sale_date") or l["sale_date"] >= since_iso
    ]
    log.info(f"  VA Courts: found {len(listings)} lis pendens / trustee filing(s) across all counties")
    return listings


def _parse_ecourts_json(data: dict, display_name: str, county_key: str, court_id: str) -> list:
    """Parse eCourts JSON response into listing dicts."""
    listings = []
    cases = (
        data.get("cases") or
        data.get("results") or
        data.get("data") or
        []
    )
    if isinstance(cases, dict):
        cases = cases.get("cases") or []

    for case in cases:
        case_num     = case.get("caseNumber") or case.get("case_number") or ""
        filed_date   = case.get("filedDate") or case.get("filed_date") or ""
        plaintiff    = case.get("plaintiff") or case.get("plaintiffs") or ""
        defendant    = case.get("defendant") or case.get("defendants") or ""
        description  = case.get("description") or case.get("caseDescription") or ""

        # Try to extract a property address from the case description
        addr_parsed, street, city, zip_code = extract_address(
            f"{description} {plaintiff} {defendant}"
        )

        # Derive filing date as ISO string
        filing_iso = None
        if filed_date:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
                try:
                    filing_iso = datetime.strptime(str(filed_date)[:10], fmt).date().isoformat()
                    break
                except ValueError:
                    continue

        trustee_name = None
        if isinstance(plaintiff, str):
            trustee_name = plaintiff[:80]

        owner_name = None
        if isinstance(defendant, str):
            owner_name = defendant[:80]

        case_url = (
            f"https://eapps.courts.state.va.us/circuitSearch/courts/{court_id}/cases/{case_num}"
            if case_num else None
        )

        notice_text = f"Case {case_num} | Filed: {filed_date} | {description}"

        listings.append({
            "id":            make_id(addr_parsed or f"{county_key}-{case_num}", filing_iso),
            "address":       addr_parsed or f"See case {case_num}",
            "city":          city.title() if city else county_city(county_key),
            "county":        display_name,
            "zip":           zip_code,
            "stage":         "pre-fc",
            "sale_date":     None,   # not yet scheduled — backfill will try to find it
            "sale_time":     None,
            "sale_location": None,
            "owner_name":    owner_name,
            "trustee":       trustee_name,
            "notice_text":   notice_text[:5000],
            "source":        "va_courts",
            "source_url":    case_url or f"https://eapps.courts.state.va.us/circuitSearch/",
        })

    return listings


def _parse_ecourts_html(html: str, display_name: str, county_key: str, court_id: str) -> list:
    """
    Fallback HTML parser for eCourts responses.
    The portal sometimes returns HTML tables instead of JSON.
    """
    listings = []
    soup = BeautifulSoup(html, "lxml")

    # Look for a results table — eCourts uses class "case-results" or similar
    table = (
        soup.find("table", class_=re.compile(r"case.?result|search.?result", re.I)) or
        soup.find("table", id=re.compile(r"case.?result|search.?result", re.I)) or
        soup.find("table")
    )
    if not table:
        return listings

    rows = table.find_all("tr")
    if len(rows) < 2:
        return listings

    # Parse header row to find column positions
    header_cells = [c.get_text(separator=" ", strip=True).lower()
                    for c in rows[0].find_all(["th", "td"])]
    col: dict[str, int] = {}
    for i, h in enumerate(header_cells):
        if "case" in h and "number" in h:
            col.setdefault("case_num", i)
        if "filed" in h or "date" in h:
            col.setdefault("date", i)
        if "plaintiff" in h or "lender" in h or "trustee" in h:
            col.setdefault("plaintiff", i)
        if "defendant" in h or "owner" in h or "borrower" in h:
            col.setdefault("defendant", i)
        if "description" in h or "type" in h:
            col.setdefault("description", i)

    for row in rows[1:]:
        cells = [c.get_text(separator=" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 2:
            continue

        case_num    = cells[col["case_num"]]  if "case_num"   in col and col["case_num"]  < len(cells) else ""
        filed_date  = cells[col["date"]]      if "date"       in col and col["date"]       < len(cells) else ""
        plaintiff   = cells[col["plaintiff"]] if "plaintiff"  in col and col["plaintiff"]  < len(cells) else ""
        defendant   = cells[col["defendant"]] if "defendant"  in col and col["defendant"]  < len(cells) else ""
        description = cells[col["description"]] if "description" in col and col["description"] < len(cells) else ""

        # Only keep rows that look like trustee / foreclosure filings
        combined = f"{plaintiff} {defendant} {description}".lower()
        if not any(kw in combined for kw in ("trustee", "deed of trust", "foreclos", "lis pendens")):
            continue

        addr_parsed, street, city, zip_code = extract_address(
            f"{description} {plaintiff} {defendant}"
        )

        filing_iso = None
        if filed_date:
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    filing_iso = datetime.strptime(filed_date[:10], fmt).date().isoformat()
                    break
                except ValueError:
                    continue

        case_url = (
            f"https://eapps.courts.state.va.us/circuitSearch/courts/{court_id}/cases/{case_num}"
            if case_num else None
        )

        listings.append({
            "id":            make_id(addr_parsed or f"{county_key}-{case_num}", filing_iso),
            "address":       addr_parsed or f"See case {case_num}",
            "city":          city.title() if city else county_city(county_key),
            "county":        display_name,
            "zip":           zip_code,
            "stage":         "pre-fc",
            "sale_date":     None,
            "sale_time":     None,
            "sale_location": None,
            "owner_name":    defendant[:80] if defendant else None,
            "trustee":       plaintiff[:80] if plaintiff else None,
            "notice_text":   f"Case {case_num} | Filed: {filed_date} | {description}"[:5000],
            "source":        "va_courts",
            "source_url":    case_url or "https://eapps.courts.state.va.us/circuitSearch/",
        })

    return listings


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

def parse_address_from_notice(text: str) -> str:
    """
    Virginia trustee sale notices typically open with the property address.
    This grabs a standard street address pattern from the notice text.
    """
    match = re.search(
        r"(\d+\s+[\w\s]+(?:Rd|St|Ave|Dr|Ln|Way|Ct|Blvd|Pl|Pike|Hwy|Ter|Cir|Loop)[^,\n]*)",
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_sale_datetime(text: str):
    """Extract sale date and time from Virginia trustee sale notice text.

    Patterns tried in order, most-specific first:

    1.  "auction [will be] on June 11, 2026 at 11:00 AM"
        "there will be an auction on May 22, 2026 at 1:30 PM"
    1b. "public auction on 5/28/2026 at 10:45 AM"          (numeric date)
    2.  "...on June 22, 2026, at 9:00 AM"                  (general VA phrase)
    2b. "...on 5/28/2026 at 10:45 AM"                      (numeric, general)
    3.  "May 22, 2026 at 1:30 PM"                          (date + at + time, no "on")
    3b. "5/28/2026 at 10:45 AM"                            (numeric, no "on")
    4.  Fallback: scan body for any date and time independently.
    """
    sale_date = None
    sale_time = None

    TIME_PAT      = r'(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.)?)'  # AM/PM optional — e.g. "9:00"
    DATE_PAT      = r'(\w+\s+\d{1,2},?\s*\d{4})'        # "June 22, 2026"
    DATE_PAT_NUM  = r'(\d{1,2}/\d{1,2}/\d{4})'           # "5/28/2026"
    DATE_FMTS     = ("%B %d, %Y", "%B %d %Y")

    def _parse_date(raw: str):
        raw = raw.strip()
        for fmt in DATE_FMTS:
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _parse_date_num(raw: str):
        """Parse M/D/YYYY or MM/DD/YYYY numeric date."""
        raw = raw.strip()
        try:
            return datetime.strptime(raw, "%m/%d/%Y").date().isoformat()
        except ValueError:
            return None

    def _clean_time(raw: str) -> str:
        return (raw.strip().upper()
                .replace("A.M.", "AM").replace("P.M.", "PM")
                .replace(" ", ""))   # "11:00 AM" → "11:00AM" for consistency

    # ── Pattern 1: "auction [will be] on [Month Day, Year] at [Time]" ─────────
    # Covers: "public auction on June 3, 2026 at 10:00 AM"
    #         "there will be an auction on May 22, 2026 at 1:30 PM"
    auction_m = re.search(
        r'auction(?:\s+will\s+be)?\s+on\s+' + DATE_PAT + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if auction_m:
        d = _parse_date(auction_m.group(1))
        t = _clean_time(auction_m.group(2))
        if d:
            return d, t

    # ── Pattern 1b: "auction on M/D/YYYY at [Time]" — numeric date ────────────
    # Covers: "public auction on 5/28/2026 at 10:45 AM"
    auction_num_m = re.search(
        r'auction(?:\s+will\s+be)?\s+on\s+' + DATE_PAT_NUM + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if auction_num_m:
        d = _parse_date_num(auction_num_m.group(1))
        t = _clean_time(auction_num_m.group(2))
        if d:
            return d, t

    # ── Pattern 2: "on [Month Day, Year], at [Time]" — general VA phrase ──────
    # Covers: "will sell at public auction on June 3, 2026, at 10:00 AM"
    general_m = re.search(
        r'\bon\s+' + DATE_PAT + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if general_m:
        d = _parse_date(general_m.group(1))
        t = _clean_time(general_m.group(2))
        if d:
            return d, t

    # ── Pattern 2b: "on M/D/YYYY at [Time]" — numeric date, general phrase ────
    general_num_m = re.search(
        r'\bon\s+' + DATE_PAT_NUM + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if general_num_m:
        d = _parse_date_num(general_num_m.group(1))
        t = _clean_time(general_num_m.group(2))
        if d:
            return d, t

    # ── Pattern 3: "[Month Day, Year] at [Time]" — date + time, no "on" ───────
    # Covers: "May 22, 2026 at 1:30 PM"
    bare_m = re.search(
        DATE_PAT + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if bare_m:
        d = _parse_date(bare_m.group(1))
        t = _clean_time(bare_m.group(2))
        if d:
            return d, t

    # ── Pattern 3b: "M/D/YYYY at [Time]" — numeric date, no "on" ─────────────
    # Covers: "5/28/2026 at 10:45 AM"
    bare_num_m = re.search(
        DATE_PAT_NUM + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if bare_num_m:
        d = _parse_date_num(bare_num_m.group(1))
        t = _clean_time(bare_num_m.group(2))
        if d:
            return d, t

    # ── Pattern 4: fallback — scan body for any date and time independently ───
    date_match = re.search(r"(\w+ \d{1,2},?\s*\d{4}|\d{1,2}/\d{1,2}/\d{4})", text)
    time_match = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.))", text, re.IGNORECASE)

    if date_match:
        raw = date_match.group(1).strip()
        for fmt in ("%B %d, %Y", "%B %d %Y", "%m/%d/%Y"):
            try:
                sale_date = datetime.strptime(raw, fmt).date().isoformat()
                break
            except ValueError:
                continue

    if time_match:
        sale_time = _clean_time(time_match.group(1))

    return sale_date, sale_time


def parse_original_principal(text: str):
    """Extract original principal amount from notice text.

    Patterns tried in order:
    1. "the original principal amount of $447,740.00"
    2. "a loan which was originally $356,684.00"
    Returns: "$447,740.00" as a string, or None.
    """
    # Pattern 1: "original principal amount of $X"
    m1 = re.search(
        r'original\s+principal\s+amount\s+of\s+(\$[\d,]+(?:\.\d{2})?)',
        text, re.IGNORECASE
    )
    if m1:
        return m1.group(1).strip()

    # Pattern 2: "a loan which was originally $X"
    m2 = re.search(
        r'loan\s+which\s+was\s+originally\s+(\$[\d,]+(?:\.\d{2})?)',
        text, re.IGNORECASE
    )
    if m2:
        return m2.group(1).strip()

    return None


def parse_deposit(text: str):
    """Extract deposit requirement from notice text.

    Matches: "A deposit of $45,000.00 or 10% of the successful bid amount"
    Returns the full deposit clause as a string, or None.
    """
    match = re.search(
        r'((?:A\s+)?deposit\s+of\s+\$[\d,]+(?:\.\d{2})?[^.]{0,80})',
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_deed_of_trust_date(text: str):
    """Extract the Deed of Trust date from notice text.

    Patterns tried in order:

    1. "Deed of Trust dated June 4, 2021"          — explicit DOT reference
       "Deed of Trust dated 06/04/2021"
    2. "original principal amount of $305,000.00 dated December 23, 2005"
       — dollar amount followed by "dated [date]"

    Returns ISO date string (YYYY-MM-DD), or None.
    """
    DATE_FMTS = ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y",
                 "%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d")

    def _try_parse(raw: str):
        raw = raw.strip().rstrip(',')
        for fmt in DATE_FMTS:
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return raw  # return raw string if no format matched

    # ── Pattern 1: "Deed of Trust dated [date]" ───────────────────────────────
    m1 = re.search(
        r'Deed\s+of\s+Trust\s+dated\s+([\w/,\s]+?\d{4})',
        text, re.IGNORECASE
    )
    if m1:
        return _try_parse(m1.group(1))

    # ── Pattern 2: "principal amount of $X.XX[,] dated [date]" ───────────────
    # Covers: "original principal amount of $305,000.00 dated December 23, 2005"
    #         "original principal amount of $235,125.00, dated March 1, 2013"
    m2 = re.search(
        r'principal\s+amount\s+of\s+\$[\d,]+(?:\.\d{2})?\s*,?\s*dated\s+([\w/,\s]+?\d{4})',
        text, re.IGNORECASE
    )
    if m2:
        return _try_parse(m2.group(1))

    return None


def parse_lender(text: str) -> str:
    """Look for common lender name patterns in notice text."""
    match = re.search(
        r"(Wells Fargo|Bank of America|Chase|JPMorgan|PNC|U\.?S\.?\s*Bank|"
        r"Rocket\s*Mortgage|Truist|SunTrust|USAA|Navy Federal|Mr\.\s*Cooper|"
        r"Freedom\s*Mortgage|Pennymac|Lakeview\s*Loan|CrossCountry)[^,.\n]*",
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_trustee(text: str) -> str:
    """Look for common Virginia trustee firm names."""
    match = re.search(
        r"(Samuel\s*I\.?\s*White|BWW\s*Law|Friedman\s*&\s*MacFadyen|"
        r"Hutchens\s*Law|Substitute\s*Trustee\s*Services|Brock\s*&\s*Scott|"
        r"McCabe\s*,?\s*Weisberg|Shapiro\s*&\s*Brown|Cohn\s*Goldberg|"
        r"Atlantic\s*Trustee\s*Services)[^,.\n]*",
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_price(text: str):
    """Parse a dollar amount string into an integer."""
    match = re.search(r"\$([\d,]+)", text)
    return int(match.group(1).replace(",", "")) if match else None


def extract_address(text: str):
    """
    Extract full address (street, city, VA, ZIP) from foreclosure notice text.

    Returns (addr_raw, street, city, zip_code) or (None, None, None, None).

    Priority order — "SALE" anchored patterns first so that when a notice
    contains multiple addresses (property + courthouse + trustee office), we
    always pick the one that immediately follows a sale reference:

      1. TRUSTEE'S SALE OF <address VA ZIP>
      2. SUBSTITUTE TRUSTEE SALE <address VA ZIP>  (handles "OF SUBSTITUTE..." prefix)
      3. TRUSTEE'S SALE newline then address on next line
      4. Any "SALE" immediately followed by an address (general fallback)
      5. Direct: house number + street + city + VA + ZIP anywhere in text
         (last resort — may pick up courthouse/trustee address if no sale anchor found)
    """
    addr_raw = None

    # Pattern 1 — TRUSTEE'S SALE OF <address incl VA ZIP>
    m = re.search(
        r"TRUSTEE.{0,3}S\s+SALE\s+OF\s+(\d+[^\n]*?(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
        text, re.I
    )
    if m:
        addr_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    # Pattern 2 — (OF) (NOTICE OF) SUBSTITUTE TRUSTEE SALE <address incl VA ZIP>
    if not addr_raw:
        m = re.search(
            r"(?:OF\s+)?(?:NOTICE\s+OF\s+)?SUBSTITUTE\s+TRUSTEE.{0,10}SALE\s+(\d+[^\n]*?(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
            text, re.I
        )
        if m:
            addr_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    # Pattern 3 — TRUSTEE'S SALE newline, address on next line
    if not addr_raw:
        m = re.search(
            r"TRUSTEE.{0,3}S\s+SALE\s*\n\s*(\d+\s+[A-Z0-9][^,\n]{4,60},\s*[A-Z][^,\n]{1,35},\s*(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
            text, re.I
        )
        if m:
            addr_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    # Pattern 4 — Generic: any word "SALE" immediately before an address
    if not addr_raw:
        m = re.search(
            r"\bSALE\b\s+(?:OF\s+)?(\d+[^\n]*?(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
            text, re.I
        )
        if m:
            addr_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    # Pattern 5 — Direct: any VA address in text (last resort)
    if not addr_raw:
        m = re.search(
            r"(\d+\s+[A-Z0-9][^,\n]{4,60},\s*[A-Z][^,\n]{1,35},\s*(?:VA|Virginia)\s+\d{5}(?:-\d{4})?)",
            text, re.I
        )
        if m:
            addr_raw = re.sub(r"\s+", " ", m.group(1)).strip()

    if not addr_raw:
        return None, None, None, None

    # ── Attorney / trustee firm address guard ─────────────────────────────────
    # Pattern 5 (last resort) can pick up the trustee's office address when it
    # appears before the property address in the notice text.  The house number
    # regex matches a VSB bar number (e.g. 77676) or suite number, followed by
    # the firm name containing LLC / PLLC / LLP / Inc / Corp / Esq / VSB / Suite.
    # Reject the match and return nothing — the scraper will skip this notice
    # rather than log a garbled trustee address as the property.
    _FIRM_INDICATORS = re.compile(
        r'\b(?:LLC|PLLC|LLP|L\.L\.C|P\.L\.L\.C|P\.C\.|Inc\.|Corp\.|'
        r'Esq\.?|Suite\s+\d|Ste\.?\s+\d|VSB\s*#?\s*\d{3,6})\b',
        re.I,
    )
    if _FIRM_INDICATORS.search(addr_raw):
        return None, None, None, None

    # Parse components from full address
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

    return addr_raw, street, city, zip_code


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def county_display(county: str) -> str:
    return {
        # Original target counties
        "fredericksburg":  "Fredericksburg City",
        "stafford":        "Stafford",
        "spotsylvania":    "Spotsylvania",
        "caroline":        "Caroline",
        "fauquier":        "Fauquier",
        "culpeper":        "Culpeper",
        "king george":     "King George",
        "hanover":         "Hanover",
        "richmond":        "Richmond City",
        "chesterfield":    "Chesterfield",
        "henrico":         "Henrico",
        "louisa":          "Louisa",
        # Roanoke area
        "roanoke":         "Roanoke",
        "roanoke city":    "Roanoke City",
        "salem":           "Salem",
        "botetourt":       "Botetourt",
        "bedford":         "Bedford",
        "franklin":        "Franklin",
        "montgomery":      "Montgomery",
        "radford":         "Radford",
        # Lynchburg area
        "lynchburg":       "Lynchburg City",
        "campbell":        "Campbell",
        "appomattox":      "Appomattox",
        "amherst":         "Amherst",
        # Charlottesville area
        "charlottesville": "Charlottesville City",
        "albemarle":       "Albemarle",
        "fluvanna":        "Fluvanna",
        "greene":          "Greene",
        "nelson":          "Nelson",
        # Shenandoah Valley
        "rockingham":      "Rockingham",
        "harrisonburg":    "Harrisonburg City",
        "page":            "Page",
        "shenandoah":      "Shenandoah",
        "augusta":         "Augusta",
        "staunton":        "Staunton City",
        "waynesboro":      "Waynesboro City",
        "warren":          "Warren",
        "frederick":       "Frederick",
        "winchester":      "Winchester City",
        "clarke":          "Clarke",
        # Martinsville / Danville area
        "martinsville":    "Martinsville City",
        "henry":           "Henry",
        "patrick":         "Patrick",
        "danville":        "Danville City",
        "danville city":   "Danville City",
        "pittsylvania":    "Pittsylvania",
        "halifax":         "Halifax",
        # Northern Neck / Middle Peninsula
        "westmoreland":    "Westmoreland",
        "northumberland":  "Northumberland",
        "lancaster":       "Lancaster",
        "essex":           "Essex",
        "richmond county": "Richmond County",
        "middlesex":       "Middlesex",
        "gloucester":      "Gloucester",
        "mathews":         "Mathews",
        # Northern Virginia
        "fairfax":         "Fairfax",
        "fairfax city":    "Fairfax City",
        "arlington":       "Arlington",
        "alexandria":      "Alexandria City",
        "loudoun":         "Loudoun",
        "prince william":  "Prince William",
        "manassas":        "Manassas City",
        # SW Virginia
        "pulaski":         "Pulaski",
        "giles":           "Giles",
        "bland":           "Bland",
        "smyth":           "Smyth",
        "wythe":           "Wythe",
        "grayson":         "Grayson",
        "carroll":         "Carroll",
        "galax":           "Galax City",
        "washington":      "Washington",
        "bristol":         "Bristol City",
        "scott":           "Scott",
        "lee":             "Lee",
        "wise":            "Wise",
        "norton":          "Norton City",
        "dickenson":       "Dickenson",
        "buchanan":        "Buchanan",
        "russell":         "Russell",
        "tazewell":        "Tazewell",
        # Other
        "bath":            "Bath",
        "highland":        "Highland",
        "alleghany":       "Alleghany",
        "rockbridge":      "Rockbridge",
        "lexington":       "Lexington City",
        "buena vista":     "Buena Vista City",
        "craig":           "Craig",
        "floyd":           "Floyd",
        "goochland":       "Goochland",
        "powhatan":        "Powhatan",
        "buckingham":      "Buckingham",
        "charlotte":       "Charlotte",
        "lunenburg":       "Lunenburg",
        "mecklenburg":     "Mecklenburg",
        "brunswick":       "Brunswick",
        "greensville":     "Greensville",
        "emporia":         "Emporia City",
        "dinwiddie":       "Dinwiddie",
        "colonial heights":"Colonial Heights City",
        "petersburg":      "Petersburg City",
        "hopewell":        "Hopewell City",
        "prince george":   "Prince George",
        "charles city":    "Charles City",
        "new kent":        "New Kent",
        "surry":           "Surry",
        "sussex":          "Sussex",
        "accomack":        "Accomack",
        "northampton":     "Northampton",
        "york":            "York",
        "james city":      "James City",
        "williamsburg":    "Williamsburg City",
        "poquoson":        "Poquoson City",
        "hampton":         "Hampton City",
        "newport news":    "Newport News City",
        "norfolk":         "Norfolk City",
        "virginia beach":  "Virginia Beach City",
        "chesapeake":      "Chesapeake City",
        "suffolk":         "Suffolk City",
        "portsmouth":      "Portsmouth City",
        "isle of wight":   "Isle of Wight",
        "southampton":     "Southampton",
        "franklin city":   "Franklin City",
    }.get(county.lower(), "")   # return "" for unrecognised values — never title-case garbage


# First words of valid Virginia county/city names (lowercase).
# Used to validate text captured by the Circuit Court regex before
# calling county_display() — filters out non-county phrases like
# "Building For", "Entrance", etc.
_VA_COUNTY_FIRST_WORDS = {
    "stafford", "spotsylvania", "caroline", "fauquier", "culpeper",
    "king", "hanover", "richmond", "chesterfield", "henrico", "louisa",
    "roanoke", "salem", "botetourt", "bedford", "franklin", "montgomery",
    "radford", "lynchburg", "campbell", "appomattox", "amherst",
    "charlottesville", "albemarle", "fluvanna", "greene", "nelson",
    "rockingham", "harrisonburg", "page", "shenandoah", "augusta",
    "staunton", "waynesboro", "warren", "frederick", "winchester",
    "clarke", "martinsville", "henry", "patrick", "danville",
    "pittsylvania", "halifax", "westmoreland", "northumberland",
    "lancaster", "essex", "middlesex", "gloucester", "mathews",
    "fairfax", "arlington", "alexandria", "loudoun", "prince", "manassas",
    "pulaski", "giles", "bland", "smyth", "wythe", "grayson", "carroll",
    "galax", "washington", "bristol", "scott", "lee", "wise", "norton",
    "dickenson", "buchanan", "russell", "tazewell", "bath", "highland",
    "alleghany", "rockbridge", "lexington", "buena", "craig", "floyd",
    "goochland", "powhatan", "buckingham", "charlotte", "lunenburg",
    "mecklenburg", "brunswick", "greensville", "emporia", "dinwiddie",
    "colonial", "petersburg", "hopewell", "surry", "sussex", "accomack",
    "northampton", "york", "james", "williamsburg", "poquoson", "hampton",
    "newport", "norfolk", "virginia", "chesapeake", "suffolk", "portsmouth",
    "isle", "southampton", "fredericksburg", "new", "charles", "goochland",
}


def valid_va_county(raw: str) -> str:
    """
    Validate a county name captured by the Circuit Court regex.
    Returns the county_display() result if the first word is a known
    Virginia county/city first word; otherwise returns '' so garbage
    phrases like 'Building For' or 'Entrance' are silently dropped.
    """
    if not raw:
        return ""
    first_word = raw.strip().split()[0].lower()
    if first_word not in _VA_COUNTY_FIRST_WORDS:
        return ""
    return county_display(raw.lower()) or raw.strip().title()


def county_city(county: str) -> str:
    """Return the main city name for a county key."""
    return {
        "fredericksburg": "Fredericksburg",
        "stafford":        "Stafford",
        "spotsylvania":    "Fredericksburg",
        "caroline":        "Bowling Green",
        "fauquier":        "Warrenton",
        "culpeper":        "Culpeper",
        "king george":     "King George",
        "hanover":         "Ashland",
        "richmond":        "Richmond",
        "chesterfield":    "Chesterfield",
        "henrico":         "Glen Allen",
        "louisa":          "Louisa",
    }.get(county.lower().replace(" city", "").strip(), county.title())


def courthouse_location(county: str) -> str:
    return {
        "fredericksburg": "Front steps, Fredericksburg Circuit Court, 815 Princess Anne St",
        "stafford":        "Front steps, Stafford Circuit Court, 1300 Courthouse Rd",
        "spotsylvania":    "Front steps, Spotsylvania Circuit Court, 9115 Courthouse Rd",
        "caroline":        "Front steps, Caroline Circuit Court, 112 Courthouse Ln",
        "fauquier":        "Front steps, Fauquier Circuit Court, 29 Ashby St, Warrenton",
        "culpeper":        "Front steps, Culpeper Circuit Court, 135 W Cameron St",
        "king george":     "Front steps, King George Circuit Court, 10459 Courthouse Dr",
        "hanover":         "Front steps, Hanover Circuit Court, 7507 Library Dr",
        "richmond":        "Front steps, Richmond City Circuit Court, 400 N 9th St",
        "chesterfield":    "Front steps, Chesterfield Circuit Court, 9500 Courthouse Rd",
        "henrico":         "Front steps, Henrico Circuit Court, 4301 E Parham Rd",
        "louisa":          "Front steps, Louisa Circuit Court, 100 W Main St",
    }.get(county.lower(), "Courthouse steps — verify with trustee")


def courthouse_for_address(county: str) -> str:
    key = county.lower().replace(" county", "").replace(" city", "").strip()
    return courthouse_location(key)


def normalize_county(raw: str) -> str:
    raw = raw.lower().replace(" county", "").replace(" city", "").strip()
    return county_display(raw)


def city_to_county(city: str) -> str:
    city = city.lower().strip()
    mapping = {
        # Fredericksburg City
        "fredericksburg":    "Fredericksburg City",
        # Stafford
        "stafford":          "Stafford",
        "aquia harbour":     "Stafford",
        "quantico":          "Stafford",
        "garrisonville":     "Stafford",
        # Spotsylvania
        "spotsylvania":      "Spotsylvania",
        "chancellor":        "Spotsylvania",
        "highland park":     "Spotsylvania",
        "lake wilderness":   "Spotsylvania",
        # Caroline
        "bowling green":     "Caroline",
        "milford":           "Caroline",
        "ruther glen":       "Caroline",
        "port royal":        "Caroline",
        # Fauquier
        "warrenton":         "Fauquier",
        "new baltimore":     "Fauquier",
        "bealeton":          "Fauquier",
        "catlett":           "Fauquier",
        "remington":         "Fauquier",
        # Culpeper
        "culpeper":          "Culpeper",
        "jeffersonton":      "Culpeper",
        # King George
        "king george":       "King George",
        "dahlgren":          "King George",
        # Hanover
        "ashland":           "Hanover",
        "mechanicsville":    "Hanover",
        "hanover":           "Hanover",
        "beaverdam":         "Hanover",
        "doswell":           "Hanover",
        "montpelier":        "Hanover",
        # Richmond City
        "richmond":          "Richmond City",
        # Chesterfield
        "chesterfield":      "Chesterfield",
        "midlothian":        "Chesterfield",
        "chester":           "Chesterfield",
        "bon air":           "Chesterfield",
        "ettrick":           "Chesterfield",
        "matoaca":           "Chesterfield",
        "swift creek":       "Chesterfield",
        "henrico":           "Henrico",
        # Henrico — NOTE: Henrico County addresses commonly use "Richmond" as
        # their mailing city (unincorporated county, no city hall).  Those will
        # map to "Richmond City" above, which is wrong.  The secondary regex
        # in _scrape_column_us_portal catches "Henrico County Courthouse" etc.
        # to override.  Specific Henrico communities are listed here for cases
        # where the address city is unambiguous.
        "glen allen":        "Henrico",
        "short pump":        "Henrico",
        "sandston":          "Henrico",
        "highland springs":  "Henrico",
        "varina":            "Henrico",
        "lakeside":          "Henrico",
        "tuckahoe":          "Henrico",
        "innsbrook":         "Henrico",
        # Louisa
        "louisa":            "Louisa",
        "mineral":           "Louisa",
    }
    for key, val in mapping.items():
        if key in city:
            return val
    return "Unknown"


def normalize_property_type(raw: str) -> str:
    raw = raw.lower()
    if any(x in raw for x in ["sfr", "single", "detached", "house"]):
        return "single-family"
    if any(x in raw for x in ["multi", "duplex", "triplex", "quadplex"]):
        return "multi-family"
    if any(x in raw for x in ["condo", "townhouse", "townhome"]):
        return "condo/townhome"
    return "single-family"


# ---------------------------------------------------------------------------
# Redfin enrichment
# ---------------------------------------------------------------------------

REDFIN_HDR = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.redfin.com/",
}


def _rf_parse(text: str) -> dict:
    """Strip Redfin's {}&& prefix and parse JSON."""
    t = text.strip()
    for prefix in ("{}&&\n", "{}&&"):
        if t.startswith(prefix):
            t = t[len(prefix):]
            break
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {}


def _stat(obj: object, key: str):
    """Extract a value from Redfin stat objects (can be dict or scalar)."""
    v = obj.get(key) if isinstance(obj, dict) else None
    if isinstance(v, dict):
        return v.get("value")
    return v


def redfin_lookup(address: str, city: str, zip_code: str = "") -> dict:
    """
    Search Redfin for a property and return enrichment data.

    Uses two Redfin endpoints:
      1. location-autocomplete  → get canonical /VA/City/Address/home/ID path
      2. home/details/initialInfo → beds, baths, sqft, year, lot, last-sale, AVM

    Returns a dict of enrichment fields; empty dict on any failure.
    """
    query = ", ".join(filter(None, [address, city, f"VA {zip_code}".strip()]))
    enrichment: dict = {}

    # ── Step 1: autocomplete search ──────────────────────────────────────────
    try:
        r = requests.get(
            "https://www.redfin.com/stingray/do/location-autocomplete",
            params={"location": query, "count": 3, "v": 2},
            headers=REDFIN_HDR,
            timeout=12,
        )
        data = _rf_parse(r.text)
        rf_path = None
        for section in data.get("payload", {}).get("sections", []):
            for row in section.get("rows", []):
                if str(row.get("type")) == "1":   # type 1 = residential property
                    rf_path = row.get("url")
                    break
            if rf_path:
                break

        if not rf_path:
            sections = data.get("payload", {}).get("sections", [])
            if not sections:
                log.info(f"    Redfin: no autocomplete response for '{address}'")
            else:
                types_seen = [row.get("type") for s in sections for row in s.get("rows", [])]
                log.info(f"    Redfin: no type-1 match for '{address}' — row types: {types_seen[:5]}")
            return {}

        enrichment["redfin_url"] = "https://www.redfin.com" + rf_path
        sleep(0.5)

    except Exception as e:
        log.info(f"    Redfin search error for '{address}': {e}")
        return {}

    # ── Step 2: initialInfo property details ─────────────────────────────────
    try:
        r2 = requests.get(
            "https://www.redfin.com/stingray/api/home/details/initialInfo",
            params={"accessLevel": 3, "path": rf_path},
            headers=REDFIN_HDR,
            timeout=15,
        )
        payload = _rf_parse(r2.text).get("payload", {})

        # Beds / baths / sqft / year / lot ─ Redfin nests these under several paths
        above = payload.get("aboveTheFold", {})
        house_stats = (
            above.get("mainHouseInfo", {}).get("homeStats") or
            above.get("mainHouseInfo", {}).get("stats") or
            above.get("homeStats") or
            {}
        )

        beds  = _stat(house_stats, "beds")
        baths = _stat(house_stats, "baths")
        sqft  = _stat(house_stats, "sqFt")
        year  = _stat(house_stats, "yearBuilt")
        lot   = _stat(house_stats, "lotSize")

        if beds  is not None: enrichment["beds"]       = int(float(beds))
        if baths is not None: enrichment["baths"]      = float(baths)
        if sqft  is not None: enrichment["sqft"]       = int(float(sqft))
        if year  is not None: enrichment["year_built"] = int(float(year))
        if lot   is not None: enrichment["lot_sqft"]   = int(float(lot))

        # Last sold date / price ─ try public records first, then saleHistory
        pub_recs = (
            payload.get("belowTheFold", {}).get("publicRecordInfo", {}).get("publicRecords") or
            payload.get("publicRecords") or
            []
        )
        if pub_recs:
            rec = pub_recs[0] if isinstance(pub_recs, list) else pub_recs
            if isinstance(rec, dict):
                ls_date  = rec.get("lastSaleDate") or rec.get("lastSaleDate2")
                ls_price = rec.get("lastSalePrice") or rec.get("price")
                if ls_date:  enrichment["last_sold_date"]  = str(ls_date)[:10]
                if ls_price: enrichment["last_sold_price"] = int(float(ls_price))

        # AVM (Redfin Estimate)
        avm = (
            payload.get("avm", {}).get("predictedValue") or
            above.get("avm", {}).get("predictedValue")
        )
        if avm:
            enrichment["redfin_estimate"] = int(float(avm))

    except Exception as e:
        log.debug(f"    Redfin detail error for {rf_path}: {e}")

    return enrichment


def enrich_with_redfin(listings: list) -> list:
    """
    Enrich listings that lack property details (beds/sqft) via Redfin.
    Already-enriched listings (sqft or beds present) are skipped.
    Rate-limited to ~1 req/1.5 s to avoid bot detection.
    """
    log.info("--- Redfin enrichment ---")
    enriched_count = 0

    for listing in listings:
        # Skip if already has property details or no address
        if listing.get("sqft") or listing.get("beds") or not listing.get("address"):
            continue

        addr = listing["address"]
        city = listing.get("city", "")
        zip_ = listing.get("zip") or ""

        log.info(f"  Enriching: {addr}, {city} {zip_}")
        data = redfin_lookup(addr, city, zip_)

        if data:
            listing.update(data)
            # Use redfin_url as source_url if we don't already have one
            if not listing.get("source_url") and data.get("redfin_url"):
                listing["source_url"] = data["redfin_url"]
            enriched_count += 1

        sleep(1.5)   # polite rate limit

    log.info(f"  Enriched {enriched_count} listing(s) via Redfin")
    return listings


# ---------------------------------------------------------------------------
# Owner enrichment — Virginia county GIS parcel APIs
# ---------------------------------------------------------------------------
# Owner Name and Mailing Address come from each county's public ArcGIS parcel
# REST service (all public record in Virginia).
#
# Estimated_Phone and Estimated_Email cannot be sourced from GIS data — they
# require a paid skip-trace service (ATTOM, White Pages Pro, etc.).  Those
# columns are left blank here and can be filled manually.
# ---------------------------------------------------------------------------

# ArcGIS parcel feature service endpoints by county.
# Each entry has:
#   url            – ArcGIS FeatureServer layer /query endpoint
#   addr_field     – the attribute name used for address matching
#   owner_variants – candidate field names for owner (tried in order)
#   mail_variants  – dict of candidate field names for mailing address parts
GIS_REGISTRY: dict[str, dict] = {
    "stafford": {
        "url": "https://gis.staffordcountyva.gov/arcgis/rest/services/Public/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME", "GRANTEE"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILING_ADDRESS", "MAILADDR", "MAILADDR1"],
            "city":  ["MAIL_CITY",  "MAILCITY",  "MAIL_CTY"],
            "state": ["MAIL_STATE", "MAILSTATE", "MAIL_ST"],
            "zip":   ["MAIL_ZIP",   "MAILZIP",   "MAIL_ZIP5"],
        },
    },
    "spotsylvania": {
        "url": "https://gis.spotsylvania.va.us/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "fredericksburg": {
        "url": "https://gis.fredericksburgva.gov/arcgis/rest/services/Property/FeatureServer/0/query",
        "addr_field": "ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME", "OWN_NAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILING_ADDRESS", "MAILADDR"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "caroline": {
        "url": "https://gis.carolinecounty.va.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER", "OWNER_NAME", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "fauquier": {
        "url": "https://gis.fauquiercounty.gov/arcgis/rest/services/Property/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILING_ADDRESS", "MAILADDR"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "culpeper": {
        "url": "https://gis.culpepercountyva.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER", "OWNER_NAME", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "king george": {
        "url": "https://gis.kinggeorgecountyva.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER", "OWNER_NAME", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "hanover": {
        "url": "https://gis.hanovercounty.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "richmond": {
        "url": "https://gis.richmondgov.com/arcgis/rest/services/Parcels/MapServer/0/query",
        "addr_field": "STREET_ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME", "OWNER1"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILING_ADDR", "MAILADDR"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "chesterfield": {
        "url": "https://gis.chesterfield.gov/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDRESS",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "henrico": {
        "url": "https://gis.henrico.us/arcgis/rest/services/Property/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER_NAME", "OWNER", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
    "louisa": {
        "url": "https://gis.louisacounty.org/arcgis/rest/services/Parcels/FeatureServer/0/query",
        "addr_field": "SITE_ADDR",
        "owner_variants": ["OWNER", "OWNER_NAME", "OWNNAME"],
        "mail_variants": {
            "line1": ["MAIL_ADDR1", "MAILADDR1", "MAILING_ADDRESS"],
            "city":  ["MAIL_CITY",  "MAILCITY"],
            "state": ["MAIL_STATE", "MAILSTATE"],
            "zip":   ["MAIL_ZIP",   "MAILZIP"],
        },
    },
}


def _pick_field(attrs: dict, candidates: list) -> str | None:
    """Return the first candidate key that exists and has a non-empty value."""
    for name in candidates:
        val = attrs.get(name) or attrs.get(name.lower()) or attrs.get(name.upper())
        if val and str(val).strip() not in ("", "null", "None", "N/A"):
            return str(val).strip()
    return None


def gis_lookup_owner(address: str, county_key: str) -> dict:
    """
    Query a Virginia county ArcGIS parcel REST API to find owner name and
    mailing address for a given street address.

    Returns a dict with keys: owner_name, owner_mailing_address,
    owner_mailing_differs.  Empty dict on failure or no match.

    The WHERE clause uses the first meaningful token(s) of the street address
    (house number + first word of street name) to form a LIKE query, which is
    more resilient to minor formatting differences than an exact match.
    """
    cfg = GIS_REGISTRY.get(county_key.lower().replace(" city", "").replace(" county", "").strip())
    if not cfg:
        return {}

    # Build a compact address fragment: house number + first word of street name
    # e.g. "1234 Main Street" → "1234 Main"
    tokens = address.strip().split()
    if len(tokens) >= 2:
        fragment = f"{tokens[0]} {tokens[1]}"
    elif tokens:
        fragment = tokens[0]
    else:
        return {}

    # Escape single quotes for SQL safety
    fragment_sql = fragment.replace("'", "''")
    where = f"UPPER({cfg['addr_field']}) LIKE '%{fragment_sql.upper()}%'"

    params = {
        "where":          where,
        "outFields":      "*",
        "returnGeometry": "false",
        "resultRecordCount": 3,   # grab top 3 to pick best match
        "f":              "json",
    }

    try:
        resp = requests.get(
            cfg["url"],
            params=params,
            headers=HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            log.debug(f"    GIS {county_key}: HTTP {resp.status_code}")
            return {}

        data = resp.json()
        features = data.get("features") or []
        if not features:
            log.debug(f"    GIS {county_key}: no parcels found for '{fragment}'")
            return {}

        # Pick the feature whose address field best matches (case-insensitive prefix)
        best = None
        for feat in features:
            attrs = feat.get("attributes") or {}
            feat_addr = str(
                attrs.get(cfg["addr_field"]) or
                attrs.get(cfg["addr_field"].lower()) or ""
            ).strip()
            if tokens[0] in feat_addr.upper():  # house number must match
                best = attrs
                break
        if best is None:
            best = features[0].get("attributes") or {}

        mv = cfg["mail_variants"]
        owner_raw  = _pick_field(best, cfg["owner_variants"])
        mail_line1 = _pick_field(best, mv["line1"])
        mail_city  = _pick_field(best, mv["city"])
        mail_state = _pick_field(best, mv["state"])
        mail_zip   = _pick_field(best, mv["zip"])

        if not owner_raw:
            return {}

        # GIS returns field values in ALL-CAPS — normalize to readable case.
        # State abbreviation stays uppercase (e.g. "VA"); everything else title-case.
        if mail_line1: mail_line1 = mail_line1.title()
        if mail_city:  mail_city  = mail_city.title()
        if mail_state: mail_state = mail_state.upper()
        if mail_zip:   mail_zip   = mail_zip.strip()

        # Build a single mailing address string
        mail_parts = [mail_line1]
        if mail_city and mail_state:
            mail_parts.append(f"{mail_city}, {mail_state} {mail_zip or ''}".strip())
        elif mail_city:
            mail_parts.append(mail_city)
        mailing_address = ", ".join(p for p in mail_parts if p)

        # Determine if mailing address differs from property address
        # Compare first token (house number) of each
        prop_num = tokens[0] if tokens else ""
        mail_num = (mail_line1 or "").strip().split()[0] if mail_line1 else ""
        differs  = "Yes" if (mail_num and mail_num != prop_num) else "No"
        if not mailing_address:
            differs = ""

        result = {
            "owner_name":            owner_raw.title(),
            "owner_mailing_address": mailing_address,
            "owner_mailing_differs": differs,
        }
        log.info(f"    GIS {county_key}: owner='{owner_raw}' mail='{mailing_address}'")
        return result

    except requests.exceptions.ConnectionError:
        log.debug(f"    GIS {county_key}: connection error (endpoint may not exist)")
        return {}
    except Exception as e:
        log.debug(f"    GIS {county_key}: error — {e}")
        return {}


def enrich_with_owner_data(listings: list) -> list:
    """
    Enrich listings with owner name and mailing address from county GIS APIs.

    Skips listings that already have owner_name populated (e.g., Fannie Mae /
    Freddie Mac) or that have no address.

    Phone and email are NOT available from GIS data and require a paid
    skip-trace service — those columns are left as None.

    Rate-limited to ~1 req/s to be polite to county servers.
    """
    log.info("--- Owner data enrichment (county GIS) ---")
    enriched_count = 0
    skipped_count  = 0

    for listing in listings:
        # Skip if already has owner data (HomePath/HomeSteps sets it directly)
        if listing.get("owner_name"):
            skipped_count += 1
            continue

        address = listing.get("address", "").strip()
        county  = listing.get("county", "").strip()
        if not address or not county:
            continue

        # Skip addresses that don't begin with a house number — these are
        # garbage entries (e.g. PNV newspaper headers like "Roanoke Times, The …")
        # that would waste 12–13 s per call waiting for GIS timeout.
        if not re.match(r'^\d+\s+\S', address):
            log.debug(f"  Owner skip (no house number): {address!r}")
            continue

        # Normalize county key for GIS registry lookup
        county_key = (
            county.lower()
            .replace(" city", "")
            .replace(" county", "")
            .strip()
        )

        log.info(f"  Owner lookup: {address} ({county})")
        owner_data = gis_lookup_owner(address, county_key)

        if owner_data:
            listing["owner_name"]            = owner_data.get("owner_name")
            listing["owner_mailing_address"] = owner_data.get("owner_mailing_address")
            listing["owner_mailing_differs"] = owner_data.get("owner_mailing_differs")
            # Phone/email require skip-trace — left blank
            listing.setdefault("owner_phone", None)
            listing.setdefault("owner_email", None)
            enriched_count += 1
        else:
            # Ensure fields exist even when lookup fails
            listing.setdefault("owner_name",            None)
            listing.setdefault("owner_mailing_address", None)
            listing.setdefault("owner_mailing_differs", None)
            listing.setdefault("owner_phone",           None)
            listing.setdefault("owner_email",           None)

        sleep(1.0)   # polite rate limit — county GIS servers are not high-capacity

    log.info(
        f"  Owner enrichment complete: {enriched_count} enriched, "
        f"{skipped_count} skipped (already set)"
    )
    return listings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def normalize_address_key(address: str) -> str:
    """
    Produce a normalized address string for cross-source duplicate detection.

    PNV and Column.us both publish the same VA legal notices, so the same
    property can arrive with slightly different formatting:
      "123 Main St"  vs  "123 MAIN STREET"

    Strategy: uppercase, expand the most common street-type abbreviations to
    their full word, strip punctuation, collapse whitespace.
    """
    if not address:
        return ""
    s = address.upper().strip()

    # Expand abbreviated street types (whole-word only, avoid partial matches)
    abbrev_map = [
        (r'\bST\b',   "STREET"),
        (r'\bAVE\b',  "AVENUE"),
        (r'\bRD\b',   "ROAD"),
        (r'\bDR\b',   "DRIVE"),
        (r'\bLN\b',   "LANE"),
        (r'\bCT\b',   "COURT"),
        (r'\bBLVD\b', "BOULEVARD"),
        (r'\bPL\b',   "PLACE"),
        (r'\bTER\b',  "TERRACE"),
        (r'\bCIR\b',  "CIRCLE"),
        (r'\bPKWY\b', "PARKWAY"),
        (r'\bHWY\b',  "HIGHWAY"),
        (r'\bFWY\b',  "FREEWAY"),
    ]
    for pattern, replacement in abbrev_map:
        s = re.sub(pattern, replacement, s)

    # Remove all punctuation, collapse spaces
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Source priority for cross-source dedup (only PNV active as of 2026-05)
_SOURCE_PRIORITY = {
    "publicnoticevirginia": 0,
}


def deduplicate(listings: list) -> list:
    """
    Remove duplicate listings in two passes:

    Pass 1 — ID hash dedup (address + sale_date MD5).
              Catches exact same address + date from the same source.

    Pass 2 — Normalized-address dedup.
              Catches same property with slightly different address strings
              across sources (e.g. PNV "123 Main St" vs Column.us "123 MAIN STREET").
              When a collision is found the listing from the higher-priority
              source wins (publicnoticevirginia > column_us > auction.com > …).
    """
    # Pass 1: hash-based dedup
    seen: dict = {}
    for listing in listings:
        seen[listing["id"]] = listing
    pass1 = list(seen.values())

    # Pass 2: normalized-address + sale_date dedup
    addr_seen: dict = {}   # key → winning listing
    for listing in pass1:
        addr_key  = normalize_address_key(listing.get("address", ""))
        sale_date = listing.get("sale_date") or ""
        key = (addr_key, sale_date)

        if key not in addr_seen:
            addr_seen[key] = listing
        else:
            # Keep whichever source has higher priority (lower number = better)
            existing_prio = _SOURCE_PRIORITY.get(addr_seen[key].get("source", ""), 99)
            new_prio      = _SOURCE_PRIORITY.get(listing.get("source", ""), 99)
            if new_prio < existing_prio:
                addr_seen[key] = listing

    result = list(addr_seen.values())
    dropped = len(pass1) - len(result)
    if dropped:
        log.info(f"  Cross-source dedup removed {dropped} duplicate address(es)")
    return result


def run():
    """
    Full pipeline: scrape all active sources → deduplicate → enrich → save.

    Source groups (edit the matching function to tune a specific source):
      Group 3 (PNV)    — scrape_public_notice_va()       publicnoticevirginia.com
      Existing         — scrape_column_us()               fredericksburg.column.us
      Group 1          — scrape_column_us_richmond()      richmond.column.us
      Group 2          — scrape_logs_legal()              logs.com/va-sales-report.html
      Group 4          — scrape_column_us_daily_progress() dailyprogress.column.us
    """
    log.info("Starting Virginia foreclosure scraper…")
    all_listings = []

    log.info(
        f"Search window: {cfg.LOOKBACK_DAYS} days  "
        f"({cfg.SINCE_DATE} → {cfg.TODAY})  |  set LOOKBACK_DAYS in scripts/config.py"
    )

    # ── Group 3: PublicNoticeVirginia.com (PNV) ───────────────────────────────
    # Virginia Code §55.1-321 requires all trustee sale notices here — it is
    # the most complete statewide source.  SINCE_DATE is passed directly to
    # PNV's "From Date" search field.
    if cfg.ENABLE_PNV:
        log.info("--- Group 3: PublicNoticeVirginia.com ---")
        all_listings.extend(scrape_public_notice_va())
    else:
        log.info("--- Group 3: PublicNoticeVirginia.com SKIPPED (ENABLE_PNV=False) ---")

    # ── Existing: Fredericksburg Free-Lance Star (Column.us) ─────────────────
    if cfg.ENABLE_COLUMN_FXBG:
        log.info("--- Existing: Column.us — Fredericksburg Free-Lance Star ---")
        all_listings.extend(scrape_column_us())
    else:
        log.info("--- Existing: Fredericksburg Column.us SKIPPED (ENABLE_COLUMN_FXBG=False) ---")

    # ── Group 1: Richmond Times-Dispatch (Column.us) ──────────────────────────
    # Covers Richmond City, Chesterfield, Henrico.
    if cfg.ENABLE_COLUMN_RICHMOND:
        log.info("--- Group 1: Column.us — Richmond Times-Dispatch ---")
        all_listings.extend(scrape_column_us_richmond())
    else:
        log.info("--- Group 1: Richmond Column.us SKIPPED (ENABLE_COLUMN_RICHMOND=False) ---")

    # ── Group 2: LOGS Legal Group / PFCVA ────────────────────────────────────
    # LOGS handles a large share of VA trustee sales; their sale report can
    # surface listings before they appear on PNV or Column.us.
    if cfg.ENABLE_LOGS_LEGAL:
        log.info("--- Group 2: LOGS Legal Group / PFCVA ---")
        all_listings.extend(scrape_logs_legal())
    else:
        log.info("--- Group 2: LOGS Legal SKIPPED (ENABLE_LOGS_LEGAL=False) ---")

    # ── Group 4: Charlottesville Daily Progress (Column.us) ───────────────────
    # Supplemental coverage for Louisa and Culpeper counties.
    if cfg.ENABLE_COLUMN_DAILYPROG:
        log.info("--- Group 4: Column.us — Charlottesville Daily Progress ---")
        all_listings.extend(scrape_column_us_daily_progress())
    else:
        log.info("--- Group 4: Daily Progress Column.us SKIPPED (ENABLE_COLUMN_DAILYPROG=False) ---")

    # ── Group 5: Auction.com (REO + active trustee pre-sales) ─────────────────
    # Covers REO bank-owned properties that appear AFTER a trustee sale
    # completes — not tracked by PNV/Column.us.  Also captures pre-sale
    # listings published through the Auction.com platform.
    if cfg.ENABLE_AUCTION_COM:
        log.info("--- Group 5: Auction.com (REO + trustee pre-sales) ---")
        all_listings.extend(scrape_auction_com())
    else:
        log.info("--- Group 5: Auction.com SKIPPED (ENABLE_AUCTION_COM=False) ---")

    # ── Group 6: Virginia Gazette / Williamsburg (Column.us) ──────────────────
    # Picks up notices from Hanover, Caroline, and King George that attorneys
    # also publish in the Williamsburg area paper.
    if cfg.ENABLE_COLUMN_WILLIAMSBURG:
        log.info("--- Group 6: Column.us — Virginia Gazette (Williamsburg) ---")
        all_listings.extend(scrape_column_us_williamsburg())
    else:
        log.info("--- Group 6: Williamsburg Column.us SKIPPED (ENABLE_COLUMN_WILLIAMSBURG=False) ---")

    # ── Group 7: Northern Virginia Daily (Column.us) ──────────────────────────
    # Captures Fauquier and Culpeper notices from the NV Daily circulation area.
    if cfg.ENABLE_COLUMN_NVDAILY:
        log.info("--- Group 7: Column.us — Northern Virginia Daily ---")
        all_listings.extend(scrape_column_us_nvdaily())
    else:
        log.info("--- Group 7: NV Daily Column.us SKIPPED (ENABLE_COLUMN_NVDAILY=False) ---")

    # ── Group 8: Samuel I. White, P.C. (SIWPC) ───────────────────────────────
    # High-volume VA foreclosure law firm.  Often lists sales 2–4 weeks before
    # they appear on PNV, giving early warning for Henrico and Chesterfield.
    if cfg.ENABLE_SIWPC:
        log.info("--- Group 8: Samuel I. White, P.C. (siwpc.com) ---")
        all_listings.extend(scrape_siwpc())
    else:
        log.info("--- Group 8: SIWPC SKIPPED (ENABLE_SIWPC=False) ---")

    # ── Group 9: Virginia eCourts — Circuit Court lis pendens ─────────────────
    # Earliest possible signal: trustee/lis pendens filings in circuit courts
    # precede PNV publication by 2–6 weeks.  Stage set to "pre-fc"; sale date
    # backfilled via Pass 1 when a PNV notice is found later.
    if cfg.ENABLE_VA_COURTS:
        log.info("--- Group 9: Virginia eCourts — Circuit Court lis pendens ---")
        all_listings.extend(scrape_va_courts())
    else:
        log.info("--- Group 9: VA Courts SKIPPED (ENABLE_VA_COURTS=False) ---")

    # ── Deduplication ─────────────────────────────────────────────────────────
    all_listings = deduplicate(all_listings)
    log.info(f"Total after dedup: {len(all_listings)} listings")

    # ── County filter — drop only confirmed out-of-scope counties ────────────
    # Records with no county (None / "") are KEPT — the county may simply be
    # undetectable from the notice text, but the property could still be in a
    # target area.  The GIS backfill (Pass 2 / Pass 6) will attempt to resolve
    # the county from the address after sync.
    # Only drop records where a county is positively identified as outside the
    # 12 target counties.
    target_display_set = set(cfg.TARGET_COUNTIES_DISPLAY)
    kept, dropped      = [], []
    for listing in all_listings:
        county = listing.get("county")
        if not county or county in target_display_set:
            kept.append(listing)
        else:
            dropped.append(listing)

    if dropped:
        from collections import Counter
        drop_counts = Counter(r.get("county") for r in dropped)
        log.info(
            f"County filter: kept {len(kept)}, dropped {len(dropped)} "
            f"confirmed out-of-scope — {dict(drop_counts)}"
        )
    all_listings = kept
    log.info(f"Total after county filter: {len(all_listings)} listings")

    # Owner enrichment — queries each county's public ArcGIS parcel REST API
    # to populate owner_name and owner_mailing_address.
    all_listings = enrich_with_owner_data(all_listings)

    save(all_listings)
    log.info("Done.")


if __name__ == "__main__":
    import sys
    if "--debug" in sys.argv:
        # Print raw HTML from PNV for selector debugging
        s = requests.Session()
        r = s.get("https://www.publicnoticevirginia.com/", headers=HEADERS, timeout=15)
        m = re.search(r'(https://www\.publicnoticevirginia\.com/\(S\([^)]+\)\))', r.url)
        base = m.group(1) if m else "https://www.publicnoticevirginia.com"
        r2 = s.get(base + "/Search.aspx", headers=HEADERS, timeout=15)
        print("=== PNV Search.aspx (first 5000 chars) ===")
        print(r2.text[:5000])
    else:
        run()
