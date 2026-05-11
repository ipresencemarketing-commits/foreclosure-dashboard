#!/bin/bash
# Westmoreland News Pipeline
# ---------------------------
# Scrapes westmorelandnews.column.us and syncs to Google Sheet.
# Covers: Westmoreland County, Northern Neck area (Richmond County, Northumberland, Lancaster).
#
# Run: bash scripts/update_westmoreland.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Westmoreland News Pipeline (westmorelandnews.column.us) ==="
echo ""

echo "--- Scraping westmorelandnews.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale" \
    --header "WESTMORELAND NEWS" \
    --source "column_us_westmoreland" \
    --output "data/foreclosures_westmoreland.json" \
    --label  "Westmoreland News"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_westmoreland.json

echo ""
echo "=== Westmoreland pipeline complete ==="
