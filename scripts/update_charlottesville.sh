#!/bin/bash
# Charlottesville Daily Progress Pipeline
# -----------------------------------------
# Scrapes dailyprogress.column.us and syncs to Google Sheet.
# Covers: Charlottesville City, Albemarle, Fluvanna, Greene, Nelson, Louisa area.
#
# Run: bash scripts/update_charlottesville.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Daily Progress Pipeline (dailyprogress.column.us) ==="
echo ""

echo "--- Scraping dailyprogress.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale" \
    --header "DAILY PROGRESS" \
    --source "column_us_charlottesville" \
    --output "data/foreclosures_charlottesville.json" \
    --label  "Charlottesville Daily Progress"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_charlottesville.json

echo ""
echo "=== Charlottesville pipeline complete ==="
