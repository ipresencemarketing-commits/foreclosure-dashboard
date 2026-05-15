# Foreclosure Finder — Source Profiles

Each active scraping source has different data characteristics. This document defines
what fields each source provides, what is N/A, known issues, and the fix status.
Use this as the spec before writing or modifying any scraper code.

All five active sources are **trustee sale notices** — courthouse auctions with a
scheduled date and time. This is the same lead type across all sources.

---

## Source Status Summary

| Source | Tag | Counties Covered | Status | Records (last run) |
|--------|-----|-----------------|--------|--------------------|
| PublicNoticeVirginia.com | `publicnoticevirginia` | All 12 (statewide search + county filter) | ⚠️ Partial — detail fetches still returning card text | 6 |
| Column.us — Free Lance-Star (Fxbg) | `column_us` | Fredericksburg City, Stafford, Spotsylvania, Caroline, King George | ✅ Working | 2 |
| Column.us — Richmond Times-Dispatch | `column_us_richmond` | Richmond City, Chesterfield, Henrico | ✅ Fixed — header corrected | 270 results on portal |
| Column.us — Virginia Gazette (Wmsbg) | `column_us_williamsburg` | Hanover, King George, Caroline (supplemental) | ❌ 0 records — needs investigation | 0 |
| ~~Samuel I. White, P.C. (SIWPC)~~ | `siwpc` | All 12 | 🚫 Removed from active sources | — |

---

## Field Expectations by Source

Legend: ✅ Expected and populated | ⚠️ Expected but unreliable | ❌ Not available from this source | 🔄 GIS backfill

| Field | PNV | Column.us | SIWPC | Notes |
|-------|-----|-----------|-------|-------|
| Address | ⚠️ Parsed from notice text | ✅ In notice text | ✅ In table row | PNV: regex parse; Column.us/SIWPC: structured |
| City | ⚠️ Derived from address | ✅ In notice text | ✅ In table row | |
| ZIP | ⚠️ Derived from address | ✅ In notice text | ✅ In table row | |
| County | ⚠️ Keyword match in notice | ✅ city_to_county() lookup | ✅ In table row | All: county filter gate enforced in main() |
| F_Sale_Date | ✅ In full notice text | ✅ In notice text | ✅ In table column | PNV requires full detail page (not card excerpt) |
| F_Sale_Time | ✅ In full notice text | ✅ In notice text | ✅ In table column | Same — full text required for PNV |
| Sale_Location | ✅ Courthouse lookup by county | ✅ Courthouse lookup by county | ✅ Courthouse lookup by county | Derived from county key |
| Listing_Price | ❌ Not in notices | ❌ Not in notices | ✅ Opening bid in table | SIWPC is the only trustee-notice source with a bid price |
| Lender | ✅ Parsed from notice | ✅ Parsed from notice | ❌ Not in table | |
| Trustee | ✅ Parsed from notice | ✅ Parsed from notice | ✅ Always "Samuel I. White, P.C." | |
| Notice_Text | ✅ Full notice (up to 5000 chars) | ✅ Full notice (up to 5000 chars) | ⚠️ Table row only — no full notice | SIWPC has no individual notice pages |
| Owner_Name | 🔄 GIS backfill | 🔄 GIS backfill | 🔄 GIS backfill | Pass 6 in backfill.py |
| Owner_Mailing_Address | 🔄 GIS backfill | 🔄 GIS backfill | 🔄 GIS backfill | |
| Est_Value | 🔄 GIS backfill | 🔄 GIS backfill | 🔄 GIS backfill | |
| Beds/Baths/Sqft | 🔄 GIS backfill | 🔄 GIS backfill | 🔄 GIS backfill | |
| Year_Built | 🔄 GIS backfill | 🔄 GIS backfill | 🔄 GIS backfill | |

---

## Source 1 — PublicNoticeVirginia.com (PNV)

