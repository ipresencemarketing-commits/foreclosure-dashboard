#!/usr/bin/env python3
from __future__ import annotations
"""
Fredericksburg Metro Foreclosure Scraper
-----------------------------------------
Pulls trustee sale notices, auction listings, and REO properties
from free public sources and saves to data/foreclosures.json.

Sources:
  1. PublicNoticeVirginia.com            — trustee sale notices (VA legal requirement)
  2. Fredericksburg Free-Lance Star      — Column.us public notice portal (Playwright)
  3. Auction.com                         — active foreclosure auctions
  4. HUD Homes                           — FHA REO listings
  5. Fannie Mae HomePath                 — Fannie Mae REO listings
  6. Freddie Mac HomeSteps               — Freddie Mac REO listings

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
    Scrapes trustee sale notices from publicnoticevirginia.com.

    The site is ASP.NET WebForms with a session ID embedded in the URL path:
      https://www.publicnoticevirginia.com/(S(sessionid))/default.aspx

    As of 2026 the county filter uses individual checkboxes (not a <select>)
    inside #countyDiv and #cityDiv.  Fredericksburg is a *city* in ASP.NET's
    taxonomy so its checkbox lives in #cityDiv, not #countyDiv.

    Approach:
      1. GET homepage → follow redirect to get the session URL
      2. GET default.aspx → extract __VIEWSTATE and all other hidden fields
      3. Find county/city checkboxes dynamically by label text
      4. POST the form with keyword="foreclosure" + target checkboxes checked
      5. Parse the GridView results table for trustee/foreclosure notices

    Virginia requires trustee sale notices to be published per VA Code § 55.1-321.
    """
    listings = []
    session = requests.Session()

    try:
        # Step 1: Hit homepage to establish ASP.NET session (follows redirect)
        resp = session.get(
            "https://www.publicnoticevirginia.com/",
            headers=HEADERS, timeout=15, allow_redirects=True
        )

        # Extract session prefix from final URL e.g. /(S(er1tscv0pg3k2gy2ul4rqhxw))
        m = re.search(r'(https://www\.publicnoticevirginia\.com/\(S\([^)]+\)\))', resp.url)
        session_base = m.group(1) if m else "https://www.publicnoticevirginia.com"
        default_url = session_base + "/default.aspx"

        log.info(f"  PNV: default URL = {default_url}")

        # Step 2: GET default.aspx for ASP.NET form tokens
        resp2 = session.get(
            default_url,
            headers={**HEADERS, "Referer": "https://www.publicnoticevirginia.com/"},
            timeout=15
        )
        soup = BeautifulSoup(resp2.text, "lxml")

        # Collect ALL hidden input fields for the POST (preserves ASP.NET state)
        post_data = []
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name", "")
            val  = inp.get("value", "")
            if name:
                post_data.append((name, val))

        post_data += [
            ("__EVENTTARGET",   ""),
            ("__EVENTARGUMENT", ""),
        ]

        # Step 3: Find target checkboxes dynamically by label text
        # County checkboxes in #countyDiv; city checkbox for Fredericksburg in #cityDiv
        COUNTY_TARGETS = [
            "caroline", "spotsylvania", "stafford",
            "fauquier", "culpeper", "king george", "hanover",
            "chesterfield", "henrico", "louisa",
        ]
        CITY_TARGETS   = ["fredericksburg", "richmond"]

        checked_count = 0
        for div_id, targets in [("countyDiv", COUNTY_TARGETS), ("cityDiv", CITY_TARGETS)]:
            div = soup.find(id=div_id) or soup.find(id=re.compile(div_id, re.I))
            if not div:
                log.warning(f"  PNV: #{div_id} not found in page")
                continue
            for inp in div.find_all("input", type="checkbox"):
                inp_id = inp.get("id", "")
                # Label may be a sibling <label for="id"> or inline text
                label_el = (soup.find("label", attrs={"for": inp_id})
                            if inp_id else None)
                if not label_el:
                    label_el = inp.find_next_sibling("label")
                label_text = label_el.get_text(strip=True).lower() if label_el else ""
                if any(t in label_text for t in targets):
                    name = inp.get("name", "")
                    if name:
                        post_data.append((name, "on"))
                        checked_count += 1
                        log.info(f"  PNV: checking '{label_text}' ({name})")

        # Fallback: hardcode known checkbox names if dynamic discovery fails
        if checked_count == 0:
            log.warning("  PNV: dynamic checkbox discovery failed — using hardcoded names")
            for name in [
                "ctl00$ContentPlaceHolder1$as1$lstCounty$16",  # Caroline
                "ctl00$ContentPlaceHolder1$as1$lstCounty$89",  # Spotsylvania
                "ctl00$ContentPlaceHolder1$as1$lstCounty$90",  # Stafford
                "ctl00$ContentPlaceHolder1$as1$lstCity$101",   # Fredericksburg City
            ]:
                post_data.append((name, "on"))

        # Search keyword
        post_data.append(("ctl00$ContentPlaceHolder1$as1$txtSearch", "foreclosure"))

        # Submit button (value="" is correct per live page inspection)
        post_data.append(("ctl00$ContentPlaceHolder1$as1$btnGo", ""))

        # Step 4: POST the search form
        resp3 = session.post(
            default_url,
            data=post_data,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": default_url,
            },
            timeout=30,
        )
        soup3 = BeautifulSoup(resp3.text, "lxml")

        # Step 5: Parse result rows from ASP.NET GridView
        # Primary: the updateWSGrid table; fallback: any data table rows
        grid = (
            soup3.find(id=re.compile(r"updateWSGrid", re.I)) or
            soup3.find(id=re.compile(r"WSExtendedGrid", re.I))
        )
        if grid:
            rows = grid.find_all("tr")[1:]  # skip header row
        else:
            rows = (
                soup3.select("table.results-table tr, table.search-results tr") or
                soup3.select("tr.GridRow, tr.GridAltRow, tr[class*='grid']") or
                []
            )

        log.info(f"  PNV: {len(rows)} raw result rows")

        for row in rows:
            # Skip header / empty rows
            if row.find("th"):
                continue
            cells = row.find_all("td")
            if not cells:
                continue

            text_raw = row.get_text(" ", strip=True)
            if not text_raw:
                continue

            link_el    = row.find("a")
            href       = link_el.get("href") if link_el else None
            source_url = None
            if href:
                source_url = (href if href.startswith("http")
                              else session_base + "/" + href.lstrip("/"))

            address          = parse_address_from_notice(text_raw)
            sale_date, sale_time = parse_sale_datetime(text_raw)
            lender           = parse_lender(text_raw)
            trustee          = parse_trustee(text_raw)

            # Identify which target county this notice belongs to
            county_key = "fredericksburg"  # default
            for c in TARGET_COUNTIES:
                if c in text_raw.lower():
                    county_key = c
                    break

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
                "source_url":       source_url,
            })

        sleep(1)

    except Exception as e:
        log.error(f"  PNV error: {e}", exc_info=True)

    log.info(f"  PublicNoticeVA: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 2: Auction.com
# ---------------------------------------------------------------------------

def scrape_auction_com() -> list:
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
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            url = "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale"
            log.info(f"  Column.us: {url}")
            page.goto(url, wait_until="networkidle", timeout=40_000)

            # Wait for at least one notice card to appear
            try:
                page.wait_for_selector("text=Foreclosure Sale", timeout=15_000)
            except PWTimeout:
                log.warning("  Column.us: timed out waiting for notices to render")
                browser.close()
                return listings

            # Click "Load more notices" until exhausted
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

            # ── Extract all Foreclosure Sale cards ────────────────────────────
            # Each notice is a <section> or <article> (or div with data attrs)
            # containing the notice type label and the full body text.
            notice_sections = page.query_selector_all(
                "[class*='notice'], [class*='card'], [class*='result'], article, section"
            )

            for section in notice_sections:
                try:
                    text = section.inner_text(timeout=3000).strip()
                except Exception:
                    continue

                if "Foreclosure Sale" not in text:
                    continue
                if not re.search(r"trustee.{0,10}sale", text, re.I):
                    continue

                # ── Address ────────────────────────────────────────────────
                # Opening line pattern: "TRUSTEE'S SALE OF {address}"
                addr_raw = None
                addr_m = re.search(
                    r"TRUSTEE[''`]?S\s+SALE\s+OF\s+([\w\d].*?)(?=\n\n|\nIn execution|\nDefault)",
                    text, re.I | re.S
                )
                if addr_m:
                    addr_raw = re.sub(r"\s+", " ", addr_m.group(1)).strip()

                # Also handle "NOTICE OF SUBSTITUTE TRUSTEE SALE\n{address}"
                if not addr_raw:
                    sub_m = re.search(
                        r"NOTICE OF SUBSTITUTE TRUSTEE SALE\s+([\w\d].*?)(?=\n\n|\nBy virtue|\nIn execution)",
                        text, re.I | re.S
                    )
                    if sub_m:
                        addr_raw = re.sub(r"\s+", " ", sub_m.group(1)).strip()

                if not addr_raw:
                    log.debug(f"  Column.us: could not parse address from card, skipping")
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
                    # Try extracting county from the notice body directly
                    county_m = re.search(
                        r"Circuit Court(?:\s+for)?\s+(?:the\s+)?(?:City of\s+)?(\w[\w\s]+?)"
                        r"(?:\s+County)?,\s+(?:Main|Courthouse|\d)",
                        text, re.I
                    )
                    if county_m:
                        county = county_display(county_m.group(1).strip().lower())
                    else:
                        log.debug(f"  Column.us: unknown county for '{city}', skipping")
                        continue

                if county.lower().replace(" city", "").replace(" county", "") not in [
                    c.lower() for c in TARGET_COUNTIES
                ]:
                    continue

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
                    "source_url":       url,
                })

            browser.close()

    except Exception as e:
        log.error(f"  Column.us error: {e}", exc_info=True)

    log.info(f"  Column.us: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 6: Freddie Mac HomeSteps
# ---------------------------------------------------------------------------

def scrape_homesteps() -> list:
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

    Primary pattern matches the standard PNV notice phrase:
      "...on June 22, 2026, at 9:00 AM"

    Fallback scans the full notice body for any date/time pattern independently.
    """
    sale_date = None
    sale_time = None

    # Primary: "on [Month Day, Year], at [Time]" — standard VA trustee sale format
    primary_m = re.search(
        r'\bon\s+(\w+\s+\d{1,2},?\s*\d{4}),?\s+at\s+(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.))',
        text, re.IGNORECASE
    )
    if primary_m:
        raw_date = primary_m.group(1).strip()
        raw_time = (primary_m.group(2).strip().upper()
                    .replace("A.M.", "AM").replace("P.M.", "PM"))
        for fmt in ("%B %d, %Y", "%B %d %Y"):
            try:
                sale_date = datetime.strptime(raw_date, fmt).date().isoformat()
                break
            except ValueError:
                continue
        return sale_date, raw_time

    # Fallback: scan for any standalone date and time in the notice body
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
        sale_time = (time_match.group(1).upper()
                     .replace("A.M.", "AM").replace("P.M.", "PM"))

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
# Main
# ---------------------------------------------------------------------------

def deduplicate(listings: list) -> list:
    """Remove duplicate listings by ID, keeping the most recently sourced."""
    seen = {}
    for listing in listings:
        seen[listing["id"]] = listing
    return list(seen.values())


def run():
    log.info("Starting Virginia foreclosure scraper (12 counties)…")
    all_listings = []

    log.info("--- PublicNoticeVirginia.com ---")
    all_listings.extend(scrape_public_notice_va())

    log.info("--- Fredericksburg Free-Lance Star (Column.us) ---")
    all_listings.extend(scrape_column_us())

    log.info("--- Auction.com ---")
    all_listings.extend(scrape_auction_com())

    log.info("--- HUD Homes ---")
    all_listings.extend(scrape_hud_homes())

    log.info("--- Fannie Mae HomePath ---")
    all_listings.extend(scrape_homepath())

    log.info("--- Freddie Mac HomeSteps ---")
    all_listings.extend(scrape_homesteps())

    all_listings = deduplicate(all_listings)
    log.info(f"Total after dedup: {len(all_listings)} listings")

    # Redfin enrichment disabled — Redfin blocks automated requests (403).
    # Property detail enrichment (beds/baths/sqft/AVM) is a Phase 2 item.
    # Revisit with county GIS portals or ATTOM Data API.
    # all_listings = enrich_with_redfin(all_listings)

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
