#!/usr/bin/env python3
"""
sync_sources_tab.py — Rebuild the "Sources" tab in the Foreclosures Google Sheet.

Lists every scraping source with its URL, technology, coverage, stage, status, and notes.
Run from Terminal:
    python3 scripts/sync_sources_tab.py

The tab is fully overwritten on each run — edit this file to update any source info.
"""

import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import gspread
from google.oauth2.service_account import Credentials
from config import CREDS_FILE, SCOPES, SHEET_ID

# ---------------------------------------------------------------------------
# Source data
# ---------------------------------------------------------------------------
# Columns: #, Source Name, Type, URL, Technology, Counties/Coverage,
#          Stage, Status, Typical Volume, Script File, Notes

HEADERS = [
    "#",
    "Source Name",
    "Type",
    "URL",
    "Technology",
    "Counties / Coverage",
    "Stage",
    "Status",
    "Typical Volume",
    "Script File",
    "Notes",
]

# Status values:
#   ✅ Active       — enabled and confirmed working
#   ⚠️ Monitoring   — enabled but 0 results, unconfirmed header, or needs validation
#   🔴 Paused       — disabled in config, fixable
#   🔴 Not Built    — no scraper yet
#   ⚠️ Unverified   — page existence unconfirmed; manual check needed

SOURCES = [
    # ── Column.us portals (scraper_column_us.py) ───────────────────────────────
    {
        "name":       "Free Lance-Star (Fredericksburg)",
        "type":       "Column.us",
        "url":        "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Fredericksburg City, Stafford, Spotsylvania, Caroline, King George",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~68/30 days",
        "script":     "scraper_column_us.py",
        "notes":      "Core source. Header: FREDERICKSBURG FREE-LANCE STAR (confirmed 2026-05-15).",
    },
    {
        "name":       "Richmond Times-Dispatch",
        "type":       "Column.us",
        "url":        "https://richmond.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Richmond City, Chesterfield, Henrico, Hanover, Louisa",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~172/30 days",
        "script":     "scraper_column_us.py",
        "notes":      "Core source. Header: RICHMOND TIMES DISPATCH (no hyphen, confirmed 2026-05-15).",
    },
    {
        "name":       "Washington Post Public Notices",
        "type":       "Column.us",
        "url":        "https://publicnotices.washingtonpost.com/?noticeType=Trustee%20Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Primarily MD/DC; VA NoVA overlap — all results synced, county filter applies",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~827 raw/30 days (mostly MD/DC)",
        "script":     "scraper_column_us.py",
        "notes":      "Custom-domain Column.us portal. noticeType=Trustee Sale. Header: THE WASHINGTON POST (confirmed). ~41+ Load More clicks — long runtime.",
    },
    {
        "name":       "Daily Press (Hampton Roads)",
        "type":       "Column.us",
        "url":        "https://dailypress.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Newport News, Hampton, York, James City, Isle of Wight, Poquoson",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "~6 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: DAILY PRESS (confirmed). Some out-of-state notices; county filter drops non-VA.",
    },
    {
        "name":       "Northern Neck News",
        "type":       "Column.us",
        "url":        "https://northernnecknews.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Richmond County (Warsaw), Northumberland, Lancaster, Westmoreland overlap",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "~2 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: NORTHERN NECK NEWS (confirmed). Fills rural Northern Neck gap.",
    },
    {
        "name":       "Fredericksburg Free Press",
        "type":       "Column.us",
        "url":        "https://fredericksburgfreepress.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Fredericksburg area (overlaps Free Lance-Star)",
        "stage":      "1",
        "status":     "⚠️ Monitoring",
        "volume":     "0 on 2026-05-22 test",
        "script":     "scraper_column_us.py",
        "notes":      "Portal confirmed live. Header: FREDERICKSBURG FREE PRESS. Zero listings so far — monitoring for when notices appear.",
    },
    {
        "name":       "Culpeper Star-Exponent",
        "type":       "Column.us",
        "url":        "https://starexponent.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Culpeper, Fauquier, Rappahannock",
        "stage":      "1",
        "status":     "⚠️ Monitoring",
        "volume":     "Low — rural area",
        "script":     "scraper_column_us.py",
        "notes":      "Header: CULPEPER STAR EXPONENT (unconfirmed — assumed). First test run needed.",
    },
    {
        "name":       "Virginia Gazette (Williamsburg)",
        "type":       "Column.us",
        "url":        "https://vagazette.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Williamsburg/James City/York primary; Hanover, King George, Caroline overlap possible",
        "stage":      "1",
        "status":     "⚠️ Monitoring",
        "volume":     "0 in current 30-day window",
        "script":     "scraper_column_us.py",
        "notes":      "Portal confirmed live 2026-05-30. Header: VIRGINIA GAZETTE (unconfirmed). Supplemental — low yield expected.",
    },
    {
        "name":       "Charlottesville Daily Progress",
        "type":       "Column.us",
        "url":        "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Charlottesville/Albemarle primary; Louisa, Culpeper overlap possible",
        "stage":      "1",
        "status":     "⚠️ Monitoring",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: CHARLOTTESVILLE DAILY PROGRESS (confirmed 2026-05-30). Enabled — first full run needed to confirm target county yield.",
    },
    {
        "name":       "Rappahannock News",
        "type":       "Column.us",
        "url":        "https://rappnews.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Rappahannock County; Culpeper/Fauquier border overlap possible",
        "stage":      "1",
        "status":     "⚠️ Monitoring",
        "volume":     "0 on 2026-05-30 detect run",
        "script":     "scraper_column_us.py",
        "notes":      "Portal live. Header: RAPPAHANNOCK NEWS (unconfirmed). Borders Culpeper/Fauquier (Stage 1 targets).",
    },
    {
        "name":       "Northern Virginia Daily",
        "type":       "Column.us",
        "url":        "https://nvdaily.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Shenandoah Valley (Warren, Shenandoah, Page) — outside Stage 1 target counties",
        "stage":      "2",
        "status":     "⚠️ Monitoring",
        "volume":     "Unknown — domain may 404",
        "script":     "scraper_column_us.py",
        "notes":      "CAUTION: nvdaily.column.us returned 404 as of 2025. NV Daily may have migrated to nvdaily.com/classifieds/ (different CMS). Enabled for investigation — expect 0 results or scraper error.",
    },
    {
        "name":       "Roanoke Times",
        "type":       "Column.us",
        "url":        "https://roanoke.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Roanoke City, Roanoke County, Salem, Botetourt, Bedford, Franklin, Montgomery, Radford",
        "stage":      "2",
        "status":     "⚠️ Monitoring",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: THE ROANOKE TIMES (confirmed 2026-05-30). Stage 2 expansion — city_to_county() needs Roanoke area additions.",
    },
    {
        "name":       "Lynchburg News & Advance",
        "type":       "Column.us",
        "url":        "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Lynchburg City, Amherst, Bedford, Campbell, Appomattox",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: LYNCHBURG NEWS & ADVANCE (confirmed 2026-05-30). Enabled 2026-05-30 — Stage 2 territory.",
    },
    {
        "name":       "Waynesboro News Virginian",
        "type":       "Column.us",
        "url":        "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Waynesboro City, Augusta County, Staunton City",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: WAYNESBORO NEWS VIRGINIAN (confirmed 2026-05-30). Enabled 2026-05-30.",
    },
    {
        "name":       "Martinsville Bulletin",
        "type":       "Column.us",
        "url":        "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Martinsville City, Henry County, Patrick County",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "~28 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: MARTINSVILLE BULLETIN (confirmed). Enabled 2026-05-30.",
    },
    {
        "name":       "Danville Register & Bee",
        "type":       "Column.us",
        "url":        "https://godanriver.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Danville City, Pittsylvania County, Henry, Halifax",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: DANVILLE REGISTER & BEE (confirmed 2026-05-30). Enabled 2026-05-30.",
    },
    {
        "name":       "Westmoreland News",
        "type":       "Column.us",
        "url":        "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Westmoreland County, Richmond County, Northumberland, Lancaster",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "~7 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: WESTMORELAND NEWS (confirmed). Northern Neck peninsula. King George border overlap. Enabled 2026-05-30.",
    },
    {
        "name":       "Daily News-Record (Harrisonburg)",
        "type":       "Column.us",
        "url":        "https://dnronline.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Harrisonburg City, Rockingham County, Page County",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "~8 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: DAILY NEWS-RECORD (confirmed). Includes timeshare trustee sales (Massanutten). Enabled 2026-05-30.",
    },
    {
        "name":       "FFXnow (Fairfax)",
        "type":       "Column.us",
        "url":        "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Fairfax County, Falls Church City",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: FFXNOW (unconfirmed). Northern Virginia. Enabled 2026-05-30.",
    },
    {
        "name":       "ARLnow (Arlington)",
        "type":       "Column.us",
        "url":        "https://arlnow.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Arlington County",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: ARLNOW (unconfirmed). Low volume expected. Enabled 2026-05-30.",
    },
    {
        "name":       "ALXnow (Alexandria)",
        "type":       "Column.us",
        "url":        "https://alxnow.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Alexandria City",
        "stage":      "2",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_column_us.py",
        "notes":      "Header: ALXNOW (unconfirmed). Low volume expected. Enabled 2026-05-30.",
    },
    {
        "name":       "Sun Gazette (Arlington/Fairfax)",
        "type":       "Column.us",
        "url":        "https://sungazette.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Arlington County, Fairfax County",
        "stage":      "2",
        "status":     "⚠️ Monitoring",
        "volume":     "0 on 2026-05-30 detect run",
        "script":     "scraper_column_us.py",
        "notes":      "Portal live. Header: SUN GAZETTE (unconfirmed).",
    },
    {
        "name":       "InsideNOVA",
        "type":       "Column.us",
        "url":        "https://insidenova.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Prince William County, Manassas City, Manassas Park City",
        "stage":      "2",
        "status":     "⚠️ Monitoring",
        "volume":     "0 on 2026-05-30 detect run",
        "script":     "scraper_column_us.py",
        "notes":      "Portal live. Header: INSIDENOVA (unconfirmed).",
    },
    {
        "name":       "Cardinal News",
        "type":       "Column.us",
        "url":        "https://cardinalnews.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Statewide digital outlet — SW and Southside VA focus",
        "stage":      "2",
        "status":     "⚠️ Monitoring",
        "volume":     "0 on 2026-05-30 detect run",
        "script":     "scraper_column_us.py",
        "notes":      "Portal live. Header: CARDINAL NEWS (unconfirmed). Nonprofit digital outlet — low volume expected.",
    },
    {
        "name":       "Bristol Herald Courier",
        "type":       "Column.us",
        "url":        "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale",
        "tech":       "Playwright (Next.js + Firebase)",
        "coverage":   "Bristol City, Washington County, Scott, Russell — far SW Virginia",
        "stage":      "3",
        "status":     "✅ Active",
        "volume":     "~10 confirmed 2026-05-30",
        "script":     "scraper_column_us.py",
        "notes":      "Header: BRISTOL HERALD COURIER (confirmed). Stage 3+ — far SW Virginia. VA/TN border; county filter important.",
    },

    # ── Law firm PDF / HTML sources ────────────────────────────────────────────
    {
        "name":       "Samuel I. White, P.C. (SIWPC)",
        "type":       "Law Firm",
        "url":        "https://www.siwpc.net/AutoUpload/Sales.pdf",
        "tech":       "requests + pdfplumber (daily PDF)",
        "coverage":   "Statewide Virginia (county-filtered)",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~4+/day (varies; 32 statewide in PDF)",
        "script":     "scraper_siwpc.py",
        "notes":      "Static PDF updated daily. SIWPC is a high-volume VA foreclosure firm. Confirmed working 2026-05-15.",
    },
    {
        "name":       "LOGS Legal Group LLP",
        "type":       "Law Firm",
        "url":        "https://www.logs.com/va-sales-report.html",
        "tech":       "Playwright + PowerBI DSR interceptor",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~110 listings",
        "script":     "scraper_logs.py",
        "notes":      "PowerBI embed. Intercepts querydata POST; decodes DSR binary format. Includes estimated opening bid. Confirmed live 2026-06-03.",
    },
    {
        "name":       "Brock & Scott, PLLC",
        "type":       "Law Firm",
        "url":        "https://www.brockandscott.com/foreclosure-sales/?_sft_foreclosure_state=va",
        "tech":       "requests + BeautifulSoup (WordPress HTML)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~20 confirmed 2026-06-03",
        "script":     "scraper_brockscott.py",
        "notes":      "Static WordPress site. Includes Opening Bid Amount. 10 listings/page, paginated. Confirmed working 2026-06-03.",
    },
    {
        "name":       "Rosenberg & Associates",
        "type":       "Law Firm",
        "url":        "https://rosenberg-assoc.com/foreclosure-sales/",
        "tech":       "requests + BeautifulSoup (static HTML table)",
        "coverage":   "Statewide Virginia (also MD/DC — filtered)",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~66 VA active 2026-06-03",
        "script":     "scraper_rosenberg.py",
        "notes":      "Static HTML table. VA + MD + DC mixed — state=VA filter applied. Active listings only (status=1). Confirmed working 2026-06-03.",
    },
    {
        "name":       "Glasser & Glasser, P.L.C.",
        "type":       "Law Firm",
        "url":        "https://www.glasserlaw.com/New%20Folder/Foreclosure%20Sales.html",
        "tech":       "Playwright (Cloudflare protection)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~21 listings 2026-06-04",
        "script":     "scraper_glasserlaw.py",
        "notes":      "Cloudflare blocks plain requests — Playwright required. Includes Bid Deposit + Original Principal. Confirmed live 2026-06-04.",
    },
    {
        "name":       "McCabe, Weisberg & Conway (MWC Law)",
        "type":       "Law Firm",
        "url":        "https://apps.mwc-law.com/SalesLists/VA.html",
        "tech":       "requests + BeautifulSoup (static HTML)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~40 listings 2026-06-04",
        "script":     "scraper_mwclaw.py",
        "notes":      "Static HTML table. No ZIP in source — backfill fills from address. Confirmed working 2026-06-04.",
    },
    {
        "name":       "Aldridge Pite, LLP",
        "type":       "Law Firm",
        "url":        "https://aldridgepite.com/sale-day-listings-selection/foreclosure-listings-virginia/",
        "tech":       "Playwright (disclaimer cookie gate)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "Unknown",
        "script":     "scraper_aldridgepite.py",
        "notes":      "Playwright clicks 'I agree' to bypass disclaimer. Statewide VA trustee sales.",
    },

    # ── Auction platforms ──────────────────────────────────────────────────────
    {
        "name":       "Auction.com (GOTO Foreclosures)",
        "type":       "Auction Platform",
        "url":        "https://www.auction.com/residential/VA/active_lt/goto_mt/foreclosures_at",
        "tech":       "GraphQL API (requests.post — no auth)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~26 VA listings 2026-06-03",
        "script":     "scraper_auctioncom.py",
        "notes":      "GOTO filter = live courthouse trustee sales only. Includes beds/baths/sqft, year built, lot size, AVM est. market value. Confirmed working 2026-06-03.",
    },
    {
        "name":       "Xome Auctions",
        "type":       "Auction Platform",
        "url":        "https://www.xome.com/auctions/foreclosuresales?ss=virginia",
        "tech":       "Two-step REST API (requests — public token)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~85 VA listings 2026-06-03",
        "script":     "scraper_xome.py",
        "notes":      "Step 1: county/date/ID map. Step 2: batch property details. Includes full courthouse address. Auth: public token in site JS.",
    },
    {
        "name":       "ServiceLink Auction",
        "type":       "Auction Platform",
        "url":        "https://www.servicelinkauction.com/foreclosures/virginia",
        "tech":       "REST API (requests — no auth)",
        "coverage":   "Statewide Virginia",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "~70-80 VA listings",
        "script":     "scraper_servicelink.py",
        "notes":      "Richest source in pipeline. Beds/baths/sqft + year built at scrape time. Exact courthouse address from API. Occupancy status. Sub-second fetch. Confirmed working 2026-06-03.",
    },
    {
        "name":       "Auction Network",
        "type":       "Auction Platform",
        "url":        "https://bid.auctionnetwork.com/Home/Auctions?auctionTypes=Foreclosure/Trustee",
        "tech":       "Playwright (JS-rendered SPA)",
        "coverage":   "Statewide Virginia (multi-state listing filtered to VA)",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "2-10 VA listings",
        "script":     "scraper_auctionnetwork.py",
        "notes":      "Low volume but unique listings from Williams & Williams and similar auctioneers. Paginated + detail page fetch. Confirmed working 2026-06-04.",
    },

    # ── Classified / newspaper (non-Column.us) ─────────────────────────────────
    {
        "name":       "Washington Times Classifieds",
        "type":       "Classifieds",
        "url":        "http://classified.washingtontimes.com/index.php?a=19&b[search_text]=foreclosure",
        "tech":       "requests + BeautifulSoup (PHP classifieds)",
        "coverage":   "NoVA primary; target overlap via Fauquier, Stafford, Spotsylvania",
        "stage":      "1",
        "status":     "✅ Active",
        "volume":     "Low — spot coverage",
        "script":     "scraper_washingtontimes.py",
        "notes":      "PHP classifieds site. Includes Commissioner's Sales (court-ordered). Primary coverage is NoVA (Fairfax/Loudoun/Prince William — dropped by county filter). Confirmed working 2026-05-22.",
    },

    # ── Paused / disabled ──────────────────────────────────────────────────────
    {
        "name":       "PublicNoticeVirginia.com (PNV)",
        "type":       "Government / Legal",
        "url":        "https://www.publicnoticevirginia.com/",
        "tech":       "Playwright (ASP.NET WebForms)",
        "coverage":   "All 12 target counties — §55.1-321 statewide mandate",
        "stage":      "1",
        "status":     "🔴 Paused",
        "volume":     "~1000 statewide raw notices",
        "script":     "scraper.py (ENABLE_PNV=False in config.py)",
        "notes":      "Paused 2026-05-22. reCAPTCHA gates every detail page — only card text accessible. Sale dates missing for most records. Re-enable when detail page access is solved (2captcha integration planned).",
    },
    {
        "name":       "TMMP (Tromberg, Miller, Morris & Partners)",
        "type":       "Law Firm",
        "url":        "https://tmppllc.com/virginia_foreclosure_sales",
        "tech":       "Unknown — page existence unconfirmed",
        "coverage":   "Claimed statewide Virginia (70+ sales)",
        "stage":      "1",
        "status":     "⚠️ Unverified",
        "volume":     "~70+ claimed",
        "script":     "Not yet built",
        "notes":      "Page existence unconfirmed. Manual visit required before building scraper. If live: static HTML table (requests + BS4) or PDF (pdfplumber).",
    },
    {
        "name":       "Southside Sentinel",
        "type":       "Classifieds",
        "url":        "https://www.ssentinel.com/Classifieds/public-notices/",
        "tech":       "requests + BeautifulSoup (static HTML)",
        "coverage":   "Middlesex County, Middle Peninsula (Essex, Gloucester, Mathews possible)",
        "stage":      "2",
        "status":     "🔴 Not Built",
        "volume":     "Unknown",
        "script":     "Not yet built (ENABLE_SOUTHSIDE_SENTINEL=False)",
        "notes":      "Confirmed live 2026-05-30. Plain HTML, no JS. Not on Column.us — independent CMS. Pattern for other small VA weeklies. Build when Stage 2 begins.",
    },
    {
        "name":       "LOGS Legal (legacy BeautifulSoup scraper)",
        "type":       "Law Firm",
        "url":        "https://www.logs.com/va-sales-report.html",
        "tech":       "BeautifulSoup HTML table (DEAD — site migrated to PowerBI)",
        "coverage":   "N/A",
        "stage":      "N/A",
        "status":     "🔴 Disabled",
        "volume":     "N/A",
        "script":     "Dead code (ENABLE_LOGS_LEGAL=False)",
        "notes":      "Old HTML table scraper broke when LOGS migrated to PowerBI embed. Replaced by scraper_logs.py (Source: LOGS Legal Group LLP above).",
    },
    {
        "name":       "Virginia eCourts",
        "type":       "Government",
        "url":        "https://eapps.courts.state.va.us/",
        "tech":       "N/A — requires authenticated session",
        "coverage":   "Statewide Virginia",
        "stage":      "N/A",
        "status":     "🔴 Disabled",
        "volume":     "N/A",
        "script":     "Dead (ENABLE_VA_COURTS=False)",
        "notes":      "eCourts (circuitSearch + CJISWeb) require authenticated session — no public API endpoint. Not feasible without account credentials.",
    },
]


