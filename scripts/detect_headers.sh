#!/bin/bash
# Runs --detect on every Column.us source with an unconfirmed header string.
# Output shows the newspaper name as it appears in the DOM — use that as the header value.

cd "$(dirname "$0")/.."

URLS=(
    "https://roanoke.column.us/search?noticeType=Foreclosure+Sale"
    "https://vagazette.column.us/search?noticeType=Foreclosure+Sale"
    "https://dailyprogress.column.us/search?noticeType=Foreclosure+Sale"
    "https://newsadvance.column.us/search?noticeType=Foreclosure+Sale"
    "https://newsvirginian.column.us/search?noticeType=Foreclosure+Sale"
    "https://godanriver.column.us/search?noticeType=Foreclosure+Sale"
    "https://martinsvillebulletin.column.us/search?noticeType=Foreclosure+Sale"
    "https://dnronline.column.us/search?noticeType=Foreclosure+Sale"
    "https://westmorelandnews.column.us/search?noticeType=Foreclosure+Sale"
    "https://heraldcourier.column.us/search?noticeType=Foreclosure+Sale"
)

for url in "${URLS[@]}"; do
    python3 /Users/jarvis/Documents/Claude/Foreclosures/scripts/scraper_column_us.py --url "$url" --detect
    echo ""
done
