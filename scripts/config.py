#!/usr/bin/env python3
"""
Foreclosure Finder — Pipeline Configuration
============================================
Central settings file for the full pipeline.

Edit values here; changes apply to the next run of any script.
All scripts (scraper.py, backfill.py, sheets_sync.py) import from this module.

Quick reference
---------------
  LOOKBACK_DAYS   — how far back to search (default 30 days)
  ENABLE_*        — toggle individual source groups on/off without touching scraper code
  HTTP_DELAY_*    — rate-limiting constants
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
# Source group toggles
# ---------------------------------------------------------------------------
# Set a flag to False to skip that group entirely without removing its code.
# Useful for debugging one source at a time or temporarily pausing a source
# that's rate-limiting or returning bad data.

ENABLE_PNV:                bool = True   # Group 3  — publicnoticevirginia.com
ENABLE_COLUMN_FXBG:        bool = True   # Existing — fredericksburg.column.us
ENABLE_COLUMN_RICHMOND:    bool = True   # Group 1  — richmond.column.us
ENABLE_LOGS_LEGAL:         bool = False  # Group 2  — DISABLED: logs.com migrated to PowerBI
                                         #            embed (2026-05); BS4 cannot parse iframe data
ENABLE_COLUMN_DAILYPROG:   bool = True   # Group 4  — dailyprogress.column.us
ENABLE_AUCTION_COM:        bool = True   # Group 5  — auction.com (REO + trustee sales)
ENABLE_COLUMN_WILLIAMSBURG:bool = True   # Group 6  — vagazette.column.us (Virginia Gazette)
ENABLE_COLUMN_NVDAILY:     bool = False  # Group 7  — DISABLED: nvdaily.column.us is 404; NV Daily
                                         #            uses its own CMS and covers wrong counties
ENABLE_SIWPC:              bool = True   # Group 8  — siwpc.com/sales-report (Samuel I. White)
ENABLE_VA_COURTS:          bool = False  # Group 9  — DISABLED: eCourts circuitSearch and CJISWeb
                                         #            both require an authenticated session; no
                                         #            public API endpoint available

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

#: Google API OAuth scopes required for read/write spreadsheet access.
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

#: Google Sheet ID for the main Foreclosures dashboard.
SHEET_ID: str = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
