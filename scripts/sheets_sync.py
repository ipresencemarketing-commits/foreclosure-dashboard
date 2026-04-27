#!/usr/bin/env python3
"""
Sync foreclosures.json → Google Sheets (FredericksburgForeclosures)
--------------------------------------------------------------------
Appends NEW listings only — existing rows are never overwritten so
any manual enrichment (owner info, equity calcs, notes) is preserved.

Setup (one-time):
  1. pip3 install gspread google-auth --break-system-packages
  2. Place your Google service account JSON at:
       credentials/service-account.json   ← preferred (gitignored)
     OR rename any savvy-factor-*.json to that path.
  3. Share the Google Sheet with the service account email
     (found in the JSON as "client_email") — give it Editor access.

Run: python3 scripts/sheets_sync.py
"""

from __future__ import annotations

import gspread
from google.oauth2.service_account import Credentials
import json
import os
import glob
import logging
from datetime import date, datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
SHEET_ID   = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
SHEET_TAB  = 0          # index of the main data tab (first sheet)
HEADER_ROW = 1          # row number that contains column headers

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_FILE    = os.path.join(PROJECT_ROOT, "data", "foreclosures.json")
CREDS_FILE   = os.path.join(PROJECT_ROOT, "credentials", "service-account.json")

# Sheet column order (must match the actual header row in the spreadsheet)
# Sale_Date and Sale_Time are appended at the end (Z, AA) to preserve existing column positions.
COLUMNS = [
    "Address", "ZIP", "Property_Type", "Status", "Listing_Price",
    "Beds_Baths_Sqft", "Year_Built", "Lot_Size", "Last_Sold_Date",
    "Last_Sold_Price", "Current_Est_Value", "Rough_Equity_Est",
    "Est_Profit_Potential", "Years_Since_Last_Sale", "Is_Auction",
    "Investment_Priority", "Owner_Name", "Owner_Mailing_Address",
    "Owner_Mailing_Differs_From_Property", "Estimated_Phone",
    "Estimated_Email", "Listing_URL", "Notes", "Date_Checked", "City",
    "Sale_Date", "Sale_Time",   # columns Z, AA — appended to avoid shifting existing data
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def find_creds_file() -> str | None:
    """Locate service-account credentials — preferred path first, then fallback."""
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    # Fallback: any savvy-factor-*.json in the project root
    pattern = os.path.join(PROJECT_ROOT, "savvy-factor-*.json")
    matches = glob.glob(pattern)
    if matches:
        log.warning(f"  Using fallback credentials: {matches[0]}")
        log.warning("  Consider moving to credentials/service-account.json")
        return matches[0]
    return None


def _fmt_price(val) -> str:
    """Format a numeric value as a dollar string, e.g. 350000 → '$350,000'."""
    if isinstance(val, (int, float)) and val:
        return f"${int(val):,}"
    return ""


def _years_since(date_str: str) -> str:
    """Return decimal years since date_str (YYYY-MM-DD), or ''."""
    if not date_str:
        return ""
    try:
        then = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        years = (date.today() - then).days / 365.25
        return f"{years:.1f}"
    except ValueError:
        return ""


def listing_to_row(listing: dict) -> list:
    """Convert a foreclosure listing dict to a sheet row (aligned to COLUMNS)."""
    stage = listing.get("stage", "")
    status = {
        "auction":  "Active Auction",
        "pre-fc":   "Pre-Foreclosure Notice",
        "reo":      "REO / Bank Owned",
    }.get(stage, stage.title())

    # ── Listing price ─────────────────────────────────────────────────────────
    price     = listing.get("asking_price")
    price_str = _fmt_price(price)

    # ── Investment priority ───────────────────────────────────────────────────
    # High   → any active auction (time-critical)
    # Medium → pre-FC with known sale date
    # Low    → REO (bank-owned, no urgency) or pre-FC with no date
    days = listing.get("days_until_sale")
    if stage == "auction":
        priority = "High"
    elif stage == "pre-fc" and days is not None and days >= 0:
        priority = "High" if days <= 30 else "Medium"
    elif stage == "pre-fc":
        priority = "Medium"
    else:
        priority = "Low"   # REO

    # ── Enrichment fields (from HomePath / Redfin) ───────────────────────────
    beds   = listing.get("beds")
    baths  = listing.get("baths")
    sqft   = listing.get("sqft")
    beds_baths_sqft = ""
    if beds or baths or sqft:
        parts_bbs = []
        if beds  is not None: parts_bbs.append(f"{int(beds)}bd")
        if baths is not None: parts_bbs.append(f"{baths}ba")
        if sqft  is not None: parts_bbs.append(f"{int(sqft):,} sqft")
        beds_baths_sqft = " / ".join(parts_bbs)

    year_built = listing.get("year_built") or ""
    lot_sqft   = listing.get("lot_sqft")
    lot_size   = f"{lot_sqft:,} sqft" if lot_sqft else ""

    last_sold_date  = listing.get("last_sold_date") or ""
    last_sold_price = _fmt_price(listing.get("last_sold_price"))

    est_value = listing.get("redfin_estimate")
    est_value_str = f"{_fmt_price(est_value)} (Est.)" if est_value else ""

    # Rough equity: estimated value minus asking price
    rough_equity = ""
    if est_value and price:
        eq = int(est_value) - int(price)
        rough_equity = _fmt_price(eq)

    # Profit potential as a percentage
    est_profit_pct = ""
    if est_value and price and int(price) > 0:
        pct = (int(est_value) - int(price)) / int(price) * 100
        est_profit_pct = f"{pct:.0f}%"

    years_since_sale = _years_since(last_sold_date)

    # ── Listing URL ───────────────────────────────────────────────────────────
    listing_url = (
        listing.get("redfin_url") or
        listing.get("source_url") or ""
    )

    # ── Notes (location, lender, trustee, source — NOT sale date/time) ───────
    note_parts = []
    if listing.get("sale_location"):
        note_parts.append(f"Loc: {listing['sale_location']}")
    if listing.get("lender"):
        note_parts.append(f"Lender: {listing['lender']}")
    if listing.get("trustee"):
        note_parts.append(f"Trustee: {listing['trustee']}")
    note_parts.append(f"Source: {listing.get('source', '')}")
    notes = " | ".join(note_parts)

    return [
        listing.get("address")  or "",           # A  Address
        listing.get("zip")      or "",            # B  ZIP
        "SFR" if listing.get("property_type") == "single-family"
             else (listing.get("property_type") or "SFR"),  # C  Property_Type
        status,                                   # D  Status
        price_str,                                # E  Listing_Price
        beds_baths_sqft,                          # F  Beds_Baths_Sqft
        str(year_built) if year_built else "",    # G  Year_Built
        lot_size,                                 # H  Lot_Size
        last_sold_date,                           # I  Last_Sold_Date
        last_sold_price,                          # J  Last_Sold_Price
        est_value_str,                            # K  Current_Est_Value
        rough_equity,                             # L  Rough_Equity_Est
        est_profit_pct,                           # M  Est_Profit_Potential
        years_since_sale,                         # N  Years_Since_Last_Sale
        "Yes" if stage == "auction" else "No",    # O  Is_Auction
        priority,                                 # P  Investment_Priority
        listing.get("owner_name") or "",          # Q  Owner_Name
        listing.get("owner_mailing_address") or "",  # R  Owner_Mailing_Address
        listing.get("owner_mailing_differs") or "",  # S  Owner_Mailing_Differs_From_Property
        listing.get("owner_phone") or "",         # T  Estimated_Phone
        listing.get("owner_email") or "",         # U  Estimated_Email
        listing_url,                              # V  Listing_URL
        notes,                                    # W  Notes
        date.today().isoformat(),                 # X  Date_Checked
        listing.get("city") or "",                # Y  City
        listing.get("sale_date")  or "",          # Z  Sale_Date
        listing.get("sale_time")  or "",          # AA Sale_Time
    ]


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> None:
    # ── 1. Load scraped data ──────────────────────────────────────────────────
    if not os.path.exists(DATA_FILE):
        log.error(f"Data file not found: {DATA_FILE} — run scraper.py first")
        return

    with open(DATA_FILE) as f:
        data = json.load(f)
    listings = data.get("listings", [])
    log.info(f"Loaded {len(listings)} listings from {DATA_FILE}")

    if not listings:
        log.info("No listings to sync.")
        return

    # ── 2. Authenticate ───────────────────────────────────────────────────────
    creds_path = find_creds_file()
    if not creds_path:
        log.error(
            "No credentials file found.\n"
            "  → Place your service account JSON at:\n"
            "      credentials/service-account.json\n"
            "  → Share the Google Sheet with the service account's client_email."
        )
        return

    creds  = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)
    log.info(f"  Authenticated with {creds_path}")

    # ── 3. Open sheet ─────────────────────────────────────────────────────────
    try:
        spreadsheet = client.open_by_key(SHEET_ID)
        sheet       = spreadsheet.get_worksheet(SHEET_TAB)
    except gspread.exceptions.APIError as e:
        log.error(f"Could not open spreadsheet: {e}")
        log.error("Make sure the sheet is shared with the service account email.")
        return

    # ── 4. Get existing addresses (to avoid duplicates) ───────────────────────
    try:
        all_values = sheet.get_all_values()
    except gspread.exceptions.APIError as e:
        log.error(f"Could not read sheet: {e}")
        return

    # Find the Address column index (0-based)
    if not all_values:
        log.warning("Sheet appears empty — writing header row first")
        sheet.append_row(COLUMNS)
        existing_addresses = set()
    else:
        # Header row → find Address column
        headers = [h.strip() for h in all_values[HEADER_ROW - 1]]

        # ── Ensure any missing columns are appended to the header row ──────────
        missing_cols = [col for col in COLUMNS if col not in headers]
        if missing_cols:
            log.info(f"  Adding {len(missing_cols)} missing header(s): {missing_cols}")
            start_col = len(headers) + 1   # 1-based column index for first new header
            # Expand the sheet grid before writing beyond current column count
            sheet.add_cols(len(missing_cols))
            log.info(f"  Expanded sheet to {len(headers) + len(missing_cols)} columns")
            for i, col_name in enumerate(missing_cols):
                sheet.update_cell(HEADER_ROW, start_col + i, col_name)
                log.info(f"    → wrote '{col_name}' to column {start_col + i}")
            # Re-read headers so addr_col lookup is accurate
            headers = [h.strip() for h in sheet.row_values(HEADER_ROW)]

        try:
            addr_col = headers.index("Address")
        except ValueError:
            addr_col = 0   # fallback: first column
        # Collect all existing addresses (lower-cased for comparison)
        existing_addresses = {
            row[addr_col].strip().lower()
            for row in all_values[HEADER_ROW:]   # skip header
            if row and row[addr_col].strip()
        }

    log.info(f"  {len(existing_addresses)} addresses already in sheet")

    # Build address → row-index map for enrichment updates (1-based, skip header)
    addr_to_row = {}
    if all_values:
        for i, row in enumerate(all_values[HEADER_ROW:], start=HEADER_ROW + 1):
            if row and len(row) > addr_col and row[addr_col].strip():
                addr_to_row[row[addr_col].strip().lower()] = i

    # Build header → column-index map (1-based)
    headers = [h.strip() for h in (all_values[HEADER_ROW - 1] if all_values else [])]
    col_idx = {h: i + 1 for i, h in enumerate(headers)}

    # Columns we will backfill if currently blank (never overwrite existing data)
    BACKFILL_COLS = [
        ("Beds_Baths_Sqft",                    "beds_baths_sqft"),
        ("Owner_Name",                          "owner_name"),
        ("Owner_Mailing_Address",               "owner_mailing_address"),
        ("Owner_Mailing_Differs_From_Property", "owner_mailing_differs"),
        ("Estimated_Phone",                     "owner_phone"),
        ("City",                                "city"),
    ]

    # Columns we ALWAYS overwrite (data quality fixes — URL format changed)
    FORCE_UPDATE_COLS = [
        "Listing_URL",
    ]

    # ── 5. Back-fill enrichment on existing rows ──────────────────────────────
    updates = []   # list of (row, col, value) to batch-update
    listings_by_addr = {
        (l.get("address") or "").strip().lower(): l for l in listings
    }

    for addr_key, row_num in addr_to_row.items():
        listing = listings_by_addr.get(addr_key)
        if not listing:
            continue
        # Pre-compute the full row so we can pull formatted values
        full_row = listing_to_row(listing)

        # Backfill empty cells
        for col_name, _ in BACKFILL_COLS:
            c = col_idx.get(col_name)
            if not c:
                continue
            data_row = all_values[row_num - 1] if row_num - 1 < len(all_values) else []
            current_val = data_row[c - 1].strip() if len(data_row) >= c else ""
            if current_val:
                continue   # already has data — don't overwrite
            new_val = full_row[c - 1] if c - 1 < len(full_row) else ""
            if new_val:
                updates.append((row_num, c, new_val))

        # Force-update specific columns regardless of current value
        for col_name in FORCE_UPDATE_COLS:
            c = col_idx.get(col_name)
            if not c:
                continue
            new_val = full_row[c - 1] if c - 1 < len(full_row) else ""
            if new_val:
                updates.append((row_num, c, new_val))

    if updates:
        log.info(f"  Back-filling {len(updates)} empty cell(s) on existing rows…")
        try:
            # Build Cell objects and send as a single batch API call
            cell_list = [gspread.Cell(row_num, col_num, val)
                         for row_num, col_num, val in updates]
            sheet.update_cells(cell_list, value_input_option="USER_ENTERED")
            log.info(f"  ✓ Enrichment back-fill complete ({len(cell_list)} cells)")
        except gspread.exceptions.APIError as e:
            log.error(f"  Back-fill failed: {e}")
    else:
        log.info("  No enrichment gaps to fill on existing rows.")

    # ── 6. Append new rows ────────────────────────────────────────────────────
    new_rows = []
    for listing in listings:
        addr = (listing.get("address") or "").strip().lower()
        if not addr or addr in existing_addresses:
            continue
        new_rows.append(listing_to_row(listing))
        existing_addresses.add(addr)   # prevent dupes within this batch

    if not new_rows:
        log.info("  No new listings to add — sheet is up to date.")
        return

    log.info(f"  Appending {len(new_rows)} new row(s)…")
    try:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
        log.info(f"  ✓ Added {len(new_rows)} new listing(s) to Google Sheet")
    except gspread.exceptions.APIError as e:
        log.error(f"  Failed to append rows: {e}")


if __name__ == "__main__":
    run()
