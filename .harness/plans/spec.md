# Spec — MRR Dashboard

> Written by the **Planner agent** for the Generator and Evaluator to consume.
> This spec covers the FULL MRR dashboard product across multiple sprints.
> **EXECUTION NOTE:** Sprint 1 closed at iteration 14 (sparse starts + 3-tier pricing + cancel-and-recreate tier changes per C-36/C-37; revised C-2 for active-sub constraint). Sprint 2 is now the active sprint.

## 1. Overview

An ambitious **Monthly Recurring Revenue (MRR) dashboard** that transforms raw Stripe subscription data into a clear, trend-driven interface for SaaS founders to track recurring revenue, cohort behavior, and churn. The product bridges Stripe's transaction data, a BigQuery warehouse, and a React dashboard to answer critical questions: "What was my MRR last month? How does it trend? Where's my churn?" The dashboard surfaces 6 months of historical data, supports drill-down by cohort, and displays actionable metrics (MRR, ARR, net retention, churn rate) with beautiful, data-forward visualization.

## 2. Target Users & Core Value

- **Primary user:** SaaS founder or finance lead who manages recurring revenue and wants deeper insights than Stripe's native UI provides
- **Core value:** "I can see my MRR trends, cohorts, and churn signals in one dashboard and make data-driven pricing and retention decisions"
- **Stretch users:** Revenue operations teams, finance analysts, product leads who need to drill into customer cohort behavior

## 3. Mode

- [x] **New project** — Generator scaffolds the stack from scratch
- [ ] **Existing codebase** — Generator extends an existing app; constrained to match conventions

### Default Stack (new project mode)

Frontend: React 18 + Vite + TypeScript + Tailwind
Backend: Python (FastAPI or lightweight CLI/script for ETL; BigQuery client library)
Data warehouse: Google BigQuery (managed analytics, no infra burden)
Tests: pytest (Python), Vitest + Playwright (React)
Style/format: ESLint + Prettier (frontend), ruff + black (Python)

## 4. Design Language

> Consulted the Anthropic frontend-design skill. Dashboard design must be data-forward, high-contrast, and optimized for quick insight.

- **Mood / identity:** Modern analytics aesthetic. Clean, high-contrast dashboard with sharp typography and generous whitespace around key metrics. Brutalist grid layout with deliberate accent colors. Inspired by tools like Mixpanel and Metabase — clarity over decoration, but with distinctive color and motion choices that avoid generic dashboard templates.

- **Type system:** 
  - **Display:** Inter or similar sans-serif for headlines (16–32px, weights 600–700)
  - **Body:** Inter or similar for UI text (13–14px, weight 400–500)
  - **Mono:** SF Mono or JetBrains Mono for numbers, raw data cells (12px, weight 400)
  - Hierarchy: Large metric values (MRR = 64px, bold); labels (12px, muted); supporting text (11px, lightest)

- **Color tokens:**
  - **Primary (accent):** `#0066FF` (electric blue, draws eyes to key metrics)
  - **Secondary (success):** `#10B981` (emerald green, signals growth)
  - **Alert (warning/danger):** `#EF4444` (red, flags churn or negative trends)
  - **Background (light):** `#FAFAFA` (off-white, reduces eye strain)
  - **Surface (cards):** `#FFFFFF` (pure white for metric cards)
  - **Border:** `#E5E7EB` (light gray, subtle separation)
  - **Text (primary):** `#1F2937` (near-black, high contrast)
  - **Text (secondary/muted):** `#6B7280` (medium gray, annotations)
  - Dark mode supported: invert lightness, preserve hue (e.g., text → `#F3F4F6`, surface → `#1F2937`)

- **Spacing scale:**
  - **Base unit:** 4px
  - **Scale stops:** 4, 8, 12, 16, 24, 32, 48, 64px
  - **Density:** Generous negative space around metrics (48–64px margins), denser rows in data tables (12px padding)

