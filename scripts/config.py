#!/usr/bin/env python3
"""
Foreclosure Finder — Pipeline Configuration
============================================
Central settings file for the full pipeline.

Edit values here; changes apply to the next run of any script.
All scripts (scraper.py, backfill.py, sheets_sync.py, run.py) import from this module.

Quick reference
---------------
  COLUMN_US_SOURCES — master source list; set enabled=True/False to control what runs
  ENABLE_PNV        — toggle PNV (handled separately by scraper.py, not run.py)
  LOOKBACK_DAYS     — how far back to search (default 30 days)
  HTTP_DELAY_*      — rate-limiting constants
"""

from datetime import date, timedelta
import os

# ---------------------------------------------------------------------------
# Search window
# ---------------------------------------------------------------------------

#: Number of calendar days to look back when fetching foreclosure notices.
#:
#: How each source uses this value:
#:   PNV (publicnoticevirginia.com) — passed directly as the "From Date" field
#:       in the search form, so the site only returns notices published on or
#:       after SINCE_DATE.
#:
#:   Column.us portals (fredericksburg / richmond / dailyprogress) — the
#:       startDate URL parameter is appended to the search URL (Column.us may
#:       honour it client-side).  After fetching, the scraper also drops any
#:       listing whose sale_date is earlier than SINCE_DATE.
#:
#:   LOGS Legal (logs.com/va-sales-report.html) — post-fetch filter drops
#:       listings whose sale_date is earlier than SINCE_DATE.
LOOKBACK_DAYS: int = 30

# Derived — computed once at import time.  Reference these in all scripts
# instead of re-computing timedelta arithmetic.
TODAY:      date = date.today()
SINCE_DATE: date = TODAY - timedelta(days=LOOKBACK_DAYS)

# ---------------------------------------------------------------------------
# Target counties (12)
# ---------------------------------------------------------------------------

#: Lowercase county keys used internally for matching and GIS lookups.
TARGET_COUNTIES: list[str] = [
    # Stage 1 — Fredericksburg + Richmond metros
    "fredericksburg", "stafford", "spotsylvania", "caroline",
    "fauquier", "culpeper", "king george", "hanover",
    "richmond", "chesterfield", "henrico", "louisa",
    # Stage 2 — Roanoke metro
    "roanoke city", "roanoke", "salem", "botetourt",
    "bedford", "franklin", "montgomery", "radford",
]

#: Display names used in the Google Sheet "County" column.
TARGET_COUNTIES_DISPLAY: list[str] = [
    # Stage 1 — Fredericksburg + Richmond metros
    "Fredericksburg City", "Stafford", "Spotsylvania", "Caroline",
    "Fauquier", "Culpeper", "King George", "Hanover",
    "Richmond City", "Chesterfield", "Henrico", "Louisa",
    # Stage 2 — Roanoke metro
    "Roanoke City", "Roanoke", "Salem", "Botetourt",
    "Bedford", "Franklin", "Montgomery", "Radford",
]

# ---------------------------------------------------------------------------
# Column.us source list  ← THE SINGLE PLACE TO ENABLE / DISABLE SOURCES
# ---------------------------------------------------------------------------
# Each entry is one Column.us newspaper portal.
# Set enabled=True to include it in the daily run; False to skip it.
# run.py reads this list — update_statewide.sh is just a wrapper that calls run.py.
#
# Fields:
#   name       — short identifier used in log messages
#   label      — human-readable newspaper name
#   url        — Column.us search URL for Foreclosure Sale notices
#   header     — UPPERCASE newspaper name as it appears in page text (block delimiter)
#   source_tag — written into each listing's "source" field
#   output     — JSON output file path (relative to project root)
#   enabled    — True = runs daily; False = skipped
#   notes      — why it's enabled/disabled (for reference)

