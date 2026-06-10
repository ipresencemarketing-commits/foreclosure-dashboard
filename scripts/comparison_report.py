#!/usr/bin/env python3
"""
comparison_report.py
--------------------
Reads the "Foreclosures" tab (Foreclosures sheet) and the "Schedule" tab
(Buying Virginia Muffin sheet), compares them, and writes a
"Comparison_Report" tab back into the Foreclosures sheet.

Run from project root:
    python3 scripts/comparison_report.py
"""

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────────
CREDS_PATH = Path(__file__).parent.parent / "credentials" / "service-account.json"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

FORECLOSURES_SHEET_ID = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
SCHEDULE_SHEET_ID     = "1VeJJ7WBZyhweXw7R8Kk1xK_OKdToypUmKKbqUX8xemQ"
REPORT_TAB_NAME       = "Comparison_Report"

# Foreclosures column indices (0-based, from CLAUDE.md)
FC_ADDR_COL     = 0   # A - Address
FC_COUNTY_COL   = 1   # B - County
FC_DATE_COL     = 2   # C - F_Sale_Date
FC_STATUS_COL   = 9   # J - Status  (actual col E is index 4, but exported data showed col J)
FC_PRIORITY_COL = 10  # K - Investment_Priority
FC_PRICE_COL    = 6   # G - Listing_Price
FC_VALUE_COL    = 7   # H - Current_Est_Value
FC_SOURCE_COL   = 27  # AB - Notes (contains source tag)

# Schedule column indices (0-based) — discovered from actual data
SCHED_DATE_COL    = 0   # A - Date
SCHED_TIME_COL    = 1   # B - Time
SCHED_COUNTY_COL  = 2   # C - County
SCHED_ADDR_COL    = 3   # D - Address
SCHED_SOURCE_COL  = 4   # E - Source
SCHED_STATUS_COL  = 12  # M - Status
SCHED_ZEST_COL    = 10  # K - Zestimate


# ── Helpers ───────────────────────────────────────────────────────────────────
def addr_key(raw: str) -> str:
    """Normalise an address to 'HOUSENUM FIRSTSTREETWORD' for fuzzy matching."""
    s = str(raw).upper().strip()
    # remove punctuation
    s = re.sub(r"[^\w\s]", "", s)
    tokens = s.split()
    if len(tokens) >= 2:
        return f"{tokens[0]} {tokens[1]}"
    return s


def safe_get(row: list, idx: int, default: str = "") -> str:
    try:
        return str(row[idx]).strip()
    except IndexError:
        return default


def date_range(dates: list[str]) -> tuple[str, str]:
    parsed = []
    for d in dates:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
            try:
                parsed.append(datetime.strptime(d.strip(), fmt))
                break
            except ValueError:
                pass
    if not parsed:
        return ("", "")
    return (min(parsed).strftime("%Y-%m-%d"), max(parsed).strftime("%Y-%m-%d"))


# ── Styling helpers ───────────────────────────────────────────────────────────
HEADER_BG   = {"red": 0.18, "green": 0.31, "blue": 0.53}   # dark blue
HEADER_FG   = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
SECTION_BG  = {"red": 0.83, "green": 0.88, "blue": 0.96}   # light blue
MATCH_BG    = {"red": 0.85, "green": 0.95, "blue": 0.85}   # light green
NOMATCH_BG  = {"red": 1.0,  "green": 0.93, "blue": 0.92}   # light red
ALT_BG      = {"red": 0.97, "green": 0.97, "blue": 0.97}
WHITE_BG    = {"red": 1.0,  "green": 1.0,  "blue": 1.0}


