#!/usr/bin/env python3
"""
diagnose_sheet.py — Print exactly what sheets_sync writes vs what the sheet contains.

Run:  python3 scripts/diagnose_sheet.py

Prints:
  1. The COLUMNS list (what the header row is supposed to be)
  2. listing_to_row() output for the first listing in foreclosures.json
  3. The ACTUAL header row currently in the Google Sheet
  4. The ACTUAL first data row in the Google Sheet
"""
import json, os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gspread
from google.oauth2.service_account import Credentials

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_FILE    = os.path.join(PROJECT_ROOT, "data", "foreclosures.json")
CREDS_FILE   = os.path.join(PROJECT_ROOT, "credentials", "service-account.json")
SHEET_ID     = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
SCOPES       = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Import from sheets_sync ───────────────────────────────────────────────────
from sheets_sync import COLUMNS, listing_to_row

# ── 1. Print COLUMNS ──────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"COLUMNS list ({len(COLUMNS)} entries):")
for i, col in enumerate(COLUMNS):
    col_letter = chr(ord('A') + i) if i < 26 else 'A' + chr(ord('A') + i - 26)
    print(f"  [{i:2d}] {col_letter} = {col}")

# ── 2. Simulate listing_to_row() for first listing ────────────────────────────
print(f"\n{'='*60}")
print("listing_to_row() output for first listing in foreclosures.json:")
try:
    with open(DATA_FILE) as f:
        data = json.load(f)
    listings = data.get("listings", [])
    if listings:
        row = listing_to_row(listings[0])
        print(f"  Row has {len(row)} values")
        for i, (col, val) in enumerate(zip(COLUMNS, row)):
            col_letter = chr(ord('A') + i) if i < 26 else 'A' + chr(ord('A') + i - 26)
            display_val = str(val)[:60] + "..." if len(str(val)) > 60 else str(val)
            print(f"  [{i:2d}] {col_letter} {col:<42} = {display_val!r}")
        if len(row) != len(COLUMNS):
            print(f"\n  !! MISMATCH: row has {len(row)} values but COLUMNS has {len(COLUMNS)}")
    else:
        print("  No listings in file.")
except Exception as e:
    print(f"  Error: {e}")

# ── 3. Read actual sheet ───────────────────────────────────────────────────────
print(f"\n{'='*60}")
print("Actual Google Sheet header row and first data row:")
try:
    creds_path = CREDS_FILE
    if not os.path.exists(creds_path):
        matches = glob.glob(os.path.join(PROJECT_ROOT, "savvy-factor-*.json"))
        creds_path = matches[0] if matches else None
    if not creds_path:
        print("  No credentials file — skipping sheet read.")
    else:
        creds  = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet  = client.open_by_key(SHEET_ID).get_worksheet(0)
        all_values = sheet.get_all_values()
        if all_values:
            header = all_values[0]
            print(f"\n  Sheet header ({len(header)} columns):")
            for i, h in enumerate(header):
                col_letter = chr(ord('A') + i) if i < 26 else 'A' + chr(ord('A') + i - 26)
                match = "✓" if i < len(COLUMNS) and h == COLUMNS[i] else "✗ MISMATCH"
                expected = COLUMNS[i] if i < len(COLUMNS) else "(no expected)"
                print(f"    [{i:2d}] {col_letter} = {h!r:30s}  expected={expected!r} {match}")
        if len(all_values) > 1:
            first_row = all_values[1]
            print(f"\n  First data row ({len(first_row)} values):")
            for i, (h, v) in enumerate(zip(header, first_row)):
                col_letter = chr(ord('A') + i) if i < 26 else 'A' + chr(ord('A') + i - 26)
                display_v = v[:50] + "..." if len(v) > 50 else v
                print(f"    [{i:2d}] {col_letter} {h:<30} = {display_v!r}")
except Exception as e:
    print(f"  Error connecting to sheet: {e}")

print(f"\n{'='*60}\n")
