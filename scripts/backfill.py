#!/usr/bin/env python3
"""
backfill.py — Scan the Google Sheet for blank cells and fill them.

Run after sheets_sync.py.  For each empty field it tries progressively
richer data sources until it finds a value or runs out of options.

Pass order
----------
  1.  F_Sale_Date / F_Sale_Time  — re-fetch source notice URL, re-parse text
  1b. F_Sale_Date / F_Sale_Time  — secondary sources for rows still blank:
        • Auction.com listing re-fetch  → parses fresh auction_date from JSON
        • PNV address search            → searches PNV by street address (not by
                                          county), catches notices the county-
                                          filtered scraper missed
  2.  County                     — city_to_county(), address parse, ZIP lookup, Census geocoder
  3. State                       — always "VA"
  4. City                        — parse from address string
  5. ZIP                         — extract 5-digit code from address
  6. Owner + Property Details  — VGIN statewide parcel API tried first (one
                                call returns owner name, mailing address, year
                                built, sqft, beds/baths, lot size, assessed
                                value, last sale); falls back to county ArcGIS;
                                Redfin supplement only when GIS missing
                                beds/sqft or value; calculates Rough_Equity_Est,
                                Est_Profit_Potential, Years_Since_Last_Sale.
  7. Derived fields only       — recalculates equity/profit/years for rows that
                                  now have inputs but still missing outputs
                                  (no API calls).
  8. Column.us Listing_URL              — Playwright DOM search to replace the
                                          generic search-page URL with the individual
                                          notice detail URL ("Copy link" URL)

Run: python3 scripts/backfill.py
"""

from __future__ import annotations

import sys
import os
import re
import glob
import json
import logging
from datetime import date
from time import sleep

import requests
from bs4 import BeautifulSoup
import gspread
from google.oauth2.service_account import Credentials

# ── Import shared helpers from scraper ───────────────────────────────────────
# sys.path insert lets us import scraper.py as a module without installing it.
# scraper.run() is guarded by __name__ == "__main__" so it won't execute.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import (           # noqa: E402
    parse_sale_datetime,
    city_to_county,
    county_display,
    GIS_REGISTRY,
    TARGET_COUNTIES,
    HEADERS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
SHEET_ID     = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
SCOPES       = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
CREDS_FILE   = os.path.join(PROJECT_ROOT, "credentials", "service-account.json")

# Reverse map: "Stafford" → "stafford", "Fredericksburg City" → "fredericksburg"
DISPLAY_TO_KEY: dict[str, str] = {
    county_display(k): k for k in TARGET_COUNTIES
}


# ── Auth ─────────────────────────────────────────────────────────────────────

def find_creds_file() -> str | None:
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    matches = glob.glob(os.path.join(PROJECT_ROOT, "savvy-factor-*.json"))
    return matches[0] if matches else None


# ── Data-fetch helpers ───────────────────────────────────────────────────────

