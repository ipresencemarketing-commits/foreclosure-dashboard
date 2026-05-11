#!/bin/bash
# Daily News-Record (Harrisonburg) Pipeline
# ------------------------------------------
# Scrapes dnronline.column.us and syncs to Google Sheet.
# Covers: Harrisonburg City, Rockingham County, Page County, Shenandoah County area.
#
# Run: bash scripts/update_harrisonburg.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://dnronline.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Daily News-Record Pipeline (dnronline.column.us) ==="
echo ""

echo "--- Scraping dnronline.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://dnronline.column.us/search?noticeType=Foreclosure+Sale" \
    --header "DAILY NEWS-RECORD" \
    --source "column_us_harrisonburg" \
    --output "data/foreclosures_harrisonburg.json" \
    --label  "Daily News-Record (Harrisonburg)"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_harrisonburg.json

echo ""
echo "=== Harrisonburg pipeline complete ==="