COLUMN_US_SOURCES: list[dict] = [
    {
        "name":       "fredericksburg",
        "label":      "Free Lance-Star (Fredericksburg)",
        "url":        "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "FREDERICKSBURG FREE-LANCE STAR",
        "source_tag": "column_us_fredericksburg",
        "output":     "data/foreclosures.json",
        "enabled":    True,
        "notes":      "Core source — Fxbg, Stafford, Spotsylvania, Caroline, King George",
    },
    {
        "name":       "fredericksburg_free_press",
        "label":      "Fredericksburg Free Press",
        "url":        "https://fredericksburgfreepress.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "FREDERICKSBURG FREE PRESS",
        "source_tag": "column_us_fxbg_free_press",
        "output":     "data/foreclosures_fxbg_free_press.json",
        "enabled":    True,
        "notes":      "Zero listings on 2026-05-22 test run — portal exists, notices may appear later",
    },
    {
        "name":       "richmond",
        "label":      "Richmond Times-Dispatch",
        "url":        "https://richmond.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "RICHMOND TIMES DISPATCH",
        "source_tag": "column_us_richmond",
        "output":     "data/foreclosures_richmond.json",
        "enabled":    True,
        "notes":      "Core source — Richmond City, Chesterfield, Henrico, Hanover",
    },
    {
        "name":       "culpeper",
        "label":      "Culpeper Star-Exponent",
        "url":        "https://starexponent.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "CULPEPER STAR EXPONENT",
        "source_tag": "column_us_culpeper",
        "output":     "data/foreclosures_culpeper.json",
        "enabled":    True,
        "notes":      "Core source — Culpeper, Fauquier",
    },
    {
        "name":       "williamsburg",
        "label":      "Virginia Gazette (Williamsburg)",
        "url":        "https://vagazette.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "VIRGINIA GAZETTE",
        "source_tag": "column_us_williamsburg",
        "output":     "data/foreclosures_williamsburg.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-22 — supplemental; Hanover, King George, Caroline overlap",
    },
    {
        "name":       "roanoke",
        "label":      "Roanoke Times",
        "url":        "https://roanoke.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "THE ROANOKE TIMES",
        "source_tag": "column_us_roanoke",
        "output":     "data/foreclosures_roanoke.json",
        "enabled":    True,
        "notes":      "Stage 2 — Roanoke City, Roanoke County, Salem, Botetourt, Bedford, Franklin, Montgomery",
    },
    {
        "name":       "lynchburg",
        "label":      "Lynchburg News & Advance",
        "url":        "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "LYNCHBURG NEWS & ADVANCE",
        "source_tag": "column_us_lynchburg",
        "output":     "data/foreclosures_lynchburg.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Lynchburg City, Amherst, Bedford, Campbell, Appomattox",
    },
    {
        "name":       "charlottesville",
        "label":      "Charlottesville Daily Progress",
        "url":        "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "CHARLOTTESVILLE DAILY PROGRESS",
        "source_tag": "column_us_dailyprogress",
        "output":     "data/foreclosures_charlottesville.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-22 — primarily Charlottesville/Albemarle; Louisa, Culpeper overlap possible",
    },
    {
        "name":       "waynesboro",
        "label":      "Waynesboro News Virginian",
        "url":        "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "WAYNESBORO NEWS VIRGINIAN",
        "source_tag": "column_us_waynesboro",
        "output":     "data/foreclosures_waynesboro.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Waynesboro City, Augusta County, Staunton City",
    },
    {
        "name":       "martinsville",
        "label":      "Martinsville Bulletin",
        "url":        "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "MARTINSVILLE BULLETIN",
        "source_tag": "column_us_martinsville",
        "output":     "data/foreclosures_martinsville.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Martinsville City, Henry County, Patrick County",
    },
    {
        "name":       "danville",
        "label":      "Danville Register & Bee",
        "url":        "https://godanriver.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "DANVILLE REGISTER & BEE",
        "source_tag": "column_us_danville",
        "output":     "data/foreclosures_danville.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Danville City, Pittsylvania County, Henry, Halifax",
    },
    {
        "name":       "westmoreland",
        "label":      "Westmoreland News",
        "url":        "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "WESTMORELAND NEWS",
        "source_tag": "column_us_westmoreland",
        "output":     "data/foreclosures_westmoreland.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Westmoreland County, Northern Neck; King George border overlap",
    },
    {
        "name":       "harrisonburg",
        "label":      "Daily News-Record (Harrisonburg)",
        "url":        "https://dnronline.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "DAILY NEWS-RECORD",
        "source_tag": "column_us_harrisonburg",
        "output":     "data/foreclosures_harrisonburg.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Harrisonburg City, Rockingham County, Page County",
    },
    {
        "name":       "ffxnow",
        "label":      "FFXnow (Fairfax)",
        "url":        "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "FFXNOW",
        "source_tag": "column_us_ffxnow",
        "output":     "data/foreclosures_ffxnow.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Fairfax County, Falls Church City; Northern Virginia",
    },
    {
        "name":       "arlnow",
        "label":      "ARLnow (Arlington)",
        "url":        "https://arlnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "ARLNOW",
        "source_tag": "column_us_arlnow",
        "output":     "data/foreclosures_arlnow.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Arlington County; Northern Virginia",
    },
    {
        "name":       "alxnow",
        "label":      "ALXnow (Alexandria)",
        "url":        "https://alxnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "ALXNOW",
        "source_tag": "column_us_alxnow",
        "output":     "data/foreclosures_alxnow.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Alexandria City; Northern Virginia",
    },
    {
        "name":       "bristol",
        "label":      "Bristol Herald Courier",
        "url":        "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "BRISTOL HERALD COURIER",
        "source_tag": "column_us_bristol",
        "output":     "data/foreclosures_bristol.json",
        "enabled":    True,
        "notes":      "Enabled 2026-05-30 — Bristol City, Washington County, Scott, Russell; SW Virginia",
    },
    {
        "name":       "nvdaily",
        "label":      "Northern Virginia Daily",
        "url":        "https://nvdaily.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "NORTHERN VIRGINIA DAILY",
        "source_tag": "column_us_nvdaily",
        "output":     "data/foreclosures_nvdaily.json",
        "enabled":    True,
        "notes":      (
            "CAUTION: nvdaily.column.us returned 404 as of 2025. "
            "NV Daily may have migrated to nvdaily.com/classifieds/ (different CMS). "
            "Coverage area is Shenandoah Valley (Shenandoah, Warren, Page counties) — "
            "outside the 12 target counties. Enabled 2026-05-22 for investigation; "
            "expect 0 results or a scraper error on first run."
        ),
    },
    # ---------------------------------------------------------------------------
    # New sources found 2026-05-30 via subdomain probe
    # ---------------------------------------------------------------------------
    {
        "name":       "dailypress",
        "label":      "Daily Press (Hampton Roads)",
        "url":        "https://dailypress.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "DAILY PRESS",
        "source_tag": "column_us_dailypress",
        "output":     "data/foreclosures_dailypress.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 6 results. Covers Newport News, Hampton, York, James City, Isle of Wight. Portal publishes some out-of-state notices — county filter drops non-VA.",
    },
    {
        "name":       "northernnecknews",
        "label":      "Northern Neck News",
        "url":        "https://northernnecknews.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "NORTHERN NECK NEWS",
        "source_tag": "column_us_northernnecknews",
        "output":     "data/foreclosures_northernnecknews.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 2 results. Covers Richmond County (Warsaw), Northumberland, Lancaster, Westmoreland overlap.",
    },
    {
        "name":       "sungazette",
        "label":      "Sun Gazette (Arlington/Fairfax)",
        "url":        "https://sungazette.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "SUN GAZETTE",
        "source_tag": "column_us_sungazette",
        "output":     "data/foreclosures_sungazette.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 0 results currently. Header unconfirmed — assumed SUN GAZETTE. Arlington/Fairfax NoVA coverage.",
    },
    {
        "name":       "insidenova",
        "label":      "InsideNOVA",
        "url":        "https://insidenova.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "INSIDENOVA",
        "source_tag": "column_us_insidenova",
        "output":     "data/foreclosures_insidenova.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 0 results currently. Header unconfirmed — assumed INSIDENOVA. Prince William/NoVA coverage.",
    },
    {
        "name":       "rappnews",
        "label":      "Rappahannock News",
        "url":        "https://rappnews.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "RAPPAHANNOCK NEWS",
        "source_tag": "column_us_rappnews",
        "output":     "data/foreclosures_rappnews.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 0 results currently. Header unconfirmed — assumed RAPPAHANNOCK NEWS. Rappahannock County coverage; Culpeper/Fauquier border.",
    },
    {
        "name":       "cardinalnews",
        "label":      "Cardinal News",
        "url":        "https://cardinalnews.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "CARDINAL NEWS",
        "source_tag": "column_us_cardinalnews",
        "output":     "data/foreclosures_cardinalnews.json",
        "enabled":    True,
        "notes":      "Confirmed live 2026-05-30, 0 results currently. Header unconfirmed — assumed CARDINAL NEWS. Statewide Virginia digital outlet.",
    },
    # ---------------------------------------------------------------------------
    # Custom-domain Column.us portals (not *.column.us subdomains)
    # Same scraper_column_us.py engine; different URL structure and noticeType param.
    # ---------------------------------------------------------------------------
    {
        "name":       "washingtonpost",
        "label":      "Washington Post Public Notices",
        "url":        "https://publicnotices.washingtonpost.com/?noticeType=Trustee%20Sale",
        "header":     "THE WASHINGTON POST",
        "source_tag": "washingtonpost",
        "output":     "data/foreclosures_washingtonpost.json",
        "enabled":    True,
        "notes":      (
            "Custom-domain Column.us portal (publicnotices.washingtonpost.com). "
            "~827 results/30 days across MD, DC, VA. noticeType='Trustee Sale' "
            "(not 'Foreclosure Sale'). ~41+ Load More clicks — expect long runtime."
        ),
    },
]

