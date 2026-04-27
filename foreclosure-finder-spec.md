# Feature Spec: Foreclosure Finder — Daily Live Dashboard

**Version:** 1.1  
**Date:** April 27, 2026  
**Author:** Joe (house flipper)  
**Status:** Draft

---

## Problem Statement

House flippers need a reliable, daily-updated view of foreclosure properties in their target markets to act before competitors. Today, finding this data requires manually checking multiple county websites, paid listing services, and MLS feeds — a time-consuming process that often results in missed deals or stale information. Without a centralized, automated tracker, opportunities slip through and due diligence is slowed by scattered data.

---

## Goals

1. **Reduce deal discovery time** — surface all active foreclosures in a target area in under 60 seconds, vs. 30–60 minutes of manual research today.
2. **Never miss a filing** — capture pre-foreclosures (NOD/lis pendens), active auctions, and REO listings within 24 hours of public record updates.
3. **Filter to investable deals** — allow Joe to apply criteria (price, property type, equity cushion) so only actionable opportunities appear.
4. **Enable daily review habit** — deliver a persistent dashboard that can be opened each morning without re-running any searches.
5. **Build a deal history** — track properties over time so Joe can see how long a property has been in foreclosure and whether bids were missed.

---

## Non-Goals

1. **Automated offer or bid submission** — the tool surfaces deals; Joe makes decisions and acts himself. No transaction execution.
2. **Nationwide coverage in v1** — the first version targets one or two counties/metro areas. Expanding coverage is a v2 initiative.
3. **MLS / Zillow active listing data** — this spec focuses on distressed/foreclosure-specific data sources, not general market listings.
4. **Title search or lien analysis** — identifying encumbrances is out of scope; Joe uses a title company for that after selecting a deal.
5. **Mobile app** — the dashboard is a desktop web artifact for now; a mobile-optimized view is a future consideration.

---

## User Stories

### Discovery

- As a house flipper, I want to see all new foreclosure filings in my target county updated every morning so that I can identify deals before they hit the open market.
- As a house flipper, I want to filter results by property type (single-family vs. multi-family) so that I only review properties that match my buy-box.
- As a house flipper, I want to filter by estimated price or assessed value so that I can exclude properties outside my capital range.
- As a house flipper, I want to see the foreclosure stage (pre-foreclosure, auction, REO) for each property so that I can prioritize outreach strategy accordingly.

### Dashboard

- As a house flipper, I want a persistent dashboard I can open every morning so that I don't have to re-run searches or remember where I left off.
- As a house flipper, I want the dashboard to refresh automatically on a daily schedule so that I always see current data without manual intervention.
- As a house flipper, I want to see a summary count of new vs. existing listings at the top of the dashboard so that I can quickly gauge deal flow.
- As a house flipper, I want to click into a property record and see its address, assessed value, auction date (if applicable), and lender so that I can decide whether to investigate further.

### Tracking

- As a house flipper, I want to mark a property as "watched," "passed," or "pursued" so that I can track my pipeline within the dashboard.
- As a house flipper, I want to see how many days a property has been in foreclosure so that I can gauge urgency and seller motivation.
- As a house flipper, I want a history of properties I've previously reviewed so that I don't waste time re-evaluating the same deal.

---

## Requirements

### Must-Have (P0)

| # | Requirement | Acceptance Criteria |
|---|---|---|
| 1 | Pull foreclosure data from public records daily | Data refreshes automatically each morning; dashboard shows "Last updated: [date/time]" |
| 2 | Display pre-foreclosure, auction, and REO listings in a single view | All three stages appear in one table/card view with a "Stage" label on each record |
| 3 | Show key property fields per listing | Each record shows: address, county, stage, estimated value/asking price, sale date, sale time, sale location, days until sale (countdown), days in foreclosure, lender/bank |
| 4 | Filter by foreclosure stage | User can toggle to show All / Pre-foreclosure / Auction / REO independently |
| 5 | Filter by property type | Single-family and multi-family options; default shows all |
| 6 | Persistent dashboard artifact | Dashboard loads in Cowork sidebar and retains state across sessions |
| 7 | Daily automated refresh | Dashboard auto-fetches fresh data on open if last refresh was >20 hours ago |
| 8 | Sale postponement disclaimer | A persistent notice on the dashboard reminds Joe to verify sale date/time directly with the trustee or on Auction.com the day before, as Virginia sales can be postponed with minimal notice |

### Nice-to-Have (P1)

| # | Requirement | Acceptance Criteria |
|---|---|---|
| 9 | Price range filter | Slider or min/max inputs; filters list in real time |
| 10 | "New today" badge on listings added since last session | Listings filed or updated in the last 24 hours show a visual "New" indicator |
| 11 | Deal status tracking (watched / passed / pursued) | User can tag each property; tags persist across sessions |
| 12 | Sort by sale date, days until sale, days in foreclosure, or price | Column headers clickable to sort ascending/descending; default sort is soonest sale date first |
| 13 | One-click link to county public record | Each listing has an external link to the original filing |

