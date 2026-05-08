# MRR Dashboard

End-to-end pipeline that:

1. Generates realistic Stripe test data (75 customers × 6 months of
   subscription history, including cancellations and tier changes).
2. Syncs Stripe → BigQuery as 3 denormalized tables.
3. Runs a single SQL query (`sql/mrr_monthly.sql`) to compute MRR per month.
4. Renders the result as a static-served line chart (Vite + React +
   Recharts) — no backend, no runtime credentials in the browser.

**Quick links:**
- MRR math + edge cases → [`sql/README.md`](sql/README.md)
- Frontend deep-dive → [`frontend/README.md`](frontend/README.md)
- How this codebase was built (development harness, Sprint 1 seed-script
  details, Stripe Test Clock semantics) → [`HARNESS.md`](HARNESS.md)

---

## Prerequisites

- **Python 3.9+** with venv (used by the Stripe seed + BigQuery sync scripts)
- **Node 18+** (used by the dashboard build)
- **Stripe test API key** (`sk_test_*` from https://dashboard.stripe.com/apikeys; live keys are rejected by the scripts)
- **Google Cloud service account JSON** with BigQuery roles (`BigQuery Data Editor`, `BigQuery Job User`, `BigQuery User`) on a project of your choice
- A `.env` file at the project root with:
  ```
  STRIPE_API_KEY=sk_test_...
  GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/sa-key.json
  GOOGLE_CLOUD_PROJECT=your-gcp-project-id
  ```

---

## One-time setup

```bash
# Python (Stripe seed + BigQuery sync)
cd scripts
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd ..

# Node (dashboard)
cd frontend
npm install
cd ..
```

---

## 1. Generate Stripe test data — `scripts/seed_stripe_data.py`

Creates 75 test customers across multiple Stripe Test Clocks with 6 months
of simulated billing history (active / canceled / past-due cohorts, plus
tier changes via cancel-and-recreate). Idempotent on re-runs (existing
seed-pattern customers are skipped).

```bash
# Load env and activate venv
set -a && source .env && set +a
source scripts/venv/bin/activate

# Default: 75 customers, ~25 test clocks (this WRITES to your Stripe
# test-mode account; takes ~10–20 min due to clock advancement)
python scripts/seed_stripe_data.py

# Common variants
python scripts/seed_stripe_data.py --num-customers 10        # smaller seed
python scripts/seed_stripe_data.py --dry-run                 # no API calls
python scripts/seed_stripe_data.py --no-reset                # don't delete prior seed-pattern data on entry
python scripts/seed_stripe_data.py --cleanup-after           # delete the test clocks at the end
python scripts/seed_stripe_data.py --cleanup                 # delete ALL seed-pattern test clocks (interactive)
```

Detailed flag reference, status-distribution targets, and Stripe Test
Clock date-field semantics → [`HARNESS.md`](HARNESS.md).

---

## 2. Sync Stripe → BigQuery — `scripts/sync_stripe_to_bq.py`

Read-only on Stripe; creates / writes to a BigQuery dataset. Pulls
Customer, Subscription (with price expanded), and Invoice objects across
all test clocks, transforms them, and merges into 3 denormalized tables
plus a `_sync_watermarks` operations table.

```bash
set -a && source .env && set +a
source scripts/venv/bin/activate

# Full refresh (truncate + reload — cheap and reproducible against test data)
python scripts/sync_stripe_to_bq.py --dataset mrr_dev --full-refresh --no-confirm

# Incremental sync (uses the watermark table; faster after the initial load)
python scripts/sync_stripe_to_bq.py --dataset mrr_dev --no-confirm

# Dry-run (creates dataset+tables but skips Stripe fetch + MERGE)
python scripts/sync_stripe_to_bq.py --dataset mrr_dev --dry-run
```

Expected output for a successful run looks like:

```
Synced 75 customers (75 inserted, 0 updated),
       82 subscriptions (82 inserted, 0 updated),
       300 invoices (300 inserted, 0 updated).
Errors: 0. Duration: ~50s
```

**Safety:** the script refuses to write to a dataset whose name contains
`prod` or `live` unless `ALLOW_PRODUCTION_SYNC=true` is set in the env.
Live API keys (`sk_live_*`) are also rejected at startup.

---

## 3. Verify the BigQuery tables (optional)

```bash
set -a && source .env && set +a
source scripts/venv/bin/activate

python -c "
from google.cloud import bigquery
c = bigquery.Client()
for t in ['customers', 'subscriptions', 'invoices', '_sync_watermarks']:
    n = next(c.query(f'SELECT COUNT(*) n FROM \`{c.project}.mrr_dev.{t}\`').result())['n']
    print(f'{t:25s} {n} rows')
"
```

---

## 4. Run the dashboard — `frontend/`

The dashboard is a static-served Vite + React + Recharts SPA. The MRR
data is computed at **build time** by running `sql/mrr_monthly.sql`
against BigQuery and writing the 7-row result to
`frontend/public/mrr.json`. The browser fetches that JSON at runtime —
no BigQuery credentials are exposed to the browser.

```bash
# From the project root, with .env loaded
set -a && source .env && set +a

cd frontend

# Regenerate the JSON from the current state of mrr_dev (optional;
# committed mrr.json works out of the box)
npm run build-data

# Start the dev server
npm run dev
# → http://localhost:5173

# OR build a static bundle for deployment
npm run build
# → dist/  (deploy to Vercel / Netlify / GitHub Pages / S3)
```

The chart should display 7 monthly data points spanning Nov 2025 → May
2026 with the title "Monthly Recurring Revenue".

To simulate the error state without breaking the JSON:
```
http://localhost:5173/?simulate=error
```

Frontend deep-dive (architecture choices, test layout, troubleshooting)
→ [`frontend/README.md`](frontend/README.md).

---

## End-to-end smoke test

After everything is set up:

```bash
set -a && source .env && set +a

# 1. (Optional, slow) Generate fresh Stripe data
# python scripts/seed_stripe_data.py --num-customers 10

# 2. Sync to BigQuery
source scripts/venv/bin/activate
python scripts/sync_stripe_to_bq.py --dataset mrr_dev --full-refresh --no-confirm

# 3. Regenerate the chart JSON
cd frontend && npm run build-data && cd ..

# 4. Run the dashboard
cd frontend && npm run dev
# Open http://localhost:5173 and confirm the 7 MRR data points
```

---

## Tests

Each layer has its own test suite:

```bash
# Stripe seed script (mocked unit tests)
source scripts/venv/bin/activate
cd scripts && python -m pytest tests/test_seed_stripe_data.py -q

# BigQuery sync (mocked unit tests + gated live integration)
python -m pytest tests/test_sync_stripe_to_bq.py -q
TEST_SYNC_INTEGRATION=1 python -m pytest tests/test_sync_stripe_to_bq.py -k integration -q   # writes to test-mode Stripe + a temporary BQ dataset

# MRR SQL (static + gated live)
python -m pytest tests/test_mrr_monthly_sql.py -q
TEST_MRR_LIVE=1 python -m pytest tests/test_mrr_monthly_sql.py -q                            # runs sql/mrr_monthly.sql against mrr_dev

# Frontend (Vitest)
cd ../frontend && npm test
RUN_E2E=1 npm run test:e2e   # Playwright E2E (requires dev server)
```

---

## Project layout

```
.
├── README.md            ← this file (run-the-system view)
├── HARNESS.md           ← build-the-system view (development harness, Sprint 1 details)
├── CLAUDE.md            ← Claude Code project context
├── QUICKSTART.md        ← harness quickstart (legacy)
├── .env                 ← your local credentials (gitignored)
│
├── scripts/             ← Python: data generation + BigQuery sync
│   ├── seed_stripe_data.py       (entry — Stripe Test Clock seeder)
│   ├── sync_stripe_to_bq.py      (entry — BigQuery sync)
│   ├── stripe_seeder/            (seed-script package)
│   ├── bq_sync/                  (BQ-sync package)
│   ├── tests/                    (pytest suite)
│   ├── requirements.txt
│   └── venv/                     (gitignored)
│
├── sql/                 ← BigQuery SQL
│   ├── mrr_monthly.sql           (the MRR calculation)
│   └── README.md                 (rules + edge cases + iteration history)
│
├── frontend/            ← Vite + React + TypeScript dashboard
│   ├── src/                      (App, MrrChart, types, tests)
│   ├── scripts/build-data.ts     (build-time SQL → public/mrr.json)
│   ├── public/mrr.json           (committed build artifact)
│   ├── tests/                    (Playwright E2E)
│   ├── package.json
│   └── README.md
│
└── .harness/            ← development-harness runtime (gitignored)
    ├── plans/
    ├── contracts/
    ├── handoffs/
    ├── evaluations/
    └── state.json
```

---

## Troubleshooting

**Stripe seed seems stuck on a clock for minutes.** The seeder advances
each Stripe Test Clock through 6 months of simulated time, polling for
ready state. ~5 min/clock is normal; 25 clocks ≈ 15-20 min total. Watch
for `Clock <id> is ready` log lines.

**`sync_stripe_to_bq.py` returns 0 customers despite seed succeeding.**
This was a real bug fixed in Sprint 2 iter-4: Stripe's `Customer.list()`
excludes test-clock-attached customers by default. The fixed fetcher
enumerates test clocks and lists per-clock. If you regress past commit
`33902c3` you may hit this again.

**Dashboard shows the wrong months ("Oct 25" instead of "Nov 2025").**
This was a timezone bug fixed at commit `32cea32` — `toLocaleDateString`
without `timeZone: 'UTC'` shifts UTC-midnight dates back by your local
offset.

**`npm run build` fails with `__dirname is not defined`.** ESM scope.
Fixed at commit `764a820` via `fileURLToPath(import.meta.url)`. Ensure
you're past that commit.

**MRR doubles for tier-change customers in their transition month.**
Fixed at commit `61fd5d3` by switching to end-of-month snapshot
(Convention A). See [`sql/README.md`](sql/README.md) for the full math.
