#!/usr/bin/env python3
"""
create_missing_tab.py
Creates (or recreates) a 'Schedule_Missing' worksheet tab in the Foreclosures
Google Sheet and writes the 111 rows that were absent from the main dashboard.

Run:
    python3 /Users/jarvis/Documents/Claude/Foreclosures/scripts/create_missing_tab.py
"""

import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────────────────────
SERVICE_ACCOUNT_FILE = "/Users/jarvis/Documents/Claude/Foreclosures/credentials/service-account.json"
SPREADSHEET_ID       = "1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c"
TAB_NAME             = "Schedule_Missing"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Header ────────────────────────────────────────────────────────────────────
HEADER = [
    "Date", "Time", "County", "Address", "Source",
    "Trustee_Contact", "Original_Note_Date", "Original_Note_Volume",
    "Phone_Seller", "Phone_Call_Made", "Zestimate", "Sewer", "Status", "Assigned",
]

# ── Row data (extracted from Schedule tab) ────────────────────────────────────
# Columns: Date | Time | County | Address | Source | Trustee_Contact |
#          Original_Note_Date | Original_Note_Volume | Phone_Seller |
#          Phone_Call_Made | Zestimate | Sewer | Status | Assigned
ROWS = [
    # ── 6/1/2026 ─────────────────────────────────────────────────────────────
    ["6/1/2026", "1:00 PM", "Fredericksburg", "714 Bunker Hill St Fredericksburg VA 22401", "BS", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "1:00 PM", "Henrico",         "2836 Neale St Richmond VA 23223",             "Tromberg", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Chesterfield",    "4107 Laurelwood Rd North Chesterfield VA 23234", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "2910 Triple Notch Ct Henrico VA 23233",       "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "11804 Britain Way Henrico VA 23238",          "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "8700 Hermitage Trace Cir Richmond VA 23228",  "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "348 Argyll Cir Highland Springs VA 23075",    "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "2965 Mountain Rd Glen Allen VA 23060",        "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "11454 River Run Dr Glen Allen VA 23059",      "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "4601 Eanes Ln Henrico VA 23231",              "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "22 Rodes Ave Sandston VA 23150",              "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "504 Mango Ct Richmond VA 23223",              "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "8201 Hungary Rd Glen Allen VA 23060",         "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Chesterfield",    "6524 Greyhaven Dr North Chesterfield VA 23234", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Chesterfield",    "701 Quarterparth Ln South Chesterfield VA 23834", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "200 Seaton Dr Richmond VA 23223",             "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Chesterfield",    "6003 Belrun Pl North Chesterfield VA 23234",  "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "2:30 PM", "Henrico",         "410 Kramer Dr Highland Springs VA 23075",     "AP", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "3:30 PM", "Henrico",         "8209 Hunters Meadow Dr Henrico VA 23231",     "Vylla Solutions", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "",        "Louisa",          "704 Kinneytown Rd Mineral VA 23117",          "Auction.com", "", "", "", "", "", "", "", "", ""],
    ["6/1/2026", "",        "Henrico",         "228 N Pine Ave Henrico VA 23075",             "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/2/2026 ─────────────────────────────────────────────────────────────
    ["6/2/2026", "11:00 AM", "Richmond",       "3015 Broad Roack Blvd Richmond VA 23224",     "Grant", "5405863807", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "11:00 AM", "Culpeper",       "15385 Turkey Trak Culpeper VA 22701",         "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "12:00 PM", "Stafford",       "14 Catherine Ln Stafford VA 22554",           "BS", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "",         "Orange",         "27629 Tatum Rd Unionville VA 22567",          "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "",         "Spotsylvania",   "10129 Duerson Ln Partlow VA 22534",           "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "",         "Chesterfield",   "9323 Edington Dr North Chesterfield VA 23237","ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "",         "Henrico",        "5514 White Oak Rd Sandston VA 23150",         "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/2/2026", "",         "Chesterfield",   "10211 Elokomin Ave Richmond VA 23237",        "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/3/2026 ─────────────────────────────────────────────────────────────
    ["6/3/2026", "10:00 AM", "Henrico",        "4703 Mill Park Dr Glen Allen VA 23060",       "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "10:00 AM", "Henrico",        "12920 Copperas Ln Henrico VA 23233",          "Lenox", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "10:45 AM", "Richmond",       "114 E 37th St Richmond VA 23224",             "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "1:00 PM",  "Spotsylvania",   "6416 Maxie Lee Ct Spotsylvania VA 22551",     "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "1:00 PM",  "Spotsylvania",   "7751 Waterford Dr Spotsylvania VA 22553",     "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "",         "Henrico",        "1305 Mormac Rd Richmond VA 23229",            "Auction.com", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "",         "Spotsylvania",   "9307 Spring Hill Ln Fredericksburg VA 22408", "Xome", "", "", "", "", "", "", "", "", ""],
    ["6/3/2026", "",         "Chesterfield",   "1015 Point of Rocks Rd Chester VA 23836",     "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/4/2026 ─────────────────────────────────────────────────────────────
    ["6/4/2026", "11:00 AM", "Fauquier",       "7553 Millpond Ct Warrenton VA 20187",         "RA", "", "", "", "", "", "", "", "", ""],
    ["6/4/2026", "12:30 PM", "Chesterfield",   "4810 Wilconna Rd Chesterfield VA 23832",      "Tromberg", "", "", "", "", "", "", "", "", ""],
    ["6/4/2026", "12:30 PM", "Louisa",         "2059 W Green Springs Rd Gordonsville VA 22942", "Lenox", "", "", "", "", "", "", "", "", ""],
    ["6/4/2026", "1:00 PM",  "Chesterfield",   "20900 Brickhouse Dr South Chesterfield VA 23803", "BS", "", "", "", "", "", "", "", "", ""],

    # ── 6/5/2026 ─────────────────────────────────────────────────────────────
    ["6/5/2026", "10:30 AM", "Louisa",         "253 Will Johnson Rd Louisa VA 23093",         "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/5/2026", "12:30 PM", "Louisa",         "227 Ellisville Dr Louisa VA 23093",           "Tromberg", "", "", "", "", "", "", "", "", ""],

    # ── 6/8/2026 ─────────────────────────────────────────────────────────────
    ["6/8/2026", "2:30 PM",  "Henrico",        "1860 Graves Rd Sandston VA 23150",            "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Chesterfield",   "5926 E Stonepath Garden Dr Chester VA 23831", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Richmond",       "1803 Dinwiddie Ave Richmond VA 23224",        "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Richmond",       "3203 Edgewood Ave Richmond VA 23222",         "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Chesterfield",   "10400 Crooked Branch Terr North Chesterfield VA 23237", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Chesterfield",   "6013 Sara Kay Dr North Chesterfield VA 23237","AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Henrico",        "2305 Brockway Ln Richmond VA 23223",          "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Chesterfield",   "13321 Kingsmill Rd Midlothian VA 23113",      "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Richmond",       "3805 Redstone Dr Richmond VA 23294",          "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "2:30 PM",  "Richmond",       "87 Erich Rd Richmond VA 23225",               "BHL", "HUD bids $219,586.35 703 796-1341 x144", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "3:45 PM",  "Hanover",        "9212 Stephens Manor Dr Mechanicsville VA 23116", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "",         "Louisa",         "704 Kinneytown Rd Mineral VA 23117",          "Auction.com", "", "", "", "", "", "", "", "", ""],
    ["6/8/2026", "",         "Henrico",        "228 N Pine Ave Henrico VA 23075",             "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/9/2026 ─────────────────────────────────────────────────────────────
    ["6/9/2026", "11:00 AM", "Culpeper",       "18020 Albert Dr Culpeper VA 22701",           "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "3:00 PM",  "Stafford",       "25 Woodmont Ct Stafford VA 22554",            "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "3:15 PM",  "Stafford",       "9 Kelley Rd Fredericksburg VA 22405",         "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "3:30 PM",  "Stafford",       "93 Brooke Crest Ln Stafford VA 22554",        "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "4:30 PM",  "Spotsylvania",   "12727 Norwood Dr Fredericksburg VA 22407",    "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "",         "Orange",         "27629 Tatum Rd Unionville VA 22567",          "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "",         "Henrico",        "5514 White Oak Rd Sandston VA 23150",         "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "",         "Spotsylvania",   "10129 Duerson Ln Partlow VA 22534",           "ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "",         "Chesterfield",   "9323 Edington Dr North Chesterfield VA 23237","ServiceLink", "", "", "", "", "", "", "", "", ""],
    ["6/9/2026", "",         "Chesterfield",   "10211 Elokomin Ave Richmond VA 23237",        "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/10/2026 ────────────────────────────────────────────────────────────
    ["6/10/2026", "10:00 AM", "Stafford",      "1502 Courthouse Rd Stafford VA 22554",        "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "10:00 AM", "Henrico",       "10613 Sherwin Pl Glen Allen VA 23059",        "Lenox", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "10:00 AM", "Henrico",       "8513 Holly Hill Rd Henrico VA 23229",         "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "11:30 AM", "Chesterfield",  "6700 Brambleton Rd Chesterfield VA 23832",    "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "12:00 PM", "Richmond",      "1905 & 2907 Second Ave Richmond VA 23222",    "Orlans", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "12:30 PM", "King George",   "6522 Wheeler Dr King George VA 22485",        "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "1:00 PM",  "Richmond",      "1501 W Cary St & 1503 W Cary St Richmond VA 23220", "Mclemore", "804 420-6330/6314", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "4:15 PM",  "Stafford",      "51 Christopher Way Stafford VA 22554",        "AP", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "",         "Henrico",       "1305 Mormac Rd Richmond VA 23229",            "Auction.com", "", "", "", "", "", "", "", "", ""],
    ["6/10/2026", "",         "Chesterfield",  "1015 Point of Rocks Rd Chester VA 23836",     "Xome", "", "", "", "", "", "", "", "", ""],

    # ── 6/11/2026 ────────────────────────────────────────────────────────────
    ["6/11/2026", "12:30 PM", "Chesterfield",  "8601 River Rd South Chesterfield VA 23803",   "WP", "", "", "", "", "", "", "", "", ""],
    ["6/11/2026", "1:00 PM",  "Chesterfield",  "14435 Hancock Towns Dr Chesterfield VA 23832","BS", "", "", "", "", "", "", "", "", ""],

    # ── 6/12/2026 ────────────────────────────────────────────────────────────
    ["6/12/2026", "3:45 PM",  "Richmond",      "5101 Parker St & 1301 Darbytown Rd Richmond VA 23231", "BS", "", "", "", "", "", "", "", "", ""],

    # ── 6/15/2026 ────────────────────────────────────────────────────────────
    ["6/15/2026", "10:00 AM", "Caroline",      "21510 Sparta Rd Milford VA 22514",            "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "10:00 AM", "Caroline",      "11456 Paige Rd Woodford VA 22580",            "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "1:00 PM",  "Spotsylvania",  "11405 Gordon Rd Fredericksburg VA 22407",     "RAS", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "1:00 PM",  "Henrico",       "5309 Wellington Ridge Rd Richmond VA 23231",  "WP", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "2:30 PM",  "Chesterfield",  "2505 Corryville Ct North Chesterfield VA 23236", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "2:30 PM",  "Henrico",       "127 N Fern Ave Henrico VA 23075",             "AP", "", "", "", "", "", "", "", "", ""],
    ["6/15/2026", "2:30 PM",  "Chesterfield",  "4225 Fordham Rd North Chesterfield VA 23236", "AP", "", "", "", "", "", "", "", "", ""],

    # ── 6/16/2026 ────────────────────────────────────────────────────────────
    ["6/16/2026", "10:00 AM", "Spotsylvania",  "4708 Wensel Rd Fredericksburg VA 22408",      "RA", "", "", "", "", "", "", "", "", ""],
    ["6/16/2026", "12:00 PM", "Stafford",      "21 Buchanan Ct Fredericksburg VA 22406",      "WP", "", "", "", "", "", "", "", "", ""],

    # ── 6/17/2026 ────────────────────────────────────────────────────────────
    ["6/17/2026", "10:00 AM", "Stafford",      "610 Holly Corner Rd Fredericksburg VA 22406", "Lenox", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "10:15 AM", "Orange",        "7555 Gold Dale Rd Locust Grove VA 22508",     "AP", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "11:30 AM", "Chesterfield",  "4101 Cara Hill Ct Chester VA 23831",          "Lenox", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "12:45 PM", "Culpeper",      "643 Holly Crest Dr Culpeper VA 22701",        "AP", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "12:45 PM", "Culpeper",      "2042 Cranberry Ln Culpeper VA 22701",         "AP", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "12:45 PM", "Culpeper",      "18266 Ragtop Rd Jeffersonton VA 22724",       "AP", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "1:00 PM",  "Spotsylvania",  "9513 Hillcrest Dr Fredericksburg VA 22407",   "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/17/2026", "2:00 PM",  "Fauquier",      "7175 McHenry Ct Remington VA 22734",          "AP", "", "", "", "", "", "", "", "", ""],

    # ── 6/18/2026 ────────────────────────────────────────────────────────────
    ["6/18/2026", "11:00 AM", "Richmond",      "1616 Bryan St Richmond VA 23223",             "Oberski", "804 697-5118", "", "", "", "", "", "", "", ""],
    ["6/18/2026", "11:30 AM", "Richmond",      "1915 4th Ave Richmond VA 23222",              "Orlans", "", "", "", "", "", "", "", "", ""],
    ["6/18/2026", "1:30 PM",  "Fauquier",      "7130 Alleghany St Warrenton VA 20187",        "DR", "", "", "", "", "", "", "", "", ""],
    ["6/18/2026", "3:00 PM",  "Fauquier",      "4750 Dumfries Rd Catlett VA 20119",           "Tromberg", "", "", "", "", "", "", "", "", ""],

    # ── 6/22/2026 ────────────────────────────────────────────────────────────
    ["6/22/2026", "9:00 AM",  "Spotsylvania",  "24 Teton Dr Fredericksburg VA 22408",         "AP", "", "", "", "", "", "", "", "", ""],
    ["6/22/2026", "9:00 AM",  "Stafford",      "221 Betty Lewis Dr Fredericksburg VA 22405",  "AP", "", "", "", "", "", "", "", "", ""],
    ["6/22/2026", "9:00 AM",  "Spotsylvania",  "10305 Bayberry Ln Spotsylvania VA 22553",     "AP", "", "", "", "", "", "", "", "", ""],
    ["6/22/2026", "12:00 PM", "Hanover",       "8391 Summer Walk Pkwy Mechanicsville VA 23116", "AP", "", "", "", "", "", "", "", "", ""],
    ["6/22/2026", "2:30 PM",  "Henrico",       "2611 Northwind Dr Henrico VA 23233",          "AP", "", "", "", "", "", "", "", "", ""],
    ["6/22/2026", "2:30 PM",  "Chesterfield",  "8406 Macandrew Terr Chesterfield VA 23838",   "AP", "", "", "", "", "", "", "", "", ""],

    # ── 6/23/2026 ────────────────────────────────────────────────────────────
    ["6/23/2026", "9:00 AM",  "Louisa",        "222 Evergreen Rd Louisa VA 23093",            "AP", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "10:00 AM", "Orange",        "3375 Germanna Hwy Locust Grove VA 22508",     "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "10:00 AM", "Chesterfield",  "3700 Maze Runner Dr #405 Midlothian VA 23112","Orlans", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "10:00 AM", "Hanover",       "7133 Lilac Ln Mechanicsville VA 23111",       "Evans", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "10:30 AM", "Henrico",       "1803 Brentwood Rd Richmond VA 23222",         "SIW", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "11:30 AM", "Chesterfield",  "9742 Cole Mill Rd North Chesterfield VA 23237","Evans", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "11:30 AM", "Chesterfield",  "4029 West Ter Chesterfield VA 23832",         "Evans", "", "", "", "", "", "", "", "", ""],
    ["6/23/2026", "12:00 PM", "Stafford",      "608 Hartwood Rd Fredericksburg VA 22406",     "BS", "", "", "", "", "", "", "", "", ""],

    # ── 6/24/2026 ────────────────────────────────────────────────────────────
    ["6/24/2026", "10:00 AM", "Stafford",      "4 Mount Vernon Ave Fredericksburg VA 22405",  "BS", "", "", "", "", "", "", "", "", ""],
    ["6/24/2026", "10:30 AM", "Chesterfield",  "14954 Dogwood Ridge Ct Chester VA 23831",     "SIW", "", "", "", "", "", "", "", "", ""],
    ["6/24/2026", "11:00 AM", "Spotsylvania",  "4101 Massaponax Church Rd Fredericksburg VA 22408", "Logs", "", "", "", "", "", "", "", "", ""],
    ["6/24/2026", "11:00 AM", "Spotsylvania",  "5929 W Copper Mountain Dr Spotsylvania VA 22553", "Logs", "", "", "", "", "", "", "", "", ""],
]

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)

    # Delete existing tab if present, then create fresh
    try:
        existing = spreadsheet.worksheet(TAB_NAME)
        spreadsheet.del_worksheet(existing)
        print(f"Deleted existing '{TAB_NAME}' tab.")
    except gspread.exceptions.WorksheetNotFound:
        pass

    ws = spreadsheet.add_worksheet(title=TAB_NAME, rows=len(ROWS) + 10, cols=len(HEADER))
    print(f"Created new worksheet '{TAB_NAME}'.")

    # Build all rows: header first, then data
    all_rows = [HEADER] + ROWS

    # Batch update — single API call
    ws.update(all_rows, "A1")

    print(f"Done — {len(ROWS)} rows written.")


if __name__ == "__main__":
    main()
