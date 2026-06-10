#!/usr/bin/env python3
"""
side_by_side_report.py
----------------------
Reads the "Foreclosures" tab and the "Schedule" tab, then writes a
"Side_By_Side_Report" tab into the Foreclosures sheet.

Every comparison dimension (County, Status, Priority, Source, etc.)
is shown in a single table with columns:
  Dimension | Foreclosures Count | Schedule Count | Difference

Run from project root:
    python3 scripts/side_by_side_report.py
"""

import re
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
REPORT_TAB_NAME       = "Side_By_Side_Report"

# Foreclosures column indices (0-based)
FC_ADDR_COL     = 0   # A - Address
FC_COUNTY_COL   = 1   # B - County
FC_DATE_COL     = 2   # C - F_Sale_Date
FC_STATUS_COL   = 9   # J - Status
FC_PRIORITY_COL = 10  # K - Investment_Priority
FC_PRICE_COL    = 6   # G - Listing_Price
FC_VALUE_COL    = 7   # H - Current_Est_Value
FC_SOURCE_COL   = 27  # AB - Notes (source tag lives here)

# Schedule column indices (0-based)
SCHED_DATE_COL   = 0
SCHED_COUNTY_COL = 2
SCHED_ADDR_COL   = 3
SCHED_SOURCE_COL = 4
SCHED_STATUS_COL = 12
SCHED_ZEST_COL   = 10

# Colors
DARK_BLUE  = {"red": 0.18, "green": 0.31, "blue": 0.53}
WHITE      = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
LIGHT_BLUE = {"red": 0.83, "green": 0.88, "blue": 0.96}
LIGHT_GRAY = {"red": 0.95, "green": 0.95, "blue": 0.95}
GREEN_BG   = {"red": 0.85, "green": 0.95, "blue": 0.85}
RED_BG     = {"red": 1.0,  "green": 0.92, "blue": 0.92}
YELLOW_BG  = {"red": 1.0,  "green": 0.98, "blue": 0.82}
FC_COL_BG  = {"red": 0.90, "green": 0.95, "blue": 1.0}   # blue tint  — Foreclosures
SC_COL_BG  = {"red": 0.95, "green": 1.0,  "blue": 0.90}  # green tint — Schedule


def safe_get(row, idx, default=""):
    try:
        return str(row[idx]).strip()
    except IndexError:
        return default


def addr_key(raw):
    s = re.sub(r"[^\w\s]", "", str(raw).upper().strip())
    tokens = s.split()
    return f"{tokens[0]} {tokens[1]}" if len(tokens) >= 2 else s


def side_by_side_table(fc_counter, sc_counter, label="Value"):
    """
    Merge two counters into rows: [label, fc_count, sc_count, diff]
    All keys from either counter are included, sorted by fc_count desc.
    """
    all_keys = sorted(
        set(fc_counter) | set(sc_counter),
        key=lambda k: -(fc_counter.get(k, 0) + sc_counter.get(k, 0)),
    )
    rows = []
    for k in all_keys:
        fc = fc_counter.get(k, 0)
        sc = sc_counter.get(k, 0)
        diff = fc - sc
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        rows.append([k or "(blank)", fc, sc, diff_str])
    # Totals row
    fc_total = sum(fc_counter.values())
    sc_total = sum(sc_counter.values())
    diff_total = fc_total - sc_total
    rows.append(["TOTAL", fc_total, sc_total,
                 f"+{diff_total}" if diff_total > 0 else str(diff_total)])
    return rows


