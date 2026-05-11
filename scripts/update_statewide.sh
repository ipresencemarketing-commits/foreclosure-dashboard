#!/bin/bash
# Virginia Statewide Foreclosure Pipeline
# =========================================
# Runs ALL Column.us scrapers in sequence and syncs each to Google Sheets.
# Covers all 15 confirmed Virginia Column.us newspaper instances.
#
# Usage:
#   bash scripts/update_statewide.sh           # full run
#   bash scripts/update_statewide.sh --no-sync # scrape only, skip Google Sheets sync
#
# Each source runs independently — failures in one pipeline do not stop others.
# Individual pipelines can also be run separately:
#   bash scripts/update_richmond.sh
#   bash scripts/update_roanoke.sh   (etc.)
#
# Virginia Column.us coverage map:
# ─────────────────────────────────────────────────────────────────────────────
#  fredericksburg  │ Free Lance-Star          │ Fredericksburg, Stafford, Spotsylvania,
#                  │                          │ King George, Caroline
#  richmond        │ Richmond Times-Dispatch  │ Richmond, Chesterfield, Henrico, Hanover
#  starexponent    │ Culpeper Star-Exponent   │ Culpeper, Fauquier
#  roanoke         │ Roanoke Times            │ Roanoke City/County, Salem, Botetourt,
#                  │                          │ Bedford, Franklin, Montgomery
#  newsadvance     │ News & Advance           │ Lynchburg, Campbell, Appomattox, Amherst
#  dailyprogress   │ Daily Progress           │ Charlottesville, Albemarle, Fluvanna,
#                  │                          │ Greene, Nelson, Louisa
#  newsvirginian   │ News Virginian           │ Waynesboro, Augusta, Staunton
#  martinsvillebulletin │ Martinsville Bulletin │ Martinsville, Henry, Patrick
#  godanriver      │ Register & Bee           │ Danville, Pittsylvania, Halifax
#  westmorelandnews│ Westmoreland News        │ Westmoreland, Northern Neck
#  ffxnow          │ FFXnow                   │ Fairfax County, City of Fairfax
#  dnronline       │ Daily News-Record        │ Harrisonburg, Rockingham, Page, Shenandoah
#  arlnow          │ ARLnow                   │ Arlington County
#  alxnow          │ ALXnow                   │ City of Alexandria
#  heraldcourier   │ Bristol Herald Courier   │ Bristol, Washington, Scott, Lee, Wise,
#                  │                          │ Dickenson, Buchanan, Russell counties
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: Hampton Roads (Virginian-Pilot/Daily Press) uses legals.hamptonroads.com,
#       not Column.us — not included here.
# NOTE: Winchester/Shenandoah area (Northern Virginia Daily) uses its own classifieds
#       system — not included here.
#
set -e
cd "$(dirname "$0")/.."

SYNC=true
PUSH_PAGES=true
for arg in "$@"; do
    [[ "$arg" == "--no-sync" ]]  && SYNC=false
    [[ "$arg" == "--no-push" ]]  && PUSH_PAGES=false
done

# ── Helper: run one pipeline, continue on failure ─────────────────────────
run_pipeline() {
    local NAME="$1"
    local URL="$2"
    local HEADER="$3"
    local SOURCE="$4"
    local OUTPUT="$5"
    local LABEL="$6"

    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo "  Pipeline: $LABEL"
    echo "────────────────────────────────────────────────────────────"

    if python3 scripts/scraper_column_us.py \
        --url    "$URL" \
        --header "$HEADER" \
        --source "$SOURCE" \
        --output "$OUTPUT" \
        --label  "$LABEL"; then
        if [[ "$SYNC" == "true" ]]; then
            python3 scripts/sheets_sync.py --file "$OUTPUT" \
                || echo "  [warn] Sheets sync failed for $LABEL — check credentials"
        fi
    else
        echo "  [error] Scraper failed for $LABEL — skipping sync"
    fi
}

echo ""
echo "=========================================================="
echo "  Virginia Statewide Foreclosure Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Sync to Google Sheets: $SYNC"
echo "=========================================================="

# ── Clear sheet before pipelines run ──────────────────────────────────────
# This guarantees a fresh start on every run — no stale rows from old column
# orderings, no leftover data from a previous partial run.
if [[ "$SYNC" == "true" ]]; then
    echo ""
    echo "--- Clearing Google Sheet (fresh start) ---"
    python3 scripts/sheets_sync.py --clear-only \
        || echo "  [warn] Sheet clear failed — check credentials"
fi

