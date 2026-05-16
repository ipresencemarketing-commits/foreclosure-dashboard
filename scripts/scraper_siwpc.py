#!/usr/bin/env python3
from __future__ import annotations
"""
Scraper — Samuel I. White, P.C. (SIWPC) Foreclosure Sales PDF
==============================================================
Downloads the daily PDF from https://www.siwpc.net/AutoUpload/Sales.pdf,
parses the structured county-grouped table, filters to target counties,
and writes a JSON file in the standard pipeline format.

PDF structure:
  VA
  <County Name>
  <Address> <City> <ZIP> <M/D/YYYY> <HH:MM:SS> <SaleCity> <FileNum>
  ...
  <Next County Name>
  ...

Fields available: address, city, zip, sale_date, sale_time, county (from header),
                  file_number. Trustee is always "Samuel I. White, P.C."
No lender or notice_text — this PDF is a summary table only.

Usage:
    python3 scripts/scraper_siwpc.py                     # writes data/foreclosures_siwpc.json
    python3 scripts/scraper_siwpc.py --output /path/to/out.json
    python3 scripts/scraper_siwpc.py --dry-run           # print matches, don't write file
"""

import argparse
import hashlib
import json
import logging
import re
import sys
import os
from datetime import date, datetime
from io import BytesIO

# ---------------------------------------------------------------------------
# Bootstrap — find project root so we can import config + scraper helpers
# ---------------------------------------------------------------------------
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
sys.path.insert(0, SCRIPT_DIR)

import config as cfg

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PDF_URL     = "https://www.siwpc.net/AutoUpload/Sales.pdf"
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "foreclosures_siwpc.json")
SOURCE_TAG  = "siwpc"

# Map PDF county/city headers → pipeline display names
# Keys are lowercase as they appear in the PDF
COUNTY_MAP: dict[str, str] = {
    # Target counties
    "fredericksburg":    "Fredericksburg City",
    "stafford":          "Stafford",
    "spotsylvania":      "Spotsylvania",
    "caroline":          "Caroline",
    "fauquier":          "Fauquier",
    "culpeper":          "Culpeper",
    "king george":       "King George",
    "hanover":           "Hanover",
    "city of richmond":  "Richmond City",
    "chesterfield":      "Chesterfield",
    "henrico":           "Henrico",
    "louisa":            "Louisa",
}

# Courthouse sale locations by display name (mirrors scraper.py courthouse_location())
COURTHOUSE: dict[str, str] = {
    "Fredericksburg City": "Front steps, Fredericksburg Circuit Court, 815 Princess Anne St",
    "Stafford":            "Front steps, Stafford Circuit Court, 1300 Courthouse Rd",
    "Spotsylvania":        "Front steps, Spotsylvania Circuit Court, 9115 Courthouse Rd",
    "Caroline":            "Front steps, Caroline Circuit Court, 112 Courthouse Ln",
    "Fauquier":            "Front steps, Fauquier Circuit Court, 29 Ashby St, Warrenton",
    "Culpeper":            "Front steps, Culpeper Circuit Court, 135 W Cameron St",
    "King George":         "Front steps, King George Circuit Court, 10459 Courthouse Dr",
    "Hanover":             "Front steps, Hanover Circuit Court, 7507 Library Dr",
    "Richmond City":       "Front steps, Richmond City Circuit Court, 400 N 9th St",
    "Chesterfield":        "Front steps, Chesterfield Circuit Court, 9500 Courthouse Rd",
    "Henrico":             "Front steps, Henrico Circuit Court, 4301 E Parham Rd",
    "Louisa":              "Front steps, Louisa Circuit Court, 100 W Main St",
}

# Lines containing these strings are PDF boilerplate — skip them
BOILERPLATE_FRAGMENTS = [
    "information reported as of",
    "samuel i. white, p.c. makes",
    "makes no representations",
    "land records in the county",
    "condition of any of the properties",
    "listed on this report will be sold",
    "users of this information",
    "accuracy of the data",
    "for additional information",
    "for additonal information",       # typo in original PDF
    "property address",                # column header row
    "foreclosure sales report",        # page title
    "448 viking drive",
    "virginia beach, va 23452",
    "(757) 457-1460",
    "* 9:00 am",
    "- call between",
]