def main():
    print("🔑  Authenticating…")
    creds  = Credentials.from_service_account_file(str(CREDS_PATH), scopes=SCOPES)
    client = gspread.authorize(creds)

    # ── Load sheets ────────────────────────────────────────────────────────
    print("📄  Reading Foreclosures tab…")
    fc_sheet = client.open_by_key(FORECLOSURES_SHEET_ID)
    fc_ws    = fc_sheet.worksheet("Foreclosures")
    fc_all   = fc_ws.get_all_values()
    fc_rows  = [r for r in fc_all[1:] if any(c.strip() for c in r)]

    print("📄  Reading Schedule tab…")
    sc_sheet  = client.open_by_key(SCHEDULE_SHEET_ID)
    sc_ws     = sc_sheet.worksheet("Schedule")
    sc_all    = sc_ws.get_all_values()
    sc_header = sc_all[0] if sc_all else []
    sc_rows   = [
        r for r in sc_all[1:]
        if len(r) > SCHED_ADDR_COL and r[SCHED_ADDR_COL].strip()
    ]

    print(f"   Foreclosures: {len(fc_rows)} rows | Schedule: {len(sc_rows)} rows")

    # ── Build counters ─────────────────────────────────────────────────────
    fc_county   = Counter(safe_get(r, FC_COUNTY_COL)   or "(blank)" for r in fc_rows)
    fc_status   = Counter(safe_get(r, FC_STATUS_COL)   or "(blank)" for r in fc_rows)
    fc_priority = Counter(safe_get(r, FC_PRIORITY_COL) or "(blank)" for r in fc_rows)

    sc_county   = Counter(safe_get(r, SCHED_COUNTY_COL) or "(blank)" for r in sc_rows)
    sc_status   = Counter(safe_get(r, SCHED_STATUS_COL) or "(blank)" for r in sc_rows)
    sc_source   = Counter(safe_get(r, SCHED_SOURCE_COL) or "(blank)" for r in sc_rows)

    # Source: Foreclosures source tag is embedded in Notes (col AB).
    # Extract the bracketed source tag, e.g. "[PNV]" or "[Column.us – richmond]"
    def extract_source(notes):
        m = re.search(r"\[([^\]]+)\]", notes)
        return m.group(1).strip() if m else "(unknown)"

    fc_source = Counter(
        extract_source(safe_get(r, FC_SOURCE_COL)) for r in fc_rows
    )

    # ── Address cross-match ────────────────────────────────────────────────
    fc_keys = {addr_key(safe_get(r, FC_ADDR_COL)) for r in fc_rows}
    matched = sum(
        1 for r in sc_rows
        if addr_key(safe_get(r, SCHED_ADDR_COL)) in fc_keys
    )
    unmatched   = len(sc_rows) - matched
    match_pct   = round(matched / len(sc_rows) * 100, 1) if sc_rows else 0

    # Date ranges
    def date_range_str(vals):
        parsed = []
        for v in vals:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
                try:
                    parsed.append(datetime.strptime(v.strip(), fmt))
                    break
                except ValueError:
                    pass
        if not parsed:
            return "—", "—"
        return min(parsed).strftime("%Y-%m-%d"), max(parsed).strftime("%Y-%m-%d")

    fc_dates = [safe_get(r, FC_DATE_COL) for r in fc_rows if safe_get(r, FC_DATE_COL)]
    sc_dates = [safe_get(r, SCHED_DATE_COL) for r in sc_rows if safe_get(r, SCHED_DATE_COL)]
    fc_dmin, fc_dmax = date_range_str(fc_dates)
    sc_dmin, sc_dmax = date_range_str(sc_dates)

    # ── Assemble output rows ───────────────────────────────────────────────
    run_ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    output = []   # list of [A, B, C, D, E]

    def blank():
        output.append(["", "", "", "", ""])

    def title(text):
        output.append([text, "", f"Generated: {run_ts}", "", ""])

    def section(text):
        output.append([f"▶  {text}", "", "", "", ""])

    def col_headers(*labels):
        output.append(list(labels) + [""] * (5 - len(labels)))

    def data_row(*vals):
        output.append(list(vals) + [""] * (5 - len(vals)))

    # ── Title ──────────────────────────────────────────────────────────────
    title("FORECLOSURES vs. SCHEDULE — SIDE-BY-SIDE REPORT")
    blank()

    # ── Summary ───────────────────────────────────────────────────────────
    section("SUMMARY")
    col_headers("Metric", "Foreclosures", "Schedule", "Difference")
    data_row("Total property rows",       len(fc_rows), len(sc_rows),
             f"{len(fc_rows)-len(sc_rows):+d}")
    data_row("Unique counties",           len(fc_county), len(sc_county),
             f"{len(fc_county)-len(sc_county):+d}")
    data_row("Rows with sale date",       len(fc_dates), len(sc_dates), "")
    data_row("Date range — earliest",     fc_dmin,        sc_dmin, "")
    data_row("Date range — latest",       fc_dmax,        sc_dmax, "")
    data_row("Addresses matched (overlap)", matched, matched, "")
    data_row("Addresses in Schedule only", "",       unmatched, "")
    data_row("Match rate",                 "",       f"{match_pct}%", "")
    blank()

    # ── By County ─────────────────────────────────────────────────────────
    section("BY COUNTY")
    col_headers("County", "Foreclosures", "Schedule", "Diff (FC − Sched)")
    for row in side_by_side_table(fc_county, sc_county, "County"):
        output.append(row + [""] * (5 - len(row)))
    blank()

    # ── By Status ─────────────────────────────────────────────────────────
    section("BY STATUS")
    col_headers("Status", "Foreclosures", "Schedule", "Diff")
    for row in side_by_side_table(fc_status, sc_status, "Status"):
        output.append(row + [""] * (5 - len(row)))
    blank()

    # ── By Investment Priority (Foreclosures only) ─────────────────────────
    section("BY INVESTMENT PRIORITY  (Foreclosures tab only)")
    col_headers("Priority", "Foreclosures", "Schedule (n/a)", "")
    for pri, cnt in fc_priority.most_common():
        data_row(pri or "(blank)", cnt, "—")
    blank()

    # ── By Source ─────────────────────────────────────────────────────────
    section("BY SOURCE")
    col_headers("Source", "Foreclosures", "Schedule", "Diff (FC − Sched)")
    for row in side_by_side_table(fc_source, sc_source, "Source"):
        output.append(row + [""] * (5 - len(row)))
    blank()

    # ── Write to sheet ─────────────────────────────────────────────────────
    print(f"📝  Writing '{REPORT_TAB_NAME}' tab…")
    try:
        ws = fc_sheet.worksheet(REPORT_TAB_NAME)
        ws.clear()
        print("   (existing tab cleared)")
    except gspread.exceptions.WorksheetNotFound:
        ws = fc_sheet.add_worksheet(
            title=REPORT_TAB_NAME, rows=max(len(output) + 20, 300), cols=5
        )
        print("   (new tab created)")

    padded = [r + [""] * (5 - len(r)) for r in output]
    ws.update("A1", padded, value_input_option="USER_ENTERED")

    # ── Formatting ─────────────────────────────────────────────────────────
    print("🎨  Applying formatting…")

    # Title row
    ws.format("A1:E1", {
        "backgroundColor": DARK_BLUE,
        "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 13},
    })

    # Freeze header row
    fc_sheet.batch_update({"requests": [{
        "updateSheetProperties": {
            "properties": {
                "sheetId": ws.id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }]})

    # Section headings, column headers, and TOTAL rows
    requests = []
    for i, row in enumerate(padded, start=1):
        val = str(row[0])
        sheet_range = f"A{i}:E{i}"

        if val.startswith("▶"):
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 0, "endColumnIndex": 5},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": LIGHT_BLUE,
                    "textFormat": {"bold": True, "fontSize": 11},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif val in ("Metric", "County", "Status", "Priority", "Source"):
            # Column header rows — shade FC column blue, Schedule column green
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 0, "endColumnIndex": 5},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": LIGHT_GRAY,
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
            }})
            # FC column (B = index 1) tinted blue
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 1, "endColumnIndex": 2},
                "cell": {"userEnteredFormat": {"backgroundColor": FC_COL_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
            # Schedule column (C = index 2) tinted green
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 2, "endColumnIndex": 3},
                "cell": {"userEnteredFormat": {"backgroundColor": SC_COL_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
        elif val == "TOTAL":
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 0, "endColumnIndex": 5},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": LIGHT_GRAY,
                    "textFormat": {"bold": True},
                }},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }})
        elif i % 2 == 0 and val and not val.startswith("▶"):
            # Alternating row shading for data rows
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 0, "endColumnIndex": 5},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": {"red": 0.98, "green": 0.98, "blue": 0.98},
                }},
                "fields": "userEnteredFormat.backgroundColor",
            }})

        # Colour the Diff column: positive = green, negative = red
        diff_val = str(row[3]) if len(row) > 3 else ""
        if diff_val.startswith("+") and diff_val != "+0":
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 3, "endColumnIndex": 4},
                "cell": {"userEnteredFormat": {"backgroundColor": GREEN_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }})
        elif diff_val.startswith("-"):
            requests.append({"repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": i-1, "endRowIndex": i,
                          "startColumnIndex": 3, "endColumnIndex": 4},
                "cell": {"userEnteredFormat": {"backgroundColor": RED_BG}},
                "fields": "userEnteredFormat.backgroundColor",
            }})

    # Column widths: A=260, B=160, C=160, D=180, E=120
    requests.append({"updateDimensionProperties": {
        "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                  "startIndex": 0, "endIndex": 1},
        "properties": {"pixelSize": 260}, "fields": "pixelSize",
    }})
    for col_idx, width in [(1, 160), (2, 160), (3, 180), (4, 120)]:
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                      "startIndex": col_idx, "endIndex": col_idx + 1},
            "properties": {"pixelSize": width}, "fields": "pixelSize",
        }})

    # Center-align numeric columns B, C, D
    requests.append({"repeatCell": {
        "range": {"sheetId": ws.id, "startRowIndex": 1,
                  "startColumnIndex": 1, "endColumnIndex": 4},
        "cell": {"userEnteredFormat": {"horizontalAlignment": "CENTER"}},
        "fields": "userEnteredFormat.horizontalAlignment",
    }})

    fc_sheet.batch_update({"requests": requests})

    print(f"\n✅  Done! '{REPORT_TAB_NAME}' tab written.")
    print(f"   Rows: {len(output)} | FC: {len(fc_rows)} | Sched: {len(sc_rows)} | Matched: {matched} ({match_pct}%)")


if __name__ == "__main__":
    main()
