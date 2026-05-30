# Foreclosure Finder — Source Profiles

Each active scraping source has different data characteristics. This document defines
what fields each source provides, what is N/A, known issues, and the fix status.
Use this as the spec before writing or modifying any scraper code.

All active sources are **trustee sale notices** — courthouse auctions with a scheduled
date and time. This is the same lead type across all three sources.

---

## Active Sources (6)

| Source | Tag | Counties Covered | Status | Volume |
|--------|-----|-----------------|--------|--------|
| Column.us — Free Lance-Star (Fxbg) | `column_us` | Fxbg City, Stafford, Spotsylvania, Caroline, King George | ✅ Working | ~5–20/month |
| Column.us — Richmond Times-Dispatch | `column_us_richmond` | Richmond City, Chesterfield, Henrico (+Hanover, Louisa) | ✅ Working | ~254 raw / 30 days |
| Column.us — Culpeper Star-Exponent | `column_us_culpeper` | Culpeper, Fauquier, Rappahannock area | ✅ Working | Low volume |
| Samuel I. White, P.C. (SIWPC) | `siwpc` | All 12 (statewide firm, county-filtered) | ✅ Working | ~4/day varies |
| Column.us — Fredericksburg Free Press | `column_us_fxbg_free_press` | Fxbg-area (overlap with Free Lance-Star) | ⚠️ Enabled — 0 results on 2026-05-22 test; monitoring | Unknown |
| The Washington Times Classifieds | `washingtontimes` | Fauquier, Stafford, Spotsylvania (NoVA-area notices w/ target county overlap) | ✅ Working | Low — spot coverage |
| Washington Post Public Notices | `washingtonpost` | MD, DC, VA (NoVA + target county overlap confirmed deeper in results) | ✅ Enabled | ~827 raw / 30 days |
| Column.us — Virginia Gazette (Wmsbg) | `column_us_williamsburg` | Supplemental — Hanover, King George, Caroline overlap | ⚠️ Enabled 2026-05-22 — needs test run to confirm header + yield | Unknown |
| Column.us — Daily Progress (Cville) | `column_us_dailyprogress` | Charlottesville/Albemarle primary; Louisa, Culpeper overlap possible | ⚠️ Enabled 2026-05-22 — needs test run to confirm yield | Unknown |
| Column.us — Northern Virginia Daily | `column_us_nvdaily` | Shenandoah Valley (outside target 12) | ⚠️ Enabled 2026-05-22 — domain may 404; needs investigation | Unknown |

## Paused / Disabled Sources

| Source | Tag | Reason |
|--------|-----|--------|
| PublicNoticeVirginia.com | `publicnoticevirginia` | Paused 2026-05-22 — card text mode only (reCAPTCHA blocks detail pages); sale dates missing for most records; re-enable when detail page access is solved |
| Auction.com | `auction_com` | Removed — REO listings, no courthouse sale date |
| Samuel I. White, P.C. | `siwpc` | Removed from active sources |
| LOGS Legal | `logs_legal` | Broken — migrated to PowerBI embed |
| Virginia eCourts | `va_courts` | Requires authenticated session |

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
**Technology:** Playwright (ASP.NET WebForms, session-based search + card text extraction)
**Counties:** All 12 target counties (scrapes statewide, county pre-filter on card text)
**Mode:** Lead discovery only — card text (~400 chars), no detail page access

### What PNV provides (card text mode)
- Property address (parsed from first ~200 chars of card excerpt)
- County (keyword match in card text — used for pre-filter)
- Partial notice text (truncated card excerpt — up to ~400 chars)
- Link to full notice detail page (for human reference, not scraped)

### What PNV does NOT provide (blocked)
- Full notice text — reCAPTCHA gates every detail page (confirmed 2026-05-15)
- Sale date/time — usually appears in the second half of the notice, past the card cutoff
- Lender / trustee details — same reason
- Asking/starting bid price
- Owner information (GIS backfill required)

### Data extraction approach
1. Playwright opens site, searches "trustee sale Virginia" with 30-day date range
2. Paginates results; pre-filters each card by county keyword (drops ~60% statewide)
3. Parses address, sale_date (if present in excerpt), county from card text directly
4. No detail page navigation — reCAPTCHA wall makes this impossible for headless browsers
5. Records without sale_date are staged as `pre-fc`; dedup logic merges with SIWPC/Column.us

### Architecture note
PNV is the broadest net (every VA trustee sale by statute) but the shallowest data.
It catches properties that SIWPC and Column.us might not have yet, giving early signal.
Sale dates fill in when the same address appears later in SIWPC or Column.us.

### Fix status
- ✅ 2026-05-15: reCAPTCHA wall confirmed on all detail pages; switched to card-text-only mode
- ✅ 2026-05-15: Added county pre-filter during pagination (skips ~60% of 1000 statewide notices)
- ✅ 2026-05-15: `max_pages=None` in production (full run); `max_pages=5` in `--pnv-only` test mode
- ✅ ENABLE_PNV = True in config.py

---

## Source 2 — Column.us Fredericksburg (Free Lance-Star)