- **Layout primitives:**
  - **Grid:** 12-column, responsive (1 column mobile, 2–3 tablet, 4+ desktop)
  - **Sidebar:** Left sidebar nav (240px fixed or collapsible), main content area full-width
  - **Card system:** Metric cards (1 metric per card, 160–240px wide), full-width tables (charts and drill-down tables)
  - **Asymmetry:** Key metric in top-left prominence, secondary metrics stacked or grid-aligned; chart area spans 2/3, drill-down sidebar 1/3

- **Imagery / illustration direction:** No illustrations. Pure data visualization (line charts for trends, bar charts for cohorts, heatmaps for churn). Monochromatic icons (16–24px) for UI affordances (calendar, download, filter). Gradients acceptable on chart lines for visual separation.

- **Motion:**
  - **Page load:** Staggered metric cards fade in (100–150ms per card, easing: cubic-bezier(0.34, 1.56, 0.64, 1))
  - **Chart updates:** Line animations when data refreshes (300ms easing: cubic-bezier(0.43, 0.13, 0.23, 0.96))
  - **Hover states:** Subtle lift on metric cards (2px drop shadow, 100ms), highlight on table rows (background tint)
  - **Micro-interactions:** Tooltip fade-in (100ms), date picker slide-down (200ms)

- **Voice & microcopy:**
  - **Tone:** Direct, analytical, occasionally approachable. "MRR down $2.5K this month — here's why" (not "MRR declined significantly")
  - **Samples:**
    - Metric label: "Monthly Recurring Revenue"
    - Empty state: "No data yet. Connect Stripe and sync your first subscription."
    - Error: "Failed to fetch BigQuery data. Check your API key and try again."
    - Success: "Synced 47 customers and 103 invoices from Stripe."

## 5. Feature List

### Feature: Data Ingestion & Seeding (Sprint 1 — this run)

- **User stories:**
  - As a developer, I can run a Python script to populate my Stripe test account with realistic customer and subscription data so that I have 6 months of billing history to visualize
  - As a developer, I can ensure the script is idempotent so that re-running it doesn't create duplicate data
  - As a developer, I can verify the script created the right mix of subscription statuses (Active, Canceled, Past Due) so that I can test the dashboard against real scenarios

- **Depth criteria:**
  - Uses Stripe Test Clocks to simulate passage of time and generate invoices across multiple months (not just current-day data)
  - Creates 50–100 unique customers with varying subscription statuses
  - Batches customer creation across multiple test clocks (respecting the 3-customer-per-clock limit)
  - Advances time in logical intervals (monthly or per billing cycle), polling for clock.ready status before proceeding
  - Handles payment failures correctly (uses `pm_card_chargeCustomerFail` token for Past Due scenarios)
  - Cancels some subscriptions partway through the 6-month window to create historical churn signal
  - Logs/prints summary output: number of customers created, subscriptions by status, date range covered, any errors
  - Handles environment variable loading (`STRIPE_API_KEY` in .env or CLI arg)
  - Re-run safety: checks for existing customers (by idempotency token or name pattern) and skips creation if already present
  - Error handling: validates API responses, handles rate limits gracefully (exponential backoff), provides actionable error messages

- **Screens / surfaces:** CLI script + README instructions (no UI)

- **AI features:** None in Sprint 1

- **Out of scope for Sprint 1:**
  - BigQuery integration
  - MRR calculation logic
  - React UI
  - API endpoints
  - Observability/logging infrastructure

---

### Feature: BigQuery Schema & ETL Sync (Sprint 2)

- **User stories:**
  - As a data engineer, I can fetch Stripe customer, subscription, and invoice data using the Stripe SDK and load it into BigQuery tables so that MRR calculations have structured data to query
  - As a developer, I can run a Python ETL script (`scripts/sync_stripe_to_bq.py`) that fetches necessary objects from Stripe and populates BigQuery tables so that the dashboard has fresh data for analysis
  - As a developer, I can re-run the ETL script idempotently so that the script is safe to re-run without creating duplicate rows

