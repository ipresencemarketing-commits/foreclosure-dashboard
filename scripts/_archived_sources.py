#!/usr/bin/env python3
"""
Foreclosure Finder — Archived / Removed Scraper Sources
=========================================================
These functions were removed from active use in May 2026 because the
underlying sites are either paywalled, have shut down their free data,
or require paid APIs.  They are preserved here for reference only.

DO NOT import this file from scraper.py or any pipeline script.
None of these functions are called by run().

Removed sources:
  scrape_auction_com()  — Auction.com (listing detail pages)
  scrape_hud_homes()    — HUD Homestore REO (hudhomestore.gov)
  scrape_homepath()     — Fannie Mae HomePath REO (homepath.fanniemae.com)
  scrape_homesteps()    — Freddie Mac HomeSteps REO (homesteps.com)

Why removed:
  Auction.com   — site is fully client-side; sitemap-based approach was
                  fragile; PNV covers the same trustee sale data for free.
  HUD Homes     — Yardi-backed JSON endpoint broke; very few VA listings.
  HomePath      — Fannie Mae partner-restricted their API in late 2025.
  HomeSteps     — Freddie Mac restructured the site; page no longer
                  exposes Drupal .property-* class names.

If any of these sites re-enable free access in the future, copy the
function back into scraper.py and add a call in run() behind an
ENABLE_* flag in config.py.
"""

from __future__ import annotations

import re
import json
import logging
from datetime import datetime
from time import sleep

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ── Shared headers (copied from scraper.py so this file is self-contained) ──
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
# Auction.com (removed 2026-05)
# ---------------------------------------------------------------------------

