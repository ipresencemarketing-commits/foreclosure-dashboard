#!/bin/bash
# -----------------------------------------------------------
# Daily foreclosure data update + GitHub push
# Runs automatically via Cowork scheduled task each morning.
# -----------------------------------------------------------

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "[$(date '+%Y-%m-%d %H:%M')] Starting foreclosure update..."

# 1. Run the scraper
cd "$REPO_DIR"
python3 scripts/scraper.py

# 2. Sync new listings to Google Sheets (non-fatal — sheet credentials may not be configured yet)
python3 scripts/sheets_sync.py || echo "  [warn] Sheets sync skipped — check credentials/service-account.json"

# 3. Stage the updated data file
git -C "$REPO_DIR" add data/foreclosures.json

# 4. Commit only if there are changes
if git -C "$REPO_DIR" diff --cached --quiet; then
  echo "No new listings found. Nothing to commit."
else
  git -C "$REPO_DIR" commit -m "Data update: $(date '+%Y-%m-%d %H:%M')"
  git -C "$REPO_DIR" push origin main
  echo "Dashboard updated and pushed to GitHub Pages."
fi

echo "[$(date '+%Y-%m-%d %H:%M')] Done."
