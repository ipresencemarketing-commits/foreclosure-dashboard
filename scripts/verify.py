#!/usr/bin/env python3
"""
verify.py — Verify sheet completeness and remediate persistent gaps.

Runs AFTER backfill.py.  Prints a before/after gap report for every
tracked field, then applies targeted strategies for values that
backfill.py could not resolve.

Remediation order
-----------------
  A. ZIP + County via Census geocoder matched-address
       The Census response includes a normalised address ("123 MAIN ST,
       STAFFORD, VA, 22554") even when the raw input address had no ZIP.
       Both ZIP and County are extracted from a single API call.

  B. County via GIS endpoint scan
       Tries each of the 12 target county ArcGIS parcel APIs in turn and
       stops at the first one that returns a parcel match.  This is the
       most thorough county-finding strategy available and is reserved for
       rows that survived every earlier pass still blank.

  C. County via newly-resolved ZIP  (for rows whose ZIP just changed)
       After Rem A fills ZIPs, re-runs zip_to_county so the hardcoded
       map can resolve county without another network call.

Run standalone:  python3 scripts/verify.py
"""

from __future__ import annotations

import sys
import os
import re
import glob
import logging
from time import sleep

import requests
import gspread
from google.oauth2.service_account import Credentials

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import (           # noqa: E402
    city_to_county,
    county_display,
    gis_lookup_owner,
    TARGET_COUNTIES,
    HEADERS,
)
from backfill import zip_to_county   # reuse the hardcoded map + zippopotam

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

# Fields included in the gap report (in display order)
TRACKED_FIELDS = [
    "ZIP", "City", "County", "State",
    "F_Sale_Date", "F_Sale_Time",
    "Owner_Name", "Owner_Mailing_Address",
]

DISPLAY_TO_KEY: dict[str, str] = {county_display(k): k for k in TARGET_COUNTIES}


# ── Auth ─────────────────────────────────────────────────────────────────────

def find_creds_file() -> str | None:
    if os.path.exists(CREDS_FILE):
        return CREDS_FILE
    matches = glob.glob(os.path.join(PROJECT_ROOT, "savvy-factor-*.json"))
    return matches[0] if matches else None


# ── Gap reporting ─────────────────────────────────────────────────────────────

def count_gaps(data: list[list], col_0: dict[str, int]) -> dict[str, int]:
    """Return {field: blank_row_count} for every tracked field."""
    result = {}
    for field in TRACKED_FIELDS:
        idx = col_0.get(field, -1)
        if idx < 0:
            result[field] = 0
        else:
            result[field] = sum(
                1 for row in data
                if not (row[idx].strip() if idx < len(row) else "")
            )
    return result


def print_gap_report(before: dict, after: dict) -> None:
    print()
    print(f"  {'Field':<45} {'Before':>8}  {'After':>6}  {'Fixed':>6}")
    print("  " + "-" * 72)
    total_before = total_after = 0
    for field in TRACKED_FIELDS:
        b = before.get(field, 0)
        a = after.get(field, 0)
        fixed = b - a
        flag = "  ✓" if fixed > 0 else ("  ✗" if a > 0 else "")
        print(f"  {field:<45} {b:>8}  {a:>6}  {fixed:>6}{flag}")
        total_before += b
        total_after  += a
    print("  " + "-" * 72)
    print(f"  {'TOTAL':<45} {total_before:>8}  {total_after:>6}  {total_before - total_after:>6}")
    print()


# ── Remediation helpers ───────────────────────────────────────────────────────

def census_zip_and_county(address: str) -> tuple[str, str]:
    """
    Call the Census Bureau geocoder and extract both ZIP and county from
    the normalised matched address it returns.

    The geocoder always returns a ZIP in `matchedAddress` even when the
    input had none — making this useful as a ZIP source, not just county.

    Returns (zip_str, county_display_name); either may be "".
    Rate-limited: sleep 1 s between calls (Census policy).
    """
    try:
        resp = requests.get(
            "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress",
            params={
                "address":   f"{address}, VA",
                "benchmark": "Public_AR_Current",
                "vintage":   "Current_Current",
                "layers":    "10",
                "format":    "json",
            },
            headers={"User-Agent": "ForeclosureFinder/1.0 (research)"},
            timeout=15,
        )
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if not matches:
            return "", ""

        match = matches[0]

        # ── ZIP from matchedAddress ───────────────────────────────────────────
        # Format: "123 MAIN ST, STAFFORD, VA, 22554"
        matched_addr = match.get("matchedAddress", "")
        zip_val = ""
        mz = re.search(r"\b(\d{5})(?:-\d{4})?\b", matched_addr)
        if mz:
            zip_val = mz.group(1)

        # ── County from geographies ───────────────────────────────────────────
        county_val = ""
        counties = match.get("geographies", {}).get("Counties", [])
        if counties:
            raw   = re.sub(r"\s+County$", "", counties[0].get("NAME", ""), flags=re.I).strip()
            raw_l = raw.lower()
            for k in TARGET_COUNTIES:
                if k in raw_l or raw_l in k:
                    county_val = county_display(k)
                    break

        return zip_val, county_val

    except Exception as exc:
        log.debug(f"  census({address!r}): {exc}")
        return "", ""


def county_via_gis_scan(address: str) -> str:
    """
    Last-resort county lookup: try every county's ArcGIS parcel API in
    turn and return the first county whose database contains this address.

    Up to 12 API calls per row — only invoke for rows where every other
    strategy has already failed.
    """
    for county_key in TARGET_COUNTIES:
        gis = gis_lookup_owner(address, county_key)
        if gis.get("owner_name"):
            log.debug(f"    GIS scan matched county '{county_key}' for {address!r}")
            return county_display(county_key)
        sleep(0.25)
    return ""


