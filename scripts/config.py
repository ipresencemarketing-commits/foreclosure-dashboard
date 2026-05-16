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
    "fredericksburg", "stafford", "spotsylvania", "caroline",
    "fauquier", "culpeper", "king george", "hanover",
    "richmond", "chesterfield", "henrico", "louisa",
]

#: Display names used in the Google Sheet "County" column.
TARGET_COUNTIES_DISPLAY: list[str] = [
    "Fredericksburg City", "Stafford", "Spotsylvania", "Caroline",
    "Fauquier", "Culpeper", "King George", "Hanover",
    "Richmond City", "Chesterfield", "Henrico", "Louisa",
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
        "enabled":    False,
        "notes":      "Paused — supplemental only, limited target county overlap",
    },
    {
        "name":       "roanoke",
        "label":      "Roanoke Times",
        "url":        "https://roanoke.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "ROANOKE TIMES",
        "source_tag": "column_us_roanoke",
        "output":     "data/foreclosures_roanoke.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "lynchburg",
        "label":      "Lynchburg News & Advance",
        "url":        "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "NEWS & ADVANCE",
        "source_tag": "column_us_lynchburg",
        "output":     "data/foreclosures_lynchburg.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "charlottesville",
        "label":      "Charlottesville Daily Progress",
        "url":        "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "DAILY PROGRESS",
        "source_tag": "column_us_charlottesville",
        "output":     "data/foreclosures_charlottesville.json",
        "enabled":    False,
        "notes":      "Outside target counties — Charlottesville/Albemarle only",
    },
    {
        "name":       "waynesboro",
        "label":      "Waynesboro News Virginian",
        "url":        "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "NEWS VIRGINIAN",
        "source_tag": "column_us_waynesboro",
        "output":     "data/foreclosures_waynesboro.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "martinsville",
        "label":      "Martinsville Bulletin",
        "url":        "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "MARTINSVILLE BULLETIN",
        "source_tag": "column_us_martinsville",
        "output":     "data/foreclosures_martinsville.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "danville",
        "label":      "Danville Register & Bee",
        "url":        "https://godanriver.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "REGISTER & BEE",
        "source_tag": "column_us_danville",
        "output":     "data/foreclosures_danville.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "westmoreland",
        "label":      "Westmoreland News",
        "url":        "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "WESTMORELAND NEWS",
        "source_tag": "column_us_westmoreland",
        "output":     "data/foreclosures_westmoreland.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "harrisonburg",
        "label":      "Daily News-Record (Harrisonburg)",
        "url":        "https://dnronline.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "DAILY NEWS-RECORD",
        "source_tag": "column_us_harrisonburg",
        "output":     "data/foreclosures_harrisonburg.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "ffxnow",
        "label":      "FFXnow (Fairfax)",
        "url":        "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "FFXNOW",
        "source_tag": "column_us_ffxnow",
        "output":     "data/foreclosures_ffxnow.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "arlnow",
        "label":      "ARLnow (Arlington)",
        "url":        "https://arlnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "ARLNOW",
        "source_tag": "column_us_arlnow",
        "output":     "data/foreclosures_arlnow.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "alxnow",
        "label":      "ALXnow (Alexandria)",
        "url":        "https://alxnow.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "ALXNOW",
        "source_tag": "column_us_alxnow",
        "output":     "data/foreclosures_alxnow.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
    {
        "name":       "bristol",
        "label":      "Bristol Herald Courier",
        "url":        "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale",
        "header":     "BRISTOL HERALD COURIER",
        "source_tag": "column_us_bristol",
        "output":     "data/foreclosures_bristol.json",
        "enabled":    False,
        "notes":      "Outside target counties — Stage 2 (statewide expansion)",
    },
]

# ---------------------------------------------------------------------------
# PNV toggle  (PNV is handled by scraper.py, not run.py)
# ---------------------------------------------------------------------------
ENABLE_PNV: bool = True   # Lead-discovery source: full notice text via 2captcha (falls back to card text if key missing)

# ---------------------------------------------------------------------------
# SIWPC toggle  (handled by scraper_siwpc.py, called directly by run.py)
# ---------------------------------------------------------------------------
ENABLE_SIWPC: bool = True   # Samuel I. White, P.C. — daily PDF at siwpc.net

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
