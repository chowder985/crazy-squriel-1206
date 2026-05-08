# Sprint 03 Contract — MRR Monthly Calculation

> **Purpose:** Bridge the spec's Sprint 3 user stories and the Evaluator's testable behaviors. Negotiated before any code is written.
> Both agents use this contract — no moving goalposts during evaluation.

---

## 1. Scope

**In scope:**
- Single BigQuery Standard SQL query file at project root: `sql/mrr_monthly.sql`
- Output schema: `(month DATE, mrr_amount NUMERIC)` where month is the first day of the calendar month (DATE type) and mrr_amount is USD dollars (no cents) as a NUMERIC type
- MRR definition: normalized monthly value of active recurring subscriptions (NOT raw revenue)
- Active subscription rule: subscription contributes to a month M if `status IN ('active', 'trialing', 'past_due')` AND `start_date ≤ DATE_TRUNC(M, MONTH) + INTERVAL 1 MONTH - INTERVAL 1 DAY` (last day of month M) AND (`canceled_at IS NULL OR canceled_at ≥ DATE_TRUNC(M, MONTH)`)
- Normalization logic: `unit_amount_cents / interval_count / 100.0` for monthly intervals; `unit_amount_cents / 12 / interval_count / 100.0` for yearly intervals
- Tier-change handling: subscriptions from Sprint 1 cancel-and-recreate tier changes (v0 and v1 subscription IDs for the same customer) are treated as distinct rows; both contribute to MRR per their own active periods (NO deduplication by stripe_customer_id)
- Dataset parameterization: query accepts a `@dataset` parameter (or templated `${dataset}` placeholder) to run against any seeded dataset (mrr_dev, mrr_test_*, etc.)
- Coverage: generates one output row per month across the seeded data range (~Nov 2025 through May 2026, ~6–7 months)
- No Stripe data mutations: Sprint 3 is read-only against BigQuery (no ETL, no syncing, no schema changes)

**Explicitly out of scope (deferred to Sprint 4+):**
- React dashboard consumption or visualization
- Expansion / churn / new MRR breakdowns (no cohort segmentation)
- Drill-down tables or filtering by tier / customer / cohort
- Materialized views or scheduled query orchestration
- Non-monthly intervals (day, week — filter or error explicitly; none in seeded data)
- Multi-currency handling (v1 assumes USD-only; non-USD rows filtered or error logged)

---

## 2. Definition of Done

A developer can run `sql/mrr_monthly.sql` against the `mrr_dev` BigQuery dataset (with the `@dataset` parameter set to `mrr_dev`) and obtain a table with:
- ≥6 rows (one per month in the seed window)
- Column structure: `month (DATE)`, `mrr_amount (NUMERIC)`
- Months in ascending order
- MRR amounts are non-negative (or zero for months with no active subs)
- Numbers match hand-verified calculations for at least one month (verified by Evaluator)

The Evaluator can independently run the query against `mrr_dev`, embed the full output table in the evaluation file, hand-verify the MRR for at least one month by writing a separate validating query, and confirm the numbers match to the nearest cent. Tier-change customers (v0 and v1 in the same month) both contribute their normalized amounts; canceled customers drop to $0 contribution the month after `canceled_at`. The query handles edge cases gracefully: if non-monthly/yearly intervals or non-USD subscriptions exist, the query documents its behavior (skip with warning row, or fail with clear error message) and the contract specifies the choice.

Sprint 4 can consume the output without further migrations (output is the schema expected by the React dashboard endpoint).

---

## 3. Affected Surfaces

| Layer | Files / paths | Net new vs change |
|---|---|---|
| SQL | `sql/mrr_monthly.sql` | new |
| Tests | `scripts/tests/test_mrr_monthly_sql.py` | new |
| Documentation | `sql/README.md` (optional inline header comment in .sql) | new |

---

## 4. Testable Criteria

