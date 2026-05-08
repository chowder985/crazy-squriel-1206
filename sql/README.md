# MRR Calculation — `sql/mrr_monthly.sql`

> **One-line definition:** MRR for month M = sum of monthly-normalized
> contributions from every subscription that is **active at the end of M**.

This file is the human-facing reference for the MRR query. The SQL itself
(`mrr_monthly.sql`) has an inline technical header for engineers reading
the code; this README is for understanding the **rules**, **rationale**, and
**edge cases** without reading SQL.

## Convention used: **end-of-month snapshot (Convention A)**

This is the SaaS industry standard — used by Stripe, ProfitWell,
ChartMogul, and Baremetrics. Three equivalent framings:

- **Snapshot semantics:** "What recurring revenue is locked in at the
  close of this month?"
- **No double-count:** a customer who upgrades mid-month has v0 canceled
  mid-M and v1 active at end-of-M — only v1 counts, not v0 + v1.
- **Cancellation semantics:** a sub canceled in M is no longer recurring
  revenue at end-of-M, so M is the first month of $0 contribution.

The trade-off: a sub canceled on Day 1 of M and one canceled on Day 30
of M both contribute $0 to M. We round to end-of-month for cleanliness
(one number per customer per month, no pro-rations).

## The three rules a subscription must satisfy to contribute to month M

A subscription contributes to month M's MRR **if and only if** all three
conditions are true.

### 1. Status filter — "subscription ever activated"

```sql
status NOT IN ('incomplete', 'incomplete_expired')
```

Excludes only subs whose first invoice never finalized. Subs that
activated and later went `canceled` / `past_due` / `unpaid` / `paused` /
`trialing` / `active` all qualify — their end-of-activity is determined
by `canceled_at`, not by the current `status` column.

> **Why not `status IN ('active', 'trialing', 'past_due')`?**
> An earlier iteration used that filter. It silently excluded canceled
> subs from every month they had been active, undercounting MRR by
> $1,450 – $2,950 per month for the seed data. See the inline comment
> on the `active_subscriptions` CTE in the SQL for the bug history.

### 2. Start boundary — "started by end of month"

```sql
start_date <= LAST_DAY(M)
```

The sub must have started on or before the last day of M.

### 3. Cancel boundary — "still active at end of month"

```sql
canceled_at IS NULL OR canceled_at > LAST_DAY(M)
```

Either the sub is still active (no `canceled_at`), OR it was canceled
**after** the last day of M. A sub canceled mid-month is NOT active at
end-of-M, so contributes $0 to M.

> **Why `> LAST_DAY(M)` and not `>= first_day(M)`?**
> An earlier iteration used the looser `canceled_at >= first_day(M)`
> rule (active for any part of M). That double-counted tier-change
> customers in their transition month — a customer who upgraded from
> $50 to $100 on Dec 9 was counted as $150 instead of $100. The
> end-of-month rule eliminates that overlap.

## Normalization formula

Each qualifying subscription contributes a monthly-normalized amount
based on its billing interval:

| If `interval` is | Monthly contribution |
|---|---|
| `month` | `unit_amount_cents / interval_count / 100` |
| `year` | `unit_amount_cents / 12 / interval_count / 100` |
| `day`, `week`, other | **Silently skipped** (returns NULL, filtered) |

Examples:

| Sub | interval | interval_count | unit_amount_cents | Monthly contribution |
|---|---|---|---|---|
| $50/month, monthly billing | `month` | 1 | 5000 | **$50.00** |
| $100 billed every 2 months | `month` | 2 | 10000 | **$50.00** |
| $1,200/year, annual billing | `year` | 1 | 120000 | **$100.00** |
| $2,400 every 2 years | `year` | 2 | 240000 | **$100.00** |

The SQL does NOT normalize across currencies — it assumes USD. The
seed data is USD-only; non-USD subs would be summed naively. (Defer to
a future iteration if multi-currency support is needed.)

## Output shape

```
month       | mrr_amount
------------|------------
2025-11-01  | NUMERIC USD
2025-12-01  | NUMERIC USD
…           | …
```

- One row per month in the seeded 6-month window (Nov 2025 – May 2026,
  7 rows inclusive — November is partial-month start; May is last
  complete month).
- `month` is the FIRST DAY of the month (DATE).
- `mrr_amount` is in dollars (NUMERIC), not cents. Zero-MRR months
  emit `0.00` rather than NULL.
- Always exactly 7 rows for the current seed window. Empty months
  (none in the current data) would still emit a row with `0.00`.

## Three edge cases worth understanding

### Edge 1 — Tier change (Sprint 1 iter-14 cancel-and-recreate)

Customer C upgrades from $50/mo to $100/mo on Dec 9.

Stripe state in BigQuery `mrr_dev.subscriptions`:
- v0: `canceled_at = 2025-12-09`, `unit_amount_cents = 5000`
- v1: `start_date = 2025-12-09`, `canceled_at = NULL`, `unit_amount_cents = 10000`

| Month | v0 contributes? | v1 contributes? | Customer C total |
|---|---|---|---|
| 2025-11 | ✓ ($50, active end-of-Nov) | ✗ (not yet started) | **$50** |
| 2025-12 | ✗ (not active end-of-Dec; canceled Dec 9) | ✓ ($100) | **$100** |
| 2026-01+ | ✗ | ✓ ($100) | **$100** |

No double-count in the transition month.

### Edge 2 — Mid-month cancellation (no replacement)

Customer D cancels their $50/mo subscription on Feb 15. No follow-up sub.

