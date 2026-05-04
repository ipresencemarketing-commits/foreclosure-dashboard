# Foreclosure Finder — Project Context for Claude

## Who I am
I'm Joe, a house flipper based in the Fredericksburg, Virginia area. My goal is to find foreclosure properties before they hit the open market, evaluate their investment potential, and contact the owners early. I run everything manually from Terminal on my Mac.

## What this project does
A Python pipeline that:
1. Scrapes foreclosure listings from multiple public sources
2. Syncs them into a Google Sheet I use as a working dashboard
3. Backfills missing fields (owner info, property details, sale dates) from free public APIs
4. Publishes a GitHub Pages site as a shareable view

## Project location
`/Users/jarvis/Documents/Claude/Foreclosures/`

## File structure
```
Foreclosures/
├── scripts/
│   ├── scraper.py        — main scraper (all sources + GIS owner enrichment)
│   ├── sheets_sync.py    — Google Sheets sync (push listings, update summary tab)
│   ├── backfill.py       — fill blank cells across 8 passes (GIS, Redfin, derived calcs)
│   ├── update.sh         — full pipeline runner (correct order of operations)
│   ├── setup.py          — one-time credential/sheet setup
│   └── verify.py         — gap report (optional)
├── data/
│   └── foreclosures.json — scraped listing output (source of truth for sheets_sync)
├── credentials/
│   └── service-account.json  — Google service account key (gitignored, never commit)
├── Pipeline_Optimization_Guide.docx  — recommended data sources & optimization notes
└── CLAUDE.md             — this file
```

## How to run the pipeline
```bash
cd ~/Documents/Claude/Foreclosures

# Full run (scrape → sync → backfill → sync → publish):
bash scripts/update.sh

# Test run without pushing to GitHub:
bash scripts/update.sh --no-push

# Individual steps:
python3 scripts/scraper.py       # scrape all sources → data/foreclosures.json
python3 scripts/sheets_sync.py   # push to Google Sheets
python3 scripts/backfill.py      # fill blank cells
```

## IMPORTANT: Bash sandbox is broken
The Cowork bash sandbox consistently fails to mount the Foreclosures folder. **Do not use the bash tool to run Python scripts.** Instead:
- Edit files directly with Read/Edit/Write tools
- Give Joe the exact Terminal command to run
- Joe is comfortable running commands in Terminal himself

## Target counties (12)
Fredericksburg City, Stafford, Spotsylvania, Caroline, Fauquier, Culpeper, King George, Hanover, Richmond City, Chesterfield, Henrico, Louisa

## Google Sheet
- **Sheet ID:** `1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c`
- 29 columns (A–AC), header row 1
- Appends new rows; backfills enrichment on existing rows without overwriting manual data
- Column order is defined by `COLUMNS` list in `sheets_sync.py` — changing it there re-orders the sheet on next sync

## Sheet columns (current order, A–AC)
| Col | Field | Source |
|-----|-------|--------|
| A | Address | All scrapers |
| B | County | Derived / GIS |
| C | F_Sale_Date | PNV, Column.us, Auction.com notice text |
| D | F_Sale_Time | PNV, Column.us notice text |
| E | Status | Derived from listing stage |
| F | Investment_Priority | High/Medium/Low — stage + days until sale |
| G | Listing_Price | Asking/starting bid from source |
| H | Current_Est_Value | GIS assessed value or Redfin estimate |
| I | Rough_Equity_Est | Est_Value − Listing_Price |
| J | Est_Profit_Potential | (Est_Value × 0.70) − Listing_Price (70% rule) |
| K | Beds_Baths_Sqft | GIS or Redfin |
| L | Year_Built | GIS or Redfin |
| M | Lot_Size | GIS |
| N | Last_Sold_Date | GIS |
| O | Last_Sold_Price | GIS |
| P | Years_Since_Last_Sale | Derived from Last_Sold_Date |
| Q | City | Parsed from address |
| R | ZIP | Parsed from address |
| S | State | Always "VA" |
| T | Property_Type | Default SFR |
| U | Is_Auction | Yes if stage=auction |
| V | Owner_Name | GIS (VGIN → county fallback) |
| W | Owner_Mailing_Address | GIS |
| X | Owner_Mailing_Differs_From_Property | Yes/No |
| Y | Estimated_Phone | Blank — requires paid skip-trace |
| Z | Estimated_Email | Blank — requires paid skip-trace |
| AA | Listing_URL | Individual notice URL or source URL |
| AB | Notes | Sale location, lender, trustee, source tag |
| AC | Date_Checked | ISO date of last sync |

## Data sources

### Foreclosure notices (primary)
| Source | URL | Notes |
|--------|-----|-------|
| Public Notice Virginia (PNV) | publicnoticevirginia.com | Best single source — free, statewide, structured. All 12 counties. Virginia Code §55.1-321 requires trustee sale notices here. |
| fredericksburg.column.us | fredericksburg.column.us | Fredericksburg/Spotsylvania supplement. Next.js + Firebase — requires Playwright. Individual notice URLs at `/notice/<slug>`. |
| Auction.com | auction.com | Bank-owned & pre-foreclosure auctions. XML sitemap + detail pages. |
| HUD Homes | hudhomestore.gov | FHA REO listings. JSON in hidden input. |
| Fannie Mae HomePath | homepath.fanniemae.com | Fannie REO. Bounding-box JSON API. Owner hardcoded "Fannie Mae". |
| Freddie Mac HomeSteps | homesteps.com | Freddie REO. Server-rendered Drupal HTML. Owner hardcoded "Freddie Mac". |

