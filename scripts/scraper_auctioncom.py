#!/usr/bin/env python3
"""
Auction.com — Virginia Foreclosure Sales Scraper
-------------------------------------------------
Scrapes upcoming trustee sale listings from the Auction.com GraphQL API:
  POST https://graph.auction.com/graphql

Site URL:
  https://www.auction.com/residential/VA/active_lt/auction_date_order_st/goto_mt/y_nbs/foreclosures_at

The site is a React SPA backed by a public GraphQL endpoint. No auth token
needed — plain requests.post() works. The `marketing_tags: "goto"` filter
restricts results to GOTO properties (live courthouse trustee sales only,
excluding online-only auctions).

Fields provided:
  ✅ Address (street, city, state, ZIP from seller_property)
  ✅ County (country_secondary_subdivision)
  ✅ Sale Date + Time (auction.start_date UTC ISO)
  ✅ Beds / Baths / SqFt (primary_property.summary)
  ✅ Year Built / Lot Size
  ✅ Est. Market Value (primary_property.summary.valuation)
  ✅ Occupancy Status (listing_configuration.occupancy_status)
  ✅ Product Type (TRUSTEE / FORECLOSURE)
  ✅ Listing URL (listing_page_path on auction.com)
  ✅ Is Hot flag
  ❌ Opening bid (starting_bid often null pre-auction)
  ❌ Lender / Trustee / Full notice text
  🔄 Owner / GIS details (GIS backfill)
"""

import json
import os
import re
import sys
import logging
from datetime import date, datetime, timezone

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scraper import make_id, county_display, courthouse_location

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")

GRAPHQL_URL  = "https://graph.auction.com/graphql"
SOURCE_URL   = "https://www.auction.com/residential/VA/active_lt/auction_date_order_st/goto_mt/y_nbs/foreclosures_at"
SOURCE_TAG   = "auction_com"
OUTPUT_FILE  = os.path.join(PROJECT_ROOT, "data", "foreclosures_auctioncom.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin":       "https://www.auction.com",
    "Referer":      "https://www.auction.com/",
}

# GraphQL query — captured from browser network tab (auction.com site JS)
# Fetches all GOTO (live courthouse) foreclosure listings for Virginia
GRAPHQL_QUERY = "\n        \n      fragment ListingCardFields on Listing {\n        __typename\n        listing_id\n        urn\n        listing_status_group\n        listing_status\n        listing_status_label(intent: SEARCH)\n        primary_photo\n        primary_property_id\n        listing_photos_count\n        listing_page_path\n        reserve_price @include(if: $hasAuthenticatedUser)\n        is_hot\n        formatted_address(format: DOUBLE_LINE)\n\n        listing_configuration {\n          product_type\n          is_reserve_displayed\n          broker_commission\n          financing_available\n          buyer_premium_available\n          interior_access_allowed\n          occupancy_status\n          asset_type\n          is_first_look_enabled\n          is_direct_offer_enabled\n          is_third_party_online\n        }\n\n        attribution_source {\n          origin_code\n        }\n\n        external_identifiers {\n          data_source\n          external_identifier\n        }\n\n        venue {\n          venue_type\n        }\n\n        event {\n          event_code\n          trustee_sale\n        }\n\n        valuation {\n          seller_current_value_amount\n        }\n\n        strategy {\n          selling_method_attributes {\n            online_segment_type\n          }\n        }\n\n        seller_property {\n          street_description\n          municipality\n          country_primary_subdivision\n          country_secondary_subdivision\n          postal_code\n        }\n\n        program_configuration {\n          program_enrollment_code\n        }\n\n        seller_terms {\n          inspection_terms {\n            is_option_contingency\n            is_contingency\n          }\n          leaseback_terms {\n            leaseback_period_in_days\n            leaseback_period_rent\n          }\n          finance_terms {\n            finance_preference\n            is_contingency\n          }\n          intent\n        }\n\n        primary_property {\n          property_id\n          summary {\n            total_bedrooms\n            total_bathrooms\n            square_footage\n            lot_size\n            year_built\n            valuation\n            structure_type_code\n            structure_type_group\n            address {\n              coordinates {\n                lon\n                lat\n              }\n            }\n          }\n          is_currently_saved @include(if: $hasAuthenticatedUser)\n          is_newly_listed\n          current_user_tracking_state {\n            is_seen\n            is_updated\n          }\n        }\n\n        auction {\n          start_date\n          end_date\n          starting_bid\n          is_online\n          visible_auction_start_date_time\n          bid_instruction {\n            nos_amount\n          }\n        }\n\n        marketing_tags {\n          tag\n        }\n\n        open_houses {\n          local_date\n          start_time\n          end_time\n        }\n\n        listing_summary {\n          is_remote_bid_enabled\n          is_remote_before_and_during_auction_enabled\n          show_opening_bid\n        }\n\n        external_information(resolvePolicy: CACHE_ONLY) {\n          collateral {\n            summary {\n              estimated\n              low\n              high\n              type\n            }\n          }\n        }\n\n        selling_method(resolvePolicy: CACHE_ONLY) {\n          __typename\n          ... on OnlineAuctionSegment {\n            _alias_OnlineAuctionSegment__starting_bid_amount: starting_bid_amount\n\n            _alias_OnlineAuctionSegment__configuration: configuration {\n              is_match_bidding_enabled\n              is_registration_deposit_required_enabled\n              bid_again_count\n              should_bid_again\n            }\n            listing_id\n            __typename\n            start_date\n            segment_type\n            initial_end_date\n            current_time\n            reserve_status\n            starting_bid_amount\n            subject_to_status\n            current_highest_bid {\n              bid_id\n              updated_date\n              bid_amount\n              type\n              terms {\n                status\n              }\n            }\n            segment_status\n            current_increment_amount\n            bid_count\n            result {\n              winning_bid_amount\n            }\n          }\n          ... on LiveAuctionSegment {\n            _alias_LiveAuctionSegment__starting_bid_amount: starting_bid_amount\n\n            _alias_LiveAuctionSegment__configuration: configuration {\n              state_deposit_rule\n            }\n            current_highest_bid {\n              bid_amount\n            }\n          }\n        }\n      }\n     \n        query resiSearch_blueprint_seekListingsFromFilters(\n          $filters: ListingCompatabilityFilters!,\n          $aggregationFields: [String!]!,\n          $hasAuthenticatedUser: Boolean!,\n          $requiresAggregation: Boolean!\n        ) {\n          seek_listings_from_filters(filters: $filters) {\n            total_count\n            total_pages\n            size\n            current_page\n            aggregation(fields: $aggregationFields) @include(if: $requiresAggregation)\n            content {\n              ...ListingCardFields\n            }\n          }\n        }\n      "

