#!/usr/bin/env python3
"""
sync_schedule_missing.py

Compares the "Schedule" tab in the Buying Virginia Muffin spreadsheet
against the "Foreclosures" tab, then creates/refreshes "Schedule_Missing"
in the FredericksburgForeclosures sheet with every Schedule row whose
address isn't already covered by the scraper pipeline.

Run from project root:
    python3 scripts/sync_schedule_missing.py
"""

import re
import sys
from pathlib import Path

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("Missing dependencies. Run: pip3 install gspread google-auth --break-system-packages")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

SERVICE_ACCOUNT_PATH = Path(__file__).parent.parent / "credentials" / "service-account.json"

FORECLOSURES_SHEET_ID   = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
MUFFIN_SHEET_ID         = "1VeJJ7WBZyhweXw7R8Kk1xK_OKdToypUmKKbqUX8xemQ"

FORECLOSURES_TAB        = "Foreclosures"
SCHEDULE_TAB            = "Schedule"
OUTPUT_TAB              = "Schedule_Missing"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Schedule tab column headers (0-indexed position 3 = Address)
SCHEDULE_HEADERS = [
    "Date", "Time", "County", "Address", "Source",
    "Trustee_Contact", "Original_Note_Date", "Original_Note_Volume",
    "Phone_Seller", "Phone_Call_Made", "Zestimate",
    "Sewer", "Status", "Assigned",
]
SCHEDULE_ADDRESS_COL = 3   # 0-indexed


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(addr: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation noise."""
    addr = addr.lower().strip()
    addr = re.sub(r"\s+", " ", addr)
    return addr


def addr_key(addr: str) -> str:
    """Return 'HOUSE_NUM FIRST_STREET_WORD' for fast fuzzy matching."""
    parts = normalize(addr).split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return normalize(addr)


def build_foreclosure_index(rows: list[list]) -> set[str]:
    """Build a set of normalized address keys from the Foreclosures tab."""
    index = set()
    for row in rows[1:]:  # skip header
        if row and row[0].strip():
            index.add(addr_key(row[0]))
    return index


def is_missing(sched_addr: str, fc_index: set[str]) -> bool:
    key = addr_key(sched_addr)
    return key not in fc_index


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Connecting to Google Sheets …")
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)

    # Read Foreclosures tab
    print(f"Reading '{FORECLOSURES_TAB}' tab …")
    fc_sheet = gc.open_by_key(FORECLOSURES_SHEET_ID)
    fc_ws    = fc_sheet.worksheet(FORECLOSURES_TAB)
    fc_rows  = fc_ws.get_all_values()
    fc_index = build_foreclosure_index(fc_rows)
    print(f"  {len(fc_rows) - 1} Foreclosures rows loaded, {len(fc_index)} unique address keys")

    # Read Schedule tab
    print(f"Reading '{SCHEDULE_TAB}' tab …")
    muffin_sheet = gc.open_by_key(MUFFIN_SHEET_ID)
    sched_ws     = muffin_sheet.worksheet(SCHEDULE_TAB)
    sched_rows   = sched_ws.get_all_values()

    # Skip header row; keep only rows that have an address
    data_rows = [r for r in sched_rows[1:] if len(r) > SCHEDULE_ADDRESS_COL and r[SCHEDULE_ADDRESS_COL].strip()]
    print(f"  {len(data_rows)} Schedule data rows loaded")

    # Identify missing rows
    missing_rows = [r for r in data_rows if is_missing(r[SCHEDULE_ADDRESS_COL], fc_index)]
    unique_missing = {addr_key(r[SCHEDULE_ADDRESS_COL]) for r in missing_rows}
    matched = len({addr_key(r[SCHEDULE_ADDRESS_COL]) for r in data_rows}) - len(unique_missing)

    print(f"\nComparison results:")
    print(f"  Schedule unique addresses : {len({addr_key(r[SCHEDULE_ADDRESS_COL]) for r in data_rows})}")
    print(f"  Matched in Foreclosures   : {matched}")
    print(f"  Missing from Foreclosures : {len(unique_missing)} unique ({len(missing_rows)} total rows incl. repeat dates)")

    # Pad rows to 14 columns so the sheet stays consistent
    def pad(row):
        padded = list(row) + [""] * 14
        return padded[:14]

    output_data = [SCHEDULE_HEADERS] + [pad(r) for r in missing_rows]

    # Create / clear the output tab
    print(f"\nWriting '{OUTPUT_TAB}' tab …")
    try:
        out_ws = fc_sheet.worksheet(OUTPUT_TAB)
        out_ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        out_ws = fc_sheet.add_worksheet(title=OUTPUT_TAB, rows=len(output_data) + 10, cols=14)

    # Batch update — one API call
    out_ws.update(output_data, value_input_option="RAW")
    # Freeze header row
    fc_sheet.batch_update({
        "requests": [{
            "updateSheetProperties": {
                "properties": {"sheetId": out_ws.id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        }]
    })

    print(f"\nDone — {len(missing_rows)} rows written to '{OUTPUT_TAB}' tab.")
    print(f"Open: https://docs.google.com/spreadsheets/d/{FORECLOSURES_SHEET_ID}")


if __name__ == "__main__":
    main()