run_pipeline "fredericksburg" \
    "https://fredericksburg.column.us/search?noticeType=Foreclosure+Sale" \
    "FREE LANCE-STAR" \
    "column_us_fredericksburg" \
    "data/foreclosures.json" \
    "Free Lance-Star (Fredericksburg)"

run_pipeline "richmond" \
    "https://richmond.column.us/search?noticeType=Foreclosure+Sale" \
    "RICHMOND TIMES DISPATCH" \
    "column_us_richmond" \
    "data/foreclosures_richmond.json" \
    "Richmond Times-Dispatch"

run_pipeline "culpeper" \
    "https://starexponent.column.us/search?noticeType=Foreclosure+Sale" \
    "CULPEPER STAR EXPONENT" \
    "column_us_culpeper" \
    "data/foreclosures_culpeper.json" \
    "Culpeper Star-Exponent"

run_pipeline "roanoke" \
    "https://roanoke.column.us/search?noticeType=Foreclosure+Sale" \
    "ROANOKE TIMES" \
    "column_us_roanoke" \
    "data/foreclosures_roanoke.json" \
    "Roanoke Times"

run_pipeline "lynchburg" \
    "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale" \
    "NEWS & ADVANCE" \
    "column_us_lynchburg" \
    "data/foreclosures_lynchburg.json" \
    "Lynchburg News & Advance"

run_pipeline "charlottesville" \
    "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale" \
    "DAILY PROGRESS" \
    "column_us_charlottesville" \
    "data/foreclosures_charlottesville.json" \
    "Charlottesville Daily Progress"

run_pipeline "waynesboro" \
    "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale" \
    "NEWS VIRGINIAN" \
    "column_us_waynesboro" \
    "data/foreclosures_waynesboro.json" \
    "Waynesboro News Virginian"

run_pipeline "martinsville" \
    "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale" \
    "MARTINSVILLE BULLETIN" \
    "column_us_martinsville" \
    "data/foreclosures_martinsville.json" \
    "Martinsville Bulletin"

run_pipeline "danville" \
    "https://godanriver.column.us/search?noticeType=Foreclosure+Sale" \
    "REGISTER & BEE" \
    "column_us_danville" \
    "data/foreclosures_danville.json" \
    "Danville Register & Bee"

run_pipeline "westmoreland" \
    "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale" \
    "WESTMORELAND NEWS" \
    "column_us_westmoreland" \
    "data/foreclosures_westmoreland.json" \
    "Westmoreland News"

run_pipeline "harrisonburg" \
    "https://dnronline.column.us/search?noticeType=Foreclosure+Sale" \
    "DAILY NEWS-RECORD" \
    "column_us_harrisonburg" \
    "data/foreclosures_harrisonburg.json" \
    "Daily News-Record (Harrisonburg)"

run_pipeline "ffxnow" \
    "https://ffxnow.column.us/search?noticeType=Foreclosure+Sale" \
    "FFXNOW" \
    "column_us_ffxnow" \
    "data/foreclosures_ffxnow.json" \
    "FFXnow (Fairfax)"

run_pipeline "arlnow" \
    "https://arlnow.column.us/search?noticeType=Foreclosure+Sale" \
    "ARLNOW" \
    "column_us_arlnow" \
    "data/foreclosures_arlnow.json" \
    "ARLnow (Arlington)"

run_pipeline "alxnow" \
    "https://alxnow.column.us/search?noticeType=Foreclosure+Sale" \
    "ALXNOW" \
    "column_us_alxnow" \
    "data/foreclosures_alxnow.json" \
    "ALXnow (Alexandria)"

run_pipeline "bristol" \
    "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale" \
    "BRISTOL HERALD COURIER" \
    "column_us_bristol" \
    "data/foreclosures_bristol.json" \
    "Bristol Herald Courier"

# ── GitHub Pages publish ───────────────────────────────────────────────────
if [[ "$PUSH_PAGES" == "true" ]]; then
    echo ""
    echo "────────────────────────────────────────────────────────────"
    echo "  Publishing to GitHub Pages..."
    echo "────────────────────────────────────────────────────────────"
    REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    if [[ -f "$REPO_DIR/scripts/build_site.py" ]]; then
        python3 scripts/build_site.py
    fi
    git -C "$REPO_DIR" add -A
    if git -C "$REPO_DIR" diff --cached --quiet; then
        echo "  No changes to commit."
    else
        git -C "$REPO_DIR" commit -m "Auto-update: $(date '+%Y-%m-%d %H:%M')"
        git -C "$REPO_DIR" push origin main
        echo "  Pushed to GitHub Pages."
    fi
fi

echo ""
echo "=========================================================="
echo "  Statewide pipeline complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================================="
echo ""