def scrape_auction_com() -> list:
    """
    REMOVED 2026-05 — not called.

    Scraped Auction.com for foreclosure listings in target Virginia counties.

    Approach used XML sitemaps (sitemap-pdp-active-tps-*.xml /
    sitemap-pdp-active-reo-*.xml) to discover active listing URLs, filtered
    by target county slug keywords, then fetched each detail page to parse
    embedded JSON auction data.

    Site is now fully client-side rendered; the sitemap approach still works
    but PNV covers the same trustee sale notices for free.  Remove this note
    if you find a compelling reason to re-enable.
    """
    return []

    # Original implementation preserved below for reference.
    listings = []

    SLUG_COUNTY: dict[str, str] = {
        "stafford-va": "Stafford", "fredericksburg-va": "Fredericksburg City",
        "spotsylvania-va": "Spotsylvania", "bowling-green-va": "Caroline",
        "ruther-glen-va": "Caroline", "milford-va": "Caroline",
        "port-royal-va": "Caroline", "woodford-va": "Caroline",
        "penola-va": "Caroline", "warrenton-va": "Fauquier",
        "new-baltimore-va": "Fauquier", "bealeton-va": "Fauquier",
        "catlett-va": "Fauquier", "remington-va": "Fauquier",
        "midland-va": "Fauquier", "culpeper-va": "Culpeper",
        "jeffersonton-va": "Culpeper", "woodville-va": "Culpeper",
        "brandy-station-va": "Culpeper", "king-george-va": "King George",
        "dahlgren-va": "King George", "ashland-va": "Hanover",
        "mechanicsville-va": "Hanover", "hanover-va": "Hanover",
        "atlee-va": "Hanover", "richmond-va": "Richmond City",
        "chesterfield-va": "Chesterfield", "midlothian-va": "Chesterfield",
        "chester-va": "Chesterfield", "bon-air-va": "Chesterfield",
        "henrico-va": "Henrico", "glen-allen-va": "Henrico",
        "short-pump-va": "Henrico", "sandston-va": "Henrico",
        "highland-springs-va": "Henrico", "louisa-va": "Louisa",
        "mineral-va": "Louisa",
    }

    try:
        idx_resp = requests.get(
            "https://www.auction.com/sitemaps/sitemapindex.xml",
            headers=HEADERS, timeout=15
        )
        idx_resp.raise_for_status()
        all_sm_urls = re.findall(r"<loc>(https://[^<]+)</loc>", idx_resp.text)
        pdp_urls = [
            u for u in all_sm_urls
            if ("sitemap-pdp-active-tps" in u or "sitemap-pdp-active-reo" in u)
            and "image" not in u
        ]
        target_detail_urls: list[str] = []
        for sm_url in pdp_urls:
            try:
                sm_resp = requests.get(sm_url, headers=HEADERS, timeout=20)
                sm_resp.raise_for_status()
                locs = re.findall(
                    r"<loc>(https://www\.auction\.com/details/[^<]+)</loc>", sm_resp.text
                )
                for u in locs:
                    slug = u.split("/details/")[-1]
                    if any(kw in slug for kw in SLUG_COUNTY):
                        target_detail_urls.append(u)
                sleep(0.3)
            except Exception as e:
                log.warning(f"  Auction.com: sitemap error {sm_url}: {e}")

        target_detail_urls = list(dict.fromkeys(target_detail_urls))

        for detail_url in target_detail_urls:
            try:
                slug       = detail_url.split("/details/")[-1]
                county_name = next(
                    (cn for kw, cn in SLUG_COUNTY.items() if kw in slug), None
                )
                det_resp = requests.get(detail_url, headers=HEADERS, timeout=20)
                det_resp.raise_for_status()
                html = det_resp.text

                title_m   = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
                title_raw = title_m.group(1).strip() if title_m else ""
                addr_part = title_raw.split(" | ")[0].strip() if " | " in title_raw else title_raw
                am = re.match(
                    r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?),\s*(.+)$", addr_part
                )
                if am:
                    street = am.group(1).strip()
                    city_name = am.group(2).strip()
                    zip_code  = am.group(4).strip()
                    if not county_name:
                        county_name = am.group(5).replace(" County", "").replace(" City", "").strip()
                else:
                    slug_no_id = re.sub(r"-\d+$", "", slug)
                    parts = slug_no_id.split("-")
                    street    = " ".join(parts[:-2]).title() if len(parts) >= 3 else slug_no_id.replace("-", " ").title()
                    city_name = parts[-2].title() if len(parts) >= 3 else ""
                    zip_code  = None

                sale_date = asking_price = None
                auction_m = re.search(
                    r'"auction"\s*:\s*(\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\})', html
                )
                if auction_m:
                    try:
                        auc = json.loads(auction_m.group(1))
                        raw_date = (auc.get("auction_date") or auc.get("visible_auction_start_date_time")
                                    or auc.get("end_date") or auc.get("start_date"))
                        if raw_date:
                            sale_date = str(raw_date)[:10]
                        bid = auc.get("starting_bid")
                        if bid and int(bid) > 1:
                            asking_price = int(bid)
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass

                listings.append({
                    "address": street, "city": city_name, "county": county_name or "Unknown",
                    "zip": zip_code, "stage": "auction", "asking_price": asking_price,
                    "sale_date": sale_date, "source": "auction.com", "source_url": detail_url,
                })
                sleep(0.4)
            except Exception as e:
                log.warning(f"  Auction.com: detail error {detail_url}: {e}")

    except Exception as e:
        log.error(f"  Auction.com error: {e}", exc_info=True)

    return listings


# ---------------------------------------------------------------------------
# HUD Homes (removed 2026-05)
# ---------------------------------------------------------------------------