# ── Main ─────────────────────────────────────────────────────────────────────

def run() -> None:
    creds_path = find_creds_file()
    if not creds_path:
        log.error("No credentials file found.")
        return

    creds       = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client      = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SHEET_ID)
    sheet       = spreadsheet.get_worksheet(0)

    log.info("Reading sheet for verification…")
    all_values = sheet.get_all_values()
    if len(all_values) < 2:
        log.info("Sheet has no data rows.")
        return

    headers = [h.strip() for h in all_values[0]]
    col_0   = {h: i     for i, h in enumerate(headers)}
    col_1   = {h: i + 1 for i, h in enumerate(headers)}
    data    = all_values[1:]   # mutable view; we update in-memory as we go
    log.info(f"  {len(data)} data rows")

    # ── Snapshot "before" gap counts ─────────────────────────────────────────
    before = count_gaps(data, col_0)
    log.info("Gap report BEFORE remediation:")
    print_gap_report(before, before)

    updates: list[gspread.Cell] = []

    def val(row: list, field: str) -> str:
        idx = col_0.get(field, -1)
        return row[idx].strip() if 0 <= idx < len(row) else ""

    def queue(row_0: int, field: str, value: str) -> None:
        """Queue a write and update the in-memory row so later passes see it."""
        c = col_1.get(field)
        if not c or not value:
            return
        updates.append(gspread.Cell(row_0 + 2, c, value))
        # Update in-memory so subsequent remediations see this as filled
        idx = col_0.get(field, -1)
        if 0 <= idx < len(data[row_0]):
            data[row_0][idx] = value
        elif idx >= 0:
            # Row is shorter than the column index — pad it
            data[row_0].extend([""] * (idx - len(data[row_0]) + 1))
            data[row_0][idx] = value

    # ── Remediation A — Census geocoder: ZIP + County in one call ────────────
    # Only rows missing ZIP or County (skip if both are already filled).
    rem_a = [
        (i, row) for i, row in enumerate(data)
        if not val(row, "ZIP") or not val(row, "County")
    ]
    log.info(f"Rem A — Census geocoder (ZIP + County): {len(rem_a)} candidate row(s)")
    filled_zip_a = filled_county_a = 0
    for i, row in rem_a:
        address    = val(row, "Address")
        has_zip    = bool(val(row, "ZIP"))
        has_county = bool(val(row, "County"))
        if has_zip and has_county:
            continue
        if not address:
            continue

        zip_val, county_val = census_zip_and_county(address)
        sleep(1.0)   # Census geocoder rate limit

        if not has_zip and zip_val:
            queue(i, "ZIP", zip_val)
            filled_zip_a += 1
            log.info(f"  row {i+2}: ZIP={zip_val} (Census)")

        if not has_county and county_val:
            queue(i, "County", county_val)
            filled_county_a += 1
            log.info(f"  row {i+2}: County={county_val} (Census)")

    log.info(f"  → ZIP filled: {filled_zip_a}  County filled: {filled_county_a}")

    # ── Remediation B — GIS endpoint scan for still-missing County ───────────
    # Only for rows where County is STILL blank after Rem A.
    rem_b = [
        (i, row) for i, row in enumerate(data)
        if not val(row, "County") and val(row, "Address")
    ]
    log.info(f"Rem B — GIS endpoint scan (County): {len(rem_b)} candidate row(s)")
    filled_county_b = 0
    for i, row in rem_b:
        address = val(row, "Address")
        county  = county_via_gis_scan(address)
        if county:
            queue(i, "County", county)
            filled_county_b += 1
            log.info(f"  row {i+2}: County={county} (GIS scan)")
        else:
            log.info(f"  row {i+2}: County still unresolved — {address!r}")
    log.info(f"  → filled {filled_county_b}/{len(rem_b)}")

    # ── Remediation C — zip_to_county for rows with ZIP but no County ────────
    # Catches rows whose ZIP was just filled in Rem A and can now map to county.
    rem_c = [
        (i, row) for i, row in enumerate(data)
        if not val(row, "County") and val(row, "ZIP")
    ]
    log.info(f"Rem C — zip_to_county for newly-filled ZIPs: {len(rem_c)} candidate row(s)")
    filled_county_c = 0
    for i, row in rem_c:
        county = zip_to_county(val(row, "ZIP"))
        if county:
            queue(i, "County", county)
            filled_county_c += 1
            log.info(f"  row {i+2}: County={county} (ZIP map, post-Rem A)")
    log.info(f"  → filled {filled_county_c}/{len(rem_c)}")

    # ── Write all updates ─────────────────────────────────────────────────────
    updates = [c for c in updates if str(c.value).strip()]
    if updates:
        log.info(f"Writing {len(updates)} update(s) to sheet…")
        try:
            sheet.update_cells(updates, value_input_option="USER_ENTERED")
            log.info(f"✓ Verification complete — {len(updates)} cell(s) updated")
        except gspread.exceptions.APIError as e:
            log.error(f"  Batch update failed: {e}")
    else:
        log.info("No new values found — sheet already fully populated.")

    # ── Gap report AFTER remediation (reflects in-memory updates) ────────────
    after = count_gaps(data, col_0)
    log.info("Gap report AFTER remediation:")
    print_gap_report(before, after)

    # ── Flag any fields that are still persistently blank ─────────────────────
    still_missing = {f: n for f, n in after.items() if n > 0}
    if still_missing:
        log.info("Fields still missing values (no automated source found):")
        for field, count in still_missing.items():
            log.info(f"  {field}: {count} row(s) — may need manual lookup or paid data")
    else:
        log.info("All tracked fields are fully populated.")


if __name__ == "__main__":
    run()
