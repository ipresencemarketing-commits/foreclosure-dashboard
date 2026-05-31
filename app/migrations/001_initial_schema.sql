-- ============================================================
-- Foreclosure Finder — Initial Database Schema
-- ============================================================
-- Run once against a fresh PostgreSQL database.
-- psql $DATABASE_URL -f migrations/001_initial_schema.sql

-- ── Extensions ───────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- LISTINGS
-- Mirrors the JSON listing shape from the pipeline.
-- The pipeline writes here instead of (or in addition to)
-- Google Sheets.
-- ============================================================
CREATE TABLE listings (
    -- Identity
    id                      TEXT PRIMARY KEY,           -- fc-xxxxxxxx from pipeline
    source                  TEXT NOT NULL,              -- column_us_richmond, siwpc, etc.
    source_url              TEXT,

    -- Property
    address                 TEXT NOT NULL,
    city                    TEXT,
    county                  TEXT,
    state                   TEXT DEFAULT 'VA',
    zip                     TEXT,
    property_type           TEXT DEFAULT 'single-family',

    -- Sale
    stage                   TEXT,                       -- auction, pre-fc, etc.
    sale_date               DATE,
    sale_time               TEXT,
    sale_location           TEXT,
    days_until_sale         INTEGER,

    -- Financials
    asking_price            NUMERIC(12,2),
    assessed_value          NUMERIC(12,2),
    original_principal      NUMERIC(12,2),
    rough_equity_est        NUMERIC(12,2),
    est_profit_potential    NUMERIC(12,2),
    deposit                 TEXT,

    -- Property details (GIS backfill)
    beds_baths_sqft         TEXT,
    year_built              INTEGER,
    lot_size                TEXT,
    last_sold_date          DATE,
    last_sold_price         NUMERIC(12,2),
    years_since_last_sale   INTEGER,

    -- Owner (GIS backfill)
    owner_name              TEXT,
    owner_mailing_address   TEXT,
    owner_mailing_differs   BOOLEAN,

    -- Notice
    lender                  TEXT,
    trustee                 TEXT,
    notice_date             DATE,
    notice_text             TEXT,
    deed_of_trust_date      DATE,
    days_in_foreclosure     INTEGER,

    -- Pipeline metadata
    first_seen              DATE DEFAULT CURRENT_DATE,
    last_updated            TIMESTAMPTZ DEFAULT NOW(),
    is_new                  BOOLEAN DEFAULT TRUE,
    investment_priority     TEXT,                       -- High / Medium / Low

    -- Contact (skip-trace — future)
    estimated_phone         TEXT,
    estimated_email         TEXT,
    notes                   TEXT
);

CREATE INDEX idx_listings_county    ON listings(county);
CREATE INDEX idx_listings_sale_date ON listings(sale_date);
CREATE INDEX idx_listings_stage     ON listings(stage);
CREATE INDEX idx_listings_source    ON listings(source);
CREATE INDEX idx_listings_first_seen ON listings(first_seen);

-- ============================================================
-- USERS
-- Managed by Supabase Auth — this table holds app-level
-- profile data linked to the Supabase auth.users UUID.
-- ============================================================
CREATE TABLE users (
    id                  UUID PRIMARY KEY,               -- matches Supabase auth.users.id
    email               TEXT UNIQUE NOT NULL,
    full_name           TEXT,
    phone               TEXT,

    -- Stripe
    stripe_customer_id  TEXT UNIQUE,
    stripe_sub_id       TEXT UNIQUE,
    plan                TEXT DEFAULT 'free',            -- free | starter | pro
    plan_status         TEXT DEFAULT 'inactive',        -- active | inactive | past_due | canceled
    plan_started_at     TIMESTAMPTZ,
    plan_ends_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- USER_COUNTIES
-- Which counties each subscriber has selected.
-- Feed only shows listings where county IN (user's counties).
-- ============================================================
CREATE TABLE user_counties (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    county      TEXT NOT NULL,                          -- matches listings.county
    state       TEXT DEFAULT 'VA',
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, county, state)
);

CREATE INDEX idx_user_counties_user_id ON user_counties(user_id);

-- ============================================================
-- SAVED_LISTINGS
-- Listings a subscriber has bookmarked.
-- ============================================================
CREATE TABLE saved_listings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listing_id  TEXT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    saved_at    TIMESTAMPTZ DEFAULT NOW(),
    notes       TEXT,
    UNIQUE(user_id, listing_id)
);

-- ============================================================
-- PLANS
-- Defines what each plan tier allows.
-- ============================================================
CREATE TABLE plans (
    name                TEXT PRIMARY KEY,   -- free | starter | pro
    display_name        TEXT NOT NULL,
    price_monthly       NUMERIC(8,2),
    max_counties        INTEGER,            -- NULL = unlimited
    stripe_price_id     TEXT,              -- from Stripe dashboard
    description         TEXT
);

INSERT INTO plans VALUES
    ('free',    'Free',         0.00,  1,    NULL, 'One county, 5 listings/day'),
    ('starter', 'Starter',     99.00,  5,    NULL, 'Up to 5 counties, all listings'),
    ('pro',     'Pro',        199.00,  NULL, NULL, 'Unlimited counties, all listings + priority alerts');

-- ============================================================
-- PIPELINE_RUNS
-- Log of each daily pipeline execution.
-- ============================================================
CREATE TABLE pipeline_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT DEFAULT 'running',     -- running | success | error
    listings_added  INTEGER DEFAULT 0,
    listings_updated INTEGER DEFAULT 0,
    error_message   TEXT,
    source_counts   JSONB                        -- {"column_us_richmond": 172, ...}
);