# ---------------------------------------------------------------------------
# Color palettes for status column
# ---------------------------------------------------------------------------
STATUS_COLORS = {
    "✅ Active":      {"red": 0.851, "green": 0.918, "blue": 0.827},   # light green
    "⚠️ Monitoring":  {"red": 1.000, "green": 0.953, "blue": 0.800},   # light yellow
    "⚠️ Unverified":  {"red": 1.000, "green": 0.953, "blue": 0.800},   # light yellow
    "🔴 Paused":      {"red": 0.988, "green": 0.812, "blue": 0.812},   # light red
    "🔴 Not Built":   {"red": 0.988, "green": 0.812, "blue": 0.812},   # light red
    "🔴 Disabled":    {"red": 0.906, "green": 0.906, "blue": 0.906},   # light grey
}

STAGE_COLORS = {
    "1":   {"red": 0.827, "green": 0.918, "blue": 0.988},   # light blue
    "2":   {"red": 0.902, "green": 0.843, "blue": 0.988},   # light purple
    "3":   {"red": 0.988, "green": 0.898, "blue": 0.843},   # light orange
    "N/A": {"red": 0.933, "green": 0.933, "blue": 0.933},   # light grey
}


def build_row(i: int, s: dict) -> list:
    return [
        i,
        s["name"],
        s["type"],
        s["url"],
        s["tech"],
        s["coverage"],
        s["stage"],
        s["status"],
        s["volume"],
        s["script"],
        s["notes"],
    ]


