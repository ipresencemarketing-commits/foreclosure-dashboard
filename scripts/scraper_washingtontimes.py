#!/usr/bin/env python3
"""
Scraper — The Washington Times Classifieds (Foreclosure Notices)
================================================================
Scrapes http://classified.washingtontimes.com for Virginia foreclosure
notices, filters to target counties, and writes JSON in the standard
pipeline format.

Platform: PHP-based classifieds (Geodesic Solutions). Plain HTML, no JS required.

URL structure:
  Search:  http://classified.washingtontimes.com/index.php?a=19&b[subcategories_also]=1&b[search_text]=foreclosure&page=N
  Detail:  http://classified.washingtontimes.com/category/{cat_id}/{cat_name}/listings/{listing_id}/{notice_id}.html

Coverage: Primarily Northern Virginia (Fairfax, Loudoun, Prince William),
          with overlap into target counties via Fauquier, Stafford, Spotsylvania.

Usage:
    python3 scripts/scraper_washingtontimes.py             # writes data/foreclosures_washingtontimes.json
    python3 scripts/scraper_washingtontimes.py --dry-run   # print matches, don't write file
    python3 scripts/scraper_washingtontimes.py --output /path/to/out.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import os
import time
from collections import Counter
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Bootstrap
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
BASE_URL    = "http://classified.washingtontimes.com"
SEARCH_URL  = (
    f"{BASE_URL}/index.php"
    "?a=19&b[subcategories_also]=1&b[search_text]=foreclosure"
)
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "data", "foreclosures_washingtontimes.json")
SOURCE_TAG  = "washingtontimes"
DELAY_SECS  = 0.75   # polite crawl delay between HTTP requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Referer": BASE_URL,
}

# Category URL fragments that indicate non-Virginia notices — skip entirely.
# Virginia categories: "Forclosure-Sales-VA", "Foreclosure-Sales-FFX-Cty",
# "Foreclosure-Sales-PW-Cty", "Legal-Notices" (filtered by text below)
SKIP_CATEGORY_FRAGMENTS = [
    "Foreclosure-Sales-DC",
    "Foreclosure-Sales-MD",
    "Foreclosure-Sales-PG",    # Prince George's County, MD
    "Foreclosure-Sales-Mont",  # Montgomery County, MD
]

# Map lowercase county keywords found in notice text → pipeline display names.
# Order matters for multi-word keys — check longer keys first.
COUNTY_MAP: dict[str, str] = {
    "king george":    "King George",
    "fredericksburg": "Fredericksburg City",
    "spotsylvania":   "Spotsylvania",
    "stafford":       "Stafford",
    "caroline":       "Caroline",
    "fauquier":       "Fauquier",
    "culpeper":       "Culpeper",
    "hanover":        "Hanover",
    "chesterfield":   "Chesterfield",
    "richmond":       "Richmond City",
    "henrico":        "Henrico",
    "louisa":         "Louisa",
}

# ── Regex patterns ───────────────────────────────────────────────────────────

# Sale date: "May 27, 2026" or "May 27 2026"
_MONTHS = (
    "January|February|March|April|May|June|"
    "July|August|September|October|November|December"
)
SALE_DATE_RE = re.compile(
    rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b"
)

# Sale time: "at 2:00 PM", "at 10:30 a.m.", "at 2:00PM"
SALE_TIME_RE = re.compile(
    r"\bat\s+(\d{1,2}:\d{2})\s*([AaPp]\.?[Mm]\.?)"
)

# County in notice text — matches patterns like:
#   "Circuit Court for Fauquier County, Virginia"
#   "County of Stafford, Commonwealth of Virginia"
#   "Stafford County, Virginia"
#   "for King George County, Virginia"
COUNTY_TEXT_RE = re.compile(
    r"(?:Circuit Court for|County of|for)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)\s+County",
    re.IGNORECASE,
)

# Deed of Trust date: "Deed of Trust dated December 6, 2007, in the original principal"
DEED_DATE_RE = re.compile(
    rf"Deed\s+of\s+Trust\s+dated\s+({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})",
    re.IGNORECASE,
)

# Original principal: "original principal amount of $250,000.00"
PRINCIPAL_RE = re.compile(
    r"original\s+principal\s+(?:amount\s+of\s+)?(\$[\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# Deposit: "A bidder\u2019s deposit of ten percent (10%)" or "deposit of $25,000"
DEPOSIT_RE = re.compile(
    r"bidder[\u2019'`]?s?\s+deposit\s+of\s+[^($]*\((\d+(?:\.\d+)?%)\)"
    r"|bidder[\u2019'`]?s?\s+deposit\s+of\s+(\$[\d,]+(?:\.\d{1,2})?)",
    re.IGNORECASE,
)

# Trustee's Sale address line: "TRUSTEE'S SALE OF 123 MAIN ST, CITY, VA 12345" 
# Handles both straight (') and Unicode right single quote (’) apostrophes.
TRUSTEE_ADDR_RE = re.compile(
    r"TRUSTEE[’'`]?S?\s+SALE\s+OF\s+(.+?)(?:\.|\s+In execution|\s+In\s+execution)",
    re.IGNORECASE,
)

# Special Commissioner's Sale: "Special Commissioner's Sale of 123 Main St"
COMMISSIONER_ADDR_RE = re.compile(
    r"(?:Special\s+)?COMMISSIONER[’'`]?S?\s+SALE\s+OF\s+(.+?)(?:\.|\s+In execution|,\s+pursuant)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def fetch(url: str, session: requests.Session) -> BeautifulSoup | None:
    """GET a page, return BeautifulSoup or None on error."""
    try:
        resp = session.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as exc:
        log.warning("Fetch failed: %s  (%s)", url, exc)
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def make_id(address: str, sale_date: str) -> str:
    """Stable unique ID from address + sale date."""
    raw = f"{address.lower().strip()}-{sale_date or 'nodate'}"
    return "fc-" + hashlib.md5(raw.encode()).hexdigest()[:8]


def days_until(sale_date_str: str) -> int | None:
    if not sale_date_str:
        return None
    try:
        return (date.fromisoformat(sale_date_str) - date.today()).days
    except ValueError:
        return None


def investment_priority(days: int | None) -> str:
    if days is None:
        return "Low"
    if days <= 7:
        return "High"
    if days <= 21:
        return "Medium"
    return "Low"


def parse_sale_date(text: str) -> str:
    """Extract first sale date from notice text → YYYY-MM-DD, or ''."""
    m = SALE_DATE_RE.search(text)
    if not m:
        return ""
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_sale_time(text: str) -> str:
    """Extract first sale time from notice text → '10:00AM', or ''."""
    m = SALE_TIME_RE.search(text)
    if not m:
        return ""
    raw_time   = m.group(1)           # e.g. "10:30"
    raw_ampm   = m.group(2).replace(".", "").upper()  # "AM" or "PM"
    return f"{raw_time}{raw_ampm}"


def detect_county(text: str) -> str | None:
    """
    Return pipeline display name for the first target county found in notice text.
    Tries regex pattern first, then keyword scan.
    """
    # 1. Regex: "Circuit Court for Fauquier County" etc.
    for m in COUNTY_TEXT_RE.finditer(text):
        candidate = m.group(1).lower()
        if candidate in COUNTY_MAP:
            return COUNTY_MAP[candidate]
        # Handle "King George" (two words) — group(1) might be "King"
        # Try extending by one word
        start = m.start(1)
        two_word = text[start:start + 20].split()[:2]
        if len(two_word) == 2:
            key2 = f"{two_word[0]} {two_word[1]}".lower()
            if key2 in COUNTY_MAP:
                return COUNTY_MAP[key2]

    # 2. Keyword scan (longer keys first to catch "king george" before "george")
    text_lower = text.lower()
    for key in sorted(COUNTY_MAP, key=len, reverse=True):
        if key in text_lower:
            return COUNTY_MAP[key]

    return None


def extract_address(text: str) -> str:
    """Pull street address from notice text."""
    for pattern in (TRUSTEE_ADDR_RE, COMMISSIONER_ADDR_RE):
        m = pattern.search(text)
        if m:
            addr = m.group(1).strip().rstrip(".,")
            return addr
    return ""


def parse_deed_date(text: str) -> str:
    """Extract deed of trust date → YYYY-MM-DD, or \'\'."""
    m = DEED_DATE_RE.search(text)
    if not m:
        return ""
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def parse_original_principal(text: str) -> str:
    """Extract original principal amount → e.g. \'$250,000.00\', or \'\'."""
    m = PRINCIPAL_RE.search(text)
    return m.group(1) if m else ""