**URL:** https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us`
**Technology:** Playwright (Next.js + Firebase client-side rendering)
**Counties:** Fredericksburg City, Stafford, Spotsylvania, Caroline, King George
**Typical volume:** ~68 listings per 30-day window (confirmed 2026-05-15)

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
2. Clicks "Load more" until exhausted (~4 clicks for 68 listings)
3. Splits page body by newspaper header into individual notice blocks
4. For each block: extracts address, county, sale_date, sale_time, lender, trustee
5. Date filter drops notices with sale_date before SINCE_DATE
6. Dedup removes duplicate IDs (same address + date)

### Newspaper header
`"FREDERICKSBURG FREE-LANCE STAR"` — confirmed from live page 2026-05-15.
Note: the scraper previously used `"FREE LANCE-STAR"` which only partially matched,
producing 3 records instead of 68. Fixed 2026-05-15.

### Known data patterns
- Notices occasionally span multiple addresses (e.g. "A/R/T/A" alternates)
- Records with unrecognized cities will have county = "" — kept and passed to GIS backfill

### Fix history
- 2026-05-15: Header corrected from `"FREE LANCE-STAR"` → `"FREDERICKSBURG FREE-LANCE STAR"`
- 2026-05-15: Added funnel logging — blocks found, parsed, date-filtered, deduped, final count
- 2026-05-15: Healed false splits — notice bodies contain "FREDERICKSBURG FREE-LANCE STAR" in
  standard publication boilerplate ("published in the FREDERICKSBURG FREE-LANCE STAR, a newspaper
  of general circulation..."). Splitting on that string truncated those notices and produced orphan
  blocks starting with ", a newspaper of general circulation". Fix merges orphan blocks back into
  the preceding block, restoring full notice text. True duplicates handled downstream by dedup.

### Fix status
- ✅ Working — data quality confirmed good 2026-05-15

---

## Source 3 — Column.us Richmond (Richmond Times-Dispatch)

**URL:** https://richmond.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_richmond`
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `RICHMOND TIMES DISPATCH` (no hyphen — confirmed 2026-05-15)
**Counties:** Richmond City, Chesterfield, Henrico — plus Hanover and Louisa notices
frequently appear here (attorneys publish in Richmond paper)
**Typical volume:** ~172 listings / 30-day window (confirmed 2026-05-15)

### What this source provides
- Full address with street, city, ZIP (structured in notice text)
- County (via `city_to_county()` lookup on parsed city)
- Sale date — 98% populated ✅
- Sale time — 99% populated ✅
- Lender — 91% populated ✅
- Trustee — 90% populated ✅ (see parsing notes below)
- Full notice text up to 5000 chars
- Individual notice permalink URL

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Data extraction approach
- `scraper_column_us.py` with Richmond URL and header "RICHMOND TIMES DISPATCH"
- Firebase hydration: 8s wait + "Load more" clicks until exhausted
- County derived from `city_to_county(city)` using expanded mapping including:
  Henrico communities (Glen Allen, Short Pump, Sandston, Highland Springs, Varina,
  Lakeside, Tuckahoe, Innsbrook), Chesterfield communities (Chester, Midlothian,
  Bon Air, Ettrick, Matoaca, Swift Creek), Hanover communities (Ashland,
  Mechanicsville, Beaverdam, Doswell, Montpelier)
- False-split healing: mid-notice mentions of "RICHMOND TIMES DISPATCH" merged back
  into preceding block to restore full notice_text

### Trustee parsing
`parse_trustee()` in `scraper.py` uses three patterns in priority order:
1. Explicit label — `Substitute Trustee: [Name]` or `Trustee: [Name]`
2. Known VA firm list — Equity Trustees, SAMUEL I. WHITE, Commonwealth Trustees,
   DolanReid PLLC, ALG Trustee, Atlantic Trustee Services, First American Title, etc.
3. Signature block — `[Full Name], [Substitute] Trustee` near end of notice

Coverage confirmed 90% (154/172). Remaining 10% are notices where the trustee
is referenced only by title ("the acting Substitute Trustee") with no firm name given.

### County breakdown (2026-05-15 run, 172 listings)
| County | Count | In scope? |
|--------|-------|-----------|
| Richmond City | 47 | ✅ |
| Chesterfield | 34 | ✅ |
| Henrico | 22 | ✅ |
| Hanover | 12 | ✅ |
| Petersburg City | 7 | ❌ filtered |
| Prince George | 6 | ❌ filtered |
| Hopewell City | 5 | ❌ filtered |
| Dinwiddie | 4 | ❌ filtered |
| Louisa | 4 | ✅ |
| New Kent | 3 | ❌ filtered |
| Colonial Heights City | 3 | ❌ filtered |
| Amelia | 3 | ❌ filtered |
| Prince Edward | 3 | ❌ filtered |
| Charles City | 3 | ❌ filtered |
| Goochland | 3 | ❌ filtered |
| Richmond City (dup) | 2 | ✅ |
| Powhatan | 2 | ❌ filtered |
| King George | 1 | ✅ |
| Lancaster | 1 | ❌ filtered |
| Surry | 1 | ❌ filtered |
| King William | 1 | ❌ filtered |
| Middlesex | 1 | ❌ filtered |
| Sussex | 1 | ❌ filtered |
| King And Queen | 1 | ❌ filtered |
| Unknown (unresolved — court order format) | 1 | dropped |

County detection now uses a 3-pass fallback:
1. `city_to_county()` lookup — catches in-scope counties directly
2. `parse_county_from_clerks_office()` — extracts jurisdiction from deed recording
   reference in notice text (51/52 unknown records resolved, 98% coverage)
3. Circuit Court mention regex — catches remaining edge cases

### Known data patterns
- **~30% out-of-scope counties:** Petersburg, Lancaster, Hartfield, Disputanta, Colonial
  Heights, Hopewell, Goochland, Powhatan, Prince George appear in raw results. County is
  now resolved for 98% of these via Clerk's Office extraction. All are dropped by the
  county filter gate (only target 12 counties kept).
- **Henrico/Richmond mailing address ambiguity:** Henrico County properties often use
  "Richmond" as mailing city → mapped to Richmond City. Both are target counties so
  they pass the filter, but county may be misclassified. "A/R/T/A HENRICO" in address
  is the signal to look for.
- **Land parcel addresses:** Notices for raw land (e.g. "31.8 Acres+/- Parsons Road")
  produce long, malformed address strings. These pass through but GIS backfill will
  likely fail to match a parcel.
- **False splits:** "RICHMOND TIMES DISPATCH" appears in notice boilerplate as
  "published in the RICHMOND TIMES DISPATCH, a newspaper of general circulation."
  Handled by false-split healing in scraper_column_us.py.

### Fix history
- 2026-05-15: Newspaper header corrected "RICHMOND TIMES-DISPATCH" → "RICHMOND TIMES DISPATCH"
  (no hyphen). This was the sole cause of 0 records.
- 2026-05-15: `city_to_county()` expanded with Henrico, Chesterfield, and Hanover communities.
- 2026-05-15: `parse_trustee()` overhauled — 3-pattern approach, coverage improved 8% → 90%.
  Added: explicit label pattern, Commonwealth Trustees, DolanReid, Equity Trustees,
  ALG Trustee, First American Title. Fixed: Pattern 3 was missing re.IGNORECASE flag.