def main():
    print("Connecting to Google Sheets…")
    creds = Credentials.from_service_account_file(CREDS_FILE, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SHEET_ID)

    # Get or create "Sources" worksheet
    tab_name = "Sources"
    try:
        ws = sh.worksheet(tab_name)
        print(f"  Found existing '{tab_name}' tab — clearing and rebuilding…")
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        print(f"  '{tab_name}' tab not found — creating…")
        ws = sh.add_worksheet(title=tab_name, rows=len(SOURCES) + 5, cols=len(HEADERS))

    # Build rows
    rows = [HEADERS]
    for i, s in enumerate(SOURCES, start=1):
        rows.append(build_row(i, s))

    ws.update("A1", rows, value_input_option="USER_ENTERED")
    print(f"  Written {len(SOURCES)} source rows.")

    # ── Formatting ────────────────────────────────────────────────────────────
    total_rows = len(SOURCES) + 1  # +1 for header
    total_cols = len(HEADERS)

    requests = []

    # Freeze header row
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": ws.id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # Header row: bold, dark background, white text
    requests.append({
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": total_cols},
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                    "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                    "horizontalAlignment": "CENTER",
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)",
        }
    })

    # Wrap all data cells; align top-left
    requests.append({
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": total_rows,
                      "startColumnIndex": 0, "endColumnIndex": total_cols},
            "cell": {
                "userEnteredFormat": {
                    "wrapStrategy": "WRAP",
                    "verticalAlignment": "TOP",
                }
            },
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)",
        }
    })

    # Status column (col H = index 7): color by status
    status_col_idx = HEADERS.index("Status")
    for row_idx, s in enumerate(SOURCES, start=1):
        color = STATUS_COLORS.get(s["status"], {"red": 1, "green": 1, "blue": 1})
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                          "startColumnIndex": status_col_idx,
                          "endColumnIndex": status_col_idx + 1},
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    # Stage column (col G = index 6): color by stage
    stage_col_idx = HEADERS.index("Stage")
    for row_idx, s in enumerate(SOURCES, start=1):
        color = STAGE_COLORS.get(s["stage"], {"red": 1, "green": 1, "blue": 1})
        requests.append({
            "repeatCell": {
                "range": {"sheetId": ws.id,
                          "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                          "startColumnIndex": stage_col_idx,
                          "endColumnIndex": stage_col_idx + 1},
                "cell": {"userEnteredFormat": {"backgroundColor": color}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        })

    # Column widths (pixels)
    col_widths = {
        0: 40,    # #
        1: 230,   # Source Name
        2: 110,   # Type
        3: 320,   # URL
        4: 200,   # Technology
        5: 280,   # Coverage
        6: 55,    # Stage
        7: 130,   # Status
        8: 130,   # Volume
        9: 200,   # Script File
        10: 380,  # Notes
    }
    for col_idx, width in col_widths.items():
        requests.append({
            "updateDimensionProperties": {
                "range": {"sheetId": ws.id, "dimension": "COLUMNS",
                          "startIndex": col_idx, "endIndex": col_idx + 1},
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    # Alternate row shading for data rows
    for row_idx in range(1, total_rows):
        if row_idx % 2 == 0:
            requests.append({
                "repeatCell": {
                    "range": {"sheetId": ws.id,
                              "startRowIndex": row_idx, "endRowIndex": row_idx + 1,
                              "startColumnIndex": 0, "endColumnIndex": total_cols},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": {"red": 0.953, "green": 0.953, "blue": 0.953}
                    }},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })

    # Bold the Source Name column
    name_col_idx = HEADERS.index("Source Name")
    requests.append({
        "repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "endRowIndex": total_rows,
                      "startColumnIndex": name_col_idx, "endColumnIndex": name_col_idx + 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat.bold",
        }
    })

    sh.batch_update({"requests": requests})
    print("  Formatting applied.")
    print(f"\n✅ Sources tab rebuilt — {len(SOURCES)} sources listed.")
    print(f"   Sheet: https://docs.google.com/spreadsheets/d/{SHEET_ID}")


if __name__ == "__main__":
    main()
