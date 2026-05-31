#!/usr/bin/env python3
"""
db_sync.py — Sync pipeline JSON output to PostgreSQL
=====================================================
Reads all enabled source JSON files and upserts listings into the database.
Run after scraper + backfill completes.

Usage:
    python3 /Users/jarvis/Documents/Claude/Foreclosures/scripts/db_sync.py

Requires:
    DATABASE_URL env var (or in .env file in project root)
    pip3 install psycopg2-binary python-dotenv
"""

import json
import os
import sys
import logging
from datetime import date, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Load .env from project root
PROJECT_ROOT = Path(__file__).parent.parent
env_file = PROJECT_ROOT / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    log.error("DATABASE_URL not set. Add it to .env or export it before running.")
    sys.exit(1)

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    log.error("psycopg2 not installed. Run: pip3 install psycopg2-binary")
    sys.exit(1)

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from config import COLUMN_US_SOURCES, ENABLE_SIWPC, ENABLE_WASHINGTONTIMES

# ── Collect all enabled output files ────────────────────────────────────────

def get_enabled_files() -> list[Path]:
    files = []
    for src in COLUMN_US_SOURCES:
        if src.get("enabled"):
            p = PROJECT_ROOT / src["output"]
            if p.exists():
                files.append(p)
    if ENABLE_SIWPC:
        p = PROJECT_ROOT / "data" / "foreclosures_siwpc.json"
        if p.exists():
            files.append(p)
    if ENABLE_WASHINGTONTIMES:
        p = PROJECT_ROOT / "data" / "foreclosures_washingtontimes.json"
        if p.exists():
            files.append(p)
    # PNV
    p = PROJECT_ROOT / "data" / "foreclosures_pnv.json"
    if p.exists():
        files.append(p)
    return files


def parse_date(val):
    if not val:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(val[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def listing_to_row(l: dict) -> dict:
    return {
        "id":                   l.get("id"),
        "source":               l.get("source", ""),
        "source_url":           l.get("source_url"),
        "address":              l.get("address", ""),
        "city":                 l.get("city"),
        "county":               l.get("county"),
        "state":                l.get("state", "VA"),
        "zip":                  l.get("zip"),
        "property_type":        l.get("property_type", "single-family"),
        "stage":                l.get("stage"),
        "sale_date":            parse_date(l.get("sale_date")),
        "sale_time":            l.get("sale_time"),
        "sale_location":        l.get("sale_location"),
        "days_until_sale":      l.get("days_until_sale"),
        "asking_price":         l.get("asking_price"),
        "assessed_value":       l.get("assessed_value") or l.get("Current_Est_Value"),
        "original_principal":   l.get("original_principal"),
        "rough_equity_est":     l.get("rough_equity_est") or l.get("Rough_Equity_Est"),
        "est_profit_potential": l.get("est_profit_potential") or l.get("Est_Profit_Potential"),
        "deposit":              str(l.get("deposit", ""))[:500] if l.get("deposit") else None,
        "beds_baths_sqft":      l.get("beds_baths_sqft"),
        "year_built":           l.get("year_built"),
        "lot_size":             l.get("lot_size"),
        "last_sold_date":       parse_date(l.get("last_sold_date")),
        "last_sold_price":      l.get("last_sold_price"),
        "years_since_last_sale":l.get("years_since_last_sale"),
        "owner_name":           l.get("owner_name"),
        "owner_mailing_address":l.get("owner_mailing_address"),
        "owner_mailing_differs":l.get("owner_mailing_differs"),
        "lender":               l.get("lender"),
        "trustee":              l.get("trustee"),
        "notice_date":          parse_date(l.get("notice_date")),
        "notice_text":          (l.get("notice_text") or "")[:10000],
        "deed_of_trust_date":   parse_date(l.get("deed_of_trust_date")),
        "days_in_foreclosure":  l.get("days_in_foreclosure"),
        "first_seen":           parse_date(l.get("first_seen")) or date.today(),
        "is_new":               l.get("is_new", True),
        "investment_priority":  l.get("investment_priority") or l.get("Investment_Priority"),
        "notes":                l.get("notes"),
    }


UPSERT_SQL = """
INSERT INTO listings (
    id, source, source_url, address, city, county, state, zip, property_type,
    stage, sale_date, sale_time, sale_location, days_until_sale,
    asking_price, assessed_value, original_principal, rough_equity_est,
    est_profit_potential, deposit, beds_baths_sqft, year_built, lot_size,
    last_sold_date, last_sold_price, years_since_last_sale,
    owner_name, owner_mailing_address, owner_mailing_differs,
    lender, trustee, notice_date, notice_text, deed_of_trust_date,
    days_in_foreclosure, first_seen, is_new, investment_priority, notes
) VALUES %s
ON CONFLICT (id) DO UPDATE SET
    source_url           = EXCLUDED.source_url,
    sale_date            = EXCLUDED.sale_date,
    sale_time            = EXCLUDED.sale_time,
    days_until_sale      = EXCLUDED.days_until_sale,
    assessed_value       = COALESCE(EXCLUDED.assessed_value, listings.assessed_value),
    rough_equity_est     = COALESCE(EXCLUDED.rough_equity_est, listings.rough_equity_est),
    est_profit_potential = COALESCE(EXCLUDED.est_profit_potential, listings.est_profit_potential),
    beds_baths_sqft      = COALESCE(EXCLUDED.beds_baths_sqft, listings.beds_baths_sqft),
    year_built           = COALESCE(EXCLUDED.year_built, listings.year_built),
    owner_name           = COALESCE(EXCLUDED.owner_name, listings.owner_name),
    owner_mailing_address= COALESCE(EXCLUDED.owner_mailing_address, listings.owner_mailing_address),
    investment_priority  = COALESCE(EXCLUDED.investment_priority, listings.investment_priority),
    last_updated         = NOW(),
    is_new               = EXCLUDED.is_new
"""

COLS = [
    "id", "source", "source_url", "address", "city", "county", "state", "zip",
    "property_type", "stage", "sale_date", "sale_time", "sale_location",
    "days_until_sale", "asking_price", "assessed_value", "original_principal",
    "rough_equity_est", "est_profit_potential", "deposit", "beds_baths_sqft",
    "year_built", "lot_size", "last_sold_date", "last_sold_price",
    "years_since_last_sale", "owner_name", "owner_mailing_address",
    "owner_mailing_differs", "lender", "trustee", "notice_date", "notice_text",
    "deed_of_trust_date", "days_in_foreclosure", "first_seen", "is_new",
    "investment_priority", "notes",
]


def main():
    files = get_enabled_files()
    log.info(f"Found {len(files)} data file(s) to sync")

    conn = psycopg2.connect(DATABASE_URL)
    cur  = conn.cursor()

    total_added   = 0
    total_skipped = 0

    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
            listings = data.get("listings", [])
            if not listings:
                log.info(f"  {path.name}: 0 listings — skipping")
                continue

            rows = []
            for l in listings:
                row = listing_to_row(l)
                if not row["id"] or not row["address"]:
                    total_skipped += 1
                    continue
                rows.append(tuple(row[c] for c in COLS))

            if rows:
                execute_values(cur, UPSERT_SQL, rows)
                conn.commit()
                log.info(f"  {path.name}: upserted {len(rows)} listings")
                total_added += len(rows)

        except Exception as e:
            conn.rollback()
            log.error(f"  {path.name}: ERROR — {e}")

    cur.close()
    conn.close()
    log.info(f"Done. {total_added} upserted, {total_skipped} skipped (no id/address).")


if __name__ == "__main__":
    main()