# ---------------------------------------------------------------------------
# PNV toggle  (PNV is handled by scraper.py, not run.py)
# ---------------------------------------------------------------------------
ENABLE_PNV: bool = False  # ON HOLD (2026-05-22) — paused for later use; re-enable by setting True

# ---------------------------------------------------------------------------
# Paused data files — sheets_sync.py will refuse to sync these
# ---------------------------------------------------------------------------
# Add the relative path (from project root) of any JSON data file whose
# source is currently paused.  This prevents accidental manual syncs.
import os as _os
_SCRIPTS_DIR = _os.path.dirname(_os.path.abspath(__file__))
_ROOT        = _os.path.join(_SCRIPTS_DIR, "..")
PAUSED_DATA_FILES: set = {
    _os.path.realpath(_os.path.join(_ROOT, "data", "foreclosures_pnv.json")),
}
del _os, _SCRIPTS_DIR, _ROOT

# ---------------------------------------------------------------------------
# Legacy scraper.py source flags (all False — dead code)
# ---------------------------------------------------------------------------
# scraper.py's run() references these flags for old Column.us / supplemental
# sources that are now dead — the live pipeline uses run.py + scraper_column_us.py.
# All set to False so scraper.py doesn't crash after PNV finishes.
ENABLE_COLUMN_FXBG:         bool = False  # Dead — handled by scraper_column_us.py
ENABLE_COLUMN_RICHMOND:     bool = False  # Dead — handled by scraper_column_us.py
ENABLE_LOGS_LEGAL:          bool = False  # Dead — LOGS Legal scraper not active
ENABLE_COLUMN_DAILYPROG:    bool = False  # Dead — handled by scraper_column_us.py
ENABLE_AUCTION_COM:         bool = False  # Dead — Auction.com scraper not active
ENABLE_COLUMN_WILLIAMSBURG: bool = False  # Dead — handled by scraper_column_us.py
ENABLE_COLUMN_NVDAILY:      bool = False  # Dead — NV Daily returns 404
ENABLE_VA_COURTS:           bool = False  # Dead — VA eCourts requires auth session