**URL:** https://www.publicnoticevirginia.com/
**Source tag:** `publicnoticevirginia`
**Legal basis:** Virginia Code §55.1-321 — all trustee sale notices statewide must be published here.
**Technology:** Playwright (ASP.NET WebForms, session-based)
**Counties:** All 12 target counties (scrapes statewide, county filter applied in main())

### What PNV provides
- Full notice text including address, sale date/time, lender, trustee, deed of trust details
- Notice date (publication date — NOT the sale date)
- Individual detail page URL per notice

### What PNV does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)
- Property details (GIS backfill required)

### Data extraction approach
1. Playwright opens site, searches "trustee sale Virginia" with date range
2. Paginates results, collects notice IDs from hidden form fields
3. Navigates to each detail page via Playwright (browser stays open — session must be live)
4. Extracts full notice text via `document.body.innerText`
5. Parses address, sale_date, sale_time, lender, trustee from full text

### Known issues
- **Detail pages still returning card text** (as of 2026-05-15 run): sale_time is always blank,
  lender/trustee blank, notice_text ends with "click 'view' to open the full text."
  Root cause not yet confirmed after Playwright fix — needs a live debug run.
- **County detection is text-based:** searches for county name in notice body.
  Fails if the county name doesn't appear verbatim. County filter in main() drops
  any PNV record with no county match.
- **Address parsing from notice text:** notices follow a consistent VA format but
  some edge cases (multi-parcel notices, road-only addresses) produce bad results.

### Fix status
- ✅ 2026-05-15: Replaced HTTP session fetch with Playwright navigation (browser stays open)
- ⚠️ Still seeing blank sale_time and missing lender/trustee — investigate next

---

## Source 2 — Column.us Fredericksburg (Free Lance-Star)

**URL:** https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us`
**Technology:** Playwright (Next.js + Firebase client-side rendering)
**Counties:** Fredericksburg City, Stafford, Spotsylvania, Caroline, King George

### What this source provides
- Full notice text (notice cards rendered by Firebase)
- Address with city and ZIP (structured in notice)
- County (derived from city via city_to_county() lookup)
- Sale date and time (parsed from notice text via parse_sale_datetime())
- Lender and trustee (parsed from notice text)
- Individual notice permalink URL (Pass 8 backfill upgrades generic → permalink)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Data extraction approach
1. Playwright loads portal URL, waits for Firebase hydration (8s)
2. Clicks "Load more" until exhausted
3. Splits page body by newspaper header ("FREE LANCE-STAR") into individual notice blocks
4. For each block: extracts address, county, sale_date, sale_time, lender, trustee
5. Drops notices whose sale_date is before SINCE_DATE

### Known issues
- None currently — this is the best-performing source (2/2 records clean in last run)
- Pass 8 backfill (permalink upgrade) requires a second Playwright run after initial sync

### Fix status
- ✅ Working correctly

---

## Source 3 — Column.us Richmond (Richmond Times-Dispatch)

**URL:** https://richmond.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_richmond`
**Technology:** Playwright (same engine as Fredericksburg)
**Counties:** Richmond City, Chesterfield, Henrico

### What this source provides
- Same fields as Fredericksburg Column.us (same scraper engine)

### What this source does NOT provide
- Same limitations as Fredericksburg Column.us

### Data extraction approach
- Identical to Fredericksburg — `_scrape_column_us_portal()` with different URL and newspaper header ("RICHMOND TIMES-DISPATCH")

### Known issues
- **0 records in last run** — Richmond/Chesterfield/Henrico are high-volume markets;
  0 results almost certainly means the scraper is failing, not that there are no notices.
  Likely cause: newspaper header text mismatch ("RICHMOND TIMES-DISPATCH" may not match
  what the portal actually renders) OR Firebase hydration timeout.

### Fix status
- ❌ Needs investigation — run with debug logging, inspect actual page text to confirm
  the newspaper header string

---

