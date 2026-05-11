#!/bin/bash
# FFXnow (Fairfax County) Pipeline
# ----------------------------------
# Scrapes ffxnow.column.us and syncs to Google Sheet.
# Covers: Fairfax County, City of Fairfax.
# Court-authorized for legal notices since early 2025.
#
# Run: bash scripts/update_ffxnow.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== FFXnow Pipeline (ffxnow.column.us) ==="
echo ""

echo "--- Scraping ffxnow.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale" \
    --header "FFXNOW" \
    --source "column_us_ffxnow" \
    --output "data/foreclosures_ffxnow.json" \
    --label  "FFXnow (Fairfax)"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_ffxnow.json

echo ""
echo "=== FFXnow pipeline complete ==="