- 2026-05-15: `parse_county_from_clerks_office()` added — 4-pattern regex covering all
  Virginia circuit court Clerk's Office phrasings. Resolves 51/52 (98%) of previously
  unknown-county records. Handles straight + curly apostrophes, bare jurisdiction names
  (Charles City, Isle of Wight), "Circuit Court of the [Name] County" format, and all
  common "for [Name] County/City" variants. Wired as Pass 2 in county fallback chain.

### Fix status
- ✅ Working — data quality confirmed good 2026-05-15

---

## Source 4 — Column.us Williamsburg (Virginia Gazette)

**URL:** https://vagazette.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_williamsburg`
**Toggle:** `williamsburg` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `VIRGINIA GAZETTE`
**Counties:** Williamsburg/James City/York primary; target overlap via Hanover, King George, Caroline
**Output:** `data/foreclosures_williamsburg.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)
- Primary coverage is Williamsburg/James City/York — outside 12 target counties. Attorneys
  sometimes dual-publish Hanover, King George, and Caroline notices here; target yield is low.

### Known issues
- **Header string unconfirmed** — `VIRGINIA GAZETTE` has not been validated against live page
  DOM text. If 0 records come back on first run, confirm the header by running:
  `python3 -c "from playwright.sync_api import sync_playwright; ..."` and checking
  `document.body.innerText` for the newspaper name as rendered.
- **Low yield expected** — supplemental source only; don't expect high volume.

### Fix status
- ⚠️ Enabled — portal confirmed live 2026-05-30; zero notices in current 30-day window (not a scraper error). Header string `VIRGINIA GAZETTE` unconfirmed but assumed correct — will validate when notices appear.

---

## Source 5 — Samuel I. White, P.C. (SIWPC)

**URL:** https://www.siwpc.net/AutoUpload/Sales.pdf
**Source tag:** `siwpc`
**Script:** `scripts/scraper_siwpc.py`
**Toggle:** `ENABLE_SIWPC` in `scripts/config.py` (currently `True`)
**Technology:** `requests` (HTTP GET) + `pdfplumber` (PDF text extraction). No Playwright — the PDF is a static file updated daily.
**Counties:** All 12 target counties — SIWPC is a statewide VA foreclosure firm.

### What this source provides
| Field | Available? | Notes |
|-------|-----------|-------|
| Address | ✅ | Address + city in one field; city parsed by backfill |
| County | ✅ | From PDF section header — most reliable source |
| Sale Date | ✅ | M/D/YYYY in table → YYYY-MM-DD |
| Sale Time | ✅ | HH:MM:SS → H:MMAM/PM |
| Sale Location | ✅ | Derived from county → courthouse lookup |
| Trustee | ✅ | Always "Samuel I. White, P.C." |
| Lender | ❌ | Not in PDF summary |
| Notice Text | ❌ | PDF is a summary table only — no full notice |
| Listing Price | ❌ | Not in this PDF (was in old HTML table, removed) |
| Owner Info | 🔄 | GIS backfill |

### PDF format
The PDF is a county-grouped table updated daily (timestamped in footer):
```
VA
Chesterfield
4512 Greenbriar Drive Chester  23831  6/9/2026  10:30:00  Chesterfield  95656
...
City of Richmond
2203 Seminary Ave Richmond     23220  6/9/2026  09:30:00  Richmond      95858
```
County/city headers are matched against `COUNTY_MAP` in the scraper. All other counties are skipped.

### Typical volume (2026-05-15 baseline)
| County | Count |
|--------|-------|
| Chesterfield | 3 |
| Richmond City | 1 |
| **Total in scope** | **4** |
| Total in PDF (statewide) | 32 |

Volume varies daily. SIWPC publishes pending sales only — once a sale occurs or is cancelled, it drops off the next PDF.

### Fix history
- 2026-05-15: Old HTML scraper (`siwpc.com/sales-report`) obsolete — site no longer exists.
  New scraper targets `siwpc.net/AutoUpload/Sales.pdf` — structured PDF, simpler and more reliable.
  Written as `scraper_siwpc.py`, wired into `run.py` via `ENABLE_SIWPC` flag in `config.py`.

### Fix status
- ✅ Working — new PDF scraper confirmed 2026-05-15

---

## Source 6 — The Washington Times Classifieds

**URL:** http://classified.washingtontimes.com/index.php?a=19&b[subcategories_also]=1&b[search_text]=foreclosure
**Source tag:** `washingtontimes`
**Script:** `scripts/scraper_washingtontimes.py`
**Toggle:** `ENABLE_WASHINGTONTIMES` in `scripts/config.py` (currently `True`)
**Technology:** `requests` + BeautifulSoup (PHP-based Geodesic classifieds platform — plain HTML, no JS required)
**Output file:** `data/foreclosures_washingtontimes.json`
**Counties:** Primarily Northern Virginia (Fairfax, Loudoun, Prince William — outside target 12), with target county overlap via Fauquier, Stafford, Spotsylvania. King George and Fredericksburg City notices appear occasionally.

### What this source provides
| Field | Available? | Notes |
|-------|-----------|-------|
| Address | ✅ | Parsed from notice text via `TRUSTEE_ADDR_RE` / `COMMISSIONER_ADDR_RE` |
| County | ✅ | Keyword + regex detection from notice text; drops non-target counties |
| Sale Date | ✅ | Month DD, YYYY format → YYYY-MM-DD |
| Sale Time | ✅ | "at H:MM AM/PM" format |
| Notice Text | ✅ | Full notice body up to 5000 chars |
| Listing URL | ✅ | Individual detail page URL |
| Lender | ❌ | Not parsed — present in notice text but no extraction implemented |
| Trustee | ❌ | Not parsed — present in notice text but no extraction implemented |
| Listing Price | ❌ | Not in classifieds text |
| Owner Info | 🔄 | GIS backfill |

### Data extraction approach
1. Paginates search results at `?a=19&b[search_text]=foreclosure&page=N`
2. Skips DC, MD, and non-Virginia category URL fragments (`SKIP_CATEGORY_FRAGMENTS`)
3. Fetches each detail page; extracts notice body from `div.content_box_1`
4. Virginia filter: notice text must contain "virginia", ", va ", or ", va\n"
5. County detection: regex for "Circuit Court for X County" → keyword scan (longer keys first)
6. Address extraction: regex for "TRUSTEE'S SALE OF …" or "COMMISSIONER'S SALE OF …"
7. Crawl delay: 0.75s between requests

### Known data patterns
- **Primary coverage is NoVA** — most listings are Fairfax/Loudoun/Prince William and are dropped by county filter. Target county yield is low (spot coverage).
- **Lender/trustee not extracted** — the fields are blank and left for manual review or future parsing. The full notice text is preserved so the data is there.
- **Special Commissioner's Sales** included — not just Trustee sales. These are court-ordered sales (often divorce/estate), a slightly different lead type.
- **Crawl delay 0.75s** — polite to the PHP classifieds server; slower than Column.us runs.

### Fix status
- ✅ Working — added 2026-05-22; confirmed functional via code review

---

## Disabled Sources

| Source | Tag | Reason |
|--------|-----|--------|
| Auction.com | `auction_com` | REO listings — different lead type, no courthouse sale date |
| LOGS Legal | `logs_legal` | Migrated to PowerBI embed; BeautifulSoup cannot parse iframe data |
| Virginia eCourts | `va_courts` | Requires authenticated session; no public API endpoint |

---

## Source 7 — Washington Post Public Notices

**URL:** https://publicnotices.washingtonpost.com/?noticeType=Trustee%20Sale
**Source tag:** `washingtonpost`
**Script:** Not yet built
**Toggle:** `washingtonpost` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Column.us portal — Next.js + Firebase client-side rendering. Identical stack to our other Column.us scrapers (`scraper_column_us.py`). Requires Playwright.
**Counties:** Primarily Maryland (Montgomery, Prince George's, Charles, Howard, Anne Arundel) and Washington DC. Virginia notices present but skewed toward NoVA: Prince William (Manassas, Woodbridge) and Loudoun (Leesburg). **No confirmed hits for any of our 12 target counties** in profiling run (2026-05-22, first page of results).

### Key differences from other Column.us portals
| Attribute | Other Column.us portals | Washington Post |
|-----------|------------------------|-----------------|
| Domain | `*.column.us` subdomain | `publicnotices.washingtonpost.com` (custom domain, still Column.us-powered) |
| Notice type URL param | `noticeType=Foreclosure+Sale` | `noticeType=Trustee%20Sale` |
| Newspaper header (page text) | e.g., `RICHMOND TIMES DISPATCH` | `THE WASHINGTON POST` |
| Volume (30-day, unfiltered) | 68–172 | ~827 |
| Target county hit rate | High (core sources) | Unknown — presumed very low |

### What this source provides (expected — based on notice text visible in profiling)
| Field | Available? | Notes |
|-------|-----------|-------|
| Address | ✅ | Structured in notice text — confirmed in sample notices |
| County | ✅ | Labeled below each card as "X County, State"; also in notice text |
| Sale Date | ✅ | Confirmed in notice text (e.g., "JUNE 10, 2026 at 1:15 PM") |
| Sale Time | ✅ | Same — present in notice text |
| Sale Location | ✅ | Courthouse named in notice text |
| Notice Text | ✅ | Full notice body visible in DOM (same as other Column.us portals) |
| Listing URL | ⚠️ | Click handlers, not `<a>` tags — same as other Column.us portals; Pass 8 slug backfill would apply |
| Lender | ✅ | Named in deed of trust language in notice text |
| Trustee | ✅ | Named in notice text |
| Listing Price | ❌ | Not in notice text |
| Owner Info | 🔄 | GIS backfill |

### Data extraction approach (planned)
This portal is a Column.us custom-domain instance and should work with `scraper_column_us.py` with
these config values:
```python
{
    "name":       "washingtonpost",
    "label":      "Washington Post Public Notices",
    "url":        "https://publicnotices.washingtonpost.com/?noticeType=Trustee%20Sale",
    "header":     "THE WASHINGTON POST",
    "source_tag": "washingtonpost",
    "output":     "data/foreclosures_washingtonpost.json",
    "enabled":    False,
    "notes":      "Custom-domain Column.us portal. Primarily MD/DC/NoVA. Target county yield unconfirmed — enable only after testing county filter hit rate.",
}
```

1. Playwright loads the portal URL, waits for Firebase hydration (8s)
2. Clicks "Load more notices" until exhausted (~41+ clicks for 827 results — much higher volume than other portals; consider batching or date-range filtering)
3. Splits page body by `"THE WASHINGTON POST"` header into individual notice blocks
4. For each block: extracts address, county, sale_date, sale_time, lender, trustee
5. County filter gate drops all non-target-county notices (expected to drop ~95%+ of results)
6. False-split healing: "THE WASHINGTON POST" may appear in notice boilerplate — same fix as other portals applies

### County filter expectation
Based on profiling (first 20 of 827 results, 2026-05-22):
- MD counties dominated: Montgomery, Prince George's, Charles, Howard, Anne Arundel
- DC notices present
- VA counties seen: Prince William (6 mentions), Loudoun (3 mentions)
- Target counties (all 12): **0 hits confirmed** in first page
- Estimated target county yield: very low — possibly <5% of raw results, possibly 0

This source is most valuable as **a supplemental NoVA net** for attorneys who publish in the
Washington Post for Fauquier, Stafford, or Spotsylvania notices targeting DC-area audiences.
Enable only after a test run confirms measurable target county yield.

### Volume note
827 results per 30-day window means `scraper_column_us.py`'s "Load more" loop fires ~41+ times.
Expect a longer runtime than other Column.us sources (~10+ minutes). All results (MD, DC, VA) are
written to the output JSON and synced to the sheet — county field is populated for filtering in the
sheet if needed.

### Profiling notes (2026-05-22)
- Confirmed Column.us-powered ("Powered by Column" link in DOM; FAQ links to `help.column.us`)
- Header string `THE WASHINGTON POST` confirmed from `document.body.innerText`
- 827 total results shown for `noticeType=Trustee Sale` in default 30-day window
- Individual notice links use click/router handlers — no `<a href>` tags (same as other Column.us portals)
- "Load more notices" button present in DOM (same scraper pattern applies)
- Full notice text with date/time/location confirmed visible in DOM text

### Fix status
- ✅ Enabled 2026-05-22 — wired into `COLUMN_US_SOURCES` in `config.py`; uses existing `scraper_column_us.py` engine unchanged. No county filter — all notices (MD, DC, VA) are written to output JSON and synced to the sheet. County field derived the same way as other Column.us sources.

---

## Source 8 — Column.us Daily Progress (Charlottesville)

**URL:** https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_dailyprogress`
**Toggle:** `charlottesville` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `CHARLOTTESVILLE DAILY PROGRESS` ✅ confirmed 2026-05-30
**Counties:** Charlottesville City / Albemarle primary; Louisa and Culpeper overlap possible
**Output:** `data/foreclosures_charlottesville.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)
- Primary coverage is Charlottesville/Albemarle — outside 12 target counties. Attorneys
  serving Louisa or Culpeper sometimes publish here.

### Known issues
- **Header string unconfirmed** — `DAILY PROGRESS` has not been validated against live DOM
  text. Run a test and check `document.body.innerText` if 0 records come back.
- **Louisa + Culpeper yield unconfirmed** — only worthwhile if those counties appear in results.

### Fix status
- ⚠️ Enabled 2026-05-22 — first run will confirm header string + target county yield

---

## Source 9 — Column.us NV Daily (Northern Virginia Daily)

**URL:** https://nvdaily.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_nvdaily`
**Toggle:** `nvdaily` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py` — **IF the portal still exists**
**Header string:** `NORTHERN VIRGINIA DAILY` (unconfirmed)
**Counties:** Shenandoah Valley (Shenandoah, Warren, Page) — **outside all 12 target counties**
**Output:** `data/foreclosures_nvdaily.json`

### Known issues
- **Domain likely 404** — `nvdaily.column.us` was returning 404 as of 2025. NV Daily is
  believed to have migrated to their own CMS at `nvdaily.com/classifieds/` (plain HTML,
  different scraper needed — NOT compatible with `scraper_column_us.py`).
- **Wrong county coverage** — Shenandoah Valley is outside the 12 target counties even if
  the portal is fixed. This source is Stage 2+ material at best.
- **First run will error or return 0** — Playwright will hit the 404 and produce no output.

### Remediation path
If you want Shenandoah Valley coverage in Stage 2:
1. Confirm whether `nvdaily.column.us` still returns 404
2. If yes, build a new plain-HTML scraper targeting `nvdaily.com/classifieds/`
3. Re-evaluate county overlap with Stage 2 target list before investing time

### Fix status
- ⚠️ Enabled 2026-05-22 for investigation — expect scraper error or 0 results on first run

---

---

## Source 10 — Column.us Culpeper Star-Exponent

**URL:** https://starexponent.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_culpeper`
**Toggle:** `culpeper` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `CULPEPER STAR EXPONENT` (unconfirmed — assumed from paper name)
**Counties:** Culpeper, Fauquier, Rappahannock (primary); Madison possible
**Output:** `data/foreclosures_culpeper.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Header string unconfirmed** — `CULPEPER STAR EXPONENT` is assumed but not validated against live DOM. If 0 records, check `document.body.innerText` for the actual newspaper name string.
- **Volume expected low** — rural coverage area; Culpeper and Fauquier are target counties but have fewer active foreclosures than Richmond/Fredericksburg metros.

### Fix status
- ⚠️ Enabled — header string unconfirmed; first test run needed

---

## Source 11 — Column.us Roanoke Times

**URL:** https://roanoke.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_roanoke`
**Toggle:** `roanoke` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `THE ROANOKE TIMES` ✅ confirmed 2026-05-30
**Counties (Stage 2 targets):** Roanoke City, Roanoke County, Salem City, Botetourt, Bedford, Franklin, Montgomery, Radford City
**Output:** `data/foreclosures_roanoke.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)
- Both "Foreclosure Sale" and "Notice of Trustee's Sale" are available as distinct notice type filters on this portal (confirmed by research)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Architecture note
Research confirmed `roanoke.column.us` is live and uses the same `column-search.netlify.app` + Firebase/Elasticsearch backend as all other Column.us portals. No code changes to `scraper_column_us.py` needed — only the header string must be validated.

### Known issues
- **Header string unconfirmed** — `ROANOKE TIMES` is the assumed page text delimiter but must be validated against the live DOM. Run a test and check `document.body.innerText` if 0 records come back.
- **Stage 2 counties not in TARGET_COUNTIES by default** — ensure `TARGET_COUNTIES` in `config.py` includes Roanoke area counties before enabling, or county filter will drop all results.
- **`city_to_county()` coverage** — Roanoke area cities (Vinton, Cave Spring, Hollins, etc.) may not be in the mapping; add them before the first production run.

### Fix status
- ⚠️ Enabled (Stage 2) — header string unconfirmed; city_to_county() needs Roanoke area additions

---

## Source 12 — Column.us Lynchburg News & Advance

**URL:** https://newsadvance.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_lynchburg`
**Toggle:** `lynchburg` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `LYNCHBURG NEWS & ADVANCE` ✅ confirmed 2026-05-30 — note: full name with city prefix, not just "NEWS & ADVANCE"
**Counties:** Lynchburg City (primary), Amherst, Bedford, Campbell, Appomattox; Rustburg, Forest area
**Output:** `data/foreclosures_lynchburg.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Header string unconfirmed** — `NEWS & ADVANCE` may be exactly what appears in DOM text, or it may include the city prefix ("LYNCHBURG NEWS & ADVANCE"). Validate before enabling.
- **Disabled — outside Stage 1 target counties** — Lynchburg area is Stage 2+ territory. Enable when expanding beyond the 12 current target counties.
- **`city_to_county()` coverage** — Lynchburg area cities not in the current mapping; add before enabling.

### Fix status
- 🔴 Disabled — Stage 2; enable when expanding to Lynchburg/Central Virginia

---

## Source 13 — Column.us Waynesboro News Virginian

**URL:** https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_waynesboro`
**Toggle:** `waynesboro` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `WAYNESBORO NEWS VIRGINIAN` ✅ confirmed 2026-05-30 — note: full name with city prefix
**Counties:** Waynesboro City (primary), Augusta County, Staunton City; Rockingham overlap possible
**Output:** `data/foreclosures_waynesboro.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)
- Research confirmed `newsvirginian.column.us` is live with "Foreclosure Sale" as an available notice type filter

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Header string unconfirmed** — `NEWS VIRGINIAN` is assumed. Validate against live DOM on first test run.
- **Disabled — outside Stage 1 target counties** — Shenandoah Valley / Augusta County is Stage 2+ territory.
- **`city_to_county()` coverage** — Waynesboro/Augusta/Staunton area not in current mapping; add before enabling.

### Fix status
- 🔴 Disabled — Stage 2; enable when expanding to Shenandoah Valley

---

## Source 14 — Column.us Danville Register & Bee

**URL:** https://godanriver.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_danville`
**Toggle:** `danville` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `DANVILLE REGISTER & BEE` ✅ confirmed 2026-05-30 — note: full name with city prefix
**Counties:** Danville City (primary), Pittsylvania County, Henry, Halifax; southside Virginia
**Output:** `data/foreclosures_danville.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)
- Research confirmed `godanriver.column.us` is live and uses the same Firebase/Elasticsearch backend

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Header string unconfirmed** — `REGISTER & BEE` is assumed. The full paper name is "Danville Register & Bee" — the DOM may render either the short or full form.
- **Disabled — outside Stage 1 target counties** — Southside Virginia is Stage 2+ territory.
- **`city_to_county()` coverage** — Danville area cities not in current mapping; add before enabling.

### Fix status
- 🔴 Disabled — Stage 2; enable when expanding to Southside Virginia

---

## Source 15 — Column.us Martinsville Bulletin

**URL:** https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_martinsville`
**Toggle:** `martinsville` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `MARTINSVILLE BULLETIN` (unconfirmed — assumed from paper name)
**Counties:** Martinsville City (primary), Henry County, Patrick County; southside Virginia
**Output:** `data/foreclosures_martinsville.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Subdomain confirmed live** — `martinsvillebulletin.column.us` confirmed 2026-05-30, 28 results. Header `MARTINSVILLE BULLETIN` confirmed.
- **Disabled — outside Stage 1 target counties** — Henry/Patrick County is Stage 2+ territory.

### Fix status
- 🔴 Disabled — Stage 2; subdomain existence unconfirmed

---

## Source 16 — Column.us Daily News-Record (Harrisonburg)

**URL:** https://dnronline.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_harrisonburg`
**Toggle:** `harrisonburg` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `DAILY NEWS-RECORD` (unconfirmed — assumed from paper name)
**Counties:** Harrisonburg City (primary), Rockingham County, Page County; Shenandoah Valley
**Output:** `data/foreclosures_harrisonburg.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Known issues
- **Subdomain confirmed live** — `dnronline.column.us` confirmed 2026-05-30, 8 results. Header `DAILY NEWS-RECORD` confirmed. Note: current results include timeshare sales at Massanutten (Rockingham County) — not residential foreclosures, but regular trustee sales will appear here too.
- **Disabled — outside Stage 1 target counties** — Shenandoah Valley is Stage 2+ territory.

### Fix status
- 🔴 Disabled — Stage 2; subdomain existence unconfirmed

---

## Source 17 — Column.us Westmoreland News

**URL:** https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_westmoreland`
**Toggle:** `westmoreland` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `WESTMORELAND NEWS` (unconfirmed — assumed from paper name)
**Counties:** Westmoreland County (primary), Richmond County, Northumberland, Lancaster; Northern Neck peninsula
**Output:** `data/foreclosures_westmoreland.json`

