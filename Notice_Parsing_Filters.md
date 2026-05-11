# Foreclosure Notice Parsing Filters

Reference for all regex patterns used to extract fields from foreclosure notice text.
Add new patterns to `scraper.py` in the corresponding function.

---

## F_Sale_Date + F_Sale_Time
**Function:** `parse_sale_datetime(text)` in `scripts/scraper.py`

Patterns tried in order — most specific first:

| # | Pattern | Example |
|---|---|---|
| 1 | `auction [will be] on [Month D, YYYY] at [H:MM AM/PM]` | `"there will be an auction on May 22, 2026 at 1:30 PM"` |
| 1b | `auction [will be] on M/D/YYYY at [H:MM AM/PM]` | `"public auction on 5/28/2026 at 10:45 AM"` |
| 2 | `on [Month D, YYYY], at [H:MM AM/PM]` | `"will sell at public auction on June 3, 2026, at 10:00 AM"` |
| 2b | `on M/D/YYYY at [H:MM AM/PM]` | `"on 5/28/2026 at 10:45 AM"` |
| 3 | `[Month D, YYYY] at [H:MM AM/PM]` | `"May 22, 2026 at 1:30 PM"` |
| 3b | `M/D/YYYY at [H:MM AM/PM]` | `"5/28/2026 at 10:45 AM"` |
| 4 | Fallback — scan body for any date and time independently | Last resort; may occasionally pick up wrong date |

**Notes:**
- AM/PM suffix is optional — `"9:00"` (no AM/PM) is handled
- Date formats supported: `June 22, 2026` / `Jun 22, 2026` / `6/22/2026`

---

## Original_Principal
**Function:** `parse_original_principal(text)` in `scripts/scraper.py`

| # | Pattern | Example | Extracted Value |
|---|---|---|---|
| 1 | `original principal amount of $X` | `"the original principal amount of $447,740.00"` | `$447,740.00` |
| 2 | `loan which was originally $X` | `"a loan which was originally $356,684.00"` | `$356,684.00` |

---

## Deposit
**Function:** `parse_deposit(text)` in `scripts/scraper.py`

| # | Pattern | Example | Extracted Value |
|---|---|---|---|
| 1 | `[A] deposit of $X [clause up to 80 chars]` | `"A deposit of $45,000.00 or 10% of the successful bid amount"` | Full clause as text |

---

## Deed_Of_Trust_Date
**Function:** `parse_deed_of_trust_date(text)` in `scripts/scraper.py`

| # | Pattern | Example | Extracted Value |
|---|---|---|---|
| 1 | `Deed of Trust dated [date]` | `"Deed of Trust dated June 4, 2021"` | `2021-06-04` |
| 2 | `principal amount of $X[,] dated [date]` | `"original principal amount of $305,000.00 dated December 23, 2005"` | `2005-12-23` |
| 2 | *(same pattern, comma variant)* | `"original principal amount of $235,125.00, dated March 1, 2013"` | `2013-03-01` |

**Notes:**
- Output is always ISO format: `YYYY-MM-DD`
- Date formats supported: `June 4, 2021` / `Jun 4, 2021` / `06/04/2021` / `06-04-2021`
- If no format matches, the raw string is stored as-is

---

## Address
**Function:** inline in `scrape_column_us()` in `scripts/scraper.py`

| # | Pattern | Example |
|---|---|---|
| Primary | `\d+ StreetText, City, VA/Virginia ZIP` | `"256 MANCHESTER DR, RUTHER GLEN, VA 22546"` |
| Fallback A | `TRUSTEE'S SALE OF {address}` (terminates at blank line, "In execution", "Default", or "(Parcel") | `"TRUSTEE'S SALE OF 12219 WARD RD, KING GEORGE, VA 22485"` |
| Fallback B | `SUBSTITUTE TRUSTEE SALE {address}` (terminates at blank line, "In execution", "By virtue") | `"SUBSTITUTE TRUSTEE SALE 9107 Judicial Center Lane..."` |
| Fallback C | `TRUSTEE'S SALE\n{address}` — address on next line, no "OF" | `"Trustee's Sale\n1 Saint Marys Lane, Stafford, Virginia 22556"` |

**Notes:**
- State field matches both `VA` and `Virginia` (spelled out)
- If no address is found, the listing is **skipped** and logged with the reason

---

## Adding New Patterns

When you find a notice phrase that isn't being parsed:

1. Paste the raw notice text snippet here as a new example
2. Identify which field it maps to
3. Add a new numbered pattern in the corresponding function in `scripts/scraper.py`
4. Run `python3 scripts/scraper.py && python3 scripts/sheets_sync.py --reset` to rebuild the sheet
