#!/bin/bash
# Virginia Statewide Foreclosure Pipeline
# =========================================
# Wrapper script — delegates entirely to run.py.
# To enable or disable sources, edit COLUMN_US_SOURCES in scripts/config.py.
#
# Usage:
#   bash scripts/update_statewide.sh           # full run
#   bash scripts/update_statewide.sh --no-sync # scrape only, skip Google Sheets
#   bash scripts/update_statewide.sh --no-push # skip GitHub Pages publish

set -e
cd "$(dirname "$0")/.."
exec python3 scripts/run.py "$@"