### Future Considerations (P2)

| # | Requirement | Notes |
|---|---|---|
| 14 | Multi-county / multi-market view | Expand beyond v1 target area; requires scalable data source strategy |
| 15 | ARV estimator integration | Pull comps to auto-calculate After Repair Value and flag deals meeting the 70% rule |
| 16 | Direct mail / skip-trace export | Export a CSV of pre-foreclosure homeowner contact info for outreach campaigns |
| 17 | SMS or email alert for new high-priority listings | Push notification when a property matching strict criteria appears |
| 18 | Mobile-optimized view | Responsive layout for on-the-go deal review |

---

## Data Sources

### Virginia foreclosure context

Virginia is a **non-judicial foreclosure state**, which significantly affects how data is sourced. There is no court filing (lis pendens) required — lenders can foreclose via a trustee sale without going through the courts. This means county circuit court records are less useful than in judicial states. The primary public notice mechanism is **newspaper legal notice publication** (required by VA Code § 55.1-321) and **trustee sale notices** filed with the locality.

### Target areas — v1 (Fredericksburg metro)

The Fredericksburg metro spans four jurisdictions, each with its own public records portal:

- **Fredericksburg City** — fredericksburgva.gov (Commissioner of Revenue / Circuit Court)
- **Stafford County** — staffordcountyva.gov (Circuit Court clerk)
- **Spotsylvania County** — spotsylvaniacounty.gov (Circuit Court clerk)
- **Caroline County** — co.caroline.va.us (Circuit Court clerk)

### Target areas — v2 (Richmond metro expansion)

- **Richmond City** — rva.gov
- **Henrico County** — henrico.us
- **Chesterfield County** — chesterfield.gov
- **Hanover County** — hanovercounty.gov

### Free data sources by foreclosure stage

| Stage | Source | Notes |
|---|---|---|
| Trustee sale / auction notices | Virginia legal notices via **VAnotices.com** and **PublicNoticeVirginia.com** | Free; required by state law to publish; updated weekly |
| Auction listings | **Auction.com** | Free to browse; covers most VA trustee sales |
| REO / bank-owned | **HUD Homes** (hudhomestore.gov), **Fannie Mae HomePath**, **Freddie Mac HomeSteps** | Free; covers federally-backed REO |
| Property details & assessed values | Each county's **GIS / property search portal** (free, public) | Stafford, Spotsylvania, and Fredericksburg all have free online property lookups |
| Sales history & deeds | **Virginia Circuit Court land records** via each county's online portal | Free; searchable by address or owner name |

---

## Recommendations

### Free-first data source strategy

Given Virginia's non-judicial foreclosure process and the current zero-budget constraint, the recommended free source stack is:

**Trustee sale notices (primary Virginia source)**
Because Virginia doesn't require court filings, the earliest public signal of an impending foreclosure is the legally required newspaper notice. VAnotices.com and PublicNoticeVirginia.com aggregate these statewide for free. Notices typically appear 2–4 weeks before the sale date, providing a window to research and act. This is the closest equivalent to a lis pendens in a judicial state and should be the primary data feed for the dashboard.

**Auction listings**
Auction.com covers Virginia trustee sales and is free to browse. It often picks up the same notices as the legal notice sites but with cleaner property data attached. Use as a secondary source to enrich records pulled from the notice sites.

**REO / Bank-owned**
HUD Homes (hudhomestore.gov), Fannie Mae HomePath (homepath.com), and Freddie Mac HomeSteps (homesteps.com) cover federally-backed REO inventory for free. Private bank REO (Chase, Wells Fargo, etc.) cannot be accessed systematically without a paid source — this is an accepted gap for v1.

**Property details and assessed values**
All four Fredericksburg-area jurisdictions offer free online property lookup. Stafford and Spotsylvania both have robust GIS portals with assessed value, square footage, year built, and ownership history. Fredericksburg City and Caroline County have simpler but functional portals. These should be queried to enrich each listing with property-level data after it is identified via the notice sources.

### Build approach recommendation

For v1 with free sources, the most reliable architecture is a **semi-automated web scraping pipeline** rather than a full API integration. Specifically:

The dashboard should be built as a persistent Cowork artifact that reads from a locally maintained data file (CSV or JSON) in the Foreclosures workspace folder. A daily scheduled task scrapes the target sources, appends new listings, and updates the file — the dashboard reads from it on open. This approach is robust to source changes, requires no API keys, and keeps all data local.

The biggest risk with free sources is **scraper fragility** — county websites change layouts without notice. Mitigate this by building simple, tolerant scrapers and flagging staleness clearly on the dashboard (e.g., a warning banner if data is >48 hours old).