### What this source provides
- Same fields as Fredericksburg Column.us (address, city, ZIP, county, sale date/time, lender, trustee, full notice text, listing URL)

### What this source does NOT provide
- Asking/starting bid price
- Owner information (GIS backfill required)

### Notes
- Northern Neck is a rural peninsula between the Potomac and Rappahannock rivers. King George County (a Stage 1 target) borders Westmoreland; notices for King George properties may occasionally appear here as dual-publication.

### Known issues
- **Subdomain confirmed live** — `westmorelandnews.column.us` confirmed 2026-05-30, 7 results. Header `WESTMORELAND NEWS` confirmed. Colonial Beach (Westmoreland County) borders King George — watch for King George notices dual-published here.
- **Disabled — outside Stage 1 target counties** — Northern Neck counties are Stage 2+ territory.

### Fix status
- 🔴 Disabled — Stage 2; subdomain existence unconfirmed

---

## Source 18 — Column.us FFXnow (Fairfax)

**URL:** https://ffxnow.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_ffxnow`
**Toggle:** `ffxnow` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `FFXNOW` (unconfirmed)
**Counties:** Fairfax County, Falls Church City; Northern Virginia
**Output:** `data/foreclosures_ffxnow.json`

### Notes
- NoVA digital news outlet. Fairfax County is outside the 12 Stage 1 target counties. Enable in Stage 2 when expanding to NoVA. Volume likely moderate given the size of Fairfax County.

