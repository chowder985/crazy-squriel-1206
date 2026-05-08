/*
 * MRR Monthly Calculation Query — BigQuery Standard SQL
 *
 * =============================================================================
 * MRR DEFINITION
 * =============================================================================
 *
 * MRR (Monthly Recurring Revenue) is the NORMALIZED MONTHLY VALUE of active
 * recurring subscriptions. It is NOT a raw revenue sum; it is a calculated
 * metric that normalizes subscription prices to a monthly base regardless of
 * their actual billing interval.
 *
 * =============================================================================
 * NORMALIZATION FORMULA
 * =============================================================================
 *
 * For each subscription, we compute its monthly contribution as follows:
 *
 * IF interval = 'month':
 *   monthly_contribution = unit_amount_cents / interval_count / 100.0
 *
 *   Example:
 *   - interval='month', interval_count=1, unit_amount_cents=$1200 (in cents)
 *     → monthly_contribution = 120000 / 1 / 100.0 = $1200.00
 *   - interval='month', interval_count=2, unit_amount_cents=$2400 (in cents)
 *     → monthly_contribution = 240000 / 2 / 100.0 = $1200.00 (bilannual, normalized to monthly)
 *
 * IF interval = 'year':
 *   monthly_contribution = unit_amount_cents / 12 / interval_count / 100.0
 *
 *   Example:
 *   - interval='year', interval_count=1, unit_amount_cents=$120000 (in cents)
 *     → monthly_contribution = 120000 / 12 / 1 / 100.0 = $100.00
 *   - interval='year', interval_count=2, unit_amount_cents=$240000 (in cents)
 *     → monthly_contribution = 240000 / 12 / 2 / 100.0 = $100.00 (biannual, normalized to monthly)
 *
 * Other intervals (day, week, etc.) are EXCLUDED from MRR calculations via
 * the normalization logic (result is NULL and filtered out).
 *
 * =============================================================================
 * ACTIVE SUBSCRIPTION RULE
 * =============================================================================
 *
 * A subscription contributes to a given month M if AND ONLY IF all of the
 * following conditions are met:
 *
 * (1) Ever-activated check: status NOT IN ('incomplete', 'incomplete_expired')
 *     - Excludes subscriptions whose first invoice never finalized (those
 *       contribute $0 forever). Subs with status 'canceled' / 'past_due' /
 *       'unpaid' / 'paused' / 'active' / 'trialing' DO appear because the
 *       `canceled_at` boundary below bounds their contribution per-month.
 *
 *     History: Sprint 3 iter-1 used `status IN ('active','trialing','past_due')`
 *     here, which caused MRR to be undercounted by every canceled sub even in
 *     the months they were actively billing. Iter-2 corrects this — see the
 *     comment block on the active_subscriptions CTE for the bug details.
 *
 * (2) Start boundary: start_date <= last_day_of_month(M)
 *     - The subscription must have started on or before the last day of month M
 *
 * (3) Cancel boundary: canceled_at IS NULL OR canceled_at > first_day_of_month(M)
 *     - The subscription must either not be canceled, OR if canceled, the
 *       cancellation occurred AFTER the first day of month M (i.e., the sub
 *       was still active at the start of M and remained active for at least
 *       one day during M).
 *
 * Rationale: A subscription is "active for ANY day in the month" if it was alive
 * from the first day through the day it was canceled (or until month end if not canceled).
 * If canceled on day 5 of the month, it contributes (active days 1-4). If canceled
 * on the first day of the month, it does NOT contribute (no active days in M;
 * canceled at the boundary).
 *
 * =============================================================================
 * TIER-CHANGE HANDLING (Cancel-and-Recreate Pattern)
 * =============================================================================
 *
 * From Sprint 1 seeding: tier changes are implemented via "cancel and recreate."
 * When a customer upgrades or downgrades, we:
 * 1. Cancel the old subscription (v0) at a point in time
 * 2. Create a new subscription (v1) with the new price
 *
 * In BigQuery, this produces TWO DISTINCT ROWS in the subscriptions table:
 * - v0: stripe_subscription_id=sub_old, stripe_customer_id=cus_X, canceled_at=<date>, status='canceled'
 * - v1: stripe_subscription_id=sub_new, stripe_customer_id=cus_X, canceled_at=NULL, status='active'
 *
 * CRITICAL: The query treats EACH ROW INDEPENDENTLY using its own start_date and canceled_at.
 * We DO NOT deduplicate by stripe_customer_id. Each subscription row contributes separately:
 * - In months where v0 is active (start <= month-end AND canceled > month-start): v0 contributes
 * - In months where v1 is active (start <= month-end AND canceled IS NULL): v1 contributes
 * - In the month of cancellation of v0: v0 contributes (canceled_at on or after month-start)
 * - No month double-counts a single customer
 *
 * Example:
 *   v0: unit_amount_cents=5000, start='2025-11-01', canceled_at='2026-03-01'
 *   v1: unit_amount_cents=10000, start='2026-03-01', canceled_at=NULL
 *
 *   Nov 2025: v0 active (started then, not canceled) → contributes $50
 *   Dec 2025: v0 active (not canceled) → contributes $50
 *   Jan 2026: v0 active (not canceled) → contributes $50
 *   Feb 2026: v0 active (not canceled) → contributes $50
 *   Mar 2026: v0 contributes (canceled on 2026-03-01 >= 2026-03-01, so active for day 1)
 *             v1 contributes (started on 2026-03-01 <= 2026-03-31)
 *             → total from this customer = $50 + $100 = $150
 *   Apr 2026: v1 active (not canceled) → contributes $100
 *   May 2026: v1 active (not canceled) → contributes $100
 *
 * =============================================================================
 * INTERVAL LIMITATION
 * =============================================================================
 *
 * Non-monthly/yearly billing intervals (day, week, etc.) are EXCLUDED from
 * MRR calculations. The normalization formula returns NULL for these intervals,
 * and they are filtered out in the final aggregation.
 *
 * If your dataset contains subscriptions with day/week intervals that SHOULD
 * contribute to MRR, you MUST update this query to include a normalization
 * formula for those intervals (e.g., unit_amount_cents / days_in_month / interval_count / 100.0
 * for daily intervals).
 *
 * =============================================================================
 * DATASET PARAMETERIZATION
 * =============================================================================
 *
 * This query uses a template variable to specify the BigQuery dataset.
 * The template placeholder is ${dataset}, which defaults to 'mrr_dev'.
 *
 * Template variable: ${dataset}
 * Default value: mrr_dev
 * Usage in query: `${dataset}.subscriptions`, `${dataset}.customers`, etc.
 *
 * Example invocation via bq CLI:
 *   bq query --use_legacy_sql=false \
 *     < sql/mrr_monthly.sql
 *   (Uses default dataset 'mrr_dev')
 *
 * To use a different dataset, substitute before running:
 *   cat sql/mrr_monthly.sql | sed 's/${dataset}/my_custom_dataset/g' | \
 *     bq query --use_legacy_sql=false -
 *
 * Example invocation via Python google-cloud-bigquery:
 *   from google.cloud import bigquery
 *   client = bigquery.Client()
 *   query = open('sql/mrr_monthly.sql').read()
 *   # Substitute dataset placeholder if needed
 *   query = query.replace('${dataset}', f'{client.project}.my_dataset')
 *   results = client.query(query).result()
 *
 * =============================================================================
 * OUTPUT SCHEMA
 * =============================================================================
 *
 * month (DATE): First day of the calendar month (YYYY-MM-01)
 * mrr_amount (NUMERIC): Total MRR in USD for that month (zero if no active subs)
 *
 * Months are in ascending order (oldest to newest).
 * All months in the seed window are represented, even if mrr_amount = 0.00.
 *
 * =============================================================================
 */