# ---------------------------------------------------------------------------
# SIWPC toggle  (handled by scraper_siwpc.py, called directly by run.py)
# ---------------------------------------------------------------------------
ENABLE_SIWPC: bool = True   # Samuel I. White, P.C. — daily PDF at siwpc.net

# ---------------------------------------------------------------------------
# Glasser Law toggle  (handled by scraper_glasserlaw.py, called by run.py)
# ---------------------------------------------------------------------------
# Playwright required — Cloudflare protection on site.
# URL: glasserlaw.com/New%20Folder/Foreclosure%20Sales.html
# ~21 VA listings. Has bid deposit, original principal, full courthouse address.
ENABLE_GLASSERLAW: bool = True

# ---------------------------------------------------------------------------
# MWC Law toggle  (handled by scraper_mwclaw.py, called by run.py)
# ---------------------------------------------------------------------------
# Static HTML — requests + BeautifulSoup, no Playwright needed.
# URL: apps.mwc-law.com/SalesLists/VA.html
# ~40 VA listings. Clean table with county, city, address, file number.
ENABLE_MWCLAW: bool = True

# ---------------------------------------------------------------------------
# LOGS Legal toggle  (handled by scraper_logs.py, called by run.py)
# ---------------------------------------------------------------------------
# Playwright-based PowerBI interceptor — no HTML scraping.
# URL: logs.com/va-sales-report.html
# Provides statewide VA trustee sales. ~110 listings.
ENABLE_LOGS: bool = True