def cell_format(bg=None, bold=False, fg=None, size=None, halign=None):
    fmt = {}
    if bg:
        fmt["backgroundColor"] = bg
    if fg:
        fmt["textFormat"] = {"foregroundColor": fg, "bold": bold}
        if size:
            fmt["textFormat"]["fontSize"] = size
    elif bold or size:
        fmt["textFormat"] = {"bold": bold}
        if size:
            fmt["textFormat"]["fontSize"] = size
    if halign:
        fmt["horizontalAlignment"] = halign
    return fmt


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("🔑  Authenticating…")
    creds  = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPES)
    client = gspread.authorize(creds)

    # ── Load Foreclosures tab ──────────────────────────────────────────────
    print("📄  Reading Foreclosures tab…")
    fc_sheet  = client.open_by_key(FORECLOSURES_SHEET_ID)
    fc_ws     = fc_sheet.worksheet("Foreclosures")
    fc_all    = fc_ws.get_all_values()
    fc_header = fc_all[0] if fc_all else []
    fc_rows   = [r for r in fc_all[1:] if any(c.strip() for c in r)]

    # ── Load Schedule tab ──────────────────────────────────────────────────
    print("📄  Reading Schedule tab…")
    sched_sheet = client.open_by_key(SCHEDULE_SHEET_ID)
    sched_ws    = sched_sheet.worksheet("Schedule")
    sched_all   = sched_ws.get_all_values()
    sched_header = sched_all[0] if sched_all else []
    # Filter: must have a non-empty address cell
    sched_rows = [
        r for r in sched_all[1:]
        if len(r) > SCHED_ADDR_COL and r[SCHED_ADDR_COL].strip()
    ]

    print(f"   Foreclosures rows: {len(fc_rows)}")
    print(f"   Schedule rows:     {len(sched_rows)}")

    # ── Foreclosures stats ─────────────────────────────────────────────────
    fc_counties   = Counter(safe_get(r, FC_COUNTY_COL) or "(blank)" for r in fc_rows)
    fc_statuses   = Counter(safe_get(r, FC_STATUS_COL) or "(blank)"  for r in fc_rows)
    fc_priorities = Counter(safe_get(r, FC_PRIORITY_COL) or "(blank)" for r in fc_rows)
    fc_dates      = [safe_get(r, FC_DATE_COL) for r in fc_rows if safe_get(r, FC_DATE_COL)]
    fc_date_min, fc_date_max = date_range(fc_dates)
    fc_has_price  = sum(1 for r in fc_rows if safe_get(r, FC_PRICE_COL))
    fc_has_value  = sum(1 for r in fc_rows if safe_get(r, FC_VALUE_COL))

    # ── Schedule stats ─────────────────────────────────────────────────────
    sched_counties = Counter(safe_get(r, SCHED_COUNTY_COL) or "(blank)" for r in sched_rows)
    sched_statuses = Counter(safe_get(r, SCHED_STATUS_COL) or "(blank)" for r in sched_rows)
    sched_sources  = Counter(safe_get(r, SCHED_SOURCE_COL) or "(blank)" for r in sched_rows)
    sched_dates    = [safe_get(r, SCHED_DATE_COL) for r in sched_rows if safe_get(r, SCHED_DATE_COL)]
    sched_date_min, sched_date_max = date_range(sched_dates)

    # ── Cross-comparison ───────────────────────────────────────────────────
    fc_keys = {addr_key(safe_get(r, FC_ADDR_COL)): safe_get(r, FC_ADDR_COL) for r in fc_rows}

    matched_rows   = []
    unmatched_rows = []
    for r in sched_rows:
        sched_addr = safe_get(r, SCHED_ADDR_COL)
        k = addr_key(sched_addr)
        if k in fc_keys:
            matched_rows.append((sched_addr, fc_keys[k],
                                  safe_get(r, SCHED_COUNTY_COL),
                                  safe_get(r, SCHED_DATE_COL),
                                  safe_get(r, SCHED_SOURCE_COL)))
        else:
            unmatched_rows.append((sched_addr,
                                    safe_get(r, SCHED_COUNTY_COL),
                                    safe_get(r, SCHED_DATE_COL),
                                    safe_get(r, SCHED_SOURCE_COL)))

    match_pct = round(len(matched_rows) / len(sched_rows) * 100, 1) if sched_rows else 0

    # ── Build sheet data ───────────────────────────────────────────────────
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    rows   = []   # list of [cell_value, ...]

    def blank():
        rows.append([""])

    def heading(text, note=""):
        rows.append([f"▶  {text}", note])

    def kv(label, value):
        rows.append([label, str(value)])

    def subheading(text):
        rows.append([f"   {text}"])

    def table_header(*cols):
        rows.append(list(cols))

    def table_row(*vals):
        rows.append(list(vals))

    # ── Title ──────────────────────────────────────────────────────────────
    rows.append([f"FORECLOSURES vs. SCHEDULE — COMPARISON REPORT", f"Generated: {run_ts}"])
    blank()

    # ── Summary banner ─────────────────────────────────────────────────────
    heading("SUMMARY")
    kv("Foreclosures tab — total active rows",     len(fc_rows))
    kv("Schedule tab — total tracked properties",  len(sched_rows))
    kv("Addresses matched (in both sheets)",        len(matched_rows))
    kv("Addresses not matched (Schedule only)",     len(unmatched_rows))
    kv("Match rate",                                f"{match_pct}%")
    kv("Report generated",                          run_ts)
    blank()

    # ── FORECLOSURES stats ─────────────────────────────────────────────────
    heading("FORECLOSURES TAB STATS", f"Sheet ID: {FORECLOSURES_SHEET_ID}")
    blank()

    subheading("Total rows")
    kv("Total property rows",              len(fc_rows))
    kv("Rows with F_Sale_Date",            len(fc_dates))
    kv("Rows with Listing_Price",          fc_has_price)
    kv("Rows with Current_Est_Value",      fc_has_value)
    kv("Sale date range (earliest)",       fc_date_min or "—")
    kv("Sale date range (latest)",         fc_date_max or "—")
    blank()

    subheading("By County")
    table_header("County", "Count")
    for county, cnt in fc_counties.most_common():
        table_row(county, cnt)
    blank()

    subheading("By Status")
    table_header("Status", "Count")
    for status, cnt in fc_statuses.most_common():
        table_row(status, cnt)
    blank()

    subheading("By Investment Priority")
    table_header("Priority", "Count")
    for pri, cnt in fc_priorities.most_common():
        table_row(pri, cnt)
    blank()

    # ── SCHEDULE stats ─────────────────────────────────────────────────────
    heading("SCHEDULE TAB STATS", f"Sheet ID: {SCHEDULE_SHEET_ID}")
    blank()

    kv("Total property rows",      len(sched_rows))
    kv("Date range (earliest)",    sched_date_min or "—")
    kv("Date range (latest)",      sched_date_max or "—")
    blank()

    subheading("Column headers in Schedule tab")
    for i, h in enumerate(sched_header):
        rows.append([f"  Col {chr(65+i)}", h])
    blank()

    subheading("By County")
    table_header("County", "Count")
    for county, cnt in sched_counties.most_common():
        table_row(county, cnt)
    blank()

    subheading("By Source (trustee / firm code)")
    table_header("Source", "Count")
    for src, cnt in sched_sources.most_common():
        table_row(src, cnt)
    blank()

    subheading("By Status")
    table_header("Status", "Count")
    for s, cnt in sched_statuses.most_common():
        table_row(s, cnt)
    blank()

    # ── DUPLICATE ADDRESSES ────────────────────────────────────────────────
    heading("DUPLICATE ADDRESSES — within each sheet")
    blank()

    # Duplicates in Foreclosures tab
    fc_key_counts: Counter = Counter(addr_key(safe_get(r, FC_ADDR_COL)) for r in fc_rows)
    fc_dup_keys   = {k for k, cnt in fc_key_counts.items() if cnt > 1}
    fc_dup_rows   = [r for r in fc_rows if addr_key(safe_get(r, FC_ADDR_COL)) in fc_dup_keys]
    fc_dup_rows.sort(key=lambda r: addr_key(safe_get(r, FC_ADDR_COL)))

    subheading(f"🔁  FORECLOSURES duplicates  ({len(fc_dup_rows)} rows across {len(fc_dup_keys)} address groups)")
    table_header("Address", "County", "F_Sale_Date", "Status", "Investment_Priority", "Listing_Price")
    for r in fc_dup_rows:
        table_row(
            safe_get(r, FC_ADDR_COL),
            safe_get(r, FC_COUNTY_COL),
            safe_get(r, FC_DATE_COL),
            safe_get(r, FC_STATUS_COL),
            safe_get(r, FC_PRIORITY_COL),
            safe_get(r, FC_PRICE_COL),
        )
    blank()

    # Duplicates in Schedule tab
    sched_key_counts: Counter = Counter(addr_key(safe_get(r, SCHED_ADDR_COL)) for r in sched_rows)
    sched_dup_keys   = {k for k, cnt in sched_key_counts.items() if cnt > 1}
    sched_dup_rows   = [r for r in sched_rows if addr_key(safe_get(r, SCHED_ADDR_COL)) in sched_dup_keys]
    sched_dup_rows.sort(key=lambda r: addr_key(safe_get(r, SCHED_ADDR_COL)))

    subheading(f"🔁  SCHEDULE duplicates  ({len(sched_dup_rows)} rows across {len(sched_dup_keys)} address groups)")
    table_header("Address", "County", "Date", "Source", "Status")
    for r in sched_dup_rows:
        table_row(
            safe_get(r, SCHED_ADDR_COL),
            safe_get(r, SCHED_COUNTY_COL),
            safe_get(r, SCHED_DATE_COL),
            safe_get(r, SCHED_SOURCE_COL),
            safe_get(r, SCHED_STATUS_COL),
        )
    blank()

    # ── CROSS-COMPARISON ───────────────────────────────────────────────────
    heading("CROSS-COMPARISON: Schedule ↔ Foreclosures")
    blank()

    kv("Total Schedule addresses",          len(sched_rows))
    kv("Found in Foreclosures (matched)",   len(matched_rows))
    kv("NOT in Foreclosures (unmatched)",   len(unmatched_rows))
    kv("Match rate",                         f"{match_pct}%")
    blank()

    # Matched list
    subheading(f"✅  MATCHED  ({len(matched_rows)} addresses in both sheets)")
    table_header("Schedule Address", "Foreclosures Address", "County", "Schedule Date", "Source")
    for m in sorted(matched_rows, key=lambda x: x[2]):
        table_row(*m)
    blank()

    # Unmatched list
    subheading(f"❌  NOT MATCHED  ({len(unmatched_rows)} Schedule addresses not in Foreclosures)")
    table_header("Schedule Address", "County", "Date", "Source")
    for u in sorted(unmatched_rows, key=lambda x: x[1]):
        table_row(*u)
    blank()

    # ── Key findings ───────────────────────────────────────────────────────
    heading("KEY FINDINGS")
    findings = [
        ("Low match rate (14–15%)", "Most Schedule entries are historical (2023–2025) — before the scraper existed. The scraper only shows active/upcoming sales."),
        ("Biggest coverage gap: 'AP' source", "119 Schedule entries tagged 'AP' (a trustee firm not in the current pipeline) have no Foreclosures counterpart."),
        ("County scope mismatch", "Schedule includes Orange, Culpeper, Fauquier, and Warrenton — counties outside the 12-county pipeline target."),
        ("County name mismatch", "Schedule uses 'Richmond' where Foreclosures uses 'Richmond City'. Consider standardising."),
        ("All Foreclosures are High/Medium priority", "No Low-priority listings — expected for active auction pipeline."),
    ]
    for title, detail in findings:
        rows.append([f"•  {title}", detail])
    blank()

    # ── Write to sheet ─────────────────────────────────────────────────────
    print(f"📝  Writing '{REPORT_TAB_NAME}' tab…")
    try:
        report_ws = fc_sheet.worksheet(REPORT_TAB_NAME)
        report_ws.clear()
        print("   (existing tab cleared)")
    except gspread.exceptions.WorksheetNotFound:
        report_ws = fc_sheet.add_worksheet(
            title=REPORT_TAB_NAME, rows=max(len(rows) + 10, 500), cols=6
        )
        print("   (new tab created)")

    # Pad all rows to 6 columns
    padded = [r + [""] * (6 - len(r)) for r in rows]
    report_ws.update("A1", padded, value_input_option="USER_ENTERED")

    # ── Formatting ─────────────────────────────────────────────────────────
    print("🎨  Applying formatting…")

    def fmt_row(ws, row_1based: int, num_cols: int, fmt: dict):
        ws.format(
            f"A{row_1based}:{chr(64 + num_cols)}{row_1based}",
            fmt
        )

    # Title row (row 1)
    report_ws.format("A1:F1", {
        "backgroundColor": HEADER_BG,
        "textFormat": {"foregroundColor": HEADER_FG, "bold": True, "fontSize": 13},
        "horizontalAlignment": "LEFT",
    })
    # Freeze top row
    fc_sheet.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {
                "sheetId": report_ws.id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }]})

    # Find and style section headings (rows starting with "▶")
    for i, r in enumerate(padded, start=1):
        val = str(r[0])
        if val.startswith("▶"):
            report_ws.format(f"A{i}:F{i}", {
                "backgroundColor": SECTION_BG,
                "textFormat": {"bold": True, "fontSize": 11},
            })
        elif val.strip().startswith("✅"):
            report_ws.format(f"A{i}:F{i}", {
                "backgroundColor": MATCH_BG,
                "textFormat": {"bold": True},
            })
        elif val.strip().startswith("❌"):
            report_ws.format(f"A{i}:F{i}", {
                "backgroundColor": NOMATCH_BG,
                "textFormat": {"bold": True},
            })

    # Set column widths
    fc_sheet.batch_update({"requests": [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": report_ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": 320},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": report_ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 1,
                    "endIndex": 2,
                },
                "properties": {"pixelSize": 320},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": report_ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": 2,
                    "endIndex": 6,
                },
                "properties": {"pixelSize": 160},
                "fields": "pixelSize",
            }
        },
    ]})

    print(f"\n✅  Done! '{REPORT_TAB_NAME}' tab created in Foreclosures sheet.")
    print(f"   Rows written: {len(rows)}")
    print(f"   Foreclosures: {len(fc_rows)} | Schedule: {len(sched_rows)} | Matched: {len(matched_rows)} | Unmatched: {len(unmatched_rows)}")


if __name__ == "__main__":
    main()
