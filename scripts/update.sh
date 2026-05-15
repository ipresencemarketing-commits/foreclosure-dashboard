#!/usr/bin/env bash
# update.sh — Foreclosure Finder pipeline
#
# Steps:
#   1. Scrape   — fetch notices from all active source groups → data/foreclosures.json
#   2. Sync     — push listings to Google Sheets (initial push, no enrichment yet)
#   3. Backfill — 8-pass enrichment: GIS owner/property, sale date re-parse, derived calcs
#   4. Publish  — commit + push to GitHub Pages
#
# Active scraper source groups (all called by scraper.py → run()):
#   Group 3  (PNV)  — publicnoticevirginia.com        (statewide; §55.1-321 required)
#   Existing        — fredericksburg.column.us         (Free-Lance Star)
#   Group 1         — richmond.column.us               (Richmond Times-Dispatch)
#   Group 2  [OFF]  — logs.com DISABLED: site migrated to PowerBI embed (2026-05)
#   Group 4         — dailyprogress.column.us          (Charlottesville Daily Progress)
#   Group 5         — auction.com                      (REO + trustee pre-sales)
#   Group 6         — vagazette.column.us              (Virginia Gazette)
#   Group 7  [OFF]  — nvdaily: uses own CMS + covers wrong counties (Shenandoah Valley)
#   Group 8         — siwpc.com/sales-report           (Samuel I. White, P.C.)
#   Group 9  [OFF]  — VA eCourts circuitSearch requires authenticated session
#
# Pipeline settings (lookback window, source toggles, rate limiting):
#   → Edit scripts/config.py   ← single place for all pipeline knobs
#     Key setting: LOOKBACK_DAYS = 30  (how far back each source searches)
#
# To tune a single source, edit the matching function in scripts/scraper.py.
# This script (update.sh) does NOT need to change when scraper sources or
# settings change — scraper.py reads config.py and manages everything internally.
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
echo "  Foreclosure Finder — Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""

# ── Step 1: Scrape ────────────────────────────────────────────────────────────
echo ">> Step 1/4 — Scraping foreclosure notices (7 active groups: PNV, Column.us ×4, Auction.com, SIWPC; Groups 2/7/9 disabled)..."
python3 scripts/scraper.py
echo "   Done."
echo ""

# ── Step 2: Sync ──────────────────────────────────────────────────────────────
echo ">> Step 2/4 — Syncing to Google Sheets (initial push)..."
python3 scripts/sheets_sync.py || echo "   [warn] Sheets sync skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 3: Backfill ──────────────────────────────────────────────────────────
# 8-pass enrichment: sale date/time (re-fetch), county, city, ZIP, owner +
# property details (VGIN statewide → county fallback → Redfin supplement),
# derived fields (equity, profit potential), Column.us permalink URLs.
echo ">> Step 3/4 — Backfilling missing fields (GIS / Redfin / derived calcs)..."
python3 scripts/backfill.py || echo "   [warn] Backfill skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 4: Publish to GitHub Pages ──────────────────────────────────────────
if [[ "$PUSH_PAGES" == "true" ]]; then
    echo ">> Step 4/4 — Publishing to GitHub Pages..."
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
    echo ">> Step 4/4 — GitHub Pages push skipped (--no-push)"
fi

echo ""
echo "=================================================="
echo "  Pipeline complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""