# Regex to detect a listing row — anchors on ZIP, date, time from the right
# Groups: (address_and_city, zip, sale_date M/D/YYYY, sale_time HH:MM:SS, sale_city, file_num)
LISTING_RE = re.compile(
    r"^(.+?)\s+"                          # address + city (greedy up to ZIP)
    r"(\d{5}(?:-\d{4})?)\s+"             # ZIP (with optional +4)
    r"(\d{1,2}/\d{1,2}/\d{4})\s+"        # sale date  M/D/YYYY
    r"(\d{2}:\d{2}:\d{2})\s+"            # sale time  HH:MM:SS
    r"(.+?)\s+"                          # sale location city
    r"(\d{4,6})\s*$"                     # firm file number
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_id(address: str, sale_date: str) -> str:
    """Stable unique ID based on address + sale date (matches scraper.py)."""
    raw = f"{address.lower().strip()}-{sale_date or 'nodate'}"
    return "fc-" + hashlib.md5(raw.encode()).hexdigest()[:8]


def days_until(sale_date_str: str) -> int | None:
    """Days from today until sale_date_str (YYYY-MM-DD)."""
    if not sale_date_str:
        return None
    try:
        return (date.fromisoformat(sale_date_str) - date.today()).days
    except ValueError:
        return None


def parse_sale_date(raw: str) -> str:
    """Convert M/D/YYYY → YYYY-MM-DD."""
    try:
        return datetime.strptime(raw, "%m/%d/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_sale_time(raw: str) -> str:
    """Convert HH:MM:SS → H:MMAM/PM (e.g. '10:30:00' → '10:30AM')."""
    try:
        dt = datetime.strptime(raw, "%H:%M:%S")
        return dt.strftime("%-I:%M%p")   # e.g. 10:30AM
    except ValueError:
        return raw


def investment_priority(days: int | None, stage: str) -> str:
    """High / Medium / Low based on days until sale."""
    if days is None:
        return "Low"
    if days <= 7:
        return "High"
    if days <= 21:
        return "Medium"
    return "Low"


def is_boilerplate(line: str) -> bool:
    low = line.lower()
    return any(frag in low for frag in BOILERPLATE_FRAGMENTS)


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------

def fetch_pdf_bytes(url: str) -> bytes:
    import requests
    log.info("Downloading PDF: %s", url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
        "Referer": "https://www.siwpc.net/",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    log.info("Downloaded %.1f KB", len(resp.content) / 1024)
    return resp.content


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def extract_text(pdf_bytes: bytes) -> str:
    """Extract full text from PDF using pdfplumber."""
    import pdfplumber
    text_parts = []
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3)
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


def parse_listings(text: str) -> list[dict]:
    """
    Parse county sections and listing rows from extracted PDF text.
    Returns list of raw dicts with all fields populated for target counties.
    """
    listings = []
    current_county_display = None   # display name from COUNTY_MAP, or None if out of scope

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if is_boilerplate(line):
            continue

        # Try to match as a listing row first
        m = LISTING_RE.match(line)
        if m:
            if current_county_display is None:
                continue   # out-of-scope county section — skip

            addr_city_raw = m.group(1).strip()
            zip_code      = m.group(2)
            sale_date_raw = m.group(3)
            sale_time_raw = m.group(4)
            # m.group(5) is the sale city — we derive location from county instead
            file_num      = m.group(6)

            sale_date = parse_sale_date(sale_date_raw)
            sale_time = parse_sale_time(sale_time_raw)
            du         = days_until(sale_date)

            # addr_city_raw = "4512 Greenbriar Drive Chester" — city is last word(s) before ZIP
            # We store the whole thing as address since city is already in county record
            address = f"{addr_city_raw}, VA {zip_code}"

            county   = current_county_display
            location = COURTHOUSE.get(county, "Courthouse steps — verify with trustee")

            listings.append({
                "id":               make_id(address, sale_date),
                "address":          address,
                "city":             "",          # backfill will populate from address
                "county":           county,
                "zip":              zip_code[:5],
                "state":            "VA",
                "stage":            "auction",
                "property_type":    "single-family",
                "assessed_value":   None,
                "asking_price":     None,
                "sale_date":        sale_date,
                "sale_time":        sale_time,
                "sale_location":    location,
                "days_until_sale":  du,
                "notice_date":      date.today().isoformat(),
                "days_in_foreclosure": 0,
                "lender":           "",          # not available in PDF summary
                "trustee":          "Samuel I. White, P.C.",
                "original_principal": "",
                "deposit":          "",
                "deed_of_trust_date": "",
                "notice_text":      "",          # no full notice text in this source
                "source":           SOURCE_TAG,
                "source_url":       PDF_URL,
                "listing_url":      PDF_URL,
                "file_number":      file_num,
                "first_seen":       date.today().isoformat(),
                "is_new":           True,
                "investment_priority": investment_priority(du, "auction"),
            })
            continue

        # Not a listing row — treat as a county/section header if it doesn't start with a digit
        if not line[0].isdigit() and line not in ("VA",):
            key = line.lower()
            current_county_display = COUNTY_MAP.get(key)   # None = out of scope

    return listings


# ---------------------------------------------------------------------------
# Merge with existing output (preserve first_seen, is_new)
# ---------------------------------------------------------------------------

def merge(new_listings: list[dict], output_path: str) -> list[dict]:
    """
    Merge new listings with any existing file so we don't lose first_seen dates.
    Existing records not in new_listings are dropped (sale may have passed).
    """
    existing: dict[str, dict] = {}
    if os.path.exists(output_path):
        try:
            with open(output_path) as f:
                old = json.load(f)
            recs = old if isinstance(old, list) else old.get("listings", [])
            existing = {r["id"]: r for r in recs}
        except Exception:
            pass

    merged = []
    for rec in new_listings:
        if rec["id"] in existing:
            old = existing[rec["id"]]
            rec["first_seen"] = old.get("first_seen", rec["first_seen"])
            rec["is_new"]     = False
        merged.append(rec)

    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="SIWPC PDF foreclosure scraper")
    parser.add_argument("--output",  default=OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true",  help="Print results, don't write file")
    args = parser.parse_args()

    log.info("=== SIWPC Scraper ===")
    log.info("Source: %s", PDF_URL)

    # Download
    pdf_bytes = fetch_pdf_bytes(PDF_URL)

    # Parse
    raw_listings = parse_listings(extract_text(pdf_bytes))
    log.info("In-scope listings found: %d", len(raw_listings))

    if not raw_listings:
        log.warning("No in-scope listings — check county headers in PDF or TARGET_COUNTIES_MAP")

    # County summary
    from collections import Counter
    counts = Counter(r["county"] for r in raw_listings)
    for county, n in sorted(counts.items()):
        log.info("  %-25s %d", county, n)

    if args.dry_run:
        print(json.dumps(raw_listings, indent=2))
        return

    # Merge + write
    listings = merge(raw_listings, args.output)
    out = {"listings": listings, "scraped_at": datetime.utcnow().isoformat() + "Z"}
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    log.info("Wrote %d listings → %s", len(listings), args.output)


if __name__ == "__main__":
    main()
