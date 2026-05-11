#!/bin/bash
# Martinsville Bulletin Pipeline
# --------------------------------
# Scrapes martinsvillebulletin.column.us and syncs to Google Sheet.
# Covers: Martinsville City, Henry County, Patrick County area.
#
# Run: bash scripts/update_martinsville.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Martinsville Bulletin Pipeline (martinsvillebulletin.column.us) ==="
echo ""

echo "--- Scraping martinsvillebulletin.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale" \
    --header "MARTINSVILLE BULLETIN" \
    --source "column_us_martinsville" \
    --output "data/foreclosures_martinsville.json" \
    --label  "Martinsville Bulletin"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_martinsville.json

echo ""
echo "=== Martinsville pipeline complete ==="