### Fix status
- 🔴 Disabled — Stage 2; NoVA coverage outside target counties

---

## Source 19 — Column.us ARLnow (Arlington)

**URL:** https://arlnow.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_arlnow`
**Toggle:** `arlnow` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `ARLNOW` (unconfirmed)
**Counties:** Arlington County; Northern Virginia
**Output:** `data/foreclosures_arlnow.json`

### Notes
- Arlington is a small, dense NoVA county. Foreclosure volume is likely low. Enable in Stage 2. Fauquier County attorneys sometimes dual-publish in NoVA papers; marginal overlap possible.

### Fix status
- 🔴 Disabled — Stage 2; NoVA coverage outside target counties

---

## Source 20 — Column.us ALXnow (Alexandria)

**URL:** https://alxnow.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_alxnow`
**Toggle:** `alxnow` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `ALXNOW` (unconfirmed)
**Counties:** Alexandria City; Northern Virginia
**Output:** `data/foreclosures_alxnow.json`

### Notes
- Alexandria is an independent city bordering Arlington and Fairfax. Volume likely low. Enable in Stage 2.

### Fix status
- 🔴 Disabled — Stage 2; NoVA coverage outside target counties

---

## Source 21 — Column.us Bristol Herald Courier

**URL:** https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_bristol`
**Toggle:** `bristol` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: False`)
**Technology:** Playwright (same engine as Fredericksburg) via `scraper_column_us.py`
**Header string:** `BRISTOL HERALD COURIER` (unconfirmed — assumed from paper name)
**Counties:** Bristol City, Washington County, Scott County, Russell County; far Southwest Virginia
**Output:** `data/foreclosures_bristol.json`