GRAPHQL_VARIABLES = {
    "filters": {
        "property_state":    "VA",
        "listing_type":      "active",
        "sort":              "auction_date_order",
        "limit":             500,
        "marketing_tags":    "goto",
        "usecode_product_type": "resi_ft",
        "version":           1,
        "offset":            0,
    },
    "hasAuthenticatedUser": False,
    "aggregationFields": [
        "primary_property_summary.structure_type_code.keyword",
        "listing_summary.is_remote_bid_enabled",
    ],
    "requiresAggregation": True,
}


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_sale_datetime(iso_str: str):
    """
    '2026-06-04T15:00:00Z' → ('2026-06-04', '11:00 AM') (converted from UTC to ET)
    Returns (date_iso, time_str) or (None, None).
    Note: Auction.com stores times in UTC. VA courthouse auctions are Eastern Time.
    ET = UTC-4 (EDT) in summer, UTC-5 (EST) in winter. Using UTC-4 for summer.
    """
    if not iso_str:
        return None, None
    try:
        dt_utc = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Convert UTC → Eastern (UTC-4 for EDT)
        dt_et = dt_utc.replace(tzinfo=timezone.utc)
        from datetime import timedelta
        dt_et_naive = dt_utc - timedelta(hours=4)
        sale_date = dt_et_naive.date().isoformat()
        h = dt_et_naive.hour
        m = dt_et_naive.minute
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        sale_time = f"{h12}:{m:02d} {ampm}"
        return sale_date, sale_time
    except (ValueError, AttributeError):
        return None, None


def resolve_county(raw: str) -> str:
    """'Fauquier' or 'Fauquier County' → display name"""
    if not raw:
        return None
    cleaned = re.sub(r"\s+County$", "", raw.strip(), flags=re.IGNORECASE)
    cd = county_display(cleaned)
    return cd if cd else cleaned.title()


def structure_type(code: str) -> str:
    mapping = {
        "SINGLE_FAMILY_HOME": "Single Family Home",
        "CONDO":              "Condo",
        "TOWNHOUSE":          "Townhouse",
        "MULTI_FAMILY":       "Multi Family",
        "LAND":               "Land",
        "MOBILE_HOME":        "Mobile Home",
    }
    return mapping.get(code, code.replace("_", " ").title() if code else "Single Family Home")


def fmt_beds_baths_sqft(summary: dict) -> str:
    parts = []
    if summary.get("total_bedrooms") is not None:
        parts.append(f"{int(summary['total_bedrooms'])}bd")
    if summary.get("total_bathrooms") is not None:
        parts.append(f"{summary['total_bathrooms']}ba")
    if summary.get("square_footage"):
        parts.append(f"{int(summary['square_footage']):,} sqft")
    return " / ".join(parts) if parts else None


# ---------------------------------------------------------------------------
# Main scraper
# ---------------------------------------------------------------------------

