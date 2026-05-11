#!/bin/bash
# ARLnow (Arlington County) Pipeline
# -------------------------------------
# Scrapes arlnow.column.us and syncs to Google Sheet.
# Covers: Arlington County.
# Court-authorized for legal notices.
#
# Run: bash scripts/update_arlnow.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://arlnow.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== ARLnow Pipeline (arlnow.column.us) ==="
echo ""

echo "--- Scraping arlnow.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://arlnow.column.us/search?noticeType=Foreclosure+Sale" \
    --header "ARLNOW" \
    --source "column_us_arlnow" \
    --output "data/foreclosures_arlnow.json" \
    --label  "ARLnow (Arlington)"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_arlnow.json

echo ""
echo "=== ARLnow pipeline complete ==="