| ID | Criticality | Behavior | Verification | Rubric Dimension |
|---|---|---|---|---|
| **C-76** | must | **File location & naming:** Query file exists at exactly `<project-root>/sql/mrr_monthly.sql` (case-sensitive). Path is relative to project root. | File system check: `test -f sql/mrr_monthly.sql`. Code review: git status. | Functionality |
| **C-77** | must | **Output schema:** Query returns exactly two columns in order: `month (DATE)`, `mrr_amount (NUMERIC)`. No extra columns, no column name aliases, no NULL markers. | Unit test: parse query, assert column count = 2, assert column names and types. Live execution: `bq query --format=csv <query>` shows header `month,mrr_amount`. | Functionality |
| **C-78** | must | **Dataset parameterization:** Query accepts `@dataset` parameter (BigQuery Standard SQL syntax) or templated `${dataset}` placeholder. Script does not hardcode dataset name; parameter defaults to `mrr_dev`. Example: `SELECT … FROM @dataset.subscriptions …` or `… FROM ${dataset}.subscriptions …`. | Code review: grep for `@dataset` or `${dataset}` in sql file; confirm no hardcoded `mrr_dev.subscriptions`. Unit test: render template with alternate dataset name; run against test dataset. | Functionality |
| **C-79** | must | **Month coverage (exactly 7 rows):** Running against `mrr_dev` produces exactly 7 rows of output (Nov 2025–May 2026 inclusive, per Sprint 1 seed window). Baseline from Sprint 2 iter-4: 44 customers, 82 subscriptions, 159 invoices seeded across this window with `start_date` ranging Nov 2025 to Jun 2026 (latest Jan); expect all 7 months to have ≥1 active subscription. If a month has zero active subs (unlikely), still output the row with mrr_amount=0.00. | Live execution: Evaluator runs query, counts rows. Assert count = 7. Assert months in ascending order, starting 2025-11-01, ending 2026-05-01. Assert all months output exactly one row, with no NULL amounts. | Functionality |
| **C-80** | must | **Active subscription rule exact:** Subscription contributes to month M if (a) `status IN ('active', 'trialing', 'past_due')`, (b) `start_date ≤ last_day_of_month(M)`, and (c) (`canceled_at IS NULL OR canceled_at ≥ first_day_of_month(M)`). Rationale: active for ANY day in the month. If subscription starts on day 15 of a month, it contributes; if canceled on day 5, it contributed through day 4, so no contribution from day 5 onward. | Code review: verify boundary logic in WHERE clause. Unit test: `test_subscription_active_on_any_day_in_month` creates mock subs with various start/canceled dates and asserts correct inclusion/exclusion. Live test: Evaluator hand-picks a known canceled customer from seeded data, verifies contribution in pre-cancel months is nonzero and post-cancel months is zero. | Functionality |
| **C-81** | must | **Normalization formula — monthly interval:** For `interval = 'month'` and `interval_count = N`, monthly contribution = `unit_amount_cents / N / 100.0` (converts cents → dollars, divides by interval count). Example: $100/month with interval_count=1 → $100. $100/2-months with interval_count=2 → $50. | Code review: assert formula in SQL CASE/WHEN or computed column. Unit test: `test_normalization_monthly` inserts mock subscription with unit_amount_cents=10000, interval='month', interval_count=1, asserts `mrr_amount = 100.00` in output. | Functionality |
| **C-82** | must | **Normalization formula — yearly interval:** For `interval = 'year'` and `interval_count = M`, monthly contribution = `unit_amount_cents / 12 / M / 100.0` (divides annual amount by 12 months, then by interval count). Example: $1200/year (interval_count=1) → $100/month. $2400/2-year (interval_count=2) → $100/month. | Code review: assert formula in SQL. Unit test: `test_normalization_yearly` inserts mock subscription with unit_amount_cents=120000, interval='year', interval_count=1, asserts `mrr_amount = 100.00` in output. If no yearly subs in seeded data, test should be conditional or use a synthetic row. | Functionality |
| **C-83** | must | **Tier-change v0/v1 both contribute:** Cancel-and-recreate tier changes from Sprint 1 produce two distinct subscription rows (v0 with old price, canceled; v1 with new price, active). Both rows are in the subscriptions table. The query must treat each row independently: if v0 was active in month 1–2 and v1 active in month 3–6, then month 2 has ONLY v0's contribution, month 3 has ONLY v1's contribution, and no month double-counts. NO deduplication by stripe_customer_id. | Unit test: `test_tier_change_v0_v1_independent_contribution` inserts mock customer with two subscriptions (same stripe_customer_id, different stripe_subscription_id): v0 unit_amount=5000, active in month 1–2, canceled on day 1 of month 3; v1 unit_amount=10000, starts month 3. Asserts month 2 mrr includes only v0 ($50), month 3 includes only v1 ($100). Live test: Evaluator queries seeded data for known tier-change customer (e.g., cus_UTav2LlkpoI1KA from Sprint 2 iter-4), verifies two subscriptions exist, spot-checks months where each sub is active. | Functionality |
| **C-84** | must | **Live numerical verification — Evaluator runs query & embeds output:** Evaluator executes `sql/mrr_monthly.sql` with `@dataset=mrr_dev` and embeds the full result table (all 7 rows with month and mrr_amount values) verbatim in the evaluation file. Result shows the raw SQL output, not summarized or reformatted. | Eval file MUST include a section like: `### SQL Execution Output\n\n\`\`\`\nmonth,mrr_amount\n2025-11-01,<value>\n...\n\`\`\``. Code review: grep evaluation file for this section. | Functionality |
| **C-85** | must | **Live numerical verification — hand-verify at least one month:** For at least one month M in the output, Evaluator independently computes the expected MRR by: (1) writing a separate validating query that selects all active subscriptions for month M and normalizes their contributions, (2) summing manually or via query, (3) recording the expected value, (4) comparing to the query output, (5) documenting in the eval file with all queries and arithmetic shown. Acceptable tolerance: exactly match to the nearest cent (no rounding tolerance; NUMERIC type handles precision). | Eval file MUST include a section like: `### Hand-Verification for Month YYYY-MM\n\nValidating query:\n\`\`\`sql\n...\n\`\`\`\n\nExpected subs:\n- sub_1: $X.XX\n- sub_2: $Y.YY\nTotal: $Z.ZZ\n\nActual output for month: $Z.ZZ\nMatch: YES (exact)`. Queries and arithmetic are shown; evaluator can reproduce the calculation. Eval file documents values to two decimal places. | Functionality |
| **C-86** | must | **Corroborating sanity test — canceled customer drops to $0:** Evaluator picks a known canceled customer from seeded data (one with `canceled_at` in the middle of the seed window, e.g., within Nov 2025–Apr 2026) from the 44-customer set. For the month in which the customer was canceled (month M where `canceled_at` falls in M), the customer's subscription MUST contribute (active for part of the month). For the month AFTER cancellation (month M+1), the contribution MUST be $0.00. Evaluator writes a query to verify this and documents the result in the eval file. Specific customer ID must be named (e.g., the stripe_customer_id of the chosen canceled sub). | Eval file MUST include a section like: `### Sanity Test: Canceled Customer Contribution\n\nCustomer: <stripe_customer_id>\nSubscription: <stripe_subscription_id>\nCanceled at: <YYYY-MM-DD HH:MM:SS UTC>\n\nMonth of cancel (e.g., 2026-02-01): MRR contribution = $X.XX (nonzero)\nMonth after cancel (e.g., 2026-03-01): MRR contribution = $0.00\nStatus: PASS/FAIL`. Query used and actual data shown. | Functionality |
| **C-87** | must | **Corroborating sanity test — tier-change contribution in different months:** Evaluator picks a known tier-change customer from seeded data (one with v0 + v1 subscriptions and different active periods, e.g., cus_UTav2LlkpoI1KA from Sprint 2 iter-4 eval). For one month where ONLY v0 is active and one month where ONLY v1 is active, verify that the monthly MRR totals match the individual subscription contributions (v0's normalized monthly amount in v0-only month, v1's normalized monthly amount in v1-only month). Evaluator writes separate queries for each month and documents in the eval file. | Eval file MUST include a section like: `### Sanity Test: Tier-Change v0/v1 Separate Contributions\n\nCustomer: <stripe_customer_id> (e.g., cus_UTav2LlkpoI1KA)\nv0 sub: <stripe_subscription_id> (canceled <YYYY-MM-DD HH:MM:SS>, unit_amount_cents=<cents>, interval='month', interval_count=1, monthly amount = $X.XX)\nv1 sub: <stripe_subscription_id> (active from <YYYY-MM-DD HH:MM:SS>, unit_amount_cents=<cents>, interval='month', interval_count=1, monthly amount = $Y.YY)\n\nMonth M (v0 active, v1 not): MRR contribution from this customer = $X.XX\nMonth M+1 (v1 active, v0 canceled): MRR contribution from this customer = $Y.YY\nStatus: PASS/FAIL`. Queries, unit_amount_cents, interval, interval_count, computed monthly amounts, and matching to MRR output are all shown. | Functionality |
| **C-88** | must | **Corroborating sanity test — incomplete_expired exclusion:** Sprint 2 iter-4 seeded data includes 10 `incomplete_expired` subscriptions (created but never paid, status='incomplete_expired'). These subs are in BigQuery but MUST NOT contribute to MRR (status is not in ('active', 'trialing', 'past_due')). Evaluator verifies that none of these 10 subscriptions appear in any month's MRR total (i.e., the query correctly filters them out). Documents the query and the status check in the eval file. | Eval file MUST include a section like: `### Sanity Test: incomplete_expired Exclusion\n\nIncomplete_expired subscriptions in seeded data:\n\nQuery:\n\`\`\`sql\nSELECT COUNT(*), SUM(unit_amount_cents) FROM @dataset.subscriptions WHERE status='incomplete_expired'\n\`\`\`\n\nResult: <count> subs, $0.00 total potential contribution\n\nVerification:\nSum of all MRR output rows (all 7 months): $<actual_total>\nSum of all active subscriptions (status IN ('active', 'trialing', 'past_due')): $<expected_total>\nMatch (all incomplete_expired correctly excluded): $<actual_total> == $<expected_total>\nStatus: PASS/FAIL`. Queries and cross-check shown. | Functionality |
| **C-90** | must | **Documentation header comment in .sql file:** `sql/mrr_monthly.sql` starts with a multi-line comment block (SQL standard `-- ...` or `/* ... */`) that explains: (1) **MRR definition:** "normalized monthly value of active recurring subscriptions"; (2) **normalization formula with examples:** "interval='month', unit_amount_cents=$1200, interval_count=2 → monthly contribution = $1200 / 2 / 100.0 = $6.00; interval='year', unit_amount_cents=$120000, interval_count=1 → monthly contribution = $120000 / 12 / 1 / 100.0 = $100.00"; (3) **active-period rule:** "subscription active if status IN ('active', 'trialing', 'past_due') AND start_date ≤ month-end AND (canceled_at IS NULL OR canceled_at ≥ month-start)"; (4) **parameter usage:** "@dataset parameter, defaults to mrr_dev; example: `@dataset.subscriptions`"; (5) **tier-change handling:** "Cancel-and-recreate tier changes produce distinct v0 and v1 rows; each contributes independently per its own start_date and canceled_at"; (6) **interval limitation:** "Non-monthly/yearly billing intervals (day, week) are excluded from MRR calculations. If your dataset contains such subscriptions and should contribute to MRR, this query must be updated." Future engineers should be able to read this comment and understand the math and constraints without external context. | Code review: grep first 150 lines of file for comment block; verify it covers all six points. Comment length: ≥20 lines. Test: comment parsing works (no SQL syntax errors from malformed comment). | Documentation |
| **C-91** | must | **No Stripe data mutations:** The SQL file is read-only against BigQuery. It does NOT contain CREATE TABLE, DROP TABLE, INSERT, UPDATE, DELETE, or any DDL/DML statement. Query is SELECT-only (and WITH clauses for CTEs allowed). No backend code invokes Stripe API mutations (no stripe.Subscription.create, stripe.Customer.delete, etc.) as part of Sprint 3 deliverable. | Code review: grep sql file for keyword patterns (CREATE, DROP, INSERT, UPDATE, DELETE, ALTER). Should find none (WITH is allowed). Grep Python test files for stripe.* mutations. Should find none in Sprint-3-specific code. Scope: only sprint-3 code; Sprint 2's ETL scripts are out of scope. | Functionality |

