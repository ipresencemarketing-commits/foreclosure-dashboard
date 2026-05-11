#!/bin/bash
# Culpeper Star-Exponent Pipeline
# --------------------------------
# Scrapes starexponent.column.us and syncs to Google Sheet.
# Covers Culpeper County; also approved newspaper for Fauquier County notices.
# Separate from the Fredericksburg and Richmond pipelines — do NOT merge.
#
# Run: bash scripts/update_culpeper.sh

set -e
cd "$(dirname "$0")/.."

echo ""
echo "=== Culpeper Star-Exponent Pipeline (starexponent.column.us) ==="
echo ""

echo "--- Scraping starexponent.column.us ---"
python3 scripts/scraper_culpeper.py

echo ""
echo "--- Syncing to Google Sheet ---"
python3 scripts/sheets_sync.py --file data/foreclosures_culpeper.json

echo ""
echo "=== Culpeper pipeline complete ==="
