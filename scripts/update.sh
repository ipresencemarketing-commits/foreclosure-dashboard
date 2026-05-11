#!/usr/bin/env bash
# update.sh — Foreclosure Finder pipeline
#
# Steps:
#   1. Scrape  — fetch all notices from PNV + Column.us → data/foreclosures.json
#   2. Sync    — push listings to Google Sheets
#   3. Publish — commit + push to GitHub Pages
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
echo ">> Step 1/3 — Scraping foreclosure notices (PNV + Column.us)..."
python3 scripts/scraper.py
echo "   Done."
echo ""

# ── Step 2: Sync ──────────────────────────────────────────────────────────────
echo ">> Step 2/3 — Syncing to Google Sheets..."
python3 scripts/sheets_sync.py || echo "   [warn] Sheets sync skipped — check credentials/service-account.json"
echo "   Done."
echo ""

# ── Step 3: Publish to GitHub Pages ──────────────────────────────────────────
if [[ "$PUSH_PAGES" == "true" ]]; then
    echo ">> Step 3/3 — Publishing to GitHub Pages..."
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
    echo ">> Step 3/3 — GitHub Pages push skipped (--no-push)"
fi

echo ""
echo "=================================================="
echo "  Pipeline complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================="
echo ""