---

## 5. Negotiation Log

### Round 1 — Generator proposes (2026-05-08)

**Overview of approach:**

Sprint 3 is a single-query deliverable: `sql/mrr_monthly.sql` computes normalized monthly MRR from the BigQuery schema created in Sprint 2. The 16 criteria above cover:
- **Schema & structure (C-76, C-77, C-78):** File location, output columns, dataset parameterization.
- **Logic & correctness (C-79 through C-83):** Month coverage, active-subscription rule, normalization formulas (monthly + yearly), tier-change independence.
- **Live verification (C-84, C-85, C-86, C-87, C-88):** Evaluator must run the query, hand-verify output, add corroborating sanity tests per the project-wide rule in `feedback_live_verify_evaluation.md`.
- **Edge cases (C-89, C-90):** Non-monthly/yearly interval handling, documentation, read-only contract.
- **Compliance (C-91):** No Stripe mutations.

**Data baseline (from Sprint 2 iter-4):**
- 44 customers synced from Stripe test-mode
- 82 subscriptions (includes tier-change v0 + v1 rows and incomplete_expired statuses)
- 159 invoices
- Coverage: ~6 months (Nov 2025–May 2026, from test-clock seeding in Sprint 1)
- Mix: ~5 tier-change customers (2 subs each, v0+v1); rest single subscriptions; ~10 incomplete_expired (non-contributing)

**Criteria counts:**
- C-76 through C-91 = 16 criteria total (all `must`).
- Next-sprint C-count: C-92 onward (preserves monotonic ID sequence from Sprint 2).

**Threshold applied:** 7/10 per criterion (full-stack rubric, same as Sprint 1 + Sprint 2).

**Rubric dimensions used:**
- Functionality (12 criteria)
- Documentation (1 criterion)

---

## 6. Threshold Applied

- **Per-criterion threshold:** 7/10 (from grading rubric; standard for full-stack work)
- **Iteration cap:** 15 per sprint
- **Escalation:** If iteration cap is hit without all criteria ≥7/10, Generator writes escalation file halting the sprint

---

## 7. Rubric Selection

- [x] **Full-stack rubric** (SQL + Python tests, no UI)
- [ ] Frontend rubric (N/A — no UI in Sprint 3)
- [ ] Design Fidelity (N/A — no Figma design in Sprint 3)

### Rubric Dimensions Applied to Sprint 3

| Dimension | Applied? | Notes |
|---|---|---|
| **Functionality** | Yes | SQL correctness: schema, output shape, normalization logic, active-month rules, tier-change handling, dataset parameterization, read-only contract |
| **Code Quality** | Yes | SQL clarity: well-named columns, modular logic where applicable, no magic numbers (constants for dates, status strings), efficient query (reasonable cardinality) |
| **Robustness & Error Handling** | Yes | Edge cases: non-monthly/yearly intervals (handled explicitly per C-89), NULL timestamps, zero-contribution months (allowed to exist), canceled-subscription boundaries |
| **Security & Secrets** | No | N/A — no secrets or external API calls in Sprint 3 |
| **Documentation** | Yes | Header comment in SQL file explaining the formula, active-period rule, and parameter usage (C-90). Test file includes docstrings. |
| **Test Coverage** | Yes | Unit tests with mock data for normalization formulas (C-81, C-82), tier-change logic (C-83). Live-verify tests executed by Evaluator (C-84 through C-88). |
| **Frontend Quality** | No | N/A — no UI in Sprint 3 |
| **Design Fidelity** | No | N/A — no Figma design in Sprint 3 |

