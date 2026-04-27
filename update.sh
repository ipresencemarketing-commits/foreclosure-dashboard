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
echo "[1/3] Running scrapers..."
python3 scripts/scraper.py
echo ""

# 2. Show what changed
echo "[2/3] Data file status:"
if git diff --quiet data/foreclosures.json 2>/dev/null; then
  echo "  No changes to foreclosures.json (data unchanged since last run)"
  DATA_CHANGED=false
else
  ADDED=$(python3 -c "
import json
try:
    old = json.load(open('/tmp/_fc_old.json')) if __import__('os').path.exists('/tmp/_fc_old.json') else []
except: old = []
new = json.load(open('data/foreclosures.json'))
print(f'{len(new)} total listings')
" 2>/dev/null || echo "see foreclosures.json")
  echo "  Updated: $ADDED"
  DATA_CHANGED=true
fi
echo ""

# 3. Commit and push if anything changed
echo "[3/3] Deploying to GitHub Pages..."
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