### Property data + owner info
| Source | URL | Notes |
|--------|-----|-------|
| VGIN Statewide Parcel API | gismaps.vdem.virginia.gov/arcgis/rest/services/VA_Base_Layers/VA_Parcels/FeatureServer/0/query | **Primary.** Single endpoint for all 12 counties. Returns owner, address, year built, sqft, beds/baths, assessed value, last sale in one call. Tried first in `gis_full_lookup()`. |
| County ArcGIS endpoints | 12 separate URLs in `GIS_REGISTRY` (scraper.py) | **Fallback** when VGIN returns no match. Same fields, county-specific URLs. |
| Redfin (unofficial API) | redfin.com/stingray/api/gis | **Secondary fallback.** Used only when GIS missing beds/sqft or assessed value. Strips `{}&&` XSS prefix from response. |

### NOT recommended / not in use
- RealtyTrac / Foreclosure.com — paywalled, PNV has same data free
- Zillow API — partner-restricted
- PropStream / BatchLeads — no public API, ~$100/month

## Backfill pass structure
```
Pass 1    — F_Sale_Date / F_Sale_Time  (re-fetch notice URL, re-parse text)
Pass 1b   — F_Sale_Date / F_Sale_Time  (secondary: Auction.com detail + PNV address search)
Pass 2    — County                     (city_to_county → address parse → ZIP → Census geocoder)
Pass 3    — State                      (always VA)
Pass 4    — City                       (parse from address)
Pass 5    — ZIP                        (extract 5-digit from address)
Pass 6    — Owner + Property Details   (VGIN → county ArcGIS fallback → Redfin supplement;
                                        ONE call per property returns both owner fields AND
                                        all property detail fields; calculates derived fields)
Pass 7    — Derived fields only        (recalculates equity/profit for rows with new inputs;
                                        no API calls)
Pass 8    — Column.us Listing_URL      (Playwright DOM: replace generic search URL with
                                        individual /notice/<slug> URL)
```

## Key technical details

### GIS lookup (`gis_full_lookup` in backfill.py)
- Tries VGIN statewide first across 5 address field name variants
- Falls back to county-specific endpoint from `GIS_REGISTRY` in scraper.py
- One HTTP call returns everything — owner name, mailing address, year built, sqft, beds, baths, lot size, assessed value, last sale date/price
- WHERE clause: `UPPER(addr_field) LIKE '%HOUSE_NUM STREETWORD%'` — resilient to minor formatting differences
- Returns top 3 features; picks best match by house number
- Sleep: 0.25s between calls

### Column.us scraping
- Next.js + Firebase app — requires Playwright/headless Chromium
- `scraper.py`: loads page, clicks "Load more" until exhausted, extracts individual notice URLs via JS DOM query, pairs with notice text blocks using `zip_longest`
- `backfill.py` Pass 8: for existing rows with the generic search URL, runs Playwright to find the individual notice permalink by address match
- Individual notice URLs: `https://fredericksburg.column.us/notice/<slug>`

### Redfin unofficial API
- Endpoint: `https://www.redfin.com/stingray/api/gis?...`
- Response prefixed with `{}&&` — strip first 4 chars before JSON parse
- Used only as fallback; may return 403 on some runs

### Derived field formulas
- `Rough_Equity_Est` = `Current_Est_Value` − `Listing_Price`
- `Est_Profit_Potential` = (`Current_Est_Value` × 0.70) − `Listing_Price` (70% rule: max flipper offer = 70% of ARV)
- `Years_Since_Last_Sale` = current year − year from `Last_Sold_Date`

### sheets_sync.py behavior
- `FORCE_UPDATE_COLS = ["Listing_URL"]` — always overwrites Listing_URL when scraper re-finds a row
- All other fields: only writes if cell is currently blank (never overwrites manual data)
- `sheet.clear()` then full rewrite is the correct fix when column order gets mismatched

### County key mapping
County display names (in sheet) → GIS_REGISTRY keys via `DISPLAY_TO_KEY` dict in backfill.py.
Example: "Fredericksburg City" → "fredericksburg", "Stafford County" → "stafford"

## GIS_REGISTRY endpoints (in scraper.py)
| County | ArcGIS URL |
|--------|-----------|
| Stafford | gis.staffordcountyva.gov/arcgis/rest/services/Public/Parcels/FeatureServer/0/query |
| Spotsylvania | gis.spotsylvania.va.us/arcgis/rest/services/Parcels/FeatureServer/0/query |
| Fredericksburg | gis.fredericksburgva.gov/arcgis/rest/services/Property/FeatureServer/0/query |
| Caroline | gis.carolinecounty.va.gov/arcgis/rest/services/Parcels/FeatureServer/0/query |
| Fauquier | gis.fauquiercounty.gov/arcgis/rest/services/Property/Parcels/FeatureServer/0/query |
| Culpeper | gis.culpepercountyva.gov/arcgis/rest/services/Parcels/FeatureServer/0/query |
| King George | gis.kinggeorgecountyva.gov/arcgis/rest/services/Parcels/FeatureServer/0/query |
| Hanover | gis.hanovercounty.gov/arcgis/rest/services/Parcels/FeatureServer/0/query |
| Richmond City | gis.richmondgov.com/arcgis/rest/services/Parcels/MapServer/0/query |
| Chesterfield | gis.chesterfield.gov/arcgis/rest/services/Parcels/FeatureServer/0/query |
| Henrico | gis.henrico.us/arcgis/rest/services/Property/Parcels/FeatureServer/0/query |
| Louisa | gis.louisacounty.org/arcgis/rest/services/Parcels/FeatureServer/0/query |

## Future improvements (not yet built)
- Owner contact enrichment: BeenVerified or Spokeo API (~$0.05/record) for phone/email
- Virginia SCC CLIQUE lookup for LLC/trust entity owners
- Scheduled daily run via Cowork scheduled tasks
- Consider PropStream/BatchLeads if you want a managed all-in-one service (~$100/month)