def scrape_hud_homes() -> list:
    """
    REMOVED 2026-05 — not called.

    Scraped HUD REO listings from HUD Homestore (hudhomestore.gov).
    The Yardi-backed JSON endpoint embedded all listings in a hidden <input>
    element.  The endpoint broke in 2026 and HUD has very few VA listings.
    """
    return []

    listings = []
    url = "https://www.hudhomestore.gov/searchresult?citystate=VA"
    TARGET_COUNTIES_HUD = {
        "stafford", "spotsylvania", "caroline", "fredericksburg",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond", "chesterfield", "henrico", "louisa",
    }
    COUNTY_DISPLAY = {
        "stafford": "Stafford", "spotsylvania": "Spotsylvania",
        "caroline": "Caroline", "fredericksburg": "Fredericksburg City",
        "fauquier": "Fauquier", "culpeper": "Culpeper",
        "king george": "King George", "hanover": "Hanover",
        "richmond": "Richmond City", "chesterfield": "Chesterfield",
        "henrico": "Henrico", "louisa": "Louisa",
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        json_input = next(
            (inp for inp in soup.find_all("input", type="hidden")
             if inp.get("value", "").startswith("[{")),
            None
        )
        if not json_input:
            m = re.search(r'value="\s*(\[\{.*?\}])\s*"', resp.text, re.S)
            raw_json = m.group(1) if m else None
        else:
            raw_json = json_input.get("value", "")

        if not raw_json:
            return listings

        for prop in json.loads(raw_json):
            county_raw = str(prop.get("propertyCounty", "")).strip().lower()
            if county_raw not in TARGET_COUNTIES_HUD:
                continue
            address  = str(prop.get("propertyAddress", "")).strip()
            city_raw = str(prop.get("propertyCity", "")).strip()
            zip_raw  = str(prop.get("propertyZip", "")).strip()
            price = None
            try:
                raw_price = prop.get("listPrice")
                if raw_price not in (None, "", "0"):
                    price = int(float(str(raw_price).replace(",", "")))
            except (ValueError, TypeError):
                pass
            sale_date = None
            raw_date = prop.get("bidOpenDate") or prop.get("listDate")
            if raw_date:
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        sale_date = datetime.strptime(str(raw_date)[:19], fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
            case_num = str(prop.get("propertyCaseNumber", "")).strip()
            source_url = (
                f"https://www.hudhomestore.gov/Listing/PropertyListing.aspx"
                f"?caseNumber={case_num.replace('-', '')}" if case_num else None
            )
            listings.append({
                "address": address, "city": city_raw, "zip": zip_raw or None,
                "county": COUNTY_DISPLAY.get(county_raw, county_raw.title()),
                "stage": "reo", "asking_price": price, "sale_date": sale_date,
                "lender": "HUD / FHA", "source": "hud_homes", "source_url": source_url,
            })
        sleep(1)
    except Exception as e:
        log.error(f"  HUD Homes error: {e}", exc_info=True)

    return listings


# ---------------------------------------------------------------------------
# Fannie Mae HomePath (removed 2026-05)
# ---------------------------------------------------------------------------

def scrape_homepath() -> list:
    """
    REMOVED 2026-05 — not called.

    Fetched Fannie Mae REO listings from HomePath's JSON API.
    Fannie Mae partner-restricted the API endpoint in late 2025.
    Bounding box covered all 12 target counties.
    """
    return []

    listings = []
    bounds = "37.30,-78.30,38.90,-77.10"
    url    = f"https://homepath.fanniemae.com/cfl/property-inventory/search?bounds={bounds}"
    TARGET_COUNTY_MAP = {
        "fredericksburg": "Fredericksburg City", "stafford": "Stafford",
        "spotsylvania": "Spotsylvania", "caroline": "Caroline",
        "fauquier": "Fauquier", "culpeper": "Culpeper",
        "king george": "King George", "hanover": "Hanover",
        "richmond": "Richmond City", "chesterfield": "Chesterfield",
        "henrico": "Henrico", "louisa": "Louisa",
    }

    try:
        resp = requests.get(
            url, headers={**HEADERS, "Accept": "application/json, text/plain, */*",
                          "Referer": "https://homepath.fanniemae.com/"}, timeout=20
        )
        resp.raise_for_status()
        for item in resp.json().get("properties") or []:
            county_raw   = (item.get("county") or "").lower().strip()
            county_clean = TARGET_COUNTY_MAP.get(county_raw)
            if not county_clean:
                continue
            address  = (item.get("addressLine1") or "").title()
            city     = (item.get("city") or "").title()
            zip_code = item.get("zipCode") or ""
            price    = item.get("price")
            prop_uuid = item.get("propertyUuid") or ""
            geo      = item.get("geoPoint") or {}
            listings.append({
                "address": address, "city": city, "county": county_clean,
                "zip": zip_code, "stage": "reo", "asking_price": price,
                "latitude": geo.get("latitude"), "longitude": geo.get("longitude"),
                "lender": "Fannie Mae", "owner_name": "Fannie Mae",
                "owner_mailing_address": "3900 Wisconsin Ave NW, Washington, DC 20016",
                "owner_mailing_differs": True,
                "owner_phone": "1-800-732-6643",
                "source": "homepath",
                "source_url": (f"https://homepath.fanniemae.com/property-detail/{prop_uuid}"
                               if prop_uuid else None),
            })
        sleep(1)
    except Exception as e:
        log.error(f"  HomePath error: {e}", exc_info=True)

    return listings


# ---------------------------------------------------------------------------
# Freddie Mac HomeSteps (removed 2026-05)
# ---------------------------------------------------------------------------

def scrape_homesteps() -> list:
    """
    REMOVED 2026-05 — not called.

    Scraped Freddie Mac HomeSteps REO listings from homesteps.com.
    Freddie Mac restructured the site in 2026; page no longer exposes the
    Drupal .property-* class names used by this scraper.
    """
    return []

    listings = []
    url = "https://www.homesteps.com/listing/search?search=Virginia"
    TARGET_COUNTIES_SET = {
        "fredericksburg city", "stafford", "spotsylvania", "caroline",
        "fauquier", "culpeper", "king george", "hanover",
        "richmond city", "chesterfield", "henrico", "louisa",
    }

    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for item in [li for li in soup.find_all("li")
                     if li.find("a", href=re.compile(r"/listingdetails/"))]:
            addr_el = item.find(class_="property-address")
            if not addr_el:
                continue
            addr_m = re.match(
                r"^(.*?),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
                addr_el.get_text(" ", strip=True)
            )
            if not addr_m or addr_m.group(3) != "VA":
                continue
            street   = addr_m.group(1).strip()
            city_raw = addr_m.group(2).strip()
            zip_code = addr_m.group(4)

            # Derive county from city — city_to_county lives in scraper.py
            # so this is non-functional here; kept for documentation only.
            county = "Unknown"
            if county == "Unknown" or county.lower() not in TARGET_COUNTIES_SET:
                continue

            price = None
            price_el = item.find(class_="property-price")
            if price_el:
                pm = re.search(r"\$([\d,]+)", price_el.get_text())
                price = int(pm.group(1).replace(",", "")) if pm else None

            beds = baths = sqft = None
            details_el = item.find(class_="property-details")
            if details_el:
                dt = details_el.get_text()
                bm = re.search(r"(\d+)\s*bed", dt)
                bam = re.search(r"([\d.]+)\s*bath", dt)
                sm  = re.search(r"([\d,]+)\s*sq\.?\s*ft", dt, re.I)
                beds  = int(bm.group(1))                    if bm  else None
                baths = float(bam.group(1))                 if bam else None
                sqft  = int(sm.group(1).replace(",", ""))   if sm  else None

            link_el = item.find("a", href=re.compile(r"/listingdetails/"))
            href = link_el["href"] if link_el else None
            source_url = ("https://www.homesteps.com" + href
                          if href and not href.startswith("http") else href)

            listings.append({
                "address": street, "city": city_raw.title(), "county": county,
                "zip": zip_code, "stage": "reo", "asking_price": price,
                "beds": beds, "baths": baths, "sqft": sqft,
                "lender": "Freddie Mac", "owner_name": "Freddie Mac",
                "owner_mailing_address": "8200 Jones Branch Dr, McLean, VA 22102",
                "owner_mailing_differs": True,
                "owner_phone": "1-800-FREDDIE",
                "source": "homesteps", "source_url": source_url,
            })
        sleep(1)
    except Exception as e:
        log.error(f"  HomeSteps error: {e}", exc_info=True)

    return listings