---

## 8. Round 2 — Evaluator review (2026-05-08)

### Overall Assessment

**Verdict:** Scope is too broad; some criteria are too vague; live-verify rule not yet strict enough; missing explicit verification targets. The 16 criteria should consolidate to ~11 final criteria. Recommend 3 rejections (merged), 4 revisions (tightened), and 1 new criterion (explicit tolerance + baseline range for MRR expectation).

**Summary:**
- **Accepted as-is:** C-76, C-77, C-78, C-80, C-81, C-82, C-83, C-84, C-90, C-91 (10 criteria)
- **Rejected:** C-79 (replaced with tighter baseline) (1 criterion → tightened to C-79 revised)
- **Revisions requested:** C-85 (tolerance spec), C-86 (named customer ID), C-87 (named customer + amounts), C-88 (narrowed), C-89 (Generator must choose approach explicitly)
- **New criteria added:** None (C-85's tolerance spec is promoted into the revision)
- **Final target:** 11 criteria after consolidation

### Accepted criteria (as-is, no changes needed)

**C-76, C-77, C-78, C-80, C-81, C-82, C-83, C-84, C-90, C-91** — all clear, testable, properly scoped.
- C-76 (file location): straightforward file system check.
- C-77 (output schema): schema validation via unit test and live execution.
- C-78 (dataset parameterization): grep + unit test covers both `@dataset` and `${dataset}` forms.
- C-80 (active subscription rule): boundary logic is precise; unit + live test paths are clear.
- C-81, C-82 (normalization formulas): formulas are explicit; unit tests with concrete numbers cover both intervals.
- C-83 (tier-change v0/v1): unit test structure and live test target (cus_UTav2LlkpoI1KA) are clear.
- C-84 (Evaluator runs query & embeds output): explicit "embed full table verbatim" requirement encodes the live-verify rule.
- C-90 (documentation header comment): all five points are clear; comment length requirement (≥15 lines) is testable.
- C-91 (read-only contract): keyword grep is straightforward; scope (Sprint 3 only) is clear.

### Revised criteria (tighten wording / add missing specificity)

**C-79 — Month coverage baseline strengthened:**

Original: "*Expected range: ~Nov 2025–May 2026 = 7 months, so ≥6 acceptable (in case Nov is sparse).*"

**Revised to:** "*Running against `mrr_dev` produces exactly 7 rows of output (Nov 2025–May 2026 inclusive, per Sprint 1 seed window). Baseline from Sprint 2 iter-4: 44 customers, 82 subscriptions, 159 invoices seeded across this window with `start_date` ranging Nov 2025 to Jun 2026 (latest Jan); expect all 7 months to have ≥1 active subscription. If November has zero active subs (unlikely), still output the row with mrr_amount=0.00.*"

**Rationale:** Original said "≥6 rows in case Nov is sparse" — too vague. The seeded data is deterministic (from Sprint 1 / Sprint 2). We know exactly which months should have active subs. Demand exactly 7 rows, and clarify that even months with zero active subs must output mrr_amount=0.00 (not NULL, not omitted). This matches the Definition of Done language ("one row per month in seed window").

---

**C-85 — Tolerance specification explicit (was buried in parenthetical):**

Original: "*Acceptable tolerance: ±$0.01 (rounding in NUMERIC vs floating-point).*"

**Revised to:** "*Acceptable tolerance: exactly match to the nearest cent (no rounding tolerance; NUMERIC type handles precision). Eval file documents the expected and actual values to two decimal places (e.g., $123.45, not $123.4 or $123).*"

**Rationale:** Original said "±$0.01 tolerance" but NUMERIC is arbitrary precision — there should be no rounding error. If there's a rounding mismatch, it's a bug, not a tolerance. Make the contract explicit: exact match. This aligns with the live-verify rule: hand-verified numbers must match the query output exactly.

---

**C-86 — Canceled customer identity must be named:**

Original: "*Evaluator picks a known canceled customer from seeded data (one with `canceled_at` in the middle of the seed window).*"

**Revised to:** "*Evaluator picks a known canceled customer from seeded data (one with `canceled_at` in the middle of the seed window, e.g., within Nov 2025–Apr 2026). ... Specific customer ID must be named (e.g., from the list of canceled-status subs in `mrr_dev`).*"

**Rationale:** Original left the customer ID choice to the Evaluator. But for reproducibility and future debugging, the contract should demand that the Evaluator **name the specific customer ID** in the eval file. This way, if a future iteration finds a bug, we can verify the exact sanity test. (Note: Sprint 2 iter-4 handoff lists specific tier-change customers like cus_UTav2LlkpoI1KA; we can infer a canceled-status customer from the 44-customer sync, but the Evaluator must query and name one.)

---

**C-87 — Tier-change customer and amounts must be explicit:**

Original: "*Evaluator picks a known tier-change customer from seeded data (one with v0 + v1 subscriptions and different active periods). For one month where ONLY v0 is active and one month where ONLY v1 is active, verify that the monthly MRR totals match the individual subscription contributions (v0's amount in v0-only month, v1's amount in v1-only month).*"

**Revised to:** "*Evaluator picks a known tier-change customer from seeded data (one with v0 + v1 subscriptions and different active periods, e.g., cus_UTav2LlkpoI1KA from Sprint 2 iter-4 eval). For one month where ONLY v0 is active and one month where ONLY v1 is active, verify that the monthly MRR totals match the individual subscription contributions (v0's normalized monthly amount in v0-only month, v1's normalized monthly amount in v1-only month). Evaluator writes separate queries for each month and documents in the eval file.*"

**Revised verification format:** *Eval file section must show specific unit_amount_cents, interval, interval_count for both v0 and v1, computed monthly amounts, and matching to the MRR output.*

**Rationale:** Same as C-86 — reproducibility and specificity. The contract now names cus_UTav2LlkpoI1KA (a known tier-change customer from Sprint 2) as an example, and demands the Evaluator document the actual amounts ($X.XX, $Y.YY) so the math is checkable. This prevents the Evaluator from skipping the test because they can't find a tier-change customer (Sprint 2 iter-4 confirmed 5 exist).

---

**C-88 — Simplified and clarified:**

Original: "*Sprint 2 iter-4 seeded data includes 10 `incomplete_expired` subscriptions (created but never paid, status='incomplete_expired'). These subs are in BigQuery but MUST NOT contribute to MRR (status is not in active set).*"

**Revised to:** "*Sprint 2 iter-4 seeded data includes 10 `incomplete_expired` subscriptions (created but never paid, status='incomplete_expired'). These subs are in BigQuery but MUST NOT contribute to MRR (status is not in ('active', 'trialing', 'past_due')). Evaluator verifies that none of these 10 subscriptions appear in any month's MRR total (i.e., the query correctly filters them out).*"

**Revised verification format:** *Eval file section shows COUNT(*) and SUM(unit_amount_cents) for status='incomplete_expired'; asserts both metrics are zero (no contribution). Then verifies that the sum of all MRR output rows equals the sum of ALL active subs, confirming incomplete_expired are not included.*

**Rationale:** Original was clear on the concept but lacked a concrete verification method. Revised gives the Evaluator a specific query path: count the incomplete_expired subs, assert zero total potential contribution, and cross-check against the overall MRR sum. This is a stronger sanity test.

---

**C-89 — Generator must choose approach and document explicitly:**

Original: "*The Generator chooses one approach; contract specifies the choice and Evaluator verifies the behavior.*"

**Revised to:** "*The Generator MUST choose one of two approaches and DOCUMENT THE CHOICE explicitly in the contract response (Round 3): (A) Fail fast — query fails with a clear error message if any non-monthly/yearly interval is encountered; OR (B) Skip silently — query includes a WHERE clause that skips non-monthly/yearly rows and produces no warning. Generator states the choice; Evaluator verifies the SQL implementation matches the stated choice.*"

**Rationale:** Original was vague about timing ("contract specifies the choice"). Revised makes it explicit: the Generator must state their choice IN THIS ROUND (Round 3), in the negotiation response. The Evaluator then verifies the choice was actually implemented. This prevents the Generator from implementing the query without deciding upfront, and ensures the Evaluator knows what to test for.

---

### Rejected criteria

**C-79 (original "Month coverage"):** REJECTED — replaced with revised C-79 (above, with exact row count of 7, not "≥6").

---

### New criteria proposed (Evaluator-added)

**None.** All Evaluator concerns are addressed via revisions to existing criteria.

---

### Notes for Generator

1. **Scope is appropriate after consolidation.** 16 original criteria consolidate to 11 final (3 merged away / revised). This is tight for a single SQL query + tests. The consolidation is non-trivial: C-79 demanded a clearer baseline; C-85/C-86/C-87/C-88/C-89 needed specificity to make live verification reproducible and unambiguous.

2. **Live-verify rule IS encoded, but relies on Generator + Evaluator collaboration.** C-84/C-85/C-86/C-87/C-88 collectively implement the live-verify rule from `feedback_live_verify_evaluation.md`. The Evaluator must run the query, hand-verify ≥1 month, add 4 sanity tests (canceled customer, tier-change, incomplete_expired, optionally non-interval edge case), and document all of it. The Generator's job is to write code that makes this possible; the Evaluator's job is to actually do it. The contract now makes this explicit at the criterion level.

3. **C-89 decision is time-sensitive.** The Generator must decide (Round 3 response) whether to fail-fast or skip-silently on non-interval data. Since Sprint 1 seeding used ONLY monthly intervals, and no yearly subs are expected in the current data, this is a future-proofing choice. Either approach is acceptable; the contract just demands clarity.

4. **C-79 baseline is deterministic, not probabilistic.** The original "expect 7 rows if data spans full Nov–May range" was weak because it implied uncertainty. Revised version names the exact range (Nov 2025–May 2026 = 7 months) and the exact source data (44 customers / 82 subscriptions from Sprint 2 iter-4). The Evaluator will simply run the query and confirm the count. No probabilistic language.

5. **C-85 exact-match tolerance is correct.** BigQuery NUMERIC is arbitrary precision. If there's a $0.01 mismatch, it's a logic bug (normalization formula off-by-one, subscription boundary mishandled, etc.), not rounding. The revised criterion makes this clear.

6. **C-86/C-87 customer IDs are reproducible.** Sprint 2 iter-4 eval lists specific tier-change customers (cus_UTav2LlkpoI1KA + 4 others) and we know there are canceled-status subs in the 44-customer set. By requiring the Evaluator to name the specific customer ID in the eval file, we ensure future iterations can re-check or debug the result. This is a key lesson from Sprint 2's "deferred-live" weakness: vague tests that can't be reproduced.

7. **C-88 cross-validation is stronger than C-86/C-87.** The incomplete_expired sanity test should also verify that the sum of all MRR output rows equals the sum of active subs only (excluding incomplete_expired). This is an additional cross-validation that was missing.

8. **Code Quality dimension should still apply.** The rubric selection lists "Code Quality" for SQL clarity. The Generator should ensure the SQL is readable: clear CTEs, named intermediate columns, comments on complex logic (e.g., the active-subscription date boundaries). This isn't a separate criterion but a quality bar across C-80/C-81/C-82/C-89/C-90.

---

### Awaiting Generator response (Round 3)

Please respond to the following by Round 3:

1. **Confirm acceptance** of all 10 accepted criteria (C-76, C-77, C-78, C-80, C-81, C-82, C-83, C-84, C-90, C-91).

2. **Confirm acceptance or push-back** on the 5 revised criteria (C-79, C-85, C-86, C-87, C-88, C-89).
   - If you disagree with a revision, state your objection and propose alternative wording.
   - If you accept a revision but think it's too strict, explain why and offer a compromise.

3. **State your choice for C-89** explicitly: **(A) Fail fast** on non-monthly/yearly intervals (query throws error), **OR (B) Skip silently** (WHERE clause filters them out). Document the choice in your Round 3 response so the Evaluator knows which behavior to test for.

4. **Confirm you understand the live-verify scope** (C-84 through C-88). These 5 criteria together demand:
   - Evaluator runs the query live and embeds the full output table.
   - Evaluator hand-verifies ≥1 month independently.
   - Evaluator runs 4 additional sanity tests (canceled customer, tier-change, incomplete_expired, non-interval edge case if needed).
   - All verification queries and actual output values are documented in the eval file.

5. **Confirm you're ready to accept Sprint 3 as 11 final criteria** (not 16 original). If you think the scope is still too broad, say so now before implementation; we can defer criteria to Sprint 4 (e.g., "yearly interval handling" could be mocked in Sprint 3 and live-tested in Sprint 4 once we seed yearly data).

---

## Round 3 — Generator response (2026-05-08)

**Overall posture:** Accept all 5 revisions unconditionally and confirm 10 as-is criteria. Choose **(B) Skip silently** for C-89 (non-monthly/yearly intervals). Final scope: 11 criteria (C-76 through C-88, C-90, C-91). Ready for implementation iteration-1.

### Acceptance of all 10 as-is criteria

Confirmed: **C-76, C-77, C-78, C-80, C-81, C-82, C-83, C-84, C-90, C-91** — all clear, testable, and properly scoped. No changes needed.

### Response to the 5 revisions requested

**C-79 (Month coverage baseline strengthened):** Accepted. The revised wording is precise: exactly 7 rows (Nov 2025–May 2026 inclusive), with all months outputting a row even if mrr_amount=0.00. This aligns perfectly with the deterministic seeded data and the Definition of Done language.

**C-85 (Tolerance specification explicit):** Accepted. Exact-match tolerance (nearest cent, no rounding tolerance) is correct for BigQuery NUMERIC arbitrary precision. Any $0.01 mismatch indicates a logic bug, not a precision issue. Eval file must show expected and actual values to two decimal places.

**C-86 (Canceled customer identity must be named):** Accepted. Requiring the Evaluator to name the specific stripe_customer_id in the eval file ensures reproducibility and future debugging. The 44-customer seeded set from Sprint 2 iter-4 includes canceled-status subscriptions; the Evaluator can query and identify one.

**C-87 (Tier-change customer and amounts must be explicit):** Accepted. Using cus_UTav2LlkpoI1KA (a known tier-change customer from Sprint 2 iter-4 eval, confirmed with 2 distinct subscriptions v0 + v1) as the canonical example strengthens the verification. Evaluator documents unit_amount_cents, interval, interval_count, and computed monthly amounts for both v0 and v1, making the math fully checkable.

**C-88 (Simplified and clarified):** Accepted. The revised verification method (COUNT(*) and SUM(unit_amount_cents) for status='incomplete_expired', then cross-check against overall MRR sum) is a strong sanity test. The contract clarifies that incomplete_expired subscriptions must contribute $0.00 to all months.

### Response to C-89 — Explicit edge-case choice: **(B) Skip silently**

**Choice:** **(B) Skip silently** — the query includes a WHERE clause that filters out non-monthly/yearly intervals (e.g., day, week) and produces no warning or error row.

**Reasoning:**
1. **Seeded data has zero day/week intervals:** Sprint 1 seeding and Sprint 2 ETL both used ONLY monthly and yearly billing intervals. The current `mrr_dev` dataset contains no day or week subscriptions, so the non-interval filter is dead code in the immediate Sprint 3 context.
2. **Fail-fast would break future datasets:** If a future project seeds in day/week intervals (e.g., for a free trial cohort), a fail-fast query would throw an error on otherwise-correct data. Skipping silently allows the query to remain valid across future datasets as long as the non-interval rows are not expected to contribute to MRR.
3. **Documentation comment (C-90) will note the limitation:** The SQL header comment will explicitly state: "Non-monthly/yearly billing intervals (day, week) are excluded from MRR calculations. If your dataset contains such subscriptions and should contribute to MRR, this query must be updated." This makes the design choice transparent to future engineers.
4. **WHERE clause is the standard pattern:** Filtering out unexpected statuses or intervals at the query level is the idiomatic approach in BI SQL; fail-fast (CASE with RAISE) is more typical for ETL pipelines, not read-only analytics queries.

**Evaluator verification:** The eval file will confirm that no unexpected rows appear in the MRR output against `mrr_dev`, validating that the skip-silently approach does not omit any data that should be included.

### Acceptance of 11-criterion final scope

Confirmed: Sprint 3 is 11 final criteria (**C-76 through C-88, C-90, C-91**; C-89 subsumed into C-79 via the skip-silently choice + C-90 documentation). This scope is tight for a single SQL query + unit/integration tests and aligns with the live-verify rule: Evaluator runs the query, hand-verifies ≥1 month, and adds 4 sanity tests. No scope deferral needed.

---

## Final Agreement (Sprint 3 — 11 criteria)

Both agents confirm agreement on the following 11 criteria. All criteria are specific, testable, and ready for implementation. The Generator will implement to satisfy each criterion's verification method; the Evaluator will grade each criterion at the per-criterion threshold of 7/10 using the rubric dimensions listed.

| ID | Criticality | Behavior | Verification | Rubric Dimension |
|---|---|---|---|---|
| **C-76** | must | **File location & naming:** Query file exists at exactly `<project-root>/sql/mrr_monthly.sql` (case-sensitive). Path is relative to project root. | File system check: `test -f sql/mrr_monthly.sql`. Code review: git status. | Functionality |
| **C-77** | must | **Output schema:** Query returns exactly two columns in order: `month (DATE)`, `mrr_amount (NUMERIC)`. No extra columns, no column name aliases, no NULL markers. | Unit test: parse query, assert column count = 2, assert column names and types. Live execution: `bq query --format=csv <query>` shows header `month,mrr_amount`. | Functionality |
| **C-78** | must | **Dataset parameterization:** Query accepts `@dataset` parameter (BigQuery Standard SQL syntax) or templated `${dataset}` placeholder. Script does not hardcode dataset name; parameter defaults to `mrr_dev`. Example: `SELECT … FROM @dataset.subscriptions …` or `… FROM ${dataset}.subscriptions …`. | Code review: grep for `@dataset` or `${dataset}` in sql file; confirm no hardcoded `mrr_dev.subscriptions`. Unit test: render template with alternate dataset name; run against test dataset. | Functionality |
| **C-79** | must | **Month coverage (exactly 7 rows):** Running against `mrr_dev` produces exactly 7 rows of output (Nov 2025–May 2026 inclusive, per Sprint 1 seed window). Baseline from Sprint 2 iter-4: 44 customers, 82 subscriptions, 159 invoices seeded across this window with `start_date` ranging Nov 2025 to Jun 2026 (latest Jan); expect all 7 months to have ≥1 active subscription. If a month has zero active subs (unlikely), still output the row with mrr_amount=0.00. | Live execution: Evaluator runs query, counts rows. Assert count = 7. Assert months in ascending order, starting 2025-11-01, ending 2026-05-01. Assert all months output exactly one row, with no NULL amounts. | Functionality |
| **C-80** | must | **Active subscription rule exact:** Subscription contributes to month M if (a) `status IN ('active', 'trialing', 'past_due')`, (b) `start_date ≤ last_day_of_month(M)`, and (c) (`canceled_at IS NULL OR canceled_at ≥ first_day_of_month(M)`). Rationale: active for ANY day in the month. If subscription starts on day 15 of a month, it contributes; if canceled on day 5, it contributed through day 4, so no contribution from day 5 onward. | Code review: verify boundary logic in WHERE clause. Unit test: `test_subscription_active_on_any_day_in_month` creates mock subs with various start/canceled dates and asserts correct inclusion/exclusion. Live test: Evaluator hand-picks a known canceled customer from seeded data, verifies contribution in pre-cancel months is nonzero and post-cancel months is zero. | Functionality |
| **C-81** | must | **Normalization formula — monthly interval:** For `interval = 'month'` and `interval_count = N`, monthly contribution = `unit_amount_cents / N / 100.0` (converts cents → dollars, divides by interval count). Example: $100/month with interval_count=1 → $100. $100/2-months with interval_count=2 → $50. | Code review: assert formula in SQL CASE/WHEN or computed column. Unit test: `test_normalization_monthly` inserts mock subscription with unit_amount_cents=10000, interval='month', interval_count=1, asserts `mrr_amount = 100.00` in output. | Functionality |
| **C-82** | must | **Normalization formula — yearly interval:** For `interval = 'year'` and `interval_count = M`, monthly contribution = `unit_amount_cents / 12 / M / 100.0` (divides annual amount by 12 months, then by interval count). Example: $1200/year (interval_count=1) → $100/month. $2400/2-year (interval_count=2) → $100/month. | Code review: assert formula in SQL. Unit test: `test_normalization_yearly` inserts mock subscription with unit_amount_cents=120000, interval='year', interval_count=1, asserts `mrr_amount = 100.00` in output. If no yearly subs in seeded data, test should be conditional or use a synthetic row. | Functionality |
| **C-83** | must | **Tier-change v0/v1 both contribute:** Cancel-and-recreate tier changes from Sprint 1 produce two distinct subscription rows (v0 with old price, canceled; v1 with new price, active). Both rows are in the subscriptions table. The query must treat each row independently: if v0 was active in month 1–2 and v1 active in month 3–6, then month 2 has ONLY v0's contribution, month 3 has ONLY v1's contribution, and no month double-counts. NO deduplication by stripe_customer_id. | Unit test: `test_tier_change_v0_v1_independent_contribution` inserts mock customer with two subscriptions (same stripe_customer_id, different stripe_subscription_id): v0 unit_amount=5000, active in month 1–2, canceled on day 1 of month 3; v1 unit_amount=10000, starts month 3. Asserts month 2 mrr includes only v0 ($50), month 3 includes only v1 ($100). Live test: Evaluator queries seeded data for known tier-change customer (e.g., cus_UTav2LlkpoI1KA from Sprint 2 iter-4), verifies two subscriptions exist, spot-checks months where each sub is active. | Functionality |
| **C-84** | must | **Live numerical verification — Evaluator runs query & embeds output:** Evaluator executes `sql/mrr_monthly.sql` with `@dataset=mrr_dev` and embeds the full result table (all 7 rows with month and mrr_amount values) verbatim in the evaluation file. Result shows the raw SQL output, not summarized or reformatted. | Eval file MUST include a section like: `### SQL Execution Output\n\n\`\`\`\nmonth,mrr_amount\n2025-11-01,<value>\n...\n\`\`\``. Code review: grep evaluation file for this section. | Functionality |
| **C-85** | must | **Live numerical verification — hand-verify at least one month:** For at least one month M in the output, Evaluator independently computes the expected MRR by: (1) writing a separate validating query that selects all active subscriptions for month M and normalizes their contributions, (2) summing manually or via query, (3) recording the expected value, (4) comparing to the query output, (5) documenting in the eval file with all queries and arithmetic shown. Acceptable tolerance: exactly match to the nearest cent (no rounding tolerance; NUMERIC type handles precision). | Eval file MUST include a section like: `### Hand-Verification for Month YYYY-MM\n\nValidating query:\n\`\`\`sql\n...\n\`\`\`\n\nExpected subs:\n- sub_1: $X.XX\n- sub_2: $Y.YY\nTotal: $Z.ZZ\n\nActual output for month: $Z.ZZ\nMatch: YES (exact)`. Queries and arithmetic are shown; evaluator can reproduce the calculation. Eval file documents values to two decimal places. | Functionality |
| **C-86** | must | **Corroborating sanity test — canceled customer drops to $0:** Evaluator picks a known canceled customer from seeded data (one with `canceled_at` in the middle of the seed window, e.g., within Nov 2025–Apr 2026) from the 44-customer set. For the month in which the customer was canceled (month M where `canceled_at` falls in M), the customer's subscription MUST contribute (active for part of the month). For the month AFTER cancellation (month M+1), the contribution MUST be $0.00. Evaluator writes a query to verify this and documents the result in the eval file. Specific customer ID must be named (e.g., the stripe_customer_id of the chosen canceled sub). | Eval file MUST include a section like: `### Sanity Test: Canceled Customer Contribution\n\nCustomer: <stripe_customer_id>\nSubscription: <stripe_subscription_id>\nCanceled at: <YYYY-MM-DD HH:MM:SS UTC>\n\nMonth of cancel (e.g., 2026-02-01): MRR contribution = $X.XX (nonzero)\nMonth after cancel (e.g., 2026-03-01): MRR contribution = $0.00\nStatus: PASS/FAIL`. Query used and actual data shown. | Functionality |
| **C-87** | must | **Corroborating sanity test — tier-change contribution in different months:** Evaluator picks a known tier-change customer from seeded data (one with v0 + v1 subscriptions and different active periods, e.g., cus_UTav2LlkpoI1KA from Sprint 2 iter-4 eval). For one month where ONLY v0 is active and one month where ONLY v1 is active, verify that the monthly MRR totals match the individual subscription contributions (v0's normalized monthly amount in v0-only month, v1's normalized monthly amount in v1-only month). Evaluator writes separate queries for each month and documents in the eval file. | Eval file MUST include a section like: `### Sanity Test: Tier-Change v0/v1 Separate Contributions\n\nCustomer: <stripe_customer_id> (e.g., cus_UTav2LlkpoI1KA)\nv0 sub: <stripe_subscription_id> (canceled <YYYY-MM-DD HH:MM:SS>, unit_amount_cents=<cents>, interval='month', interval_count=1, monthly amount = $X.XX)\nv1 sub: <stripe_subscription_id> (active from <YYYY-MM-DD HH:MM:SS>, unit_amount_cents=<cents>, interval='month', interval_count=1, monthly amount = $Y.YY)\n\nMonth M (v0 active, v1 not): MRR contribution from this customer = $X.XX\nMonth M+1 (v1 active, v0 canceled): MRR contribution from this customer = $Y.YY\nStatus: PASS/FAIL`. Queries, unit_amount_cents, interval, interval_count, computed monthly amounts, and matching to MRR output are all shown. | Functionality |
| **C-88** | must | **Corroborating sanity test — incomplete_expired exclusion:** Sprint 2 iter-4 seeded data includes 10 `incomplete_expired` subscriptions (created but never paid, status='incomplete_expired'). These subs are in BigQuery but MUST NOT contribute to MRR (status is not in ('active', 'trialing', 'past_due')). Evaluator verifies that none of these 10 subscriptions appear in any month's MRR total (i.e., the query correctly filters them out). Documents the query and the status check in the eval file. | Eval file MUST include a section like: `### Sanity Test: incomplete_expired Exclusion\n\nIncomplete_expired subscriptions in seeded data:\n\nQuery:\n\`\`\`sql\nSELECT COUNT(*), SUM(unit_amount_cents) FROM @dataset.subscriptions WHERE status='incomplete_expired'\n\`\`\`\n\nResult: <count> subs, $0.00 total potential contribution\n\nVerification:\nSum of all MRR output rows (all 7 months): $<actual_total>\nSum of all active subscriptions (status IN ('active', 'trialing', 'past_due')): $<expected_total>\nMatch (all incomplete_expired correctly excluded): $<actual_total> == $<expected_total>\nStatus: PASS/FAIL`. Queries and cross-check shown. | Functionality |
| **C-90** | must | **Documentation header comment in .sql file:** `sql/mrr_monthly.sql` starts with a multi-line comment block (SQL standard `-- ...` or `/* ... */`) that explains: (1) **MRR definition:** "normalized monthly value of active recurring subscriptions"; (2) **normalization formula with examples:** "interval='month', unit_amount_cents=$1200, interval_count=2 → monthly contribution = $1200 / 2 / 100.0 = $6.00; interval='year', unit_amount_cents=$120000, interval_count=1 → monthly contribution = $120000 / 12 / 1 / 100.0 = $100.00"; (3) **active-period rule:** "subscription active if status IN ('active', 'trialing', 'past_due') AND start_date ≤ month-end AND (canceled_at IS NULL OR canceled_at ≥ month-start)"; (4) **parameter usage:** "@dataset parameter, defaults to mrr_dev; example: `@dataset.subscriptions`"; (5) **tier-change handling:** "Cancel-and-recreate tier changes produce distinct v0 and v1 rows; each contributes independently per its own start_date and canceled_at"; (6) **interval limitation:** "Non-monthly/yearly billing intervals (day, week) are excluded from MRR calculations. If your dataset contains such subscriptions and should contribute to MRR, this query must be updated." Future engineers should be able to read this comment and understand the math and constraints without external context. | Code review: grep first 150 lines of file for comment block; verify it covers all six points. Comment length: ≥20 lines. Test: comment parsing works (no SQL syntax errors from malformed comment). | Documentation |
| **C-91** | must | **No Stripe data mutations:** The SQL file is read-only against BigQuery. It does NOT contain CREATE TABLE, DROP TABLE, INSERT, UPDATE, DELETE, or any DDL/DML statement. Query is SELECT-only (and WITH clauses for CTEs allowed). No backend code invokes Stripe API mutations (no stripe.Subscription.create, stripe.Customer.delete, etc.) as part of Sprint 3 deliverable. | Code review: grep sql file for keyword patterns (CREATE, DROP, INSERT, UPDATE, DELETE, ALTER). Should find none (WITH is allowed). Grep Python test files for stripe.* mutations. Should find none in Sprint-3-specific code. Scope: only sprint-3 code; Sprint 2's ETL scripts are out of scope. | Functionality |

**Final agreement reached. All 11 criteria are specific, testable, and ready for implementation. Generator proceeding to Sprint 3 iteration-1 implementation.**

---

## Round 4 — Evaluator sign-off (2026-05-08)

### Confirmation of Final Agreement

Evaluator has reviewed the entire contract end-to-end, including Round 1 (Generator initial proposal), Round 2 (Evaluator's detailed review with 5 revisions + 10 acceptances), and Round 3 (Generator's unconditional acceptance of all revisions and explicit choice of **(B) Skip silently** for non-interval handling).

**All Round 2 revisions have been resolved:**
- ✓ C-79: Month coverage baseline tightened to exactly 7 rows with zero-MRR output for sparse months.
- ✓ C-85: Tolerance specification corrected to exact-match (nearest cent), reflecting BigQuery NUMERIC arbitrary precision.
- ✓ C-86: Canceled customer identity requirement now enforces naming specific stripe_customer_id in eval file.
- ✓ C-87: Tier-change verification now names canonical example (cus_UTav2LlkpoI1KA) and demands explicit unit_amount_cents, interval, interval_count documentation.
- ✓ C-88: incomplete_expired sanity test strengthened with COUNT/SUM cross-validation against overall MRR sum.
- ✓ C-89 → C-90: Non-monthly/yearly interval handling choice documented as (B) Skip silently, with explicit comment in C-90's documentation header covering the limitation.

### Acknowledgment of Final Agreement

**15 testable criteria signed off:** C-76 through C-88, C-90, C-91. (Note: C-89 as a standalone criterion has been merged into C-90's documentation comment. Generator's Round 3 stated "11 final criteria," but the table enumerates 15 rows; this is a counting discrepancy in the narrative, not a substantive issue — the 15 criteria are all distinct, specific, and properly scoped.)

Live-verify rule compliance per project memory:
- ✓ C-84 (Evaluator runs query live, embeds full output table)
- ✓ C-85 (Evaluator hand-verifies ≥1 month with independent SQL query, exact-cent tolerance)
- ✓ C-86 (Evaluator tests canceled customer contribution boundary, names specific customer ID)
- ✓ C-87 (Evaluator tests tier-change v0/v1 independent contributions, names customer + documents amounts)
- ✓ C-88 (Evaluator tests incomplete_expired exclusion with COUNT/SUM cross-check)

### Extra-rigorous verification commitment

During the evaluation phase, I will apply heightened scrutiny to the following criteria, given their centrality to the contract:

- **C-85 (exact-cent hand-verification):** I will compute expected MRR for at least two months (not just one) using independent SQL queries and cross-check arithmetic manually. Any discrepancy >$0.00 is a hard fail; I will not round or grant tolerance.
- **C-79 (exactly 7 rows):** I will verify the output contains exactly 7 rows with no NULL amounts, and that all months (even zero-MRR months) are represented as `mrr_amount=0.00`, not omitted.
- **C-87 (tier-change amounts explicit):** I will verify that the Generator's implementation correctly isolates v0 and v1 contributions for cus_UTav2LlkpoI1KA and document the specific unit_amount_cents values from BigQuery in my eval file.

**Contract locked. Generator proceeding to Sprint 3 iteration-1 implementation.**
