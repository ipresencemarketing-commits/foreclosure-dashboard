#!/usr/bin/env bash
# update.sh — Full Foreclosure Finder pipeline
#
# Order of operations:
#   1. Scrape   — fetch new foreclosure listings from all sources
#   2. Sync     — push new listings into Google Sheets
#   3. Backfill — fill blank cells (VGIN/GIS, Redfin, derived calcs, Column.us URLs)
#   4. Sync     — push backfilled data back into Google Sheets
#   5. Verify   — gap report (optional, skipped if verify.py not present)
#   6. Publish  — stage data + commit + push to GitHub Pages
#
# Usage:
#   bash scripts/update.sh            # full run
#   bash scripts/update.sh --no-push  # skip GitHub Pages push (for testing)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PUSH_PAGES=true

for arg in "$@"; do
    [[ "$arg" == "--no-push" ]] && PUSH_PAGES=false
done

cd "$REPO_DIR"

echo ""
echo "=================================================="
echo "  Foreclosure Finder — Full Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""

# ── Step 1: Scrape ────────────────────────────────────────────────────────────
echo ">> Step 1/6 — Scraping foreclosure notices..."
python3 scripts/scraper.py
echo "   Done."
echo ""

# ── Step 2: Sync (initial push of new/updated listings) ──────────────────────
echo ">> Step 2/6 — Syncing new listings to Google Sheets..."
python3 scripts/sheets_sync.py || echo "   [warn] Sheets sync skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 3: Backfill ──────────────────────────────────────────────────────────
# Pass 1/1b — F_Sale_Date / F_Sale_Time   (notice URL re-fetch; Auction.com; PNV search)
# Pass 2    — County                      (city_to_county, address parse, ZIP, Census geocoder)
# Pass 3    — State                       (always VA)
# Pass 4    — City                        (parse from address)
# Pass 5    — ZIP                         (extract from address)
# Pass 6    — Owner + Property Details    (VGIN statewide → county ArcGIS fallback → Redfin;
#                                          single call per property returns owner name,
#                                          mailing address, year built, sqft, beds/baths,
#                                          lot size, assessed value, last sale;
#                                          calculates Rough_Equity_Est, Est_Profit_Potential,
#                                          Years_Since_Last_Sale)
# Pass 7    — Derived fields only         (recalculates equity/profit for rows with new data)
# Pass 8    — Column.us notice URLs       (Playwright DOM search; requires playwright)
echo ">> Step 3/6 — Running backfill..."
python3 scripts/backfill.py || echo "   [warn] Backfill skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 4: Sync (push backfilled data) ──────────────────────────────────────
echo ">> Step 4/6 — Syncing enriched data back to Google Sheets..."
python3 scripts/sheets_sync.py || echo "   [warn] Sheets sync skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 5: Verify (optional gap report) ─────────────────────────────────────
echo ">> Step 5/6 — Verifying data gaps..."
if [[ -f "$REPO_DIR/scripts/verify.py" ]]; then
    python3 scripts/verify.py || echo "   [warn] Verify skipped — check credentials/service-account.json"
else
    echo "   (verify.py not found — skipping)"
fi
echo ""

# ── Step 6: Publish to GitHub Pages ──────────────────────────────────────────
if [[ "$PUSH_PAGES" == "true" ]]; then
    echo ">> Step 6/6 — Publishing to GitHub Pages..."
    # Rebuild static site if a build script exists
    if [[ -f "$REPO_DIR/scripts/build_site.py" ]]; then
        python3 scripts/build_site.py
    fi
    git -C "$REPO_DIR" add -A
    if git -C "$REPO_DIR" diff --cached --quiet; then
        echo "   No changes to commit."
    else
        git -C "$REPO_DIR" commit -m "Auto-update: $(date '+%Y-%m-%d %H:%M')"
        git -C "$REPO_DIR" push origin main
        echo "   Pushed to GitHub Pages."
    fi
else
    echo ">> Step 6/6 — GitHub Pages push skipped (--no-push)"
fi

echo ""
echo "=================================================="
echo "  Pipeline complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""
