#!/bin/bash
# ALXnow (City of Alexandria) Pipeline
# ---------------------------------------
# Scrapes alxnow.column.us and syncs to Google Sheet.
# Covers: City of Alexandria.
# Court-authorized for legal notices.
#
# Run: bash scripts/update_alxnow.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://alxnow.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== ALXnow Pipeline (alxnow.column.us) ==="
echo ""

echo "--- Scraping alxnow.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://alxnow.column.us/search?noticeType=Foreclosure+Sale" \
    --header "ALXNOW" \
    --source "column_us_alxnow" \
    --output "data/foreclosures_alxnow.json" \
    --label  "ALXnow (Alexandria)"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_alxnow.json

echo ""
echo "=== ALXnow pipeline complete ==="