- **Depth criteria:**
  - Schema is denormalized for MRR-calculation clarity (logic over 3NF normalization): 3 tables (customers, subscriptions, invoices) sufficient for Sprint 3 MRR queries
  - Fetches from Stripe: Customer objects, Subscription objects (including status, canceled_at, current_period_start/end, billing_cycle_anchor), Invoice objects
  - Price details (unit_amount, interval, interval_count) are denormalized into the Subscription row; no separate Price table in v1
  - Stripe Subscription rows are treated as facts (one BigQuery row per Stripe Subscription ID); tier changes from Sprint 1 (cancel-and-recreate) produce distinct subscription rows in the history, supporting chronological trend analysis
  - ETL script handles incremental sync: fetches only new/changed data since last successful run, does NOT re-import all records on every run
  - Idempotency: uses Stripe object IDs (customer_id, subscription_id, invoice_id) as primary keys; re-running the script does not produce duplicate rows
  - Error handling: logs failed syncs, can resume from last successful batch; validates API responses
  - Performance: syncs complete in <60s for typical usage (100–1000 customers)

- **Screens / surfaces:** CLI script (`scripts/sync_stripe_to_bq.py`), optional dashboard "Last synced" timestamp

- **AI features:** None

- **Out of scope for Sprint 2:**
  - Real-time streaming (batch syncs are sufficient)
  - Custom data quality rules beyond schema validation
  - Data retention policies (BigQuery defaults acceptable for v1)
  - Cloud Scheduler integration (script is runnable via CLI; scheduling is Sprint 5)

---

### Feature: MRR Calculation Logic (Sprint 3)

- **User stories:**
  - As a product manager, I can see my MRR calculated accurately month-by-month so that I trust the dashboard for financial decisions
  - As a developer, I can run a SQL query in BigQuery to compute the monthly MRR from the existing subscriptions and invoices data

- **Depth criteria:**
  - MRR is defined as: **"the normalized monthly value of active recurring subscriptions"** (NOT raw revenue sums).
  - **Active subscriptions:** a subscription contributes to a month's MRR if it was in an active billing state for ANY part of that month. Status check: `status IN ('active', 'trialing', 'past_due')` AND subscription start date ≤ month end AND (canceled_at IS NULL OR canceled_at ≥ month start).
  - **Normalization:** for subscriptions with billing interval, compute the normalized monthly contribution as: `unit_amount_cents / interval_count / 100.0` for monthly intervals; `unit_amount_cents / 12 / interval_count / 100.0` for yearly intervals. Day/week intervals not in scope.
  - **Tier changes:** cancel-and-recreate tier changes from Sprint 1 produce distinct subscription rows (v0 and v1 IDs). The query must treat each row independently using its own `start_date` and `canceled_at` to compute the correct monthly contribution.
  - **Output schema:** query returns rows of shape `month (DATE, first day of month) | mrr_amount (NUMERIC, USD dollars)`.
  - **Month coverage:** generate a date series covering the 6-month seed window (Nov 2025–May 2026 or inferred from `MIN(start_date)` to current date). One row per month.
  - **Dataset parameterization:** query must accept a dataset name parameter (e.g., `@dataset` or `${dataset}`) so it can be reused across dev/test datasets.
  - **Currency:** assume USD for v1 (matches Sprint 1 seed). Queries may filter or error on non-USD subscriptions.

- **Screens / surfaces:** `sql/mrr_monthly.sql` (single BigQuery Standard SQL file at project root)

- **AI features:** None

- **Out of scope for Sprint 3:**
  - New / expansion / churn MRR breakdowns (split by cohort or tier)
  - Cohort segmentation or filtering
  - Prorations beyond simple boundary rules
  - Real-time / streaming calculations
  - Materialized views or scheduled query orchestration

---

### Feature: React Dashboard — Lightweight SPA with Line Chart (Sprint 4)