### Notes
- Southwest Virginia is Stage 2+ territory. The Bristol metro straddles the VA/TN state line; county filter is important to drop Tennessee-side notices. Enable when expanding to far Southwest Virginia.

### Known issues
- **Subdomain confirmed live** — `heraldcourier.column.us` confirmed 2026-05-30, 10 results. Header `BRISTOL HERALD COURIER` confirmed. Coverage is Washington County (Abingdon/Bristol area).
- **Disabled — outside Stage 1 and Stage 2 target counties** — Far Southwest VA is Stage 3+ territory.

### Fix status
- 🔴 Disabled — Stage 3+; subdomain existence unconfirmed

---

## Source 22 — Southside Sentinel (Independent HTML)

**URL:** https://www.ssentinel.com/Classifieds/public-notices/
**Source tag:** `southside_sentinel`
**Script:** Not yet built — new source
**Toggle:** `ENABLE_SOUTHSIDE_SENTINEL` in `scripts/config.py` (not yet added)
**Technology:** Static HTML — `requests` + BeautifulSoup. No JavaScript required.
**Counties:** Middlesex County (primary), Middle Peninsula (Essex, Gloucester, Mathews possible)
**Output:** `data/foreclosures_southside_sentinel.json`

### What this source provides
| Field | Available? | Notes |
|-------|-----------|-------|
| Address | ✅ | In notice text — confirmed in live HTML |
| County | ✅ | Implied by geography; Middlesex confirmed |
| Sale Date | ✅ | In notice text — confirmed June 2026 dates in live HTML |
| Sale Time | ✅ | In notice text |
| Notice Text | ✅ | Full HTML notice body — no paywall, no JS |
| Listing URL | ✅ | Direct HTML page URL |
| Lender | ⚠️ | Likely in notice text; not yet parsed |
| Trustee | ⚠️ | Likely in notice text; not yet parsed |
| Listing Price | ❌ | Not in notice classifieds |
| Owner Info | 🔄 | GIS backfill |