### When to add a paid source

Once deal flow is validated and a budget is available, ATTOM Data Solutions offers the best coverage-to-cost ratio for foreclosure data. A single-county subscription typically runs $50–$150/month and eliminates scraper maintenance entirely. RealtyTrac is an alternative but is generally considered less current. Revisit this decision after 60–90 days of using the free-source dashboard.

### Known data gaps and recommended solutions

The following spreadsheet fields cannot be populated automatically with free sources. These are the recommended paths to fill them:

**Current Estimated Value, Rough Equity Est, Est Profit Potential, Years Since Last Sale**
These require a market value estimate (AVM). Redfin and Zillow both block automated requests with 403 errors. Options:
- **ATTOM Data API** (~$50–150/month per county) — clean REST API, provides AVM, last sale, year built, lot size, and full property characteristics. Best long-term solution once budget is available.
- **Manual lookup** — for deals you're actively considering, pull the Zestimate or Redfin estimate directly from Zillow.com or Redfin.com (2 minutes per property). More accurate for individual deal analysis than a bulk API estimate anyway.

**Last Sold Date / Last Sold Price**
Deed and sales history are public record in Virginia but require querying the Virginia Circuit Court land records system (https://lrs.courts.state.va.us/), which is not accessible via a simple API. Options:
- **ATTOM Data API** — includes full sales history.
- **Manual lookup** — Virginia Circuit Court land records are free and searchable by address at lrs.courts.state.va.us. Takes ~1 minute per property.

**Year Built / Lot Size**
Available from county assessor portals (Stafford, Spotsylvania, Fredericksburg City, Caroline all have free online property lookup) but each county uses a different system with no common API. Options:
- **ATTOM Data API** — includes full property characteristics.
- **Manual lookup** — each county's assessor website is searchable by address for free. Stafford and Spotsylvania have the most complete online portals.
- **County GIS REST APIs** — Stafford and Spotsylvania use ArcGIS-based systems that likely have queryable REST endpoints. The correct URLs require browser-based discovery; this is a viable free automation path to pursue in Phase 2.

---

## Success Metrics

### Leading Indicators (Days 1–30)

| Metric | Target |
|---|---|
| Dashboard opened per week | ≥5 sessions/week (daily habit established) |
| Properties reviewed per session | ≥10 properties |
| Time from open to first actionable lead identified | <5 minutes |
| Data freshness | <24 hours lag vs. public record filing date |

### Lagging Indicators (Month 1–3)

| Metric | Target |
|---|---|
| Deals pursued from dashboard-sourced leads | ≥2 deals in pipeline within 90 days |
| Time saved vs. manual research | Estimated 4–6 hours/week recovered |
| Missed deals (properties sold before review) | Reduce to <1/month |

---

## Open Questions

| # | Question | Owner | Blocking? |
|---|---|---|---|
| 1 | ~~Which county/metro is the primary target for v1?~~ **Resolved:** Fredericksburg metro (Fredericksburg City, Stafford County, Spotsylvania County, Caroline County) as v1; Richmond metro (Richmond City, Henrico, Chesterfield, Hanover) as v2 expansion. | Joe | Closed |
| 2 | ~~What is the budget for paid data APIs?~~ **Resolved:** No budget for v1; free sources only. Revisit after 60–90 days. | Joe | Closed |
| 3 | Should the 70% ARV rule be applied as a filter, or just displayed? | Joe | No — can be added in P1 |
| 4 | How should "days in foreclosure" be calculated? **Note:** Virginia is non-judicial — no lis pendens. Default to date of first trustee sale notice publication. | Data/engineering | No — default established |
| 5 | Are there specific lenders or banks Joe wants to prioritize (e.g., known REO sellers)? | Joe | No — nice-to-have filter if yes |

---

## Timeline Considerations

- **Phase 1 (v1 MVP):** Fredericksburg metro (Fredericksburg City, Stafford, Spotsylvania, Caroline), P0 requirements only, daily refresh, live dashboard artifact. Free sources: VAnotices.com, Auction.com, HUD/HomePath/HomeSteps, county GIS portals.
- **Phase 2:** Add P1 features (price filter, deal tracking, new-today badges) after validating daily usage habit in Fredericksburg market.
- **Phase 3:** Expand to Richmond metro (Richmond City, Henrico, Chesterfield, Hanover) using the same source architecture. Evaluate ATTOM Data as a paid upgrade if budget is available.
- **Phase 4:** ARV estimator integration and direct mail / skip-trace export.

No hard external deadlines identified. Recommend targeting Phase 1 completion within 1–2 weeks to begin validating deal flow during active foreclosure season.

---

*This spec is a living document. Update open questions and requirements as target area and data sources are confirmed.*
