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
# The header is rewritten on every sync run, so changing this list
# automatically re-orders the spreadsheet on the next run.
COLUMNS = [
    "Address",                              # A  — property street address
    "County",                               # B  — moved to front for quick scanning
    "F_Sale_Date",                          # C  — foreclosure sale date (most time-critical)
    "F_Sale_Time",                          # D  — foreclosure sale time
    "Status",                               # E
    "Investment_Priority",                  # F
    "Listing_Price",                        # G
    "Current_Est_Value",                    # H
    "Rough_Equity_Est",                     # I
    "Est_Profit_Potential",                 # J
    "Beds_Baths_Sqft",                      # K
    "Year_Built",                           # L
    "Lot_Size",                             # M
    "Last_Sold_Date",                       # N
    "Last_Sold_Price",                      # O
    "Years_Since_Last_Sale",                # P
    "City",                                 # Q
    "ZIP",                                  # R
    "State",                                # S
    "Property_Type",                        # T
    "Is_Auction",                           # U
    "Owner_Name",                           # V
    "Owner_Mailing_Address",                # W
    "Owner_Mailing_Differs_From_Property",  # X
    "Estimated_Phone",                      # Y
    "Estimated_Email",                      # Z
    "Listing_URL",                          # AA
    "Notes",                                # AB
    "Date_Checked",                         # AC
    "Notice_Text",                          # AD — full text of the foreclosure notice
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
    # lot_size: accept pre-formatted string (e.g. "0.45 ac") from scraper,
    # or fall back to raw lot_sqft integer and convert to sqft label.
    lot_size = (
        listing.get("lot_size")
        or (f"{listing['lot_sqft']:,} sqft" if listing.get("lot_sqft") else "")
    )

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
        listing.get("address")  or "",            # A  Address
        listing.get("county")   or "",            # B  County
        listing.get("sale_date")  or "",          # C  F_Sale_Date
        listing.get("sale_time")  or "",          # D  F_Sale_Time
        status,                                   # E  Status
        priority,                                 # F  Investment_Priority
        price_str,                                # G  Listing_Price
        est_value_str,                            # H  Current_Est_Value
        rough_equity,                             # I  Rough_Equity_Est
        est_profit_pct,                           # J  Est_Profit_Potential
        beds_baths_sqft,                          # K  Beds_Baths_Sqft
        str(year_built) if year_built else "",    # L  Year_Built
        lot_size,                                 # M  Lot_Size
        last_sold_date,                           # N  Last_Sold_Date
        last_sold_price,                          # O  Last_Sold_Price
        years_since_sale,                         # P  Years_Since_Last_Sale
        listing.get("city") or "",                # Q  City
        listing.get("zip")  or "",                # R  ZIP
        "VA",                                     # S  State
        "SFR" if listing.get("property_type") == "single-family"
             else (listing.get("property_type") or "SFR"),  # T  Property_Type
        "Yes" if stage == "auction" else "No",    # U  Is_Auction
        listing.get("owner_name") or "",          # V  Owner_Name
        listing.get("owner_mailing_address") or "",  # W  Owner_Mailing_Address
        listing.get("owner_mailing_differs") or "",  # X  Owner_Mailing_Differs_From_Property
        listing.get("owner_phone") or "",         # Y  Estimated_Phone
        listing.get("owner_email") or "",         # Z  Estimated_Email
        listing_url,                              # AA Listing_URL
        notes,                                    # AB Notes
        date.today().isoformat(),                 # AC Date_Checked
        listing.get("notice_text") or "",         # AD Notice_Text
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

    # ── Detect column-order mismatch and clear if needed ────────────────────
    # If the existing header row doesn't exactly match COLUMNS, the sheet data
    # is misaligned with the code.  The only safe fix is a full clear-and-rewrite.
    # This happens whenever the COLUMNS list is reordered in the code.
    existing_header = all_values[0] if all_values else []
    # Trim trailing empty cells before comparing
    existing_header_trimmed = [c.strip() for c in existing_header if c.strip()]
    if existing_header_trimmed and existing_header_trimmed != COLUMNS:
        log.warning(
            f"  Header mismatch detected — clearing sheet and rewriting.\n"
            f"    Expected: {COLUMNS[:5]}…\n"
            f"    Found:    {existing_header_trimmed[:5]}…"
        )
        sheet.clear()
        all_values = []   # treat sheet as empty so all rows are appended fresh
        log.info("  Sheet cleared — will rewrite all rows.")

    # ── Always write the canonical header row ────────────────────────────────
    try:
        sheet.update([COLUMNS], "A1", value_input_option="RAW")
        log.info(f"  Header row confirmed ({len(COLUMNS)} columns)")
    except gspread.exceptions.APIError as e:
        log.error(f"  Could not write header row: {e}")
        return

    # Address is always column A (index 0)
    addr_col = 0

    # Collect existing addresses from the snapshot we already read
    if not all_values:
        existing_addresses = set()
    else:
        existing_addresses = {
            row[addr_col].strip().lower()
            for row in all_values[HEADER_ROW:]   # skip header row
            if row and len(row) > addr_col and row[addr_col].strip()
        }

    log.info(f"  {len(existing_addresses)} addresses already in sheet")

    # Build address → sheet-row map for enrichment updates (1-based row numbers)
    addr_to_row = {}
    for i, row in enumerate(all_values[HEADER_ROW:], start=HEADER_ROW + 1):
        if row and len(row) > addr_col and row[addr_col].strip():
            addr_to_row[row[addr_col].strip().lower()] = i

    # Column index map derived from COLUMNS (authoritative — matches what we just wrote)
    col_idx = {h: i + 1 for i, h in enumerate(COLUMNS)}

    # Columns we will backfill if currently blank (never overwrite existing data)
    BACKFILL_COLS = [
        ("Beds_Baths_Sqft",                    "beds_baths_sqft"),
        ("Owner_Name",                          "owner_name"),
        ("Owner_Mailing_Address",               "owner_mailing_address"),
        ("Owner_Mailing_Differs_From_Property", "owner_mailing_differs"),
        ("Estimated_Phone",                     "owner_phone"),
        ("Estimated_Email",                     "owner_email"),
        ("City",                                "city"),
        ("State",                               None),   # always "VA" — derived in listing_to_row
        ("County",                              "county"),
        # Sale date/time come from the full PNV notice body — may be missing
        # on first scrape if the detail page wasn't fetched yet.  Backfill
        # once they're found on a subsequent run.
        ("F_Sale_Date",                         "sale_date"),
        ("F_Sale_Time",                         "sale_time"),
    ]

    # Columns we ALWAYS overwrite (data quality fixes — URL format changed)
    FORCE_UPDATE_COLS = [
        "Listing_URL",
    ]

    # ── 5. Back-fill enrichment + mark expired auctions on existing rows ───────
    updates = []   # list of (row, col, value) to batch-update
    listings_by_addr = {
        (l.get("address") or "").strip().lower(): l for l in listings
    }
    today_iso = date.today().isoformat()
    expired_count = 0

    for addr_key, row_num in addr_to_row.items():
        data_row = all_values[row_num - 1] if row_num - 1 < len(all_values) else []

        # ── Mark past-auction rows as "Sale Passed – Verify" ─────────────────
        # If the row's F_Sale_Date is a past date AND Status is still an active
        # auction label, flip the status so the row stops showing as actionable.
        # We never flip REO or pre-foreclosure rows — only auction ones.
        status_c    = col_idx.get("Status")
        sale_date_c = col_idx.get("F_Sale_Date")
        if status_c and sale_date_c:
            current_status    = (data_row[status_c - 1].strip()
                                 if len(data_row) >= status_c else "")
            current_sale_date = (data_row[sale_date_c - 1].strip()
                                 if len(data_row) >= sale_date_c else "")
            if (current_sale_date
                    and current_sale_date < today_iso
                    and current_status == "Active Auction"):
                updates.append((row_num, status_c, "Sale Passed – Verify"))
                expired_count += 1

        # ── Backfill empty enrichment cells ──────────────────────────────────
        listing = listings_by_addr.get(addr_key)
        if not listing:
            continue
        # Pre-compute the full row so we can pull formatted values
        full_row = listing_to_row(listing)

        for col_name, _ in BACKFILL_COLS:
            c = col_idx.get(col_name)
            if not c:
                continue
            current_val = data_row[c - 1].strip() if len(data_row) >= c else ""
            if current_val:
                continue   # already has data — don't overwrite
            # State has no json_key — always "VA"; others come from listing_to_row()
            if col_name == "State":
                new_val = "VA"
            else:
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

    if expired_count:
        log.info(f"  Flagged {expired_count} past-auction row(s) as 'Sale Passed – Verify'")

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
    else:
        log.info(f"  Appending {len(new_rows)} new row(s)…")
        try:
            # Use direct-range update instead of append_rows.
            # append_rows uses the Sheets API's table-detection which clips writes
            # to the width of the existing data (e.g., 25 cols if old rows stop at Y).
            # Direct update writes exactly what we provide, all 29 columns.
            next_row = max(2, len(all_values) + 1)  # always below header (row 1)
            sheet.update(new_rows, f"A{next_row}", value_input_option="USER_ENTERED")
            log.info(f"  ✓ Added {len(new_rows)} new listing(s) to Google Sheet")
        except gspread.exceptions.APIError as e:
            log.error(f"  Failed to append rows: {e}")

    # ── 7. Update Summary tab ─────────────────────────────────────────────────
    update_summary_tab(spreadsheet, sheet)


def update_summary_tab(spreadsheet: gspread.Spreadsheet, data_sheet: gspread.Worksheet) -> None:
    """
    Write key stats to the 'Summary' tab so Total Properties displays as a
    plain integer (not a date).  The cell value is written as RAW so Google
    Sheets cannot reformat it as a date serial number.

    Layout written (starting at A1):
        Metric            | Value
        Total Properties  | <int>
        Last Updated      | YYYY-MM-DD
        Active Auctions   | <int>
        Pre-FC Notices    | <int>
        REO / Bank Owned  | <int>
    """
    try:
        try:
            summary = spreadsheet.worksheet("Summary")
        except gspread.exceptions.WorksheetNotFound:
            summary = spreadsheet.add_worksheet(title="Summary", rows=20, cols=4)
            log.info("  Created 'Summary' tab")

        # Read all rows from the data sheet to count statuses.
        all_rows = data_sheet.get_all_values()
        if len(all_rows) <= 1:
            total = 0
            auctions = pre_fc = reo = 0
        else:
            data_rows = all_rows[1:]   # skip header
            total = len(data_rows)
            # Status column (E = index 4 in new column order)
            status_idx = COLUMNS.index("Status")
            statuses = [r[status_idx].strip() if len(r) > status_idx else "" for r in data_rows]
            auctions = sum(1 for s in statuses if s == "Active Auction")
            pre_fc   = sum(1 for s in statuses if s == "Pre-Foreclosure Notice")
            reo      = sum(1 for s in statuses if s == "REO / Bank Owned")

        today = date.today().isoformat()

        # Write the summary block.  Use RAW so numbers are never misread as dates.
        summary_data = [
            ["Metric",                "Value"],
            ["Total Properties",      total],
            ["Last Updated",          today],
            ["Active Auctions",       auctions],
            ["Pre-FC Notices",        pre_fc],
            ["REO / Bank Owned",      reo],
        ]
        summary.update(summary_data, "A1", value_input_option="RAW")
        log.info(f"  ✓ Summary tab updated — {total} total properties")

    except gspread.exceptions.APIError as e:
        log.error(f"  Summary tab update failed: {e}")


if __name__ == "__main__":
    run()
