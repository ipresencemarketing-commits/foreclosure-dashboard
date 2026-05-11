#!/bin/bash
# Bristol Herald Courier Pipeline
# ---------------------------------
# Scrapes heraldcourier.column.us and syncs to Google Sheet.
# Covers: Bristol City, Washington County, Scott County, Lee County, Wise County,
#         Dickenson County, Buchanan County, Russell County (SW Virginia).
#
# Run: bash scripts/update_bristol.sh
#
# If 0 listings reported, run detect mode to verify the paper header:
#   python3 scripts/scraper_column_us.py \
#     --url "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale" --detect

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Bristol Herald Courier Pipeline (heraldcourier.column.us) ==="
echo ""

echo "--- Scraping heraldcourier.column.us ---"
python3 scripts/scraper_column_us.py \
    --url    "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale" \
    --header "BRISTOL HERALD COURIER" \
    --source "column_us_bristol" \
    --output "data/foreclosures_bristol.json" \
    --label  "Bristol Herald Courier"

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_bristol.json

echo ""
echo "=== Bristol pipeline complete ==="