- **Deliverable summary:** `/frontend/` directory at project root containing a Vite + React + TypeScript single-page app that renders ONE line chart showing MRR over the 6-month seed window. Data comes from `sql/mrr_monthly.sql` executed at build time, serialized to a static JSON file shipped with the bundle.

- **User stories:**
  - As a founder, I can open a single web page and see the monthly MRR trend at a glance, so I can spot growth or contraction
  - As a developer, I can run `npm run build` (or equivalent) which queries BigQuery, writes the JSON, and produces a deployable static bundle
  - As an operator, I can deploy the bundle to any static host (Vercel, Netlify, GH Pages, S3 + CloudFront) with no backend infrastructure

- **Depth criteria:**
  - **Stack:** React + TypeScript + Vite. Lightweight toolchain, no Next.js (overkill), no Create React App (deprecated). Vite chosen for fast dev server and minimal bundle.
  - **Chart library:** Open to Generator's choice during contract negotiation (Recharts, Chart.js, Vega-Lite, or SVG-by-hand). Must produce a clean line chart with axes, labels, and 7 data points visible.
  - **Build pipeline:** A `scripts/build-data.ts` (or `.mjs`) script runs at build time. It uses the `google-cloud-bigquery` Node SDK to execute `sql/mrr_monthly.sql`, substitutes `${dataset}` for the env var `BQ_DATASET` (default `mrr_dev`), and writes the result to `frontend/src/data/mrr.json` (or `frontend/public/mrr.json`). Script runs as a `prebuild` npm step or via script composition.
  - **Auth at build time:** `GOOGLE_APPLICATION_CREDENTIALS` env var read by the Node BigQuery client. Same service account JSON used for `sync_stripe_to_bq.py` works; no new credential needed.
  - **Auth at runtime:** None. Browser fetches the static JSON; no BQ creds exposed in the browser.
  - **Output JSON shape:** Matches SQL result — array of objects `[{"month": "2025-11-01", "mrr_amount": 1250.00}, ...]`. Brief documentation in `frontend/README.md` for future engineers.
  - **Page:** Single route, likely `/` (no router needed for v1). Title "Monthly Recurring Revenue". Chart fills most of the viewport with reasonable padding. X-axis = month labels (e.g., "Nov 2025"), Y-axis = "$ MRR".
  - **States:** Loading state while fetching JSON (brief flash; bundle ships with JSON, so fast); empty state if JSON is empty (gracefully handled, shouldn't occur in v1); error state if JSON fails to parse (defensive).
  - **Responsive:** Chart resizes on viewport change; readable on desktop + tablet. Phone-sized is nice-to-have, not required.
  - **Accessibility:** Chart has alt text or aria-label describing the trend. Color contrast meets WCAG 2.2 AA (passes axe-core). Keyboard focus traversal works.
  - **Tests:** Unit tests for chart component (renders without crashing, displays correct number of data points). Integration test for build-data script (mocked BigQuery client, verifies JSON output shape). Live test gated by env var (`TEST_FRONTEND_LIVE=1`) that runs actual build-data script against `mrr_dev` and asserts JSON has 7 rows with expected shape.

- **Screens / surfaces:**
  - `/` — MRR line chart (single view, full-width)

- **AI features:** None in Sprint 4

- **Out of scope for Sprint 4:**
  - Summary cards (current MRR, MoM change, etc.)
  - Cohort filters or drill-down tables
  - Date range picker or custom filters
  - CSV / PDF export
  - Heatmaps or other chart types
  - Settings page
  - Authentication / login
  - Backend API
  - Real-time data refresh
  - Multiple metrics / charts

---

### Feature: Polish & Observability (Sprint 5+)

- **User stories:**
  - As a founder, I want to know when the dashboard data was last synced so that I understand freshness
  - As a developer, I can monitor the ETL pipeline for failures so that I catch stale data before the user notices
  - As a founder, I can export the full dataset or schedule weekly MRR reports so that I can share with stakeholders

- **Depth criteria:**
  - "Last synced" timestamp visible on dashboard, refreshes with each manual sync or auto-refresh
  - Logging: all ETL and query errors captured with timestamps and context
  - Alerts: email or Slack notification on sync failure or MRR anomaly (>10% variance from trend)
  - Export: CSV and PDF formats, pre-filled email template for sharing
  - Scheduled reports: cron-based PDF generation + email delivery (optional stretch goal)
  - Performance optimization: query caching (materialized views for common cohorts), BigQuery cost tracking
  - Dark mode: toggle available, respects system preference

- **Screens / surfaces:**
  - Dashboard footer: "Last synced at {timestamp}" + Sync Now button
  - Settings page: `/settings` — API key management, alert preferences, export schedule
  - Admin dashboard (optional): sync history, error logs, query performance

- **AI features:** Optional — MRR anomaly detection using Anthropic API (given historical MRR, flag unexpected dips)

- **Out of scope for Sprint 5+:**
  - Custom dimension analysis (e.g., MRR by geography, plan, or custom field)
  - Forecasting models

---

## 6. Data Model (sketch only)

Denormalized schema (fewer, wider tables for MRR-calculation clarity):

| Table | Key Fields | Notes |
|---|---|---|
| **customers** | stripe_customer_id (PK), email, name, created_at, default_currency, livemode, test_clock_id, metadata (JSON) | One row per Stripe Customer. Includes test_clock_id for traceability of seed runs. |
| **subscriptions** | stripe_subscription_id (PK), stripe_customer_id (FK), status, current_price_id, unit_amount_cents, currency, interval, interval_count, billing_cycle_anchor, current_period_start, current_period_end, start_date, canceled_at, ended_at, created_at, livemode, idempotency_key, metadata (JSON) | One row per Stripe Subscription. Denormalizes Price details (amount, interval) so Sprint 3 MRR queries need only subscriptions + invoices. Tier changes from Sprint 1 produce distinct rows (v0 and v1 subscriptions for the same customer); chronologically successive rows support trend analysis. |
| **invoices** | stripe_invoice_id (PK), stripe_customer_id (FK), stripe_subscription_id (FK, nullable), period_start, period_end, status, total_cents, amount_paid_cents, amount_due_cents, currency, paid_at, created_at, livemode, metadata (JSON) | One row per Stripe Invoice. Line items collapsed into per-invoice totals (denormalized); no separate line-item table in v1. Subscription FK is nullable for one-off invoices. |

> Sketch only — Generator may refine during Sprint 2 contract negotiation per the principle: **fewer, wider tables → simpler MRR SQL in Sprint 3**.

## 7. Page / Screen List

- Frontend: `/frontend/` — Vite + React + TypeScript SPA, renders a single line chart from build-time JSON (Sprint 4)
- `/` — Main page (MRR line chart, single view)
- `/dashboard` — Main MRR dashboard (summary cards, MRR trend chart, cohort drill-down table, date/cohort filters) (Sprint 5+)
- `/dashboard/cohorts` — Cohort explorer view (grid of cohorts with MRR heatmap by month) (Sprint 5+)
- `/settings` — Configuration (Stripe API key, BigQuery credentials, alert preferences, export schedule) (Sprint 5+)
- CLI: `python scripts/seed_stripe_data.py` — Data generation script (Sprint 1)
- CLI: `python scripts/sync_stripe_to_bq.py` — ETL sync script (Sprint 2)

## 8. AI Features (cross-cutting)

**Sprint 1–4:** None.

**Sprint 5 (stretch):** Anomaly detection on MRR time series using Anthropic Messages API. Given the user's historical MRR values and trend, flag unexpected dips with a brief explanation ("MRR dropped $5K — detected 3 customer cancellations in premium tier; possible churn risk"). Requires a small LLM call per dashboard load (cached to avoid cost/latency).

Default provider: Anthropic Messages API. User provides API key in settings; all calls go through the backend (not exposed client-side).

## 9. Sprint Decomposition (proposed)

> Sprint 1 is complete. Sprint 2 is complete. Sprint 3 is now active.

1. **Sprint 1 — Data Seeding (CLOSED).** Python script using Stripe Test Clocks to populate 50–100 test customers with 6 months of billing history (Active, Canceled, Past Due statuses). Includes README instructions for running the script. No application code, no UI.

2. **Sprint 2 — BigQuery & ETL Pipeline (CLOSED).** BigQuery dataset schema + Python ETL script for incremental sync from Stripe. Handles subscriptions, invoices, payment events. Scheduled via Cloud Scheduler or cron.

3. **Sprint 3 — MRR Calculation Logic (CLOSED).** Single BigQuery Standard SQL query (`sql/mrr_monthly.sql`) that computes the normalized monthly value of active recurring subscriptions. Output: month-by-month MRR for the 6-month seed window. Respects tier changes (cancel-and-recreate), billing intervals (monthly/yearly), and active subscription boundary rules.

4. **Sprint 4 — Lightweight React Dashboard (THIS RUN).** `/frontend` Vite + React + TypeScript SPA with a single line chart visualizing the 6-month MRR trend. Data sourced via build-time execution of `sql/mrr_monthly.sql`, serialized to static JSON. No backend, no runtime BQ creds in the browser. Deployable to any static host.

5. **Sprint 5 — Polish & Observability.** Last synced timestamp, ETL monitoring, email alerts on failures, scheduled PDF reports, dark mode toggle, optional anomaly detection.

> The Generator may renegotiate sprint boundaries if sizing is off during contract negotiation.

## 10. Out of Scope

- Multi-tenant SaaS (single Stripe account per dashboard instance)
- Custom dimensions (industry, geography, custom fields) in v1
- Forecasting or predictive MRR
- Advanced cohort analysis (magic number, payback period, LTV/CAC)
- Real-time streaming (batch ETL sufficient)
- Integrations with other payment processors (Stripe only for v1)
- Mobile app (responsive web only)

## 11. Success Criteria (high-level)

- **Functional:** Seeded data exists; React dashboard loads and displays accurate MRR for test data; filters and drill-down work
- **Data integrity:** BigQuery dataset is populated; ETL sync produces no duplicates; MRR calculations match Stripe's reported revenue ±2%
- **UX quality:** Dashboard is usable without documentation; empty/error/loading states are present; responsive on desktop and tablet
- **Performance:** Dashboard loads in <3s; BigQuery queries complete in <2s for typical cohort size (100–1000 customers)
- **Accessibility:** WCAG 2.2 AA minimum (color contrast, keyboard nav, screen reader support, semantic HTML)
- **Reliability:** ETL script handles Stripe API rate limits and retries; no data loss on failure; observability in place (logs, last-synced timestamp)

---

## Execution Notes

**Sprint 1 (closed at iter-14):**
- Stripe Test Clocks used to simulate 6 months of billing history with sparse subscription starts (months 0–4 per customer, drawn uniformly).
- Multi-tier pricing: basic ($50/month), pro ($100/month), enterprise ($250/month). ~30% of customers experience a tier change (cancel-then-recreate on Stripe; v0 and v1 subscription IDs in the history).
- Subscription statuses: Active, Canceled (month 3–4 post-start), Past Due (via `pm_card_chargeCustomerFail` token).
- Idempotency keys: `seed-sub-{customer_id}-v0` for initial, `seed-sub-{customer_id}-v1` for post-tier-change.

**Sprint 2 (active):**
- ETL script fetches Stripe Customers, Subscriptions, and Invoices (via Stripe SDK).
- Denormalized 3-table BigQuery schema: customers, subscriptions (with price details), invoices (with line items rolled up).
- Idempotent sync: uses Stripe object IDs as primary keys; re-runs do not produce duplicates.
- Supports both first-time bulk load and incremental sync.
- Schema designed for Sprint 3 MRR SQL: a single query over subscriptions + invoices should compute monthly MRR per customer per month without further migrations.
