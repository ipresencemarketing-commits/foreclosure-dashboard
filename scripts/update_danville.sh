#!/bin/bash
# Danville Register & Bee Pipeline
# ----------------------------------
# Scrapes godanriver.column.us and syncs to Google Sheet.
# Covers: Danville City, Pittsylvania County, Halifax County area.
#
# Run: bash scripts/update_danville.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://godanriver.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Danville Register & Bee Pipeline (godanriver.column.us) ==="
echo ""

echo "--- Scraping godanriver.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://godanriver.column.us/search?noticeType=Foreclosure+Sale" \
    --header "REGISTER & BEE" \
    --source "column_us_danville" \
    --output "data/foreclosures_danville.json" \
    --label  "Danville Register & Bee"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_danville.json

echo ""
echo "=== Danville pipeline complete ==="