def parse_deposit(text: str) -> str:
    """Extract bidder deposit → e.g. \'10%\' or \'$25,000\', or \'\'."""
    m = DEPOSIT_RE.search(text)
    if not m:
        return ""
    return m.group(1) or m.group(2) or ""


def is_virginia_notice(text: str) -> bool:
    """Return True if the notice text references Virginia (not Maryland/DC)."""
    text_lower = text.lower()
    if "virginia" in text_lower or ", va " in text_lower or ", va\n" in text_lower:
        return True
    return False


def should_skip_category(href: str) -> bool:
    """Return True if the listing URL is for a non-Virginia category."""
    return any(frag in href for frag in SKIP_CATEGORY_FRAGMENTS)


# ---------------------------------------------------------------------------
# Search results page — collect listing URLs
# ---------------------------------------------------------------------------

def collect_listing_urls(session: requests.Session) -> list[str]:
    """
    Paginate through all search results pages and collect detail page URLs
    for non-DC, non-MD categories.
    """
    urls: list[str] = []
    page = 1

    while True:
        page_url = f"{SEARCH_URL}&page={page}" if page > 1 else SEARCH_URL
        log.info("Fetching search results page %d: %s", page, page_url)
        soup = fetch(page_url, session)
        if soup is None:
            break

        articles = soup.find_all("article")
        if not articles:
            log.info("No articles on page %d — done paginating.", page)
            break

        found_on_page = 0
        for article in articles:
            link = article.find("a", href=True)
            if not link:
                continue
            href = link["href"]
            # Make absolute URL if relative
            if not href.startswith("http"):
                href = f"{BASE_URL}/{href.lstrip('/')}"
            # Skip known non-Virginia categories
            if should_skip_category(href):
                log.debug("Skipping non-VA category: %s", href)
                continue
            urls.append(href)
            found_on_page += 1

        log.info("  Page %d: %d candidate listings (after category filter)", page, found_on_page)

        # Check for a next-page link by looking for a link to page+1
        # (string= match is fragile due to whitespace; URL pattern is reliable)
        next_link = soup.find("a", href=re.compile(rf"[?&]page={page + 1}\b"))
        if not next_link:
            log.info("No next-page link — pagination complete.")
            break

        page += 1
        time.sleep(DELAY_SECS)

    log.info("Total candidate listing URLs collected: %d", len(urls))
    return urls