### Data extraction approach (planned)
1. `requests.get()` the public-notices URL — no JS required
2. BeautifulSoup parses individual notice listing links
3. For each notice: fetch detail page, extract full notice body text
4. Parse address, sale date, sale time, county from notice text using existing `scraper.py` helpers
5. County filter gate: Middlesex is outside Stage 1 target counties; relevant for Stage 2 (statewide)

### Architecture note
This paper is **not on Column.us** — it's a fully independent static HTML classifieds system. It represents the pattern for dozens of small Virginia weeklies that may publish foreclosure notices outside the Column.us ecosystem. Once a scraper is built for this one, the same approach (requests + BeautifulSoup + notice text parsing) applies to other independent papers.

### Coverage context
Middlesex County is on the Middle Peninsula (between the Rappahannock and York rivers). It's a rural county not covered by any confirmed Column.us subdomain. This source fills that gap for Stage 2 statewide expansion.

### Fix status
- 🔴 Not yet built — new source confirmed live 2026-05-30; scraper and config toggle needed for Stage 2

---

## Source 23 — LOGS Legal Group LLP

**URL:** https://www.logs.com/va-sales-report.html
**Source tag:** `logs_legal`
**Script:** Not yet built (previous scraper is dead — LOGS migrated to PowerBI embed)
**Toggle:** `ENABLE_LOGS_LEGAL` in `scripts/config.py` (currently `False` — dead legacy flag)
**Technology:** PowerBI embed (JavaScript-rendered) — requires Playwright to interact with the embedded report
**Counties:** Statewide Virginia (LOGS is a major VA foreclosure law firm)

### What this source provides
| Field | Available? | Notes |
|-------|-----------|-------|
| Address | ✅ | In PowerBI table rows |
| County | ✅ | In PowerBI table — likely a column |
| Sale Date | ✅ | In PowerBI table |
| Sale Time | ✅ | In PowerBI table |
| Listing Price | ✅ | **Estimated opening bid** included — unique among law firm sources |
| Trustee | ✅ | Always "LOGS Legal Group LLP" |
| Lender | ❌ | Not in summary table |
| Notice Text | ❌ | Summary table only, no full notice text |
| Owner Info | 🔄 | GIS backfill |

### Why this source matters
LOGS is the **only other law firm besides SIWPC** confirmed to publish a public VA trustee sale list with estimated opening bid amounts. That bid price is valuable data for investment priority scoring.

### Scraping challenge
PowerBI embeds load data via authenticated internal API calls (Power BI REST API or Azure Analysis Services). Playwright can interact with the visual report but extracting tabular data requires either:
- Intercepting the network requests PowerBI makes to its backend (XHR/fetch intercept in Playwright)
- Reading the rendered table DOM after PowerBI fully hydrates

**This is the hardest scraping challenge in the pipeline.** The previous `logs_legal` scraper was an HTML table scraper that broke when LOGS migrated to PowerBI. Rebuilding it requires Playwright + network interception.

### Fix status
- 🔴 Dead — old HTML scraper obsolete (LOGS migrated to PowerBI). New Playwright scraper needed; complexity is high. Research and build when SIWPC + Column.us sources are stable.

---

## Source 24 — Tromberg, Miller, Morris & Partners (TMMP)

**URL:** https://tmppllc.com/virginia_foreclosure_sales (unverified)
**Source tag:** `tmmp`
**Script:** Not yet built
**Technology:** Unknown — possibly static HTML table or PDF
**Counties:** Claimed statewide Virginia coverage (38+ counties/cities claimed but unverified)

