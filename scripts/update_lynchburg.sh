#!/bin/bash
# Lynchburg News & Advance Pipeline
# -----------------------------------
# Scrapes newsadvance.column.us and syncs to Google Sheet.
# Covers: Lynchburg City, Campbell, Appomattox, Amherst, Bedford area.
#
# Run: bash scripts/update_lynchburg.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Lynchburg News & Advance Pipeline (newsadvance.column.us) ==="
echo ""

echo "--- Scraping newsadvance.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale" \
    --header "NEWS & ADVANCE" \
    --source "column_us_lynchburg" \
    --output "data/foreclosures_lynchburg.json" \
    --label  "Lynchburg News & Advance"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_lynchburg.json

echo ""
echo "=== Lynchburg pipeline complete ==="
