#!/usr/bin/env python3
from __future__ import annotations
"""
Fredericksburg Metro Foreclosure Scraper
-----------------------------------------
Pulls trustee sale notices from free public sources and saves to data/foreclosures.json.

Sources:
  1. PublicNoticeVirginia.com            — trustee sale notices (VA legal requirement)
  2. Fredericksburg Free-Lance Star      — Column.us public notice portal (Playwright)

Target counties: Fredericksburg City, Stafford, Spotsylvania, Caroline, Fauquier,
                  Culpeper, King George, Hanover, Richmond City, Chesterfield, Henrico, Louisa

Run: python3 scripts/scraper.py
Requires: pip install requests beautifulsoup4 lxml
"""

import re
import requests
import json
import hashlib
import os
import logging
from datetime import date, datetime, timedelta
from bs4 import BeautifulSoup
from time import sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "foreclosures.json")

TARGET_COUNTIES = [
    "fredericksburg", "stafford", "spotsylvania", "caroline",
    "fauquier", "culpeper", "king george", "hanover",
    "richmond", "chesterfield", "henrico", "louisa",
]

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

    # Preserve first_seen; flag listings added today as new
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
            "target_counties": [
                "Fredericksburg City", "Stafford", "Spotsylvania", "Caroline",
                "Fauquier", "Culpeper", "King George", "Hanover",
                "Richmond City", "Chesterfield", "Henrico", "Louisa",
            ],
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
# Source 1: PublicNoticeVirginia.com
# ---------------------------------------------------------------------------