WITH month_series AS (
  -- Generate the 7-month window: Nov 2025 through May 2026 inclusive
  SELECT month_start
  FROM UNNEST(
    GENERATE_DATE_ARRAY(
      DATE('2025-11-01'),
      DATE('2026-05-01'),
      INTERVAL 1 MONTH
    )
  ) AS month_start
),

active_subscriptions AS (
  -- Select subscriptions that ever activated. The end-of-active-period is
  -- determined per-month by `canceled_at` in the JOIN below, NOT by the
  -- current `status` column.
  --
  -- Sprint 3 iter-2 fix: the original filter
  --   WHERE status IN ('active','trialing','past_due')
  -- excluded subs whose CURRENT status is 'canceled' even from months when
  -- they were actively billing. With Sprint 1's seed (28 canceled subs),
  -- MRR was undercounted by $1,450-$2,950 per month for Nov-Mar; the
  -- "Mar/Apr/May plateau at $6,700" was an artifact of this bug. Corrected
  -- MRR shows the expected churn-driven decline post-March.
  --
  -- The correct filter excludes only never-activated statuses:
  --   - 'incomplete'         — first invoice never finalized
  --   - 'incomplete_expired' — Stripe gave up on the first invoice
  -- Subs that activated and later went canceled / past_due / unpaid /
  -- paused / trialing still appear in the months they were active because
  -- the `canceled_at > first_day(M)` rule in the JOIN bounds their
  -- contribution correctly.
  SELECT
    DATE(start_date) AS sub_start_date,
    CASE
      WHEN canceled_at IS NOT NULL THEN DATE(canceled_at)
      ELSE NULL
    END AS sub_canceled_date,
    status,
    unit_amount_cents,
    LOWER(`interval`) AS interval_type,
    interval_count
  FROM `${dataset}.subscriptions`
  WHERE status NOT IN ('incomplete', 'incomplete_expired')
),

monthly_contributions AS (
  -- For each month and each active subscription, compute the normalized contribution
  SELECT
    m.month_start,
    s.sub_start_date,
    s.sub_canceled_date,
    s.status,
    s.unit_amount_cents,
    s.interval_type,
    s.interval_count,
    CASE
      WHEN s.interval_type = 'month'
        THEN s.unit_amount_cents / s.interval_count / 100.0
      WHEN s.interval_type = 'year'
        THEN s.unit_amount_cents / 12.0 / s.interval_count / 100.0
      ELSE NULL
    END AS normalized_monthly_amount
  FROM month_series m
  CROSS JOIN active_subscriptions s
  WHERE
    -- Start boundary: subscription started on or before the last day of this month
    s.sub_start_date <= LAST_DAY(m.month_start)
    AND
    -- Cancel boundary: subscription either not canceled OR canceled on/after first day of month
    (s.sub_canceled_date IS NULL OR s.sub_canceled_date >= m.month_start)
),

final_aggregation AS (
  SELECT
    month_start AS month,
    COALESCE(SUM(normalized_monthly_amount), 0.00) AS mrr_amount
  FROM monthly_contributions
  -- Filter out non-monthly/yearly intervals (NULL normalized_monthly_amount)
  WHERE normalized_monthly_amount IS NOT NULL
  GROUP BY month_start
)

SELECT
  month,
  CAST(mrr_amount AS NUMERIC) AS mrr_amount
FROM final_aggregation
ORDER BY month ASC;
