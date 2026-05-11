#!/bin/bash
# Richmond Times-Dispatch Pipeline
# ---------------------------------
# Scrapes richmond.column.us and syncs to Google Sheet.
# Separate from the Fredericksburg and Culpeper pipelines — do NOT merge.
#
# Run: bash scripts/update_richmond.sh
# Optional: bash scripts/update_richmond.sh --no-push

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Richmond Times-Dispatch Pipeline (richmond.column.us) ==="
echo ""

echo "--- Scraping richmond.column.us ---"
python3 scripts/scraper_richmond.py

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_richmond.json

echo ""
echo "=== Richmond pipeline complete ==="
