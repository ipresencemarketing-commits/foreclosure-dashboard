#!/usr/bin/env python3
"""
Foreclosure Finder — Canonical Listing Schema
==============================================
Single source of truth for the structure of a foreclosure listing dict.

Every scraper function returns raw dicts; every listing passes through
normalize_listing() before being written to foreclosures.json.  This
ensures:

  • All fields are always present (never KeyError on the consumer side)
  • Types are consistent (int prices, bool flags, None not "")
  • Derived / computed fields are pre-calculated once at save time
  • The JSON is ready to be served directly to a mobile app or REST API

Schema version is bumped whenever a field is added, renamed, or removed
so app clients can detect and handle format changes.

Phone-app field notes
---------------------
  estimated_value     — best available: GIS assessed → Redfin estimate
  latitude / longitude — populated when Census geocoder runs (backfill Pass 2)
  status              — human-readable label for UI display
  is_expired          — boolean; sale date has passed
  days_until_sale     — integer; negative means past, None means unknown
  rough_equity        — int dollars: estimated_value − asking_price
  profit_potential    — int dollars: (estimated_value × 0.70) − asking_price
                        (70% rule — maximum flipper offer relative to ARV)
  schema_version      — bump this when the shape changes
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

SCHEMA_VERSION = "2.0"

# ---------------------------------------------------------------------------
# Field registry
# ---------------------------------------------------------------------------
# Each entry: (field_name, default_value)
# The default is used when the incoming dict is missing the key entirely.
# None = intentionally absent (not yet enriched); "" would hide that.

_FIELD_DEFAULTS: list[tuple[str, Any]] = [
    # ── Identity ──────────────────────────────────────────────────────────
    ("id",                              None),   # unique key; set by scraper
    ("schema_version",                  SCHEMA_VERSION),

    # ── Location ──────────────────────────────────────────────────────────
    ("address",                         None),
    ("city",                            None),
    ("zip",                             None),
    ("state",                           "VA"),
    ("county",                          None),
    ("latitude",                        None),   # float; from Census geocoder
    ("longitude",                       None),   # float; from Census geocoder

    # ── Sale / auction ────────────────────────────────────────────────────
    ("sale_date",                        None),   # ISO date string "YYYY-MM-DD"
    ("sale_time",                        None),
    ("sale_location",                    None),
    ("stage",                            None),   # "auction" | "pre-fc" | "reo"
    ("status",                           None),   # computed; human label for UI
    ("is_expired",                       None),   # bool; sale_date < today
    ("days_until_sale",                  None),   # int; negative = past

    # ── Financial ─────────────────────────────────────────────────────────
    ("asking_price",                     None),   # int cents or None
    ("estimated_value",                  None),   # int; GIS assessed → Redfin
    ("rough_equity",                     None),   # int; estimated_value − asking_price
    ("profit_potential",                 None),   # int; (estimated_value×0.70)−asking_price
    ("investment_priority",              None),   # "High" | "Medium" | "Low"

    # ── Mortgage / notice ──────────────────────────────────────────────────
    ("deed_of_trust_date",               None),
    ("original_principal",               None),
    ("deposit",                          None),
    ("lender",                           None),
    ("trustee",                          None),

    # ── Property details ──────────────────────────────────────────────────
    ("property_type",                    "single-family"),
    ("beds",                             None),   # int
    ("baths",                            None),   # float
    ("sqft",                             None),   # int
    ("year_built",                       None),   # int
    ("lot_size",                         None),   # string e.g. "0.34 ac"

    # ── Sale history ──────────────────────────────────────────────────────
    ("last_sold_date",                   None),   # ISO date string
    ("last_sold_price",                  None),   # int
    ("years_since_last_sale",            None),   # float; computed

    # ── Owner ──────────────────────────────────────────────────────────────
    ("owner_name",                       None),
    ("owner_mailing_address",            None),
    ("owner_mailing_differs",            None),   # bool (True/False/None)
    ("owner_phone",                      None),   # blank until skip-trace
    ("owner_email",                      None),   # blank until skip-trace

    # ── Source metadata ────────────────────────────────────────────────────
    ("source",                           None),   # scraper tag e.g. "pnv", "column_fxbg"
    ("source_url",                       None),
    ("notice_text",                      None),   # full text up to 5000 chars
    ("date_scraped",                     None),   # ISO date; set at scrape time
]

# Flat set of all canonical field names (used for validation)
CANONICAL_FIELDS: set[str] = {name for name, _ in _FIELD_DEFAULTS}


# ---------------------------------------------------------------------------
# normalize_listing()
# ---------------------------------------------------------------------------

def normalize_listing(raw: dict) -> dict:
    """
    Return a fully-normalized listing dict ready for JSON serialization.

    Steps:
      1. Apply field defaults (every key is always present)
      2. Coerce types (prices → int, bools → bool, strings stripped)
      3. Compute derived fields (status, is_expired, days_until_sale,
         estimated_value, rough_equity, profit_potential,
         years_since_last_sale, investment_priority)
      4. Set schema_version

    Unknown keys from the raw dict are preserved under their original name
    so no data is silently dropped — the app/sheet can choose to ignore them.
    """
    out: dict = {}

    # ── 1. Start from defaults, then overlay raw values ───────────────────
    for field, default in _FIELD_DEFAULTS:
        out[field] = raw.get(field, default)

    # Preserve any extra keys the scraper attached (forward compatibility)
    for k, v in raw.items():
        if k not in out:
            out[k] = v

    # ── 2. Type coercions ──────────────────────────────────────────────────

    # Prices — store as int (cents would be better long-term but keep dollars
    # for now to match existing GIS/Redfin output)
    for price_field in ("asking_price", "last_sold_price", "original_principal"):
        out[price_field] = _to_int(out.get(price_field))

    # estimated_value: prefer GIS assessed value, fall back to Redfin estimate
    gis_val    = _to_int(raw.get("assessed_value") or raw.get("estimated_value"))
    redfin_val = _to_int(raw.get("redfin_estimate"))
    out["estimated_value"] = gis_val or redfin_val

    # Integer property fields
    for int_field in ("beds", "sqft", "year_built"):
        out[int_field] = _to_int(out.get(int_field))

    # Float
    for float_field in ("baths", "latitude", "longitude"):
        out[float_field] = _to_float(out.get(float_field))

    # owner_mailing_differs: normalize to bool
    omdf = out.get("owner_mailing_differs")
    if isinstance(omdf, str):
        out["owner_mailing_differs"] = omdf.strip().lower() in ("yes", "true", "1")
    elif omdf is not None:
        out["owner_mailing_differs"] = bool(omdf)

    # Strip strings
    for str_field in ("address", "city", "state", "county", "zip",
                      "owner_name", "owner_mailing_address", "source"):
        if isinstance(out.get(str_field), str):
            out[str_field] = out[str_field].strip() or None

    # State always "VA"
    out["state"] = "VA"

    # ── 3. Computed / derived fields ───────────────────────────────────────

    today = date.today()

    # days_until_sale / is_expired
    sale_date_str = out.get("sale_date")
    if sale_date_str:
        try:
            sale_dt = datetime.strptime(str(sale_date_str)[:10], "%Y-%m-%d").date()
            out["days_until_sale"] = (sale_dt - today).days
            out["is_expired"]      = sale_dt < today
        except ValueError:
            out["days_until_sale"] = None
            out["is_expired"]      = None
    else:
        out["days_until_sale"] = None
        out["is_expired"]      = None

    # status (human label for UI)
    stage = out.get("stage") or ""
    if out.get("is_expired"):
        out["status"] = "Sale Passed – Verify"
    else:
        out["status"] = {
            "auction": "Active Auction",
            "pre-fc":  "Pre-Foreclosure Notice",
            "reo":     "REO / Bank Owned",
        }.get(stage, stage.title() if stage else None)

    # investment_priority
    days = out.get("days_until_sale")
    if out.get("is_expired"):
        out["investment_priority"] = "Low"
    elif stage == "auction":
        out["investment_priority"] = "High"
    elif stage == "pre-fc" and days is not None and days >= 0:
        out["investment_priority"] = "High" if days <= 30 else "Medium"
    elif stage == "pre-fc":
        out["investment_priority"] = "Medium"
    else:
        out["investment_priority"] = "Low"

    # rough_equity and profit_potential
    est_val = out.get("estimated_value")
    price   = out.get("asking_price")
    if est_val is not None and price is not None:
        out["rough_equity"]     = int(est_val) - int(price)
        out["profit_potential"] = int(int(est_val) * 0.70) - int(price)
    else:
        out["rough_equity"]     = None
        out["profit_potential"] = None

    # years_since_last_sale
    lsd = out.get("last_sold_date")
    if lsd:
        try:
            sold_dt = datetime.strptime(str(lsd)[:10], "%Y-%m-%d").date()
            out["years_since_last_sale"] = round((today - sold_dt).days / 365.25, 1)
        except ValueError:
            out["years_since_last_sale"] = None
    else:
        out["years_since_last_sale"] = None

    # Remove the legacy always-zero field (replaced by days_until_sale)
    out.pop("days_in_foreclosure", None)

    # Ensure schema version is set
    out["schema_version"] = SCHEMA_VERSION

    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_int(val) -> int | None:
    """Coerce value to int, return None if not possible."""
    if val is None or val == "" or val == "N/A":
        return None
    try:
        return int(float(str(val).replace(",", "").replace("$", "").strip()))
    except (ValueError, TypeError):
        return None


def _to_float(val) -> float | None:
    """Coerce value to float, return None if not possible."""
    if val is None or val == "" or val == "N/A":
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None
