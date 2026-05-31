# Foreclosure Finder — Task List

Last updated: 2026-05-31

---

## Account Setup (Joe does these)

- [ ] **1. Create Supabase project**
  - Go to supabase.com → New project → name it `foreclosure-finder`
  - Settings → API → copy:
    - Project URL (`https://xxxx.supabase.co`)
    - Anon/public key (long JWT string)
    - JWT Secret (under JWT Settings)

- [ ] **2. Create Railway account + connect GitHub repo**
  - Go to railway.app → New project → Deploy from GitHub
  - Connect GitHub account → select the Foreclosures repo
  - No further config needed yet

- [ ] **3. Create Stripe account + products**
  - Go to stripe.com → stay in **test mode**
  - Products → Add product: `Starter` — $99/month recurring → copy Price ID (`price_xxx`)
  - Products → Add product: `Pro` — $199/month recurring → copy Price ID (`price_xxx`)
  - Developers → API keys → copy Secret key (`sk_test_xxx`)

- [ ] **4. Pick a domain name**
  - Examples: foreclosurefinder.io, vaforeclosures.com, vaforeclosureleads.com
  - Purchase from Namecheap, Google Domains, or similar
  - Will point to Railway (backend) and Vercel (frontend) once deployed

---

## Deployment (do together once accounts are ready)

- [ ] **5. Wire credentials + deploy backend to Railway**
  - Bring Supabase, Railway, and Stripe credentials to Claude Code
  - Claude creates `.env` files, deploys FastAPI backend to Railway
  - Runs database migration (`001_initial_schema.sql`)
  - Verifies API is live at Railway URL

- [ ] **6. Deploy frontend to Vercel**
  - Connect `app/frontend` to Vercel
  - Set env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_API_URL`
  - Deploy and point custom domain

- [ ] **7. Wire Stripe webhook to Railway backend**
  - Stripe dashboard → Developers → Webhooks → Add endpoint
  - URL: `https://your-backend.railway.app/billing/webhook`
  - Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
  - Copy webhook signing secret (`whsec_xxx`) → add to Railway env vars

- [ ] **8. Seed database with existing pipeline data**
  - Run `db_sync.py` against live database
  - Backfills all current listings from JSON data files into PostgreSQL
  - Verify counts match Google Sheets

- [ ] **9. End-to-end smoke test**
  - Create test account → select counties → Stripe checkout (test card `4242 4242 4242 4242`)
  - Verify listings appear filtered by county
  - Test save/unsave, billing portal, sign out

---

## Remaining Scrapers

- [ ] **10. Build TMMP scraper**
  - First: manually visit `tmppllc.com/virginia_foreclosure_sales` to confirm page is live
  - If confirmed: build scraper (requests + BS4 if HTML table, pdfplumber if PDF)
  - Add to pipeline and SOURCES.md

- [ ] **11. Build LOGS Legal scraper (PowerBI)**
  - Target: `logs.com/va-sales-report.html`
  - Statewide VA trustee sales with estimated opening bid amounts
  - Requires Playwright + PowerBI network request interception
  - Hardest remaining scraper — tackle after simpler ones are stable

- [ ] **12. Build Southside Sentinel scraper**
  - Target: `ssentinel.com/Classifieds/public-notices/`
  - Covers Middlesex County + Middle Peninsula
  - Static HTML — simple requests + BeautifulSoup build
  - Add `ENABLE_SOUTHSIDE_SENTINEL` toggle to pipeline

---

## Pipeline

- [ ] **13. Add DATABASE_URL to launchd daily schedule**
  - Add `DATABASE_URL` env var to `com.foreclosure.daily-update.plist`
  - So `db_sync.py` runs automatically after each daily pipeline execution
  - Verify first automated run writes to the live database

---

## Reference

### What's already built
| Component | Status | Location |
|-----------|--------|----------|
| Data pipeline (25 Column.us sources + SIWPC + Washington Times) | ✅ Running daily | `scripts/` |
| Google Sheets dashboard | ✅ Live | Sheet ID: `1_Nztmx-poW29M1moBPkfMyfj6nMeRqewML7GGjJwQ-c` |
| PostgreSQL schema | ✅ Built | `app/migrations/001_initial_schema.sql` |
| FastAPI backend (listings, users, billing, auth) | ✅ Built | `app/backend/` |
| Pipeline → PostgreSQL bridge | ✅ Built | `scripts/db_sync.py` |
| Frontend (login, dashboard, listing detail, settings, pricing) | ✅ Built | `app/frontend/` |
| Railway deploy config | ✅ Built | `app/backend/Procfile` |

### Tech stack
| Layer | Technology |
|-------|-----------|
| Database | PostgreSQL (Railway) |
| Backend | Python + FastAPI |
| Frontend | Next.js (React) + Tailwind |
| Auth | Supabase |
| Billing | Stripe |
| Frontend hosting | Vercel |
| Backend hosting | Railway |

### Pricing
| Plan | Price | Counties |
|------|-------|----------|
| Free | $0 | 1 county |
| Starter | $99/month | Up to 5 counties |
| Pro | $199/month | Unlimited (all 95 VA counties) |