## Source 4 — Column.us Williamsburg (Virginia Gazette)

**URL:** https://vagazette.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_williamsburg`
**Technology:** Playwright (same engine as Fredericksburg)
**Counties:** Supplemental for Hanover, King George, Caroline

### What this source provides
- Same fields as Fredericksburg Column.us

### What this source does NOT provide
- Same limitations as Fredericksburg Column.us
- This portal covers Williamsburg/James City/York primarily — target county overlap is
  limited. Attorneys sometimes dual-publish Hanover, King George, Caroline notices here.

### Known issues
- **0 records in last run** — could be legitimately empty (low overlap with target counties)
  OR the newspaper header "VIRGINIA GAZETTE" may not match the portal's rendered text.
- Lower priority than Richmond — smaller potential yield from target counties.

### Fix status
- ❌ Needs investigation — confirm whether 0 is legitimate or a header mismatch

---

## Source 5 — Samuel I. White, P.C. (SIWPC)

**URL:** https://www.siwpc.com/sales-report
**Source tag:** `siwpc`
**Technology:** requests + BeautifulSoup (server-rendered HTML table, no JS required)
**Counties:** All 12 (own county filter in scraper, county filter gate in main())

### What this source provides
- Address (from table column)
- County (from table column — most reliable county source of all five)
- Sale date (from table column — dedicated date column, most reliable date source)
- Sale time (from table column)
- Opening bid / asking price (from table column — only trustee-notice source with this)
- Trustee (always "Samuel I. White, P.C.")
- Notice text = full table row joined as text

### What this source does NOT provide
- Lender (not in their sales report table)
- Full notice text (table row only — no individual notice page)
- Owner information (GIS backfill required)

### Data extraction approach
1. requests.get() with verify=False (SSL cert issue — see Known Issues)
2. BeautifulSoup parses all HTML tables
3. _col_map() identifies column positions by header keywords
4. _row_county() filters rows to target counties
5. Parses date, time, address, price from identified columns
6. Fallback: text-scan if no structured table found

### Known issues
- **0 records in last run** — SIWPC is a high-volume VA foreclosure firm; 0 results
  likely means the table structure changed or the SSL bypass is not working.
- **SSL certificate:** siwpc.com uses a *.bizland.com wildcard cert that doesn't cover
  the hostname. verify=False applied with InsecureRequestWarning suppressed.
- **Table structure sensitivity:** _col_map() matches column headers by keyword.
  If SIWPC renames a column (e.g. "Sale Date" → "Auction Date") the mapping breaks
  silently and returns 0 records.
- **Early-warning value:** SIWPC often lists sales 2–4 weeks before PNV. High priority
  to get working — provides lead time unavailable from other sources.

### Fix status
- ❌ Needs investigation — fetch live page, inspect actual table headers and structure

---

## Disabled Sources

| Source | Tag | Reason |
|--------|-----|--------|
| Auction.com | `auction_com` | REO listings — different lead type, no courthouse sale date |
| Daily Progress (Column.us) | `column_us_dailyprogress` | Charlottesville/Albemarle — outside 12 target counties |
| LOGS Legal | `logs_legal` | Migrated to PowerBI embed; BeautifulSoup cannot parse iframe data |
| NV Daily (Column.us) | `column_us_nvdaily` | nvdaily.column.us returns 404; wrong county coverage |
| Virginia eCourts | `va_courts` | Requires authenticated session; no public API endpoint |

---

## Fix Order (by lead volume potential)

1. **SIWPC** — highest-volume firm, early-warning value, simple HTML table scraper.
   Investigate why 0 records, fix table parsing.
2. **Column.us Richmond** — Richmond/Chesterfield/Henrico are large markets.
   Confirm newspaper header string, fix if mismatched.
3. **PNV** — Still returning card text instead of full notice. Debug Playwright detail fetch.
4. **Column.us Williamsburg** — Supplemental only; lower yield. Confirm header or accept 0.