def fetch_notice_text(url: str) -> str:
    """
    Fetch a PNV or Column.us notice detail page and return the fullest
    text block available.  Mirrors the detail-fetch logic in scraper.py.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        soup = BeautifulSoup(resp.text, "lxml")
        body = (
            soup.find(id=re.compile(r"notice.?(text|body|detail)", re.I)) or
            soup.find(class_=re.compile(r"notice.?(text|body|detail)", re.I)) or
            soup.find("div", class_=re.compile(r"content|main|article", re.I))
        )
        return body.get_text(" ", strip=True) if body else soup.get_text(" ", strip=True)
    except Exception as exc:
        log.debug(f"  fetch_notice_text({url!r}): {exc}")
        return ""


def get_auction_com_date(url: str) -> tuple[str, str]:
    """
    Re-fetch an Auction.com listing and extract a current auction date from
    the embedded JSON block.  Auction.com refreshes dates as sales are
    scheduled, so this catches dates that weren't set at initial scrape time.

    Returns (sale_date_iso, "") — time is not available on Auction.com pages.
    """
    if not url or "auction.com" not in url.lower():
        return "", ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        text = resp.text
        # Primary: "auction_date":"2026-06-15"
        for pattern in [
            r'"auction_date"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            r'"auctionDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            r'"sale_date"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            r'"saleDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return m.group(1), ""
        # Fallback: look for a human-readable date near "auction" keyword
        sale_date, sale_time = parse_sale_datetime(text)
        if sale_date:
            return sale_date, sale_time
    except Exception as exc:
        log.debug(f"  get_auction_com_date({url!r}): {exc}")
    return "", ""


def search_pnv_by_address(address: str) -> tuple[str, str]:
    """
    Search PublicNoticeVirginia.com for a specific property address.

    Uses PNV's keyword text field with "HOUSE_NUMBER STREET_NAME" as the
    search term — completely different from the county-checkbox scraper, so
    it catches notices the county-filtered pass may have missed.

    No county checkboxes are posted (avoids the ASP.NET ParseInt32 crash).
    Results are verified against the address before a detail page is fetched.

    Returns (sale_date_iso, sale_time) or ("", "").
    """
    # Build search term: house number + first meaningful word of street name
    # "1234 Main Street, Stafford, VA 22554" → "1234 MAIN"
    # Strip city/state/ZIP first so we don't accidentally use them as street words
    street_part = re.split(r",\s*[A-Za-z].*$", address)[0].strip()
    tokens = street_part.upper().split()
    # tokens[0] should be house number, tokens[1] street word
    if len(tokens) < 2:
        return "", ""
    house_num   = tokens[0]
    search_term = f"{house_num} {tokens[1]}"

    session = requests.Session()
    try:
        # ── Step 1: establish ASP.NET session (follows redirect to session URL) ──
        resp = session.get(
            "https://www.publicnoticevirginia.com/",
            headers=HEADERS, timeout=15, allow_redirects=True,
        )
        m = re.search(
            r"(https://www\.publicnoticevirginia\.com/\(S\([^)]+\)\))", resp.url
        )
        session_base = m.group(1) if m else "https://www.publicnoticevirginia.com"
        default_url  = session_base + "/default.aspx"

        # ── Step 2: GET default.aspx for hidden form tokens ───────────────────
        resp2 = session.get(
            default_url,
            headers={**HEADERS, "Referer": "https://www.publicnoticevirginia.com/"},
            timeout=15,
        )
        soup = BeautifulSoup(resp2.text, "lxml")

        post_data: list[tuple[str, str]] = []
        for inp in soup.find_all("input", type="hidden"):
            name = inp.get("name", "")
            val  = inp.get("value", "")
            if name:
                post_data.append((name, val))

        post_data += [
            ("__EVENTTARGET",   ""),
            ("__EVENTARGUMENT", ""),
            # Address-based keyword — no county checkboxes (avoids ParseInt32 crash)
            ("ctl00$ContentPlaceHolder1$as1$txtSearch", search_term),
            ("ctl00$ContentPlaceHolder1$as1$btnGo",     ""),
        ]

        # ── Step 3: POST search and parse result grid ─────────────────────────
        resp3 = session.post(
            default_url,
            data=post_data,
            headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer":      default_url,
            },
            timeout=30,
        )
        soup3 = BeautifulSoup(resp3.text, "lxml")

        grid = (
            soup3.find(id=re.compile(r"updateWSGrid", re.I)) or
            soup3.find(id=re.compile(r"WSExtendedGrid", re.I))
        )
        if not grid:
            log.debug(f"  PNV search: no grid returned for {search_term!r}")
            return "", ""

        rows = grid.find_all("tr")[1:]   # skip header
        for row in rows:
            if row.find("th"):
                continue
            row_text = row.get_text(" ", strip=True).upper()

            # Must be a trustee/sale notice
            if not re.search(r"TRUSTEE|DEED OF TRUST|SALE OF REAL PROPERTY", row_text):
                continue
            # Must mention our house number (prevents false-positive street matches)
            if house_num not in row_text:
                continue

            link = row.find("a")
            if not link:
                continue
            href = link.get("href", "")
            detail_url = (
                href if href.startswith("http")
                else session_base + "/" + href.lstrip("/")
            )

            # ── Step 4: fetch detail page and parse date ──────────────────────
            det     = session.get(
                detail_url,
                headers={**HEADERS, "Referer": default_url},
                timeout=15,
            )
            det_soup = BeautifulSoup(det.text, "lxml")
            body = (
                det_soup.find(id=re.compile(r"notice.?(text|body|detail)", re.I)) or
                det_soup.find(class_=re.compile(r"notice.?(text|body|detail)", re.I)) or
                det_soup.find("div", class_=re.compile(r"content|main|article", re.I))
            )
            full_text = body.get_text(" ", strip=True) if body else det_soup.get_text(" ", strip=True)

            sale_date, sale_time = parse_sale_datetime(full_text)
            if sale_date:
                log.debug(f"  PNV search: found {sale_date} for {address!r}")
                return sale_date, sale_time
            sleep(0.5)

    except Exception as exc:
        log.debug(f"  search_pnv_by_address({address!r}): {exc}")

    return "", ""


# ── GIS field-name candidates for property detail fields ─────────────────────
# Virginia county ArcGIS parcel APIs use different column names for the same
# concept — these lists cover every variant we've seen across all 12 counties.
# The most common names are listed first to minimise failed lookups.
_YR_BUILT_FIELDS  = [
    "YEAR_BUILT", "YR_BLT", "YRBLT", "BUILT_YR", "BUILD_YEAR",
    "EFFECTIVEYEARBUILT", "ACTUAL_YEAR_BUILT", "YEAR_BLT",
    "YR_BUILT", "CONST_YR", "CONSTRUCTION_YEAR", "YEAR_CONSTRUCTED",
]
_SQFT_FIELDS      = [
    "TOTAL_SQFT", "LIVING_AREA", "SQFT", "FINISHED_SQ_FT",
    "TOTAL_AREA", "LIV_AREA", "BLDG_AREA", "BUILDING_SQFT",
    "TOTAL_LIV_AREA", "HEATED_AREA", "TOTAL_LIVING_SQ_FT",
    "TOT_LIVING_AREA", "BUILDING_AREA", "TOTAL_FINISHED_AREA",
    "CALC_SQFT", "TOTAL_FIN_SQFT", "SQFT_LIVING", "TOTAL_SQ_FT",
]
_LOT_ACRES_FIELDS = [
    "ACRES", "LOT_ACRES", "CALC_ACRES", "AREA_ACRES",
    "LAND_ACRES", "PARCEL_ACRES", "TOTAL_ACRES", "LOT_AREA_ACRES",
]
_LOT_SQFT_FIELDS  = [
    "LOT_SIZE", "LOT_AREA", "LOT_SQFT", "LOT_SIZE_SF", "PARCEL_SQFT",
]  # fallback when no acres field exists — convert to acres before storing
_ASSESSED_FIELDS  = [
    "TOTAL_VALUE", "ASSESSED_VALUE", "ASMT_VALUE", "TOT_ASD_VAL",
    "TOTAL_ASD", "TOTAL_ASSESSED_VALUE", "ASMT_TOT", "TOT_ASMT",
    "ASSESS_VAL", "TOTAL_MARKET_VALUE", "TAXABLE_VALUE",
    "TOTAL_TAXABLE_VALUE", "FMKT_VALUE", "FAIR_MKT_VALUE",
]
_SALE_DATE_FIELDS = [
    "SALE_DATE", "LAST_SALE_DATE", "LAST_SALE_DT", "DEED_DATE",
    "SALEDT", "TRANSFER_DATE", "LAST_CONVEYANCE_DATE",
    "CONV_DATE", "RECORD_DATE", "SALES_DATE", "DEED_DT",
]
_SALE_PRC_FIELDS  = [
    "SALE_PRICE", "LAST_SALE_PRICE", "DEED_PRICE", "SALES_PRICE",
    "SALEPRICE", "TRANSFER_PRICE", "LAST_CONVEYANCE_AMT",
    "CONV_PRICE", "LAST_SALE_AMT",
]
_BEDS_FIELDS      = [
    "BEDROOMS", "BED_ROOMS", "BEDS", "NO_OF_BEDS", "NUM_BEDS",
    "BDRMS", "BEDROOM_COUNT", "NO_BEDROOMS", "NUM_BEDROOMS",
]
_BATHS_FIELDS     = [
    "BATHROOMS", "BATHS", "FULL_BATHS", "BATH_ROOMS", "NO_OF_BATHS",
    "NUM_BATHS", "BTHRM", "BATH_COUNT", "FULL_BATH_COUNT",
]


def _pick_numeric(attrs: dict, candidates: list) -> float | None:
    """
    Return the first non-zero positive numeric value from `attrs` matching
    any name in `candidates` (case-insensitive). Returns None if not found.
    """
    attrs_up = {k.upper(): v for k, v in attrs.items()}
    for field in candidates:
        v = attrs_up.get(field.upper())
        if v is None:
            continue
        try:
            n = float(v)
            if n > 0:
                return n
        except (ValueError, TypeError):
            continue
    return None


def _parse_gis_date(raw) -> str:
    """
    Normalise a GIS date value to ISO format (YYYY-MM-DD).

    ArcGIS stores dates in several ways:
      • epoch milliseconds (int/float)  e.g. 1623801600000
      • ISO string                       e.g. "2021-06-15"
      • US slash format                  e.g. "06/15/2021"
      • Compact string                   e.g. "20210615"
    Returns "" if the value cannot be parsed or represents an empty/null date.
    """
    if raw is None:
        return ""
    # Epoch milliseconds
    if isinstance(raw, (int, float)) and raw > 0:
        try:
            from datetime import datetime as _dt
            dt = _dt.utcfromtimestamp(raw / 1000)
            if dt.year > 1970:
                return dt.strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            pass
    raw_s = str(raw).strip()
    if not raw_s or raw_s in ("-1", "0", "null", "None", ""):
        return ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw_s)          # ISO
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})", raw_s)      # MM/DD/YYYY
    if m:
        return f"{m.group(3)}-{m.group(1).zfill(2)}-{m.group(2).zfill(2)}"
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", raw_s)            # YYYYMMDD
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


# ── VGIN statewide parcel API ────────────────────────────────────────────────
# Single endpoint that covers all 12 target Virginia counties.
# Eliminates per-county routing and returns the same fields as county GIS portals.
VGIN_URL = (
    "https://gismaps.vdem.virginia.gov/arcgis/rest/services/"
    "VA_Base_Layers/VA_Parcels/FeatureServer/0/query"
)
# VGIN address field candidates — tried in order until a non-empty hit is returned
_VGIN_ADDR_FIELDS = ["SITE_ADD", "SITEADDRESS", "SITE_ADDRESS", "ADDRESS", "ADDR"]


def _pick_str(attrs: dict, candidates: list) -> str | None:
    """Return the first non-empty string value from attrs matching any candidate (case-insensitive)."""
    attrs_up = {k.upper(): v for k, v in attrs.items()}
    for field in candidates:
        v = attrs_up.get(field.upper())
        if v and str(v).strip() not in ("", "null", "None", "N/A"):
            return str(v).strip()
    return None


def _parse_full_attrs(attrs: dict, addr_field: str, cfg: dict | None) -> dict:
    """
    Extract all owner + property detail fields from a single ArcGIS attribute dict.

    Works for both VGIN statewide responses (cfg=None) and county-specific
    responses (cfg = GIS_REGISTRY entry).  Returns {} if no useful data found.
    """
    result: dict = {}

    # ── Owner name ────────────────────────────────────────────────────────────
    owner_cands = (cfg or {}).get("owner_variants") or [
        "OWNER_NAME", "OWNER", "OWNNAME", "GRANTEE", "OWN_NAME",
    ]
    owner = _pick_str(attrs, owner_cands)
    if owner:
        result["owner_name"] = owner.title()

    # ── Mailing address ───────────────────────────────────────────────────────
    mv = (cfg or {}).get("mail_variants") or {
        "line1": ["MAIL_ADDR1", "MAIL_ADD1", "MAIL_ADD", "MAILING_ADDRESS", "MAILADDR", "MAILADDR1"],
        "city":  ["MAIL_CITY",  "MAILCITY",  "MAIL_CTY"],
        "state": ["MAIL_STATE", "MAILSTATE", "MAIL_ST"],
        "zip":   ["MAIL_ZIP",   "MAILZIP",   "MAIL_ZIP5"],
    }
    ml1   = _pick_str(attrs, mv["line1"])
    mcity = _pick_str(attrs, mv["city"])
    mst   = _pick_str(attrs, mv["state"])
    mzip  = _pick_str(attrs, mv["zip"])
    if ml1:
        mailing = ", ".join(p for p in [ml1, mcity, mst, mzip] if p)
        result["owner_mailing_address"] = mailing
        site = str(attrs.get(addr_field) or "").upper()
        result["owner_mailing_differs"] = "Yes" if ml1.upper() not in site else "No"

    # ── Year built ────────────────────────────────────────────────────────────
    yr = _pick_numeric(attrs, _YR_BUILT_FIELDS)
    if yr and 1800 < yr <= 2030:
        result["year_built"] = int(yr)

    # ── Living area (sq ft) ───────────────────────────────────────────────────
    sqft = _pick_numeric(attrs, _SQFT_FIELDS)
    if sqft and sqft > 0:
        result["sqft"] = int(sqft)

    # ── Lot size — prefer acres; fall back to sq ft and convert ──────────────
    lot_acres = _pick_numeric(attrs, _LOT_ACRES_FIELDS)
    if lot_acres and lot_acres > 0:
        result["lot_size"] = f"{lot_acres:.2f} ac"
    else:
        lot_sf = _pick_numeric(attrs, _LOT_SQFT_FIELDS)
        if lot_sf and lot_sf > 500:
            result["lot_size"] = f"{lot_sf / 43560:.2f} ac"
        elif lot_sf and lot_sf > 0:
            result["lot_size"] = f"{lot_sf:.2f} ac"

    # ── Assessed / market value ───────────────────────────────────────────────
    av = _pick_numeric(attrs, _ASSESSED_FIELDS)
    if av and av > 0:
        result["assessed_value"] = int(av)
    else:
        land = _pick_numeric(attrs, ["LAND_VALUE", "LAND_ASMT", "LAND_ASD"])
        impr = _pick_numeric(attrs, ["IMPR_VALUE", "IMPROVEMENT_VALUE",
                                     "IMP_VALUE", "BLDG_VALUE", "BUILDING_VALUE"])
        total = (land or 0) + (impr or 0)
        if total > 0:
            result["assessed_value"] = int(total)

    # ── Last sale date ────────────────────────────────────────────────────────
    attrs_up = {k.upper(): v for k, v in attrs.items()}
    for f in _SALE_DATE_FIELDS:
        raw_date = attrs_up.get(f.upper())
        if raw_date is not None:
            parsed = _parse_gis_date(raw_date)
            if parsed:
                result["last_sale_date"] = parsed
                break

    # ── Last sale price ───────────────────────────────────────────────────────
    sp = _pick_numeric(attrs, _SALE_PRC_FIELDS)
    if sp and sp > 0:
        result["last_sale_price"] = int(sp)

    # ── Beds / baths ──────────────────────────────────────────────────────────
    beds = _pick_numeric(attrs, _BEDS_FIELDS)
    if beds and beds > 0:
        result["beds"] = int(beds)

    baths = _pick_numeric(attrs, _BATHS_FIELDS)
    if baths and baths > 0:
        result["baths"] = round(float(baths), 1)

    return result


def _gis_query(url: str, addr_field: str, fragment_sql: str,
               house_num: str, cfg: dict | None) -> dict | None:
    """
    Fire one ArcGIS REST query and return parsed attrs dict, or None on miss.
    Internal helper for gis_full_lookup().
    """
    where = f"UPPER({addr_field}) LIKE '%{fragment_sql.upper()}%'"
    try:
        resp = requests.get(
            url,
            params={
                "where":             where,
                "outFields":         "*",
                "returnGeometry":    "false",
                "resultRecordCount": 3,
                "f":                 "json",
            },
            headers=HEADERS,
            timeout=12,
        )
        if resp.status_code != 200:
            return None
        features = resp.json().get("features") or []
        if not features:
            return None
        # Pick the feature whose address field contains the house number
        best = None
        for feat in features:
            fa = str((feat.get("attributes") or {}).get(addr_field) or "").upper()
            if house_num in fa:
                best = feat.get("attributes") or {}
                break
        if best is None:
            best = features[0].get("attributes") or {}
        return _parse_full_attrs(best, addr_field, cfg)
    except requests.exceptions.ConnectionError:
        return None
    except Exception as exc:
        log.debug(f"  _gis_query({addr_field}@{url[:60]}): {exc}")
        return None


def gis_full_lookup(address: str, county_key: str) -> dict:
    """
    Single ArcGIS call that returns BOTH owner info AND property detail fields.

    Strategy:
      1. Try VGIN statewide parcel API (covers all 12 counties in one endpoint).
         Attempts several common address field names until a non-empty result is
         returned.
      2. Fall back to the county-specific endpoint in GIS_REGISTRY if VGIN
         returns no match.

    Returns a merged dict with all available keys:
      Owner:    owner_name, owner_mailing_address, owner_mailing_differs
      Property: year_built, sqft, lot_size, assessed_value, last_sale_date,
                last_sale_price, beds, baths
    Returns {} on total failure.
    """
    tokens = address.strip().split()
    if not tokens:
        return {}
    fragment = f"{tokens[0]} {tokens[1]}" if len(tokens) >= 2 else tokens[0]
    fragment_sql = fragment.replace("'", "''")
    house_num = tokens[0].upper()

    # 1. Try VGIN statewide
    for addr_field in _VGIN_ADDR_FIELDS:
        result = _gis_query(VGIN_URL, addr_field, fragment_sql, house_num, None)
        if result:
            log.debug(f"  gis_full_lookup: VGIN hit (field={addr_field}) for {address!r}")
            return result

    # 2. Fall back to county-specific endpoint
    key = county_key.lower().replace(" city", "").replace(" county", "").strip()
    cfg = GIS_REGISTRY.get(key)
    if not cfg:
        log.debug(f"  gis_full_lookup: no registry entry for county '{county_key}'")
        return {}
    result = _gis_query(cfg["url"], cfg["addr_field"], fragment_sql, house_num, cfg)
    if result:
        log.debug(f"  gis_full_lookup: county GIS hit ({county_key}) for {address!r}")
        return result or {}
    return {}


def get_redfin_estimate(address: str, zip_code: str) -> dict:
    """
    Best-effort Redfin property lookup via their unofficial search API.

    Returns a subset of these keys (only those found):
        beds, baths, sqft, year_built, redfin_estimate (current value)

    Returns {} if Redfin blocks the request or can't find the address.
    This is a supplemental source — never required for pipeline success.
    """
    search_q = f"{address}, VA {zip_code}".strip() if zip_code else f"{address}, VA"
    try:
        resp = requests.get(
            "https://www.redfin.com/stingray/api/gis",
            params={
                "al":       "1",
                "num_homes": "1",
                "q":        search_q,
                "sf":       "1,2,3,5,6,10,12",
                "start":    "0",
                "status":   "9",
                "uipt":     "1,2,3,4,5,6,7,8",
                "v":        "8",
            },
            headers={
                **HEADERS,
                "Referer": "https://www.redfin.com/",
                "Accept":  "application/json",
            },
            timeout=15,
        )
        text = resp.text
        # Redfin prepends "{}&&" to prevent XSS response-hijacking
        if text.startswith("{}&&"):
            text = text[4:]
        data   = json.loads(text)
        homes  = data.get("payload", {}).get("homes", [])
        if not homes:
            return {}

        h      = homes[0]
        result: dict = {}

        # Nested value objects: {"value": 3, "displayLevel": 1}
        def _rv(key):
            v = h.get(key)
            if isinstance(v, dict):
                return v.get("value")
            return v

        beds  = _rv("beds")
        baths = _rv("baths")
        sqft  = _rv("sqFt") or _rv("totalSqFt")
        yr    = _rv("yearBuilt")
        est   = _rv("price") or _rv("listingPrice") or _rv("lastSalePrice")

        if isinstance(beds,  (int, float)) and beds  > 0: result["beds"]             = int(beds)
        if isinstance(baths, (int, float)) and baths > 0: result["baths"]            = round(float(baths), 1)
        if isinstance(sqft,  (int, float)) and sqft  > 0: result["sqft"]             = int(sqft)
        if isinstance(yr,    (int, float)) and yr   > 1800: result["year_built"]     = int(yr)
        if isinstance(est,   (int, float)) and est   > 0: result["redfin_estimate"]  = int(est)

        log.debug(f"  Redfin {address!r}: {result}")
        return result

    except Exception as exc:
        log.debug(f"  get_redfin_estimate({address!r}): {exc}")
        return {}


def zip_to_county(zip_code: str) -> str:
    """
    Resolve a 5-digit Virginia ZIP code to a county display name.

    Strategy 1 — hardcoded map of every ZIP in our 12 target counties.
                  Instant, no network, handles the most common cases.
    Strategy 2 — zippopotam.us free API → place name → city_to_county().
                  Catches ZIPs not in the hardcoded map.

    Returns a county display name (e.g. "Stafford") or "" on failure.
    ZIP codes that cross county lines are assigned to the dominant county.
    """
    zip_code = zip_code.strip().split("-")[0]   # strip ZIP+4 suffix
    if not re.match(r"^\d{5}$", zip_code):
        return ""

    # ── Hardcoded map for all known ZIPs in our 12-county target area ─────────
    # Source: USPS ZIP Code lookup + Virginia county GIS boundary data.
    # ZIPs on county borders are assigned to the county containing most addresses.
    ZIP_COUNTY: dict[str, str] = {
        # ── Fredericksburg City ───────────────────────────────────────────────
        "22401": "Fredericksburg City",
        "22402": "Fredericksburg City",
        "22403": "Fredericksburg City",
        "22404": "Fredericksburg City",
        # ── Stafford ──────────────────────────────────────────────────────────
        "22405": "Stafford",   # Falmouth
        "22406": "Stafford",   # Stafford (south)
        "22430": "Stafford",   # Aquia Harbour
        "22463": "Stafford",   # Garrisonville
        "22471": "Stafford",
        "22476": "Stafford",
        "22485": "Stafford",   # King George border area — Stafford majority
        "22554": "Stafford",   # Stafford (main)
        "22555": "Stafford",
        "22556": "Stafford",   # Stafford (north)
        "22558": "Stafford",
        # ── Spotsylvania ──────────────────────────────────────────────────────
        "22407": "Spotsylvania",  # border with Stafford — Spotsylvania majority
        "22408": "Spotsylvania",  # border with Stafford — Spotsylvania majority
        "22501": "Spotsylvania",  # Locust Grove / Lake of the Woods
        "22508": "Spotsylvania",  # Locust Grove
        "22551": "Spotsylvania",  # Spotsylvania CH
        "22553": "Spotsylvania",  # Spotsylvania
        # ── Caroline ──────────────────────────────────────────────────────────
        "22427": "Caroline",   # Bowling Green adjacent
        "22509": "Caroline",   # Milford
        "22529": "Caroline",   # Olney
        "22534": "Caroline",   # Pendleton
        "22535": "Caroline",   # Port Royal
        "22542": "Caroline",   # Ruther Glen
        "22546": "Caroline",   # Ruther Glen / Ladysmith
        "22548": "Caroline",   # Woodford
        "22565": "Caroline",   # Bowling Green
        "22567": "Caroline",   # Woodford
        # ── King George ───────────────────────────────────────────────────────
        "22443": "King George",  # Colonial Beach area
        "22448": "King George",  # Dahlgren
        "22460": "King George",
        "22469": "King George",  # Hague
        "22472": "King George",
        "22473": "King George",  # Reedville area
        "22476": "King George",
        "22480": "King George",
        "22482": "King George",
        "22488": "King George",
        # ── Fauquier ──────────────────────────────────────────────────────────
        "20118": "Fauquier",   # Upperville
        "20119": "Fauquier",   # Catlett
        "20130": "Fauquier",   # Paris
        "20137": "Fauquier",   # Broad Run
        "20138": "Fauquier",   # Calverton
        "20139": "Fauquier",   # Casanova
        "20140": "Fauquier",   # Rectortown
        "20141": "Fauquier",   # Upperville / Round Hill border
        "20143": "Fauquier",   # Catharpin border — Fauquier majority
        "20144": "Fauquier",   # Delaplane
        "20184": "Fauquier",   # Flint Hill
        "20185": "Fauquier",   # Hume
        "20186": "Fauquier",   # Warrenton
        "20187": "Fauquier",   # Warrenton (east)
        "20188": "Fauquier",   # Warrenton (north)
        "20189": "Fauquier",   # Warrenton (PO box)
        "22736": "Fauquier",   # Lignum / Culpeper border — Fauquier majority
        # ── Culpeper ──────────────────────────────────────────────────────────
        "22701": "Culpeper",
        "22702": "Culpeper",
        "22711": "Culpeper",   # Brightwood
        "22712": "Culpeper",   # Bealeton border — mostly Culpeper
        "22713": "Culpeper",   # Boston
        "22714": "Culpeper",   # Brandy Station
        "22715": "Culpeper",   # Brightwood
        "22716": "Culpeper",   # Castleton
        "22718": "Culpeper",   # Elk Run Church
        "22719": "Culpeper",   # Etlan
        "22720": "Culpeper",   # Midland / Fauquier border — Culpeper majority
        "22721": "Culpeper",   # Mitchells
        "22722": "Culpeper",   # Mitchells
        "22724": "Culpeper",   # Rixeyville
        "22725": "Culpeper",   # Leon
        "22726": "Culpeper",   # Lignum
        "22727": "Culpeper",   # Madison border
        "22728": "Culpeper",   # Midland
        "22729": "Culpeper",   # Mitchells
        "22730": "Culpeper",   # Oakwood
        "22731": "Culpeper",   # Radiant
        "22732": "Culpeper",   # Rapidan
        "22733": "Culpeper",   # Rapidan
        "22734": "Culpeper",   # Remington / Fauquier border — Culpeper majority
        "22735": "Culpeper",   # Reva
        "22737": "Culpeper",   # Rixeyville
        "22738": "Culpeper",   # Rochelle
        "22739": "Culpeper",   # Somerville
        "22740": "Culpeper",   # Sperryville / Rappahannock border
        "22741": "Culpeper",   # Stevensburg
        "22742": "Culpeper",   # Sumerduck
        "22743": "Culpeper",   # Syria / Madison border
        # ── Hanover ───────────────────────────────────────────────────────────
        "23005": "Hanover",    # Ashland
        "23047": "Hanover",    # Hanover CH
        "23058": "Hanover",    # Glen Allen border
        "23059": "Hanover",    # Glen Allen / Henrico border — Hanover majority
        "23069": "Hanover",    # Hanover
        "23111": "Hanover",    # Mechanicsville
        "23116": "Hanover",    # Mechanicsville (north)
        "23146": "Hanover",    # Rockville
        "23162": "Hanover",    # Studley
        "23192": "Hanover",    # Montpelier
        # ── Henrico ───────────────────────────────────────────────────────────
        "23060": "Henrico",    # Glen Allen
        "23150": "Henrico",    # Sandston
        "23173": "Henrico",    # University of Richmond
        "23222": "Henrico",    # Highland Park (Henrico section)
        "23223": "Henrico",    # Sandston / Henrico east
        "23226": "Henrico",    # Richmond west / Henrico
        "23227": "Henrico",    # Highland Springs
        "23228": "Henrico",    # Henrico north
        "23229": "Henrico",    # Henrico west
        "23230": "Henrico",    # Henrico central
        "23231": "Henrico",    # Henrico east (Varina)
        "23233": "Henrico",    # Short Pump / West End
        "23234": "Henrico",    # Henrico south
        "23238": "Henrico",    # Henrico (Tuckahoe)
        "23250": "Henrico",    # Richmond International Airport
        # ── Chesterfield ──────────────────────────────────────────────────────
        "23112": "Chesterfield",  # Midlothian
        "23113": "Chesterfield",  # Midlothian (west)
        "23114": "Chesterfield",  # Midlothian
        "23120": "Chesterfield",  # Moseley
        "23236": "Chesterfield",  # Chesterfield north
        "23237": "Chesterfield",  # Chesterfield (Chester area)
        "23832": "Chesterfield",  # Chesterfield CH
        "23833": "Chesterfield",  # Church Road
        "23834": "Chesterfield",  # Colonial Heights border — Chesterfield majority
        "23836": "Chesterfield",  # Chester
        "23838": "Chesterfield",  # Chesterfield (Matoaca)
        # ── Louisa ────────────────────────────────────────────────────────────
        "23022": "Louisa",     # Bumpass
        "23063": "Louisa",     # Gum Spring
        "23065": "Louisa",     # Goochland border — Louisa majority
        "23093": "Louisa",     # Louisa CH
        "23117": "Louisa",     # Mineral
        "23119": "Louisa",     # Montpelier area
        "23160": "Louisa",     # Sandy Hook
        # ── Richmond City ─────────────────────────────────────────────────────
        "23218": "Richmond City",
        "23219": "Richmond City",
        "23220": "Richmond City",
        "23221": "Richmond City",
        "23224": "Richmond City",
        "23225": "Richmond City",
        "23232": "Richmond City",
        "23240": "Richmond City",
        "23241": "Richmond City",
        "23249": "Richmond City",
        "23260": "Richmond City",
        "23261": "Richmond City",
        "23269": "Richmond City",
        "23284": "Richmond City",
        "23285": "Richmond City",
        "23286": "Richmond City",
        "23298": "Richmond City",
    }

    if zip_code in ZIP_COUNTY:
        return ZIP_COUNTY[zip_code]

    # ── Strategy 2: zippopotam.us — free, no key, returns place name ──────────
    try:
        resp = requests.get(
            f"https://api.zippopotam.us/us/{zip_code}",
            headers={"User-Agent": "ForeclosureFinder/1.0 (research)"},
            timeout=10,
        )
        if resp.status_code == 200:
            for place in resp.json().get("places", []):
                result = city_to_county(place.get("place name", ""))
                if result and result.lower() != "unknown":
                    return result
    except Exception as exc:
        log.debug(f"  zip_to_county({zip_code}): zippopotam error: {exc}")

    return ""


def geocode_county(address: str) -> str:
    """
    US Census Bureau Geocoder — free, no API key, .gov domain.
    Returns the bare county name ("Stafford") or "" on failure.

    Docs: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.pdf
    """
    try:
        resp = requests.get(
            "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
            params={
                "address":   f"{address}, VA",
                "benchmark": "Public_AR_Current",
                "vintage":   "Current_Current",
                "layers":    "10",   # county layer
                "format":    "json",
            },
            headers={"User-Agent": "ForeclosureFinder/1.0 (research)"},
            timeout=15,
        )
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if not matches:
            return ""
        counties = matches[0].get("geographies", {}).get("Counties", [])
        if not counties:
            return ""
        # API returns e.g. "Stafford County" — strip the suffix
        raw = re.sub(r"\s+County$", "", counties[0].get("NAME", ""), flags=re.I).strip()
        return raw
    except Exception as exc:
        log.debug(f"  geocode_county({address!r}): {exc}")
        return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> None:
    creds_path = find_creds_file()
    if not creds_path:
        log.error("No credentials file found — see sheets_sync.py setup.")
        return

    creds       = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client      = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)
    sheet       = spreadsheet.get_worksheet(0)

    log.info("Reading sheet…")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        log.info("Sheet has no data rows — nothing to backfill.")
        return

    headers = [h.strip() for h in all_values[0]]
    col_0   = {h: i     for i, h in enumerate(headers)}   # 0-based for list indexing
    col_1   = {h: i + 1 for i, h in enumerate(headers)}   # 1-based for gspread.Cell
    data    = all_values[1:]                               # rows 2..N (0-based in this list)

    log.info(f"  {len(data)} data rows loaded")

    updates: list[gspread.Cell] = []

    def val(row: list, field: str) -> str:
        """Return the stripped cell value for a field, or ''."""
        idx = col_0.get(field, -1)
        return row[idx].strip() if 0 <= idx < len(row) else ""

    def queue(row_0idx: int, field: str, value: str) -> None:
        """Queue a cell update.  row_0idx is 0-based index into `data`."""
        c = col_1.get(field)
        if c and value:
            updates.append(gspread.Cell(row_0idx + 2, c, value))

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1 — F_Sale_Date / F_Sale_Time
    # Strategy: re-fetch the listing's source notice URL and re-parse the text.
    # Only PNV and Column.us notices carry sale date/time in their body text.
    # ─────────────────────────────────────────────────────────────────────────
    p1 = [
        (i, row) for i, row in enumerate(data)
        if not val(row, "F_Sale_Date")
        and re.search(r"publicnoticevirginia|column\.us", val(row, "Listing_URL"), re.I)
    ]
    log.info(f"Pass 1 — F_Sale_Date/Time: {len(p1)} candidate row(s)")
    filled_p1 = 0
    for i, row in p1:
        url  = val(row, "Listing_URL")
        text = fetch_notice_text(url)
        if not text:
            continue
        sale_date, sale_time = parse_sale_datetime(text)
        if sale_date:
            queue(i, "F_Sale_Date", sale_date)
            filled_p1 += 1
        if sale_time:
            queue(i, "F_Sale_Time", sale_time)
        if sale_date:
            log.info(f"  row {i+2}: F_Sale_Date={sale_date}  F_Sale_Time={sale_time or '—'}")
        sleep(0.6)   # polite rate limit
    log.info(f"  → filled {filled_p1}/{len(p1)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 1b — F_Sale_Date / F_Sale_Time  (secondary sources)
    # For rows STILL missing a sale date after Pass 1, try:
    #   • Auction.com listing re-fetch  — parses current auction_date from JSON
    #   • PNV address search            — keyword search by house# + street,
    #                                     no county checkboxes (avoids ParseInt32
    #                                     crash), catches notices the county-
    #                                     filtered scraper may have missed.
    # REO / bank-owned rows are skipped — they have no trustee auction date.
    # ─────────────────────────────────────────────────────────────────────────
    # Build a set of row 0-indices that Pass 1 already queued so we don't
    # redundantly re-fetch them.
    p1_filled_rows: set[int] = {
        c.row - 2                        # Cell.row is 1-based; data list is 0-based
        for c in updates
        if c.col == col_1.get("F_Sale_Date")
    }
    p1b = [
        (i, row) for i, row in enumerate(data)
        if not val(row, "F_Sale_Date")
        and i not in p1_filled_rows
        and val(row, "Status") != "REO / Bank Owned"
        and val(row, "Address")
    ]
    log.info(f"Pass 1b — F_Sale_Date/Time (secondary sources): {len(p1b)} candidate row(s)")
    filled_p1b_auction = filled_p1b_pnv = 0

    for i, row in p1b:
        url     = val(row, "Listing_URL")
        address = val(row, "Address")
        sale_date = ""
        sale_time = ""

        # ── Auction.com re-fetch ──────────────────────────────────────────────
        if url and "auction.com" in url.lower():
            sale_date, sale_time = get_auction_com_date(url)
            if sale_date:
                filled_p1b_auction += 1
                log.info(f"  row {i+2}: F_Sale_Date={sale_date}  F_Sale_Time={sale_time or '—'}  (Auction.com)")
            sleep(0.5)

        # ── PNV address search ────────────────────────────────────────────────
        if not sale_date and address:
            sale_date, sale_time = search_pnv_by_address(address)
            if sale_date:
                filled_p1b_pnv += 1
                log.info(f"  row {i+2}: F_Sale_Date={sale_date}  F_Sale_Time={sale_time or '—'}  (PNV search)")
            sleep(0.5)

        if sale_date:
            queue(i, "F_Sale_Date", sale_date)
        if sale_time:
            queue(i, "F_Sale_Time", sale_time)

    total_p1b = filled_p1b_auction + filled_p1b_pnv
    log.info(
        f"  → Auction.com: {filled_p1b_auction}  "
        f"PNV search: {filled_p1b_pnv}  "
        f"total: {total_p1b}/{len(p1b)}"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 2 — County
    # Strategy A: city_to_county() from the City column.
    # Strategy B: parse city from the Address field, retry city_to_county().
    # Strategy C: ZIP code → county (hardcoded map, then zippopotam.us API).
    # Strategy D: US Census Geocoder (free, .gov, no key) — last resort.
    # ─────────────────────────────────────────────────────────────────────────
    p2 = [(i, row) for i, row in enumerate(data) if not val(row, "County")]
    log.info(f"Pass 2 — County: {len(p2)} candidate row(s)")
    filled_p2 = 0
    for i, row in p2:
        city    = val(row, "City")
        address = val(row, "Address")
        county  = ""

        # Strategy A: city_to_county from the City column
        if city:
            result = city_to_county(city)
            if result and result.lower() != "unknown":
                county = result

        # Strategy B: parse city from the address string
        if not county and address:
            m = re.search(r",\s*([A-Za-z ]+),\s*VA\b", address, re.I)
            if m:
                parsed_city = m.group(1).strip()
                result = city_to_county(parsed_city)
                if result and result.lower() != "unknown":
                    county = result

        # Strategy C: ZIP → county (hardcoded map, then zippopotam.us)
        # Use the ZIP column first; fall back to extracting it from the address.
        if not county:
            zip_val = val(row, "ZIP")
            if not zip_val:
                zm = re.search(r"\b(2[0-9]{4})\b", address)  # VA ZIPs start with 2
                if zm:
                    zip_val = zm.group(1)
            if zip_val:
                county = zip_to_county(zip_val)
                if county:
                    log.info(f"  row {i+2}: County={county} (via ZIP {zip_val})")

        # Strategy D: Census geocoder (1 req/sec rate limit — sleep below)
        if not county and address:
            raw = geocode_county(address)
            if raw:
                raw_l = raw.lower()
                for k in TARGET_COUNTIES:
                    if k in raw_l or raw_l in k:
                        county = county_display(k)
                        break
            sleep(1.0)   # Census geocoder rate-limited to ~1 req/sec

        if county:
            queue(i, "County", county)
            filled_p2 += 1
            log.info(f"  row {i+2}: County={county}")
        else:
            log.debug(f"  row {i+2}: County unknown (addr={address!r})")

    log.info(f"  → filled {filled_p2}/{len(p2)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 3 — State
    # Always "VA" — just fill any cell that's blank.
    # ─────────────────────────────────────────────────────────────────────────
    p3 = [(i, row) for i, row in enumerate(data) if not val(row, "State")]
    log.info(f"Pass 3 — State: {len(p3)} row(s) → filling 'VA'")
    for i, row in p3:
        queue(i, "State", "VA")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 4 — City
    # Strategy: parse from the address field (NUMBER STREET, CITY, VA ZIP).
    # ─────────────────────────────────────────────────────────────────────────
    p4 = [(i, row) for i, row in enumerate(data) if not val(row, "City")]
    log.info(f"Pass 4 — City: {len(p4)} candidate row(s)")
    filled_p4 = 0
    for i, row in p4:
        address = val(row, "Address")
        m = re.search(r",\s*([A-Za-z][A-Za-z ]+?),\s*VA\b", address, re.I)
        if m:
            city = m.group(1).strip().title()
            if city:
                queue(i, "City", city)
                filled_p4 += 1
    log.info(f"  → filled {filled_p4}/{len(p4)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 5 — ZIP
    # Strategy: extract 5-digit code from the Address field.
    # ─────────────────────────────────────────────────────────────────────────
    p5 = [(i, row) for i, row in enumerate(data) if not val(row, "ZIP")]
    log.info(f"Pass 5 — ZIP: {len(p5)} candidate row(s)")
    filled_p5 = 0
    for i, row in p5:
        address = val(row, "Address")
        m = re.search(r"\b(2[0-9]{4})\b", address)   # VA ZIPs start with 2
        if m:
            queue(i, "ZIP", m.group(1))
            filled_p5 += 1
    log.info(f"  → filled {filled_p5}/{len(p5)}")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 6 — Owner + Property Details (combined GIS call)
    #
    # One call per property returns BOTH owner info AND all property detail
    # fields.  Previously these were two separate passes (6 + 7), each making
    # a separate ArcGIS request.  Merging them halves API traffic.
    #
    # Source priority:
    #   1. VGIN statewide parcel API — single endpoint for all 12 counties.
    #      Tried first; eliminates per-county URL routing when it matches.
    #   2. County-specific ArcGIS endpoint (GIS_REGISTRY fallback).
    #   3. Redfin unofficial API — only called when GIS is missing beds/sqft
    #      OR assessed value (i.e. rural/unmapped parcels), which is <20% of rows.
    #
    # Candidate rows: any row that is missing Owner_Name OR any raw GIS field.
    # Rows that already have all GIS fields but are missing only DERIVED fields
    # (Rough_Equity_Est, Est_Profit_Potential, Years_Since_Last_Sale) are handled
    # in the fast, API-free Pass 7 below.
    # ─────────────────────────────────────────────────────────────────────────
    RAW_GIS_FIELDS = [
        "Year_Built", "Beds_Baths_Sqft", "Lot_Size",
        "Last_Sold_Date", "Last_Sold_Price", "Current_Est_Value",
    ]
    p6 = [
        (i, row) for i, row in enumerate(data)
        if val(row, "Address") and val(row, "County")
        and (
            not val(row, "Owner_Name")
            or any(not val(row, f) for f in RAW_GIS_FIELDS)
        )
    ]
    log.info(f"Pass 6 — GIS Full Lookup (owner + property): {len(p6)} candidate row(s)")
    filled_p6_owner = filled_p6_gis = filled_p6_redfin = filled_p6_calc = 0

    for i, row in p6:
        address    = val(row, "Address")
        county_dn  = val(row, "County")
        zip_code   = val(row, "ZIP")
        county_key = DISPLAY_TO_KEY.get(county_dn)
        if not county_key:
            # Fallback: derive county from City field (handles "Unknown" rows
            # from Auction.com/Column.us where county couldn't be parsed at
            # scrape time but the city is known).
            city = val(row, "City")
            if city:
                derived = city_to_county(city)
                county_key = DISPLAY_TO_KEY.get(derived)
                if county_key:
                    log.debug(f"  row {i+2}: county '{county_dn}' → resolved via city '{city}' → '{derived}'")
                    # Write the resolved county back so future passes don't repeat this
                    queue(i, "County", derived)
        if not county_key:
            log.debug(f"  row {i+2}: county '{county_dn}' not in registry — skipping GIS")
            continue

        gis = gis_full_lookup(address, county_key)
        sleep(0.25)   # VGIN handles higher throughput than county endpoints

        # ── Owner fields ──────────────────────────────────────────────────────
        if gis.get("owner_name") and not val(row, "Owner_Name"):
            queue(i, "Owner_Name",                          gis["owner_name"])
            queue(i, "Owner_Mailing_Address",               gis.get("owner_mailing_address", ""))
            queue(i, "Owner_Mailing_Differs_From_Property", gis.get("owner_mailing_differs", ""))
            filled_p6_owner += 1
            log.info(f"  row {i+2}: Owner={gis['owner_name']}")

        # ── Redfin fallback — only when GIS missing beds/sqft or value ────────
        needs_bbs = not val(row, "Beds_Baths_Sqft") and ("beds" not in gis or "sqft" not in gis)
        needs_est = not val(row, "Current_Est_Value") and "assessed_value" not in gis
        rf: dict = {}
        if needs_bbs or needs_est:
            rf = get_redfin_estimate(address, zip_code)
            if rf:
                filled_p6_redfin += 1
                log.info(f"  row {i+2}: Redfin supplement → {list(rf.keys())}")
            sleep(1.0)

        # ── Merge: GIS primary, Redfin fills remaining gaps ───────────────────
        year_built      = gis.get("year_built")     or rf.get("year_built")
        sqft            = gis.get("sqft")           or rf.get("sqft")
        lot_size        = gis.get("lot_size", "")
        assessed_value  = gis.get("assessed_value")
        redfin_est      = rf.get("redfin_estimate")
        est_val         = redfin_est or assessed_value
        beds            = gis.get("beds")           or rf.get("beds")
        baths           = gis.get("baths")          or rf.get("baths")
        last_sale_date  = gis.get("last_sale_date", "")
        last_sale_price = gis.get("last_sale_price")

        if gis:
            filled_p6_gis += 1

        # ── Write property fields ─────────────────────────────────────────────
        if year_built and not val(row, "Year_Built"):
            queue(i, "Year_Built", str(year_built))

        if not val(row, "Beds_Baths_Sqft"):
            parts = []
            if beds:  parts.append(f"{beds} bd")
            if baths:
                b_str = f"{int(baths)} ba" if float(baths) == int(baths) else f"{baths} ba"
                parts.append(b_str)
            if sqft:  parts.append(f"{sqft:,} sqft")
            bbs = " / ".join(parts)
            if bbs:
                queue(i, "Beds_Baths_Sqft", bbs)

        if lot_size and not val(row, "Lot_Size"):
            queue(i, "Lot_Size", lot_size)

        if last_sale_date and not val(row, "Last_Sold_Date"):
            queue(i, "Last_Sold_Date", last_sale_date)
        if last_sale_price and not val(row, "Last_Sold_Price"):
            queue(i, "Last_Sold_Price", f"${last_sale_price:,}")

        if est_val and not val(row, "Current_Est_Value"):
            label = "(Est.)" if redfin_est else "(Assessed)"
            queue(i, "Current_Est_Value", f"${int(est_val):,} {label}")

        # ── Derived calculations ──────────────────────────────────────────────
        listing_raw = re.sub(r"[^0-9]", "", val(row, "Listing_Price"))
        try:
            listing_price = int(listing_raw) if listing_raw else 0
        except ValueError:
            listing_price = 0

        if not est_val:
            ev_raw = re.sub(r"[^0-9]", "", val(row, "Current_Est_Value"))
            try:
                est_val = int(ev_raw) if ev_raw else 0
            except ValueError:
                est_val = 0

        if est_val and est_val > 0 and listing_price > 0:
            if not val(row, "Rough_Equity_Est"):
                equity = int(est_val) - listing_price
                queue(i, "Rough_Equity_Est",
                      f"+${equity:,}" if equity >= 0 else f"-${abs(equity):,}")
                filled_p6_calc += 1
            if not val(row, "Est_Profit_Potential"):
                profit = int(est_val * 0.70) - listing_price
                queue(i, "Est_Profit_Potential",
                      f"+${profit:,}" if profit >= 0 else f"-${abs(profit):,}")

        sale_date_for_yrs = last_sale_date or val(row, "Last_Sold_Date")
        if sale_date_for_yrs and not val(row, "Years_Since_Last_Sale"):
            try:
                sale_yr = int(sale_date_for_yrs[:4])
                yrs = date.today().year - sale_yr
                if 0 <= yrs <= 100:
                    queue(i, "Years_Since_Last_Sale", str(yrs))
            except (ValueError, IndexError):
                pass

    log.info(
        f"  → GIS hits: {filled_p6_gis}  owner filled: {filled_p6_owner}  "
        f"Redfin supplements: {filled_p6_redfin}  derived calcs: {filled_p6_calc}  "
        f"rows processed: {len(p6)}"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 7 — Derived fields (no API calls)
    #
    # Rows that skipped Pass 6 because their raw GIS fields were already filled
    # may still be missing calculated fields if Listing_Price wasn't available
    # at the time of the last GIS run.  This pass is purely computational.
    # ─────────────────────────────────────────────────────────────────────────
    p7 = [
        (i, row) for i, row in enumerate(data)
        if val(row, "Current_Est_Value") and val(row, "Listing_Price")
        and (
            not val(row, "Rough_Equity_Est")
            or not val(row, "Est_Profit_Potential")
        )
    ]
    p7b = [
        (i, row) for i, row in enumerate(data)
        if val(row, "Last_Sold_Date") and not val(row, "Years_Since_Last_Sale")
    ]
    log.info(
        f"Pass 7 — Derived fields (no API): "
        f"{len(p7)} equity/profit row(s), {len(p7b)} years-since-sale row(s)"
    )
    filled_p7 = 0

    for i, row in p7:
        listing_raw = re.sub(r"[^0-9]", "", val(row, "Listing_Price"))
        ev_raw      = re.sub(r"[^0-9]", "", val(row, "Current_Est_Value"))
        try:
            listing_price = int(listing_raw) if listing_raw else 0
            est_val       = int(ev_raw)       if ev_raw      else 0
        except ValueError:
            continue
        if listing_price <= 0 or est_val <= 0:
            continue
        if not val(row, "Rough_Equity_Est"):
            equity = est_val - listing_price
            queue(i, "Rough_Equity_Est",
                  f"+${equity:,}" if equity >= 0 else f"-${abs(equity):,}")
            filled_p7 += 1
        if not val(row, "Est_Profit_Potential"):
            profit = int(est_val * 0.70) - listing_price
            queue(i, "Est_Profit_Potential",
                  f"+${profit:,}" if profit >= 0 else f"-${abs(profit):,}")

    for i, row in p7b:
        try:
            sale_yr = int(val(row, "Last_Sold_Date")[:4])
            yrs = date.today().year - sale_yr
            if 0 <= yrs <= 100:
                queue(i, "Years_Since_Last_Sale", str(yrs))
        except (ValueError, IndexError):
            pass

    log.info(f"  → filled {filled_p7} equity rows, {len(p7b)} years-since-sale rows")

    # ─────────────────────────────────────────────────────────────────────────
    # Pass 8 — Column.us individual notice URLs
    #
    # sheets_sync.py force-updates Listing_URL for any row whose address still
    # appears in the current scraper output.  Pass 8 handles the remaining rows
    # — ones that are no longer scraped but still show the generic search-page
    # URL instead of an individual notice link.
    #
    # Strategy: open Column.us once with Playwright, load all cards, then for
    # each candidate row search the rendered DOM for a notice link whose card
    # text contains the property's house number and street name.
    #
    # Requires Playwright.  Skipped silently if not installed.
    # ─────────────────────────────────────────────────────────────────────────
    COLUMN_US_SEARCH_URL = (
        "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale"
    )
    p8 = [
        (i, row) for i, row in enumerate(data)
        if val(row, "Address")
        and (
            val(row, "Listing_URL") == COLUMN_US_SEARCH_URL
            or (
                not val(row, "Listing_URL")
                and "column_us" in val(row, "Notes").lower()
            )
        )
    ]
    log.info(f"Pass 8 — Column.us notice URLs: {len(p8)} candidate row(s)")

    if p8:
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=HEADERS.get("User-Agent", "Mozilla/5.0")
                )
                page = context.new_page()

                log.info("  Pass 8: loading Column.us search page…")
                page.goto(COLUMN_US_SEARCH_URL, wait_until="load", timeout=40_000)
                page.wait_for_timeout(8_000)

                # Expand all cards with "Load more" clicks
                while True:
                    try:
                        btn = page.query_selector('button:has-text("Load more")')
                        if btn and btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(2_000)
                        else:
                            break
                    except Exception:
                        break

                # JavaScript that searches the loaded DOM for a notice link
                # whose ancestor card text contains both the house number and
                # the first street word.  Arguments are passed as a list so
                # no string-injection issues with special characters.
                FIND_NOTICE_JS = """
                    ([houseNum, streetWord]) => {
                        const links = document.querySelectorAll('a[href]');
                        for (const a of links) {
                            if (!/\\/notice[s]?\\/[\\w-]+/i.test(a.href)) continue;
                            let el = a;
                            for (let j = 0; j < 20; j++) {
                                if (!el.parentElement) break;
                                el = el.parentElement;
                                const txt = (el.innerText || '').toUpperCase();
                                if (txt.includes(houseNum) && txt.includes(streetWord)) {
                                    return a.href;
                                }
                            }
                        }
                        return null;
                    }
                """

                filled_p8 = 0
                for i, row in p8:
                    address = val(row, "Address")
                    tokens  = address.strip().upper().split()
                    if len(tokens) < 2:
                        continue
                    house_num   = tokens[0]
                    street_word = tokens[1]

                    try:
                        notice_url = page.evaluate(
                            FIND_NOTICE_JS, [house_num, street_word]
                        )
                        if notice_url:
                            queue(i, "Listing_URL", notice_url)
                            filled_p8 += 1
                            log.info(f"  row {i+2}: Listing_URL={notice_url}")
                        else:
                            log.debug(
                                f"  row {i+2}: no Column.us notice found "
                                f"for {address!r} — may have expired"
                            )
                    except Exception as exc:
                        log.debug(f"  row {i+2}: Column.us DOM search error: {exc}")

                browser.close()
                log.info(f"  → filled {filled_p8}/{len(p8)}")

        except ImportError:
            log.info(
                "  Pass 8 skipped — playwright not installed.\n"
                "    Install: pip3 install playwright --break-system-packages"
                " && playwright install chromium"
            )

    # ─────────────────────────────────────────────────────────────────────────
    # Commit all updates in one batch API call
    # ─────────────────────────────────────────────────────────────────────────
    # Filter out any empty-value cells that slipped through
    updates = [c for c in updates if str(c.value).strip()]

    if not updates:
        log.info("All fields already populated — nothing to update.")
        return

    log.info(f"Writing {len(updates)} cell update(s) to sheet…")
    try:
        sheet.update_cells(updates, value_input_option="USER_ENTERED")
        log.info(f"✓ Backfill complete — {len(updates)} cell(s) updated")
    except gspread.exceptions.APIError as e:
        log.error(f"Batch update failed: {e}")


if __name__ == "__main__":
    run()