### Status
Research found claims that TMMP publishes a public Virginia trustee sale list at `tmppllc.com/virginia_foreclosure_sales` with 70+ scheduled sales including file numbers, bid deposits, property addresses, and sale dates. However, **2 of 3 verification votes could not confirm the page is real/accessible**. The firm is a known Virginia foreclosure practice (USFN member).

### Next step
Manual visit to `tmppllc.com/virginia_foreclosure_sales` to confirm whether the page exists and what format the data is in. If confirmed:
- If static HTML table: build a `requests` + BeautifulSoup scraper (same pattern as SIWPC old scraper)
- If PDF: build a `pdfplumber` scraper (same pattern as SIWPC new scraper)
- If JS-rendered: build a Playwright scraper

### Fix status
- ⚠️ Unverified — manual check needed before any scraper work

---

---

## Source 25 — Column.us Daily Press (Hampton Roads)

**URL:** https://dailypress.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_dailypress`
**Toggle:** `dailypress` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `DAILY PRESS` ✅ confirmed 2026-05-30
**Counties:** Newport News City, Hampton City, York County, James City County, Isle of Wight, Poquoson; Hampton Roads metro
**Output:** `data/foreclosures_dailypress.json`

### What this source provides
- Same fields as other Column.us portals (address, county, sale date/time, lender, trustee, full notice text, listing URL)

### Known issues
- **Out-of-state notices present** — the portal publishes some non-Virginia notices (sample showed Michigan "Delta County"). County filter drops all non-VA results automatically.
- **6 results confirmed** on 2026-05-30 detect run.

### Fix status
- ✅ Enabled 2026-05-30 — header confirmed, county filter handles out-of-state noise

---

## Source 26 — Column.us Northern Neck News

**URL:** https://northernnecknews.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_northernnecknews`
**Toggle:** `northernnecknews` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `NORTHERN NECK NEWS` ✅ confirmed 2026-05-30
**Counties:** Richmond County (Warsaw) primary; Northumberland, Lancaster, Westmoreland overlap
**Output:** `data/foreclosures_northernnecknews.json`

### Notes
- First confirmed notice was Warsaw, VA (Richmond County) — rural Northern Neck peninsula. Low volume expected but fills a gap not covered by other portals.
- Overlaps geographically with `westmorelandnews.column.us` — some attorneys may dual-publish.

### Fix status
- ✅ Enabled 2026-05-30 — 2 results confirmed, header confirmed

---

## Source 27 — Column.us Sun Gazette (Arlington/Fairfax)

**URL:** https://sungazette.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_sungazette`
**Toggle:** `sungazette` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `SUN GAZETTE` (unconfirmed — 0 results on 2026-05-30 detect run)
**Counties:** Arlington County, Fairfax County; Northern Virginia
**Output:** `data/foreclosures_sungazette.json`

### Fix status
- ⚠️ Enabled 2026-05-30 — portal live, 0 results currently, header unconfirmed

---

## Source 28 — Column.us InsideNOVA

**URL:** https://insidenova.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_insidenova`
**Toggle:** `insidenova` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `INSIDENOVA` (unconfirmed — 0 results on 2026-05-30 detect run)
**Counties:** Prince William County, Manassas City, Manassas Park City; Northern Virginia
**Output:** `data/foreclosures_insidenova.json`

### Fix status
- ⚠️ Enabled 2026-05-30 — portal live, 0 results currently, header unconfirmed

---

## Source 29 — Column.us Rappahannock News

**URL:** https://rappnews.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_rappnews`
**Toggle:** `rappnews` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `RAPPAHANNOCK NEWS` (unconfirmed — 0 results on 2026-05-30 detect run)
**Counties:** Rappahannock County primary; Culpeper/Fauquier border overlap possible
**Output:** `data/foreclosures_rappnews.json`

### Notes
- Rappahannock County is a small, rural county bordering Culpeper and Fauquier (both Stage 1 targets). Attorneys serving those counties may occasionally publish here.

### Fix status
- ⚠️ Enabled 2026-05-30 — portal live, 0 results currently, header unconfirmed

---

## Source 30 — Column.us Cardinal News

**URL:** https://cardinalnews.column.us/search?noticeType=Foreclosure+Sale
**Source tag:** `column_us_cardinalnews`
**Toggle:** `cardinalnews` entry in `COLUMN_US_SOURCES` in `scripts/config.py` (currently `enabled: True`)
**Technology:** Playwright via `scraper_column_us.py`
**Header string:** `CARDINAL NEWS` (unconfirmed — 0 results on 2026-05-30 detect run)
**Counties:** Statewide Virginia digital outlet — Southwest and Southside Virginia focus
**Output:** `data/foreclosures_cardinalnews.json`

### Notes
- Cardinal News is a nonprofit digital outlet covering news that large papers miss, focused on Southwest and Southside VA. If attorneys publish legal notices here, it could fill rural county gaps. Low volume expected.

### Fix status
- ⚠️ Enabled 2026-05-30 — portal live, 0 results currently, header unconfirmed

---

## Fix Order (by lead volume potential)

1. **SIWPC** — highest-volume firm, early-warning value, simple HTML table scraper.
   Investigate why 0 records, fix table parsing.
2. **Column.us Richmond** — Richmond/Chesterfield/Henrico are large markets.
   Confirm newspaper header string, fix if mismatched.
3. **PNV** — Still returning card text instead of full notice. Debug Playwright detail fetch.
4. **Column.us Williamsburg** — Confirm header string on first run; accept 0 if legitimately empty.
5. **Column.us Daily Progress** — Confirm header string; only valuable if Louisa/Culpeper yield confirmed.
6. **Column.us Culpeper** — Confirm header string; target counties Culpeper + Fauquier are in scope.
7. **TMMP** — Manual verify `tmppllc.com/virginia_foreclosure_sales`; if live, build scraper.
8. **LOGS Legal** — PowerBI scraper is complex; tackle after simpler sources are stable.
9. **NV Daily** — Domain likely 404; wrong county coverage. Revisit in Stage 2 with new scraper.
10. **Southside Sentinel** — Stage 2 (Middlesex County, statewide expansion). Simple HTML scraper.
11. **Stage 2 Column.us sources** — Roanoke, Waynesboro, Lynchburg, Danville (confirm header strings, expand city_to_county mapping, add target counties to config).
