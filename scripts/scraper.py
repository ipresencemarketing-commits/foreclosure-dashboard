#!/usr/bin/env python3
"""
Fredericksburg Metro Foreclosure Scraper
-----------------------------------------
Pulls trustee sale notices, auction listings, and REO properties
from free public sources and saves to data/foreclosures.json.

Sources:
  1. PublicNoticeVirginia.com  — trustee sale notices (VA legal requirement)
  2. Auction.com               — active foreclosure auctions
  3. HUD Homes                 — FHA REO listings
  4. Fannie Mae HomePath        — Fannie Mae REO listings

Target counties: Fredericksburg City, Stafford, Spotsylvania, Caroline

Run: python3 scripts/scraper.py
Requires: pip install requests beautifulsoup4 lxml
"""

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

TARGET_COUNTIES = ["fredericksburg", "stafford", "spotsylvania", "caroline"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(address: str, sale_date: str) -> str:
    """Stable unique ID based on address + sale date."""
    raw = f"{address.lower().strip()}-{sale_date or 'nordate'}"
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
            "target_counties": ["Fredericksburg City", "Stafford", "Spotsylvania", "Caroline"],
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

    NOTE: This scraper is written against the site structure as of early 2026.
    If the site changes its layout, update the CSS selectors below.
    Run with --debug to print raw HTML for inspection.

    The site requires searching per county. We loop over all four target counties.
    """
    listings = []
    base_url = "https://publicnoticevirginia.com"

    for county in TARGET_COUNTIES:
        url = f"{base_url}/search?keywords=foreclosure&county={county}&state=VA"
        log.info(f"  PublicNoticeVA — {county.title()}: {url}")
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")

            # TODO: Inspect the actual HTML and update these selectors.
            # Typical structure on legal notice aggregators:
            #   <div class="notice-item"> or <article class="notice">
            #     <h3 class="notice-title">...</h3>
            #     <div class="notice-body">...</div>
            #   </div>
            # Run: python3 scripts/scraper.py --debug to print raw HTML.

            notice_items = soup.select(".notice-item, article.notice, .search-result-item")

            if not notice_items:
                log.warning(f"  No items found for {county} — selector may need updating")
                continue

            for item in notice_items:
                title_el = item.select_one(".notice-title, h3, h4")
                body_el = item.select_one(".notice-body, .notice-text, p")
                link_el = item.select_one("a")

                raw_text = body_el.get_text(" ", strip=True) if body_el else ""
                title_text = title_el.get_text(strip=True) if title_el else ""
                source_url = base_url + link_el["href"] if link_el and link_el.get("href") else None

                # Parse address from notice text (notices typically start with property address)
                address = parse_address_from_notice(raw_text) or title_text
                sale_date, sale_time = parse_sale_datetime(raw_text)
                lender = parse_lender(raw_text)
                trustee = parse_trustee(raw_text)
                county_clean = county_display(county)

                listing = {
                    "id": make_id(address, sale_date),
                    "address": address,
                    "city": county_city(county),
                    "county": county_clean,
                    "zip": None,
                    "stage": "auction" if sale_date else "prefc",
                    "property_type": "single-family",
                    "assessed_value": None,
                    "asking_price": None,
                    "sale_date": sale_date,
                    "sale_time": sale_time,
                    "sale_location": courthouse_location(county),
                    "days_until_sale": None,
                    "notice_date": date.today().isoformat(),
                    "days_in_foreclosure": 0,
                    "lender": lender,
                    "trustee": trustee,
                    "source": "publicnoticevirginia",
                    "source_url": source_url,
                }
                listings.append(listing)

            sleep(1.5)  # Be polite — don't hammer the server

        except Exception as e:
            log.error(f"  Error scraping publicnoticevirginia.com for {county}: {e}")

    log.info(f"  PublicNoticeVA: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 2: Auction.com
# ---------------------------------------------------------------------------

def scrape_auction_com() -> list:
    """
    Scrapes active auction listings for Fredericksburg VA from Auction.com.

    Auction.com uses a React frontend. The public search page renders listings
    as JSON embedded in a <script id="__NEXT_DATA__"> tag (Next.js pattern).
    We parse that JSON directly — no Selenium needed for basic listings.

    If this stops working, the fallback is:
      pip install selenium webdriver-manager
      (then use a headless Chrome approach)
    """
    listings = []
    url = "https://www.auction.com/residential/?state=VA&city=fredericksburg&county=stafford,spotsylvania,caroline"
    log.info(f"  Auction.com: {url}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Try Next.js data blob first
        next_data = soup.find("script", {"id": "__NEXT_DATA__"})
        if next_data:
            data = json.loads(next_data.string)
            # Navigate the JSON structure — path varies by Auction.com version
            # Typical: data["props"]["pageProps"]["listings"] or similar
            props = data.get("props", {}).get("pageProps", {})
            raw_listings = (
                props.get("listings")
                or props.get("searchResults", {}).get("listings")
                or []
            )

            for item in raw_listings:
                address = item.get("address", {})
                full_address = address.get("street", "") or item.get("streetAddress", "")
                city = address.get("city", "") or item.get("city", "")
                county = address.get("county", "") or ""
                zip_code = address.get("zip", "") or item.get("postalCode", "")
                sale_date = item.get("saleDate") or item.get("auctionDate")
                if sale_date:
                    sale_date = sale_date[:10]  # Trim to YYYY-MM-DD

                listing = {
                    "id": make_id(full_address, sale_date),
                    "address": full_address,
                    "city": city,
                    "county": normalize_county(county),
                    "zip": zip_code,
                    "stage": "auction",
                    "property_type": normalize_property_type(item.get("propertyType", "")),
                    "assessed_value": None,
                    "asking_price": item.get("openingBid") or item.get("startingBid"),
                    "sale_date": sale_date,
                    "sale_time": item.get("saleTime"),
                    "sale_location": item.get("saleLocation") or courthouse_for_address(county),
                    "days_until_sale": None,
                    "notice_date": None,
                    "days_in_foreclosure": None,
                    "lender": item.get("lender") or item.get("beneficiary"),
                    "trustee": item.get("trustee"),
                    "source": "auction.com",
                    "source_url": f"https://www.auction.com/details/{item.get('slug', '')}",
                }
                listings.append(listing)
        else:
            # Fallback: parse HTML cards
            # TODO: Update selector if Next.js data not found
            cards = soup.select("[data-testid='property-card'], .property-card, .listing-card")
            log.warning(f"  Auction.com: Next.js data not found, found {len(cards)} HTML cards")

    except Exception as e:
        log.error(f"  Error scraping auction.com: {e}")

    log.info(f"  Auction.com: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 3: HUD Homes
# ---------------------------------------------------------------------------

def scrape_hud_homes() -> list:
    """
    Scrapes HUD REO listings for the Fredericksburg area.

    HUD Homes has a JSON API endpoint used by their search page.
    We call it directly for the target zip codes.
    """
    listings = []
    # HUD's internal API (discovered via browser devtools — may change)
    url = "https://www.hudhomestore.gov/Home/PropertySearchResult.aspx"
    params = {
        "sState": "VA",
        "sCity": "FREDERICKSBURG,STAFFORD,SPOTSYLVANIA,BOWLING GREEN",
        "iPage": 1,
        "sPageSize": 50,
    }
    log.info(f"  HUD Homes: {url}")

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # HUD renders an HTML table
        rows = soup.select("table.property-list tr, #propertyList tr, tr.property-row")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            address = cells[0].get_text(strip=True)
            city = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            price_text = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            price = parse_price(price_text)
            link = row.find("a")

            listing = {
                "id": make_id(address, None),
                "address": address,
                "city": city,
                "county": city_to_county(city),
                "zip": None,
                "stage": "reo",
                "property_type": "single-family",
                "assessed_value": None,
                "asking_price": price,
                "sale_date": None,
                "sale_time": None,
                "sale_location": None,
                "days_until_sale": None,
                "notice_date": None,
                "days_in_foreclosure": None,
                "lender": "HUD / FHA",
                "trustee": None,
                "source": "hud_homes",
                "source_url": "https://www.hudhomestore.gov" + link["href"] if link else None,
            }
            listings.append(listing)

    except Exception as e:
        log.error(f"  Error scraping HUD Homes: {e}")

    log.info(f"  HUD Homes: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Source 4: Fannie Mae HomePath
# ---------------------------------------------------------------------------

def scrape_homepath() -> list:
    """
    Scrapes Fannie Mae REO listings from HomePath.com.
    HomePath uses a REST API — we call it directly.
    """
    listings = []
    # HomePath API endpoint (discovered via browser devtools)
    url = "https://www.homepath.com/api/property/search"
    payload = {
        "state": "VA",
        "city": "Fredericksburg",
        "radius": 30,
        "pageSize": 50,
        "page": 1,
    }
    log.info(f"  HomePath: {url}")

    try:
        resp = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        properties = data.get("properties") or data.get("results") or []

        for item in properties:
            address = item.get("streetAddress") or item.get("address", {}).get("street", "")
            city = item.get("city", "") or item.get("address", {}).get("city", "")
            zip_code = item.get("zipCode") or item.get("postalCode", "")
            price = item.get("listPrice") or item.get("price")

            listing = {
                "id": make_id(address, None),
                "address": address,
                "city": city,
                "county": city_to_county(city),
                "zip": zip_code,
                "stage": "reo",
                "property_type": normalize_property_type(item.get("propertyType", "")),
                "assessed_value": None,
                "asking_price": price,
                "sale_date": None,
                "sale_time": None,
                "sale_location": None,
                "days_until_sale": None,
                "notice_date": None,
                "days_in_foreclosure": None,
                "lender": "Fannie Mae",
                "trustee": None,
                "source": "homepath",
                "source_url": f"https://www.homepath.com/property/{item.get('mlsId', '')}",
            }
            listings.append(listing)

    except Exception as e:
        log.error(f"  Error scraping HomePath: {e}")

    log.info(f"  HomePath: found {len(listings)} listings")
    return listings


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

def parse_address_from_notice(text: str) -> str:
    """
    Virginia trustee sale notices typically open with the property address.
    This grabs the first line up to the first comma-separated city/state block.
    Adjust the regex if notices in your target counties have a different format.
    """
    import re
    match = re.search(r"(\d+\s+[\w\s]+(?:Rd|St|Ave|Dr|Ln|Way|Ct|Blvd|Pl|Pike|Hwy)[^,]*)", text, re.IGNORECASE)
    return match.group(1).strip() if match else text[:80]


def parse_sale_datetime(text: str):
    """Extract sale date and time from notice body text."""
    import re
    # Match patterns like "May 15, 2026" or "05/15/2026"
    date_match = re.search(r"(\w+ \d{1,2},\s*\d{4}|\d{1,2}/\d{1,2}/\d{4})", text)
    time_match = re.search(r"(\d{1,2}:\d{2}\s*(?:AM|PM|a\.m\.|p\.m\.))", text, re.IGNORECASE)

    sale_date = None
    if date_match:
        raw = date_match.group(1).strip()
        for fmt in ("%B %d, %Y", "%m/%d/%Y"):
            try:
                sale_date = datetime.strptime(raw, fmt).date().isoformat()
                break
            except ValueError:
                continue

    sale_time = time_match.group(1).upper().replace("A.M.", "AM").replace("P.M.", "PM") if time_match else None
    return sale_date, sale_time


def parse_lender(text: str) -> str:
    """Look for common lender name patterns in notice text."""
    import re
    match = re.search(
        r"((?:Wells Fargo|Bank of America|Chase|JPMorgan|PNC|U\.?S\.? Bank|Rocket|Truist|SunTrust|USAA|Navy Federal)[^,.\n]*)",
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_trustee(text: str) -> str:
    """Look for common Virginia trustee firm names."""
    import re
    match = re.search(
        r"(Samuel I\. White|BWW Law|Friedman.*?MacFadyen|Hutchens|Substitute Trustee Services|Brock.*?Scott|McCabe.*?Weisberg)[^,.\n]*",
        text, re.IGNORECASE
    )
    return match.group(1).strip() if match else None


def parse_price(text: str):
    """Parse a dollar amount string into an integer."""
    import re
    match = re.search(r"\$([\d,]+)", text)
    if match:
        return int(match.group(1).replace(",", ""))
    return None


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def county_display(county: str) -> str:
    return {
        "fredericksburg": "Fredericksburg City",
        "stafford": "Stafford",
        "spotsylvania": "Spotsylvania",
        "caroline": "Caroline",
    }.get(county.lower(), county.title())


def county_city(county: str) -> str:
    return {
        "fredericksburg": "Fredericksburg",
        "stafford": "Stafford",
        "spotsylvania": "Fredericksburg",
        "caroline": "Bowling Green",
    }.get(county.lower(), county.title())


def courthouse_location(county: str) -> str:
    return {
        "fredericksburg": "Front steps, Fredericksburg Circuit Court, 815 Princess Anne St",
        "stafford":       "Front steps, Stafford Circuit Court, 1300 Courthouse Rd",
        "spotsylvania":   "Front steps, Spotsylvania Circuit Court, 9115 Courthouse Rd",
        "caroline":       "Front steps, Caroline Circuit Court, 112 Courthouse Ln",
    }.get(county.lower(), "Courthouse steps (verify with trustee)")


def courthouse_for_address(county: str) -> str:
    return courthouse_location(county.lower().replace(" county", "").replace(" city", ""))


def normalize_county(raw: str) -> str:
    raw = raw.lower().replace(" county", "").replace(" city", "").strip()
    return county_display(raw)


def city_to_county(city: str) -> str:
    city = city.lower().strip()
    mapping = {
        "fredericksburg": "Fredericksburg City",
        "stafford": "Stafford",
        "aquia harbour": "Stafford",
        "quantico": "Stafford",
        "spotsylvania": "Spotsylvania",
        "chancellor": "Spotsylvania",
        "bowling green": "Caroline",
        "milford": "Caroline",
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
    if "condo" in raw or "townhouse" in raw or "townhome" in raw:
        return "condo/townhome"
    return "single-family"


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
    log.info("Starting Fredericksburg foreclosure scraper...")
    all_listings = []

    log.info("--- PublicNoticeVirginia.com ---")
    all_listings.extend(scrape_public_notice_va())

    log.info("--- Auction.com ---")
    all_listings.extend(scrape_auction_com())

    log.info("--- HUD Homes ---")
    all_listings.extend(scrape_hud_homes())

    log.info("--- Fannie Mae HomePath ---")
    all_listings.extend(scrape_homepath())

    all_listings = deduplicate(all_listings)
    log.info(f"Total after dedup: {len(all_listings)} listings")
    save(all_listings)
    log.info("Done.")


if __name__ == "__main__":
    import sys
    if "--debug" in sys.argv:
        # Print raw HTML from the first source for selector debugging
        resp = requests.get(
            "https://publicnoticevirginia.com/search?keywords=foreclosure&county=fredericksburg&state=VA",
            headers=HEADERS, timeout=15
        )
        print(resp.text[:5000])
    else:
        run()