# ---------------------------------------------------------------------------
# Detail page — parse one listing
# ---------------------------------------------------------------------------

def parse_detail_page(url: str, soup: BeautifulSoup) -> dict | None:
    """
    Parse a detail page into a listing dict.
    Returns None if the notice is not a Virginia target-county foreclosure.
    """
    # Extract notice body text from the description container.
    # DOM path: div.content_box_1.clearfix > div > p > span (notice sentences)
    desc_div = (
        soup.find("div", class_="content_box_1")
        or soup.find("div", class_=re.compile(r"content_box", re.I))
        or soup.find("article")
    )
    notice_text = desc_div.get_text(" ", strip=True) if desc_div else soup.get_text(" ", strip=True)

    # Must be Virginia
    if not is_virginia_notice(notice_text):
        log.debug("Skipping non-VA notice: %s", url)
        return None

    # Must be in a target county
    county = detect_county(notice_text)
    if not county:
        log.debug("County not in target list — skipping: %s", url)
        return None

    # Parse fields
    address   = extract_address(notice_text)
    sale_date = parse_sale_date(notice_text)
    sale_time = parse_sale_time(notice_text)
    du        = days_until(sale_date)

    if not address:
        log.warning("Could not extract address from: %s", url)
        return None

    # Truncate notice text to 5000 chars (matches pipeline convention)
    notice_trimmed = notice_text[:5000].strip()

    return {
        "id":                make_id(address, sale_date),
        "address":           address,
        "city":              "",          # backfill will parse from address
        "county":            county,
        "zip":               "",          # backfill will parse from address
        "state":             "VA",
        "stage":             "auction",
        "property_type":     "single-family",
        "assessed_value":    None,
        "asking_price":      None,
        "sale_date":         sale_date,
        "sale_time":         sale_time,
        "sale_location":     "",          # backfill will fill from county
        "days_until_sale":   du,
        "notice_date":       date.today().isoformat(),
        "days_in_foreclosure": 0,
        "lender":            "",
        "trustee":           "",
        "original_principal": parse_original_principal(notice_text),
        "deposit":           parse_deposit(notice_text),
        "deed_of_trust_date": parse_deed_date(notice_text),
        "notice_text":       notice_trimmed,
        "source":            SOURCE_TAG,
        "source_url":        SEARCH_URL,
        "listing_url":       url,
        "file_number":       "",
        "first_seen":        date.today().isoformat(),
        "is_new":            True,
        "investment_priority": investment_priority(du),
    }


# ---------------------------------------------------------------------------
# Merge with existing output
# ---------------------------------------------------------------------------

def merge(new_listings: list[dict], output_path: str) -> list[dict]:
    """Merge with existing file to preserve first_seen dates."""
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
    parser = argparse.ArgumentParser(description="Washington Times classifieds foreclosure scraper")
    parser.add_argument("--output",  default=OUTPUT_PATH, help="Output JSON path")
    parser.add_argument("--dry-run", action="store_true",  help="Print results, don't write file")
    args = parser.parse_args()

    log.info("=== Washington Times Scraper ===")
    log.info("Source: %s", SEARCH_URL)
    log.info("Output: %s", args.output)

    session = requests.Session()

    # Step 1 — collect candidate listing URLs from all search result pages
    listing_urls = collect_listing_urls(session)

    # Deduplicate (same listing can appear across multiple pages)
    listing_urls = list(dict.fromkeys(listing_urls))
    log.info("Unique candidate URLs: %d", len(listing_urls))

    # Step 2 — fetch each detail page and parse
    raw_listings: list[dict] = []
    for i, url in enumerate(listing_urls, 1):
        log.info("[%d/%d] Fetching: %s", i, len(listing_urls), url)
        soup = fetch(url, session)
        if soup is None:
            continue
        listing = parse_detail_page(url, soup)
        if listing:
            log.info("  ✓ %s  |  %s  |  %s", listing["county"], listing["address"][:60], listing["sale_date"])
            raw_listings.append(listing)
        time.sleep(DELAY_SECS)

    log.info("In-scope listings found: %d", len(raw_listings))

    if not raw_listings:
        log.warning("No target-county listings found. Washington Times may not cover these counties today.")

    # County summary
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