def scrape_public_notice_va() -> list:
    """
    Scrapes trustee sale notices from publicnoticevirginia.com using Playwright.

    Switched from requests to Playwright to handle three issues:
      1. First-visit human verification check — Playwright passes as a real browser
      2. ASP.NET pagination — clicks "Next" through all result pages
      3. Broader keyword coverage — uses PNV's own "popular searches" keyword set

    Approach:
      1. Open site in headless Chromium (spoof webdriver flag)
      2. Fill the search box with the popular searches keyword set
      3. Submit and wait for results
      4. Loop: collect all notice URLs on current page → click Next → repeat
      5. Navigate to each notice detail page and parse text
      6. Filter to target counties; build listing dict

    Virginia requires trustee sale notices per VA Code § 55.1-321.
    """
    listings = []

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning(
            "  PNV: playwright not installed — skipping.\n"
            "    Install with:  pip3 install playwright --break-system-packages\n"
            "                   playwright install chromium"
        )
        return listings

    # Full keyword set from PNV's "popular searches" dropdown.
    # Space-separated terms = OR search on PNV — maximises notice coverage.
    SEARCH_KEYWORDS = (
        "real estate foreclosure foreclosed foreclose "
        "judicial sale judgment notice of sale forfeiture forfeit"
    )

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
            # Spoof navigator.webdriver so the human-check JS doesn't flag us
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            log.info("  PNV: opening site with Playwright")
            page.goto("https://www.publicnoticevirginia.com/", wait_until="load", timeout=45_000)
            # Give the page time to finish any JS challenges / redirects
            page.wait_for_timeout(5_000)

            # ── Fill search box ───────────────────────────────────────────────
            search_sel = 'input[name*="txtSearch"], input[id*="txtSearch"]'
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
            log.info(f"  PNV: search box filled")

            # ── Submit ────────────────────────────────────────────────────────
            btn_sel = 'input[name*="btnGo"], input[id*="btnGo"], input[value="Search"], input[type="submit"]'
            page.click(btn_sel)
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2_000)

            # ── Paginate through all result pages ────────────────────────────
            all_notice_urls: list[str] = []
            page_num = 1

            while True:
                log.info(f"  PNV: collecting notice URLs from results page {page_num}")

                # Extract notice links from grid rows on this page.
                # Skip pagination links (page numbers, Next, Prev, >, <).
                urls_on_page: list[str] = page.evaluate("""
                    () => {
                        const seen = new Set();
                        const out  = [];
                        const SKIP = /^(next|prev|previous|first|last|[0-9]+|>|<|>>|<<)$/i;
                        // Try known grid IDs first, fall back to first <table>
                        const grid = (
                            document.querySelector('[id*="WSGrid"]') ||
                            document.querySelector('[id*="updateWSGrid"]') ||
                            document.querySelector('table')
                        );
                        if (!grid) return out;
                        for (const row of grid.querySelectorAll('tr')) {
                            if (row.querySelector('th')) continue;  // header row
                            const link = row.querySelector('a[href]');
                            if (!link) continue;
                            const txt  = link.textContent.trim();
                            const href = link.href || '';
                            if (href && !SKIP.test(txt) && !seen.has(href)) {
                                seen.add(href);
                                out.push(href);
                            }
                        }
                        return out;
                    }
                """)

                all_notice_urls.extend(urls_on_page)
                log.info(f"  PNV: page {page_num} → {len(urls_on_page)} notice link(s)")

                # ── Try to advance to the next page ──────────────────────────
                # ASP.NET GridView pager: "Next" text link or ">" symbol link
                next_btn = (
                    page.query_selector('a:text-is("Next")') or
                    page.query_selector('a:text-is(">")') or
                    page.query_selector('a[title*="Next" i]') or
                    page.query_selector('a[title*="next page" i]')
                )
                if next_btn and next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_load_state("networkidle", timeout=20_000)
                    page.wait_for_timeout(1_500)
                    page_num += 1
                else:
                    log.info(f"  PNV: no more pages (last page = {page_num})")
                    break

            # Deduplicate across pages
            all_notice_urls = list(dict.fromkeys(all_notice_urls))
            log.info(f"  PNV: {len(all_notice_urls)} unique notice URLs across {page_num} page(s)")

            # ── Fetch each notice detail page and parse ───────────────────────
            for notice_url in all_notice_urls:
                try:
                    page.goto(notice_url, wait_until="load", timeout=20_000)
                    page.wait_for_timeout(600)
                    full_text = page.inner_text("body")

                    # Must mention a trustee/foreclosure keyword to be relevant
                    if not re.search(
                        r"trustee|deed of trust|sale of real property|foreclos|judicial sale",
                        full_text, re.I
                    ):
                        continue

                    address              = parse_address_from_notice(full_text)
                    sale_date, sale_time = parse_sale_datetime(full_text)
                    lender               = parse_lender(full_text)
                    trustee              = parse_trustee(full_text)

                    # Filter to target counties
                    county_key = None
                    text_lower = full_text.lower()
                    for c in TARGET_COUNTIES:
                        if c in text_lower:
                            county_key = c
                            break
                    if county_key is None:
                        log.debug(f"  PNV: no target county in notice — skipping")
                        continue

                    listings.append({
                        "id":               make_id(address, sale_date),
                        "address":          address,
                        "city":             county_city(county_key),
                        "county":           county_display(county_key),
                        "zip":              None,
                        "stage":            "auction" if sale_date else "pre-fc",
                        "property_type":    "single-family",
                        "assessed_value":   None,
                        "asking_price":     None,
                        "sale_date":        sale_date,
                        "sale_time":        sale_time,
                        "sale_location":    courthouse_location(county_key),
                        "days_until_sale":  None,
                        "notice_date":      date.today().isoformat(),
                        "days_in_foreclosure": 0,
                        "lender":           lender,
                        "trustee":          trustee,
                        "source":           "publicnoticevirginia",
                        "source_url":       notice_url,
                    })

                    sleep(0.3)   # polite rate limit between notice page fetches

                except Exception as e:
                    log.warning(f"  PNV: error fetching notice {notice_url}: {e}")

            browser.close()

    except Exception as e:
        log.error(f"  PNV error: {e}", exc_info=True)

    log.info(f"  PublicNoticeVA: found {len(listings)} listings")
    return listings

# ---------------------------------------------------------------------------
# REMOVED SOURCES (kept for reference — not called by run())
# Auction.com, HUD Homes, Fannie Mae HomePath, Freddie Mac HomeSteps
# were removed 2026-05 — pipeline now uses PNV + Column.us only.
# ---------------------------------------------------------------------------

def scrape_auction_com() -> list:
    """REMOVED — not called. Scrapes Auction.com for foreclosure listings."""
    return []
    # Original implementation preserved below for reference.
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
    """REMOVED — not called."""
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
    """REMOVED — not called."""
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


# ---------------------------------------------------------------------------
# Source 5: Fredericksburg Free-Lance Star (Column.us)
# ---------------------------------------------------------------------------

