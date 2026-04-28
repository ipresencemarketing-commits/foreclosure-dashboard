#!/usr/bin/env bash
# Foreclosure dashboard updater
# Run from anywhere: bash ~/Documents/Claude/Foreclosures/update.sh

set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

echo "=== Foreclosure Dashboard Update ==="
echo "Working in: $REPO_DIR"
echo ""

# 1. Run the scraper
echo "[1/4] Running scrapers..."
python3 scripts/scraper.py
echo ""

# 2. Sync to Google Sheets
echo "[2/4] Syncing to Google Sheets..."
if [ -f "credentials/service-account.json" ]; then
  python3 scripts/sheets_sync.py
else
  echo "  ⚠ credentials/service-account.json not found — skipping Sheets sync"
  echo "    Place your service account JSON at credentials/service-account.json to enable sync"
fi
echo ""

# 3. Show what changed
echo "[3/4] Data file status:"
if git diff --quiet data/foreclosures.json 2>/dev/null; then
  echo "  No changes to foreclosures.json (data unchanged since last run)"
else
  TOTAL=$(python3 -c "
import json
data = json.load(open('data/foreclosures.json'))
m = data.get('meta', {})
print(f\"{m.get('total_count','?')} total listings ({m.get('new_today','?')} new today)\")
" 2>/dev/null || echo "see foreclosures.json")
  echo "  Updated: $TOTAL"
fi
echo ""

# 4. Commit and push if anything changed
echo "[4/4] Deploying to GitHub Pages..."
git add -A

if git diff --cached --quiet; then
  echo "  Nothing to commit — dashboard is already up to date."
else
  TIMESTAMP=$(date "+%Y-%m-%d %H:%M")
  git commit -m "chore: data refresh $TIMESTAMP"
  git push
  echo "  ✓ Pushed! GitHub Pages will update in ~30 seconds."
fi

echo ""
echo "=== Done ==="