| Month | Sub contributes? | Customer D total |
|---|---|---|
| 2026-01 | ✓ ($50, active end-of-Jan) | **$50** |
| 2026-02 | ✗ (canceled Feb 15, not active Feb 28) | **$0** |
| 2026-03+ | ✗ | **$0** |

The cancel month is the first $0 month (not the month after).

### Edge 3 — Boundary cancellations

| Cancel timestamp | Counted in Dec? | Counted in Jan? | Why |
|---|---|---|---|
| 2025-12-31 23:59:59 | ✗ | ✗ | `canceled_at > LAST_DAY(Dec)` is FALSE; not active end-of-Dec |
| 2026-01-01 00:00:01 | ✓ | ✗ | `canceled_at > LAST_DAY(Dec)` is TRUE; active end-of-Dec, not Jan |

The boundary is **exclusive at end-of-month**. In practice cancellations
rarely land exactly at midnight UTC, so this rarely matters.

## Live-verified MRR series (against `mrr_dev`)

Computed by Convention A on the Sprint 1 seeded data (75 customers,
82 subscriptions including 17 tier-change pairs, 28 cancellations
spread across Dec 2025 – Apr 2026):

| month | mrr_amount |
|---|---|
| 2025-11-01 | **$2,700** |
| 2025-12-01 | **$5,450** |
| 2026-01-01 | **$5,900** |
| 2026-02-01 | **$6,700** |
| 2026-03-01 | **$6,950** ← peak |
| 2026-04-01 | **$6,700** |
| 2026-05-01 | **$6,700** |

Shape: ramps Nov → Mar peak as customers come online, then declines as
the Mar/Apr cancellations drop off (under Convention A their $0
contribution starts in their cancel month, so the dip is visible
immediately, not delayed by one month).

## What's NOT calculated (intentionally out of scope for v1)

- **Raw revenue** (sum of paid invoices) — that's a different signal;
  would query the `invoices` table, not `subscriptions`.
- **Expansion / contraction MRR** (separating tier upgrades from new
  customers) — would require comparing v0 → v1 amounts within a
  customer. Possible future enhancement.
- **Churn MRR as a separate line** — under Convention A, churn is
  implicit in the month-over-month decline. A churn breakdown would
  need to track *which* subs went from contributing to not-contributing.
- **Pro-rated MRR** — would distribute mid-month tier changes across
  days. We round to end-of-month for simpler semantics.
- **Multi-currency normalization** — query assumes USD only.
- **Streaming / real-time** — query is a batch snapshot, not an event
  stream.

## How to run it

### Via BigQuery Python SDK (used by the frontend's build script)

```python
from google.cloud import bigquery
client = bigquery.Client()
sql = open('sql/mrr_monthly.sql').read().replace(
    '${dataset}', f'{client.project}.mrr_dev'
)
for row in client.query(sql).result():
    print(row['month'], row['mrr_amount'])
```

### Via the `bq` CLI (if installed)

```bash
DATASET="${PROJECT}.mrr_dev"
sed "s/\${dataset}/$DATASET/g" sql/mrr_monthly.sql | \
  bq query --use_legacy_sql=false
```

### Against a different dataset

The SQL is parameterized via the `${dataset}` placeholder. Substitute
it with `<project>.<dataset_name>` before sending to BigQuery. The same
SQL works against any dataset that conforms to the schema in
`scripts/bq_sync/schema.py` (i.e., a dataset populated by
`scripts/sync_stripe_to_bq.py`).

## Test coverage

`scripts/tests/test_mrr_monthly_sql.py` contains 11 tests across two
layers:

- **Layer A (static analysis, 7 tests):** runs on every `pytest`
  invocation. Verifies the SQL file structure, header sections,
  `${dataset}` placeholder usage, status filter form, normalization
  formula presence, GENERATE_DATE_ARRAY usage, and that no DDL/DML
  statements have been added.
- **Layer B (live integration, 4 tests):** gated by
  `TEST_MRR_LIVE=1`. Runs the SQL against a real dataset (default
  `mrr_dev`), hand-verifies the canceled-customer rule (C-86), the
  tier-change rule (C-87), and the incomplete_expired exclusion (C-88).

Each Layer-B test runs an **independent recompute query** that re-derives
the expected value via a different SQL framing, then asserts exact-cent
match against the main query's output. This protects against the
regression class that bit Sprint 3 iter-1 (mocks accepted any value;
the bug only surfaced when numbers were independently checked).

To run live:

```bash
cd /Users/ilhoonlee/Projects/optisigns-assessment
set -a && source .env && set +a
cd scripts && source venv/bin/activate
TEST_MRR_LIVE=1 pytest tests/test_mrr_monthly_sql.py -v
```

## Iteration history (audit trail)

| Iteration | Cancel boundary | Status filter | Issue | Fix |
|---|---|---|---|---|
| iter-1 | `canceled_at >= first_day(M)` | `IN ('active','trialing','past_due')` | Excluded canceled subs from active months → undercount $1.4K – $3K/month | — (shipped buggy) |
| iter-2 | `canceled_at >= first_day(M)` | `NOT IN ('incomplete','incomplete_expired')` | Tier-change customers double-counted in transition months ($150 instead of $100) | — (shipped buggy) |
| **iter-3 (current)** | **`canceled_at > LAST_DAY(M)`** | `NOT IN ('incomplete','incomplete_expired')` | — | end-of-month snapshot eliminates double-count |

Each transition was driven by a real numerical bug surfaced by user
inspection of the data. Both iter-1 and iter-2 had unit tests that
"passed" but were dead — they ran the query and asserted only that it
returned 7 rows, not that the values were correct. iter-3 fixed the
tests as well: C-86 and C-87 now do independent recomputes and assert
exact-cent match against the main query output. Future regressions will
fail loudly.