def scrape(since_date: date = None) -> list:
    if since_date is None:
        from config import SINCE_DATE
        since_date = SINCE_DATE

    log.info(f"Starting Auction.com scraper (VA GOTO foreclosures, since {since_date})")

    try:
        r = requests.post(
            GRAPHQL_URL,
            json={"query": GRAPHQL_QUERY, "variables": GRAPHQL_VARIABLES},
            headers=HEADERS,
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()["data"]["seek_listings_from_filters"]
    except Exception as e:
        log.error(f"  GraphQL error: {e}")
        return []

    raw = data.get("content", [])
    log.info(f"  {data['total_count']} total listings, {len(raw)} returned")

    listings  = []
    seen_ids  = set()
    skipped   = 0

    for item in raw:
        # Only trustee / foreclosure sales
        cfg = item.get("listing_configuration", {})
        if cfg.get("asset_type") not in ("FORECLOSURE", None):
            skipped += 1
            continue

        auction     = item.get("auction", {})
        sale_date, sale_time = parse_sale_datetime(
            auction.get("visible_auction_start_date_time") or auction.get("start_date", "")
        )

        if not sale_date:
            skipped += 1
            continue
        if sale_date < since_date.isoformat():
            skipped += 1
            continue

        sp       = item.get("seller_property", {})
        street   = (sp.get("street_description") or "").strip().title()
        city     = (sp.get("municipality") or "").strip().title()
        state    = sp.get("country_primary_subdivision", "VA")
        zipcode  = (sp.get("postal_code") or "").strip()
        county   = resolve_county(sp.get("country_secondary_subdivision", ""))

        if state != "VA" or not street:
            skipped += 1
            continue

        address  = f"{street}, {city}, VA {zipcode}".strip(", ")
        if not county:
            county = "Unknown"

        summary  = (item.get("primary_property") or {}).get("summary", {})
        val      = summary.get("valuation") or (item.get("valuation") or {}).get("seller_current_value_amount")
        starting_bid = auction.get("starting_bid")
        if starting_bid is None:
            sm = item.get("selling_method") or {}
            starting_bid = sm.get("_alias_LiveAuctionSegment__starting_bid_amount")

        listing_path = item.get("listing_page_path", "")
        listing_url  = f"https://www.auction.com{listing_path}" if listing_path else SOURCE_URL

        # Build notice text
        notice_parts = []
        listing_id_num = item.get("listing_id", "")
        if listing_id_num:
            notice_parts.append(f"Listing ID: {listing_id_num}")
        occ = cfg.get("occupancy_status", "")
        if occ:
            notice_parts.append(f"Occupancy: {occ.replace('_',' ').title()}")
        if item.get("is_hot"):
            notice_parts.append("Hot")

        lot_size_raw = summary.get("lot_size")

        days_until = (date.fromisoformat(sale_date) - date.today()).days
        listing_id = make_id(address, sale_date)

        if listing_id in seen_ids:
            continue
        seen_ids.add(listing_id)

        listings.append({
            "id":                listing_id,
            "address":           address,
            "city":              city,
            "county":            county,
            "state":             "VA",
            "zip":               zipcode,
            "property_type":     structure_type(summary.get("structure_type_code")),
            "stage":             "auction",
            "sale_date":         sale_date,
            "sale_time":         sale_time,
            "sale_location":     courthouse_location(county),
            "days_until_sale":   days_until,
            "asking_price":      int(starting_bid) if starting_bid else None,
            "assessed_value":    int(val) if val else None,
            "beds_baths_sqft":   fmt_beds_baths_sqft(summary),
            "year_built":        int(summary["year_built"]) if summary.get("year_built") else None,
            "lot_size":          f"{lot_size_raw} acres" if lot_size_raw else None,
            "lender":            None,
            "trustee":           None,
            "notice_text":       " | ".join(notice_parts) if notice_parts else None,
            "source":            SOURCE_TAG,
            "source_url":        listing_url,
            "first_seen":        date.today().isoformat(),
            "is_new":            True,
        })

    log.info(f"  {len(listings)} listings kept | {skipped} skipped")
    return listings


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(listings: list):
    today = date.today().isoformat()
    existing = {"meta": {}, "listings": []}
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE) as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            pass

    existing_map = {l["id"]: l for l in existing.get("listings", [])}
    added = updated = 0
    for l in listings:
        if l["id"] in existing_map:
            existing_map[l["id"]].update({k: v for k, v in l.items() if v is not None})
            updated += 1
        else:
            existing_map[l["id"]] = l
            added += 1

    out = {
        "meta":     {"source": SOURCE_TAG, "updated": today, "url": SOURCE_URL},
        "listings": list(existing_map.values()),
    }
    with open(OUTPUT_FILE, "w") as f:
        json.dump(out, f, indent=2, default=str)

    log.info(f"Saved → {OUTPUT_FILE}  ({added} added, {updated} updated, {len(out['listings'])} total)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    listings = scrape()
    save(listings)
    log.info("Done.")
