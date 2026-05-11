#!/bin/bash
# Waynesboro News Virginian Pipeline
# ------------------------------------
# Scrapes newsvirginian.column.us and syncs to Google Sheet.
# Covers: Waynesboro City, Augusta County, Staunton City area.
#
# Run: bash scripts/update_waynesboro.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== News Virginian Pipeline (newsvirginian.column.us) ==="
echo ""

echo "--- Scraping newsvirginian.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale" \
    --header "NEWS VIRGINIAN" \
    --source "column_us_waynesboro" \
    --output "data/foreclosures_waynesboro.json" \
    --label  "Waynesboro News Virginian"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_waynesboro.json

echo ""
echo "=== Waynesboro pipeline complete ==="
