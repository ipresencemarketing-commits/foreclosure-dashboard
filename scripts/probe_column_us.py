#!/usr/bin/env python3
"""
Column.us Subdomain Probe
--------------------------
Checks a list of candidate Virginia newspaper subdomains to find
which ones are live Column.us portals with foreclosure notices.

Does NOT use Playwright — just a fast HTTP GET to each subdomain.
A live Column.us portal returns HTML containing "Powered by Column".

Usage:
    python3 /Users/jarvis/Documents/Claude/Foreclosures/scripts/probe_column_us.py
"""

import requests
import sys
import time

# ---------------------------------------------------------------------------
# Already confirmed — skip these
# ---------------------------------------------------------------------------
ALREADY_KNOWN = {
    "fredericksburg", "fredericksburgfreepress", "richmond", "starexponent",
    "vagazette", "roanoke", "newsadvance", "dailyprogress", "newsvirginian",
    "godanriver", "martinsvillebulletin", "dnronline", "westmorelandnews",
    "heraldcourier", "nvdaily", "ffxnow", "arlnow", "alxnow",
}

# ---------------------------------------------------------------------------
# Candidate Virginia newspaper subdomains to probe
# Format: ("subdomain", "Paper Name / Region")
# ---------------------------------------------------------------------------
CANDIDATES = [
    # Hampton Roads / Tidewater
    ("pilotonline",         "Virginian-Pilot (Norfolk/Virginia Beach)"),
    ("dailypress",          "Daily Press (Newport News/Hampton Roads)"),
    ("hamptonroads",        "Hampton Roads alt subdomain"),
    ("gazette",             "Gazette (Newport News/Williamsburg alt)"),
    ("smithfieldtimes",     "Smithfield Times (Isle of Wight)"),
    ("suffolknewsherald",   "Suffolk News-Herald"),
    ("franklinews",         "Franklin News-Record (Southampton)"),

    # Staunton / Shenandoah Valley
    ("newsleader",          "Staunton News Leader"),
    ("augustafreepress",    "Augusta Free Press"),
    ("shenandoahvalleyherald", "Shenandoah Valley Herald"),
    ("page",                "Page News & Courier (Luray)"),
    ("pagevalleynews",      "Page Valley News"),

    # Southwest Virginia
    ("wytheville",          "Wytheville Enterprise"),
    ("wythevilleenterprise", "Wytheville Enterprise alt"),
    ("galax",               "Galax Gazette"),
    ("galaxgazette",        "Galax Gazette alt"),
    ("bluefield",           "Bluefield Daily Telegraph"),
    ("bluefieldtelegraph",  "Bluefield Daily Telegraph alt"),
    ("richlandsnewspress",  "Richlands News-Press (Tazewell)"),
    ("newsmessenger",       "Smyth County News & Messenger"),
    ("smythcountynews",     "Smyth County News alt"),
    ("coalfield",           "Coalfield Progress (Wise County)"),
    ("coalfieldprogress",   "Coalfield Progress alt"),
    ("lonestarnews",        "Lone Star News (Lee County)"),
    ("scottcounty",         "Scott County Virginia Star"),
    ("dickensonnews",       "Dickenson Star"),

    # Northern Virginia / DC suburbs
    ("loudounnow",          "Loudoun Now"),
    ("leesburgtoday",       "Leesburg Today"),
    ("princewilliamtimes",  "Prince William Times"),
    ("potomaclocal",        "Potomac Local"),
    ("connectionnewspapers", "Connection Newspapers (NoVA)"),
    ("sungazette",          "Sun Gazette (Arlington/Fairfax)"),
    ("insidenovacom",       "InsideNOVA"),
    ("insidenova",          "InsideNOVA alt"),
    ("fauquier",            "Fauquier Times"),
    ("fauquiertimes",       "Fauquier Times alt"),
    ("rappnews",            "Rappahannock News"),
    ("rappahannock",        "Rappahannock News alt"),

    # Central Virginia
    ("cardinal",            "Cardinal News (general VA)"),
    ("cardinalnews",        "Cardinal News alt"),
    ("farmvilleherald",     "Farmville Herald (Prince Edward)"),
    ("farmville",           "Farmville Herald alt"),
    ("kenbridge",           "Kenbridge-Victoria Dispatch (Lunenburg)"),
    ("southhillenterprise", "South Hill Enterprise (Mecklenburg)"),
    ("mecklenburg",         "Mecklenburg Sun"),
    ("emporia",             "Emporia-Greensville paper"),
    ("crescentnews",        "Crescent News"),
    ("tappahannock",        "Tappahannock-area paper"),
    ("essex",               "Essex County paper"),
    ("kilmarnock",          "Kilmarnock-area (Lancaster County)"),
    ("northernneck",        "Northern Neck News"),
    ("northernnecknews",    "Northern Neck News alt"),
    ("tidewater",           "Tidewater Review (West Point)"),
    ("tidewaterreview",     "Tidewater Review alt"),
    ("mathews",             "Mathews Journal"),
    ("middlesex",           "Middlesex Southside Sentinel alt"),
    ("gloucester",          "Gloucester-Mathews Gazette-Journal"),
    ("gazettejournal",      "Gloucester Gazette-Journal alt"),

    # Piedmont / Southside
    ("orangecountyreview",  "Orange County Review"),
    ("orange",              "Orange County Review alt"),
    ("madison",             "Madison County Eagle"),
    ("madisoncounty",       "Madison County Eagle alt"),
    ("nelsongazette",       "Nelson County Times/Gazette"),
    ("nelson",              "Nelson County alt"),
    ("buckinghamcounty",    "Buckingham County paper"),
    ("appomattox",          "Appomattox Times-Virginian"),
    ("amherst",             "Amherst New-Era Progress"),
    ("amherstnewera",       "Amherst New-Era Progress alt"),
    ("bedford",             "Bedford Bulletin"),
    ("bedfordbulletin",     "Bedford Bulletin alt"),
    ("floyd",               "Floyd Press"),
    ("floydpress",          "Floyd Press alt"),
    ("giles",               "Giles News (Pearisburg)"),
    ("gilesnews",           "Giles News alt"),
    ("pulaskiledger",       "Pulaski Southwest Times"),
    ("southwesttimes",      "Southwest Times (Pulaski) alt"),
    ("carroll",             "Carroll News (Hillsville)"),
    ("grayson",             "Grayson Gazette-News"),

    # Eastern Shore
    ("easternshorepost",    "Eastern Shore Post"),
    ("easternshore",        "Eastern Shore alt"),
    ("accomack",            "Accomack/Northampton paper"),
    ("coastalreview",       "Coastal Review"),

    # Other possible Column.us patterns
    ("vapress",             "Virginia Press alt"),
    ("vanews",              "Virginia News alt"),
    ("timesdispatch",       "Richmond Times-Dispatch alt"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

def probe(subdomain: str) -> tuple[bool, int]:
    """Returns (is_column_us, http_status_code)."""
    url = f"https://{subdomain}.column.us/search?noticeType=Foreclosure+Sale"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        is_column = "Powered by Column" in r.text or "column.us" in r.text.lower() or "enotice" in r.text.lower()
        return is_column, r.status_code
    except Exception:
        return False, 0

def main():
    print(f"\nProbing {len(CANDIDATES)} candidate Column.us subdomains...\n")
    print(f"{'Subdomain':<30} {'Status':>6}  Result")
    print("-" * 60)

    found = []
    for subdomain, label in CANDIDATES:
        if subdomain in ALREADY_KNOWN:
            continue
        is_live, code = probe(subdomain)
        if is_live:
            status = "✅ LIVE"
            found.append((subdomain, label, code))
        elif code == 200:
            status = f"⚠️  200 (not Column.us)"
        elif code == 404:
            status = "   404"
        elif code == 0:
            status = "   timeout/error"
        else:
            status = f"   {code}"
        print(f"{subdomain:<30} {code:>6}  {status}  — {label}")
        time.sleep(0.3)

    print("\n" + "=" * 60)
    if found:
        print(f"\n✅ Found {len(found)} new Column.us portal(s):\n")
        for subdomain, label, code in found:
            url = f"https://{subdomain}.column.us/search?noticeType=Foreclosure+Sale"
            print(f"  {subdomain}.column.us  —  {label}")
            print(f"  {url}\n")
        print("Next step: run --detect on each to confirm the header string.")
    else:
        print("\nNo new Column.us portals found.")

if __name__ == "__main__":
    main()