# ---------------------------------------------------------------------------
# Auction.com toggle  (handled by scraper_auctioncom.py, called by run.py)
# ---------------------------------------------------------------------------
# GraphQL API — no Playwright, no auth token needed.
# URL: auction.com/residential/VA/.../foreclosures_at (GOTO filter = live courthouse sales)
# ~26 VA listings. Provides beds/baths/sqft, year built, lot size, est. market value.
ENABLE_AUCTIONCOM: bool = True

# ---------------------------------------------------------------------------
# Xome Auction toggle  (handled by scraper_xome.py, called by run.py)
# ---------------------------------------------------------------------------
# Two-step REST API — no Playwright needed. Step 1 fetches county/date/ID
# map; Step 2 batch-fetches all property details in a single call.
# URL: xome.com/auctions/foreclosuresales?ss=virginia
# Auth: public token embedded in site JS (not user-specific).
# ~85 VA listings. Includes full courthouse address from API.
ENABLE_XOME: bool = True

# ---------------------------------------------------------------------------
# ServiceLink Auction toggle  (handled by scraper_servicelink.py, called by run.py)
# ---------------------------------------------------------------------------
# Pure REST API — no Playwright, no HTML parsing. Sub-second fetch.
# URL: servicelinkauction.com/foreclosures/virginia
# Richest source in the pipeline: beds/baths/sqft, year built, lot size,
# occupancy status, exact courthouse address, individual listing URL.
# ~70-80 active VA listings. API limit=100 max.
ENABLE_SERVICELINK: bool = True

# ---------------------------------------------------------------------------
# Rosenberg & Associates toggle  (handled by scraper_rosenberg.py, called by run.py)
# ---------------------------------------------------------------------------
# Static HTML table — requests + BeautifulSoup, no Playwright needed.
# URL: rosenberg-assoc.com/foreclosure-sales/
# VA + MD + DC mixed; filters to VA only. ~66 active VA listings.
ENABLE_ROSENBERG: bool = True

# ---------------------------------------------------------------------------
# Brock & Scott toggle  (handled by scraper_brockscott.py, called by run.py)
# ---------------------------------------------------------------------------
# Static HTML scraper — no Playwright needed.
# URL: brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va
# Covers statewide Virginia. Unique: provides Opening Bid Amount.
ENABLE_BROCKSCOTT: bool = True

