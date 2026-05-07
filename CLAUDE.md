# MRR Dashboard — Project Context

## What This Is

An ambitious **Monthly Recurring Revenue (MRR) dashboard** that ingests raw Stripe subscription data, calculates recurring revenue metrics, and presents them as a clear, trend-driven visualization.

**Stack:**
- **Data source:** Stripe (test mode for development, production-ready at launch)
- **ETL & transformation:** Python (scheduled sync pipeline) + BigQuery (warehousing)
- **BI & visualization:** React frontend with real-time dashboard widgets
- **Design:** Data-forward aesthetic inspired by modern analytics (high-contrast, readable typography, generous whitespace around key metrics)

## Architecture (30k ft view)

```
Stripe Subscriptions & Invoices
        ↓
    [Python ETL Script]
  (sync API calls → transform → validate)
        ↓
    Google BigQuery
  (time-series facts, dimensions)
        ↓
    React Dashboard
  (query via BigQuery API → display MRR trend, cohorts, churn)
```

## Why This Matters

Revenue visibility is critical for SaaS. Most founders use Stripe's built-in dashboard, but it lacks:
- Historical trend analysis (6m, 12m)
- Cohort-based churn and expansion
- Actionable alerts (MRR dropped? know why)
- Custom KPI dashboards per business model

This product fixes that.

## Execution Model

Built iteratively via the Claude Code harness. **Each sprint produces a testable slice of the product:**
- **Sprint 1** (THIS RUN): Data generation (Stripe Test Clocks, seeded customers, 6-month history)
- **Sprint 2**: BigQuery schema + ETL sync
- **Sprint 3**: MRR calculation logic (math + tests)
- **Sprint 4**: React dashboard (charts, tables, drill-down)
- **Sprint 5+**: Polish (export, alerts, observability)

Each sprint iterates on a contract with explicit acceptance criteria. The Generator implements; the Evaluator verifies.

## Key Constraints

- **Stripe Test Clocks:** 3 customers per clock max, 3 subscriptions per customer max → need to create 17–34 clocks to seed 50–100 customers
- **Time advancement:** Can jump up to 2x the billing period per call; must wait for `ready` status before next call
- **Payment failures:** Use `pm_card_chargeCustomerFail` token to create Past Due subscriptions
- **Idempotency:** Script must be safe to re-run without duplicating data

## Success = Shipped

A working React dashboard that answers: "What was my MRR last month? Last quarter? How does it trend?"