def scrape_column_us() -> list:
    """
    Scrapes foreclosure sale notices from the Fredericksburg Free-Lance Star's
    Column.us public notice portal.

    URL: https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale

    Column.us is a Next.js + Firebase app — the page shell is server-rendered
    but all notice cards are injected client-side via the Firebase SDK.
    Python requests alone returns an empty shell; Playwright is required to
    execute JavaScript and wait for notices to render.

    Each notice card contains:
      - Notice type label ("Foreclosure Sale")
      - Full notice body text (CSS visually clips it, but full text is in the DOM)
      - Publication date (YYYY-MM-DD)

    From the body text we extract:
      - Property address  (from "TRUSTEE'S SALE OF {address}" opening line)
      - Sale date / time  (from "on June 22, 2026, at 9:00 AM" standard VA phrase)
      - Lender / trustee  (via existing parse helpers)

    Requires: pip3 install playwright && playwright install chromium
    """
    listings = []

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning(
            "  Column.us: playwright not installed — skipping.\n"
            "    Install with:  pip3 install playwright --break-system-packages\n"
            "                   playwright install chromium"
        )
        return listings

    try:
        with sync_playwright() as pw:
            # Launch with args that suppress headless detection
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ]
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                # Spoof navigator.webdriver = false
                java_script_enabled=True,
            )
            # Hide the webdriver flag that sites use to detect headless browsers
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()

            url = "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale"
            log.info(f"  Column.us: {url}")

            # Use "load" (not "networkidle") — Firebase's persistent WebSocket
            # connection prevents networkidle from ever firing cleanly.
            page.goto(url, wait_until="load", timeout=40_000)

            # Give the Firebase/React app time to fetch and render cards
            page.wait_for_timeout(8_000)

            # Confirm notices loaded — look for the repeating newspaper header
            try:
                page.wait_for_function(
                    "document.body.innerText.includes('FREDERICKSBURG FREE-LANCE STAR')",
                    timeout=20_000
                )
            except PWTimeout:
                log.warning("  Column.us: page body never contained notice text after 20s")
                browser.close()
                return listings

            # Click "Load more notices" until exhausted to get all pages
            while True:
                try:
                    btn = page.query_selector('button:has-text("Load more")')
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(2000)
                    else:
                        break
                except Exception:
                    break

            # ── Capture individual notice detail URLs from the DOM ────────────
            # Each notice card on Column.us has a link to its canonical detail
            # page (the URL surfaced by the "Copy link" button on fredericksburg.com).
            # These links appear in DOM order, which matches the text-block order
            # we derive below, so we can zip them together 1-to-1.
            #
            # Selector: any <a> whose href contains "/notice/" (not just "/notices"
            # nav links) — Column.us detail pages follow the pattern:
            #   https://fredericksburg.column.us/notice/<slug>
            #   https://fredericksburg.column.us/notices/<id>
            try:
                notice_urls: list = page.evaluate("""
                    () => {
                        const seen  = new Set();
                        const links = document.querySelectorAll('a[href]');
                        const out   = [];
                        for (const a of links) {
                            const h = a.href || '';
                            // Match /notice/<something> or /notices/<something>
                            if (/\\/notice[s]?\\/[\\w-]+/i.test(h) && !seen.has(h)) {
                                seen.add(h);
                                out.push(h);
                            }
                        }
                        return out;
                    }
                """)
            except Exception as e:
                log.debug(f"  Column.us: could not extract notice URLs from DOM: {e}")
                notice_urls = []

            log.info(f"  Column.us: {len(notice_urls)} individual notice URL(s) found")

            # ── Extract notices from full body text ───────────────────────────
            # CSS class names vary between browser/headless renders (Tailwind
            # purging, React hydration timing). Splitting by the newspaper
            # header line is resilient to any DOM structure changes.
            body_text = page.inner_text("body")

            # Each notice block starts with "FREDERICKSBURG FREE-LANCE STAR"
            raw_blocks = re.split(r"FREDERICKSBURG FREE-LANCE STAR", body_text, flags=re.I)
            # First element is the page chrome (search form etc.) — drop it
            notice_blocks = raw_blocks[1:]
            log.info(f"  Column.us: {len(notice_blocks)} notice blocks found")

            kept = skipped_trust = skipped_addr = skipped_county = 0

            # Pair each notice block with its individual detail URL.
            # Both sequences are in DOM order, so zip works 1-to-1.
            # If the counts differ (DOM query missed some), fall back to the
            # search page URL for unmatched blocks.
            from itertools import zip_longest
            block_url_pairs = zip_longest(notice_blocks, notice_urls, fillvalue=None)

            for block_text, notice_url in block_url_pairs:
                if not block_text:
                    continue   # extra URL with no matching text block — skip
                text = block_text.strip()

                # Column.us already filters to "Foreclosure Sale" notices, but
                # the block may contain editorial text, ads, or other filler.
                # Accept any block that mentions trustee, substitute trustee,
                # or foreclosure sale — all are VA auction notice patterns.
                if not re.search(
                    r"trustee.{0,15}sale|substitute trustee|foreclosure sale",
                    text, re.I
                ):
                    skipped_trust += 1
                    continue

                # ── Address ────────────────────────────────────────────────
                # Primary: match a Virginia street address directly.
                # Handles all observed notice formats:
                #   "TRUSTEE'S SALE OF 256 MANCHESTER DR, RUTHER GLEN, VA 22546 In execution..."
                #   "Trustee's Sale 9422 WILDWOOD KNL FARM LN, SPOTSYLVANIA, VA 22551 (Parcel..."
                #   "TRUSTEE'S SALE OF 12219 WARD RD, KING GEORGE, VA 22485"
                # Pattern: house-number + street text + comma + city + ", VA " + ZIP
                addr_raw = None
                direct_m = re.search(
                    r"(\d+\s+[A-Z0-9][^,\n]{4,60},\s*[A-Z][^,\n]{1,35},\s*VA\s+\d{5}(?:-\d{4})?)",
                    text, re.I
                )
                if direct_m:
                    addr_raw = re.sub(r"\s+", " ", direct_m.group(1)).strip()

                # Fallback A: "TRUSTEE'S SALE OF {address}" with flexible terminator
                if not addr_raw:
                    addr_m = re.search(
                        r"TRUSTEE.{0,3}S\s+SALE\s+OF\s+([\w\d].*?)(?=\n\n|\n?In\s+execution|\nDefault|\nVirginia|\(Parcel)",
                        text, re.I | re.S
                    )
                    if addr_m:
                        addr_raw = re.sub(r"\s+", " ", addr_m.group(1)).strip()

                # Fallback B: "SUBSTITUTE TRUSTEE SALE / NOTICE\n{address}"
                if not addr_raw:
                    sub_m = re.search(
                        r"(?:NOTICE OF )?SUBSTITUTE TRUSTEE.{0,10}SALE\s+([\w\d].*?)(?=\n\n|\n?In\s+execution|\nBy virtue|\nVirginia)",
                        text, re.I | re.S
                    )
                    if sub_m:
                        addr_raw = re.sub(r"\s+", " ", sub_m.group(1)).strip()

                if not addr_raw:
                    log.info(f"  Column.us: no address found — snippet: {text[:120]!r}")
                    skipped_addr += 1
                    continue

                # Parse "Street, City, ST ZIP" from address line
                parsed = re.match(
                    r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                    addr_raw
                )
                if parsed:
                    street   = parsed.group(1).strip()
                    city     = parsed.group(2).strip()
                    zip_code = parsed.group(4)
                else:
                    street   = addr_raw[:80]
                    city     = ""
                    zip_code = None

                # Derive county; skip if outside our target area
                county = city_to_county(city)
                if county == "Unknown":
                    # Try extracting county name from Circuit Court reference
                    county_m = re.search(
                        r"Circuit Court(?:\s+for)?\s+(?:the\s+)?(?:City of\s+)?(\w[\w\s]+?)"
                        r"(?:\s+County)?,\s+(?:Main|Courthouse|\d)",
                        text, re.I
                    )
                    if county_m:
                        # Trim to first 2 words — county names are at most 2 words
                        # (e.g. "King George"); lazy regex can over-capture trailing
                        # text like "Spotsylvania County On June 1"
                        raw_county = " ".join(county_m.group(1).strip().split()[:2])
                        county = county_display(raw_county.lower())
                    else:
                        log.info(f"  Column.us: unknown county for city='{city}' addr='{addr_raw[:60]}'")
                        skipped_county += 1
                        continue

                if county.lower().replace(" city", "").replace(" county", "") not in [
                    c.lower() for c in TARGET_COUNTIES
                ]:
                    log.info(f"  Column.us: county '{county}' not in target list — skipping")
                    skipped_county += 1
                    continue

                kept += 1

                # ── Sale date / time (standard VA notice phrase) ───────────
                sale_date, sale_time = parse_sale_datetime(text)

                # ── Lender / trustee ───────────────────────────────────────
                lender  = parse_lender(text)
                trustee = parse_trustee(text)

                listings.append({
                    "id":               make_id(street, sale_date),
                    "address":          street,
                    "city":             city.title(),
                    "county":           county,
                    "zip":              zip_code,
                    "stage":            "auction" if sale_date else "pre-fc",
                    "property_type":    "single-family",
                    "assessed_value":   None,
                    "asking_price":     None,
                    "sale_date":        sale_date,
                    "sale_time":        sale_time,
                    "sale_location":    courthouse_location(
                                            county.lower().replace(" city","").replace(" county","").strip()
                                        ),
                    "days_until_sale":  None,
                    "notice_date":      date.today().isoformat(),
                    "days_in_foreclosure": 0,
                    "lender":           lender,
                    "trustee":          trustee,
                    "source":           "column_us",
                    # Individual notice detail page URL (the link behind "Copy link").
                    # Falls back to the search page URL if the DOM query didn't
                    # return a matching link for this block.
                    "source_url":       notice_url or url,
                })

            log.info(
                f"  Column.us: {kept} kept | "
                f"{skipped_trust} dropped (not trustee/foreclosure) | "
                f"{skipped_addr} dropped (no address) | "
                f"{skipped_county} dropped (county outside target)"
            )
            browser.close()

    except Exception as e:
        log.error(f"  Column.us error: {e}", exc_info=True)

    log.info(f"  Column.us: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 6: Freddie Mac HomeSteps
# ---------------------------------------------------------------------------

def scrape_homesteps() -> list:
    """REMOVED — not called."""
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
    return match.group(1).strip() if match else text[:80]


def parse_sale_datetime(text: str):
    """Extract sale date and time from Virginia trustee sale notice text.

    Three patterns tried in order, most-specific first:

    1. Auction keyword pattern (PNV):
         "auction will be on June 11, 2026 at 11:00AM"
         "auction on May 27, 2026, at 1:00 PM"

    2. General "on [Date], at [Time]" (PNV / Column.us standard VA phrase):
         "...on June 22, 2026, at 9:00 AM"

    3. Fallback: scan entire body for any date + time independently.
    """
    sale_date = None
    sale_time = None

    TIME_PAT  = r'(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.))'
    DATE_PAT  = r'(\w+\s+\d{1,2},?\s*\d{4})'
    DATE_FMTS = ("%B %d, %Y", "%B %d %Y")

    def _parse_date(raw: str):
        raw = raw.strip()
        for fmt in DATE_FMTS:
            try:
                return datetime.strptime(raw, fmt).date().isoformat()
            except ValueError:
                continue
        return None

    def _clean_time(raw: str) -> str:
        return (raw.strip().upper()
                .replace("A.M.", "AM").replace("P.M.", "PM")
                .replace(" ", ""))   # "11:00 AM" → "11:00AM" for consistency

    # ── Pattern 1: "auction [will be] on [Date] at [Time]" ───────────────────
    auction_m = re.search(
        r'auction(?:\s+will\s+be)?\s+on\s+' + DATE_PAT + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if auction_m:
        d = _parse_date(auction_m.group(1))
        t = _clean_time(auction_m.group(2))
        if d:
            return d, t

    # ── Pattern 2: "on [Date], at [Time]" — general VA trustee sale phrase ───
    general_m = re.search(
        r'\bon\s+' + DATE_PAT + r',?\s+at\s+' + TIME_PAT,
        text, re.IGNORECASE
    )
    if general_m:
        d = _parse_date(general_m.group(1))
        t = _clean_time(general_m.group(2))
        if d:
            return d, t

    # ── Pattern 3: fallback — scan for any date and time independently ────────
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


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def county_display(county: str) -> str:
    return {
        "fredericksburg": "Fredericksburg City",
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
    }.get(county.lower(), county.title())


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
        # Richmond City
        "richmond":          "Richmond City",
        # Chesterfield
        "chesterfield":      "Chesterfield",
        "midlothian":        "Chesterfield",
        "chester":           "Chesterfield",
        "bon air":           "Chesterfield",
        # Henrico
        "glen allen":        "Henrico",
        "short pump":        "Henrico",
        "sandston":          "Henrico",
        "highland springs":  "Henrico",
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


# Source priority for cross-source dedup: prefer the more detail-rich source
_SOURCE_PRIORITY = {
    "publicnoticevirginia": 0,
    "column_us":            1,
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
    log.info("Starting Virginia foreclosure scraper (12 counties)…")
    all_listings = []

    log.info("--- PublicNoticeVirginia.com ---")
    all_listings.extend(scrape_public_notice_va())

    log.info("--- Fredericksburg Free-Lance Star (Column.us) ---")
    all_listings.extend(scrape_column_us())

    all_listings = deduplicate(all_listings)
    log.info(f"Total after dedup: {len(all_listings)} listings")

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