# ---------------------------------------------------------------------------
# Southside Sentinel toggle  (scraper not yet built — Stage 2)
# ---------------------------------------------------------------------------
# Static HTML classifieds at ssentinel.com/Classifieds/public-notices/
# Covers Middlesex County and the Middle Peninsula (outside Stage 1 target counties).
# Set True when the scraper is built and Stage 2 expansion begins.
ENABLE_SOUTHSIDE_SENTINEL: bool = False

# ---------------------------------------------------------------------------
# TMMP toggle  (scraper not yet built — needs manual verification first)
# ---------------------------------------------------------------------------
# Tromberg, Miller, Morris & Partners — claimed public VA sale list at
# tmppllc.com/virginia_foreclosure_sales. Page existence unconfirmed.
# Do not build scraper until page is manually verified.
ENABLE_TMMP: bool = False

# ---------------------------------------------------------------------------
# Washington Times toggle  (handled by scraper_washingtontimes.py)
# ---------------------------------------------------------------------------
# Covers Northern VA classifieds (Fairfax, Loudoun, Prince William).
# Target-county overlap: primarily Fauquier, Stafford, Spotsylvania.
# Platform: PHP classifieds (classified.washingtontimes.com) — plain HTML scraper.
ENABLE_WASHINGTONTIMES: bool = True

# ---------------------------------------------------------------------------
# Redfin toggle  (backfill.py Pass 6 — unofficial API for value estimates)
# ---------------------------------------------------------------------------
# When False (default), GIS assessed value is the only Current_Est_Value source.
# Set True only if VGIN + county ArcGIS are consistently missing assessed values.
ENABLE_REDFIN: bool = False

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# ── scraper.py ────────────────────────────────────────────────────────────────

#: Milliseconds to wait after a Column.us page loads, giving Firebase time
#: to fetch and render all notice cards before we start reading the DOM.
COLUMN_US_LOAD_WAIT_MS: int = 8_000

#: Milliseconds to wait after each "Load more notices" click on Column.us.
COLUMN_US_LOAD_MORE_WAIT_MS: int = 2_500

# ── backfill.py ───────────────────────────────────────────────────────────────

#: Seconds between GIS / VGIN parcel API calls.
#: VGIN handles higher throughput than county-specific endpoints.
HTTP_DELAY_SECONDS: float = 0.25

#: Seconds between notice detail-page re-fetches (PNV address search,
#: Auction.com re-fetch, source URL re-fetch in Pass 1).
NOTICE_FETCH_DELAY_SECONDS: float = 0.5

#: Seconds between Redfin unofficial API calls.
#: Redfin is aggressive about rate-limiting; keep this at 1.0+.
REDFIN_DELAY_SECONDS: float = 1.0

#: Seconds between US Census geocoder calls.
#: The Census API is rate-limited to approximately 1 request/second.
CENSUS_DELAY_SECONDS: float = 1.0

# ---------------------------------------------------------------------------
# Google Sheets credentials + target spreadsheet
# ---------------------------------------------------------------------------
# These are consumed by sheets_sync.py and backfill.py.
# Centralised here so both scripts stay in sync without copy-paste.

#: Service account JSON credential file (gitignored — never commit).
_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.join(_SCRIPT_DIR, "..")

CREDS_FILE: str = os.path.join(_PROJECT_ROOT, "credentials", "service-account.json")

#: 2captcha API key — used to solve reCAPTCHA on PNV detail pages.
#: Read from credentials/twocaptcha_key.txt (gitignored).
#: Set to None if the file is missing — PNV falls back to card-text-only mode.
_TWOCAPTCHA_KEY_FILE = os.path.join(_PROJECT_ROOT, "credentials", "twocaptcha_key.txt")
try:
    with open(_TWOCAPTCHA_KEY_FILE) as _f:
        TWOCAPTCHA_API_KEY = _f.read().strip() or None  # str or None
except FileNotFoundError:
    TWOCAPTCHA_API_KEY = None

#: Google API OAuth scopes required for read/write spreadsheet access.
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

#: Google Sheet ID for the main Foreclosures dashboard.
SHEET_ID: str = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
