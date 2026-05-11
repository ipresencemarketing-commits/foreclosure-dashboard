#!/bin/bash
# Roanoke Times Pipeline
# ----------------------
# Scrapes roanoke.column.us and syncs to Google Sheet.
# Covers: Roanoke City, Salem, Roanoke County, Botetourt, Bedford, Franklin, Montgomery, and more.
#
# Run: bash scripts/update_roanoke.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://roanoke.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Roanoke Times Pipeline (roanoke.column.us) ==="
echo ""

echo "--- Scraping roanoke.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://roanoke.column.us/search?noticeType=Foreclosure+Sale" \
    --header "ROANOKE TIMES" \
    --source "column_us_roanoke" \
    --output "data/foreclosures_roanoke.json" \
    --label  "Roanoke Times"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_roanoke.json

echo ""
echo "=== Roanoke pipeline complete ==="
