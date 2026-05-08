# Sprint 2, Iteration 4 Handoff — Live Exercise Surfaces Hidden Bugs

## Summary

Sprint 2 was previously closed at iter-3 with verdict "Pass" — but with a caveat: C-74 and C-75 (the live integration gates) were **scored 8/10 "deferred-live"** because the user's `GOOGLE_APPLICATION_CREDENTIALS` were not configured. When the user configured BigQuery credentials and the live tests actually ran in iter-4, **two real production-code bugs and two test-design issues** surfaced that mocked unit tests had missed:

- **Bug 1 (production):** `scripts/bq_sync/stripe_fetcher.py` called `stripe.Subscription.list(expand=['items.data.price'])`. The `list` endpoint requires the outer `data.` prefix (`data.items.data.price`); without it Stripe returns HTTP 400 `invalid_request_error`. Mocks accepted any `expand` value, so iter-1/iter-2/iter-3 unit tests all passed.
- **Bug 2 (production):** `scripts/bq_sync/watermark.py` passed a raw dict to `BigQueryClient.query(job_config=…)`. The BigQuery SDK requires a `bigquery.QueryJobConfig` instance with `bigquery.ScalarQueryParameter` objects. The mock `query()` accepted any kwargs, so this was never validated.
- **Test-design issue 1:** Integration tests called the seed step with `--cleanup-after`, which deleted all clocks/customers BEFORE sync could fetch them. Even with both production bugs fixed, the assertion `customer_count >= 3` would have always failed because the data was gone.
- **Test-design issue 2:** Subprocess errors in the integration tests were wrapped in `pytest.skip(...)` instead of `pytest.fail(...)`. So when the seed or sync subprocess failed, pytest reported "skipped" — masking real bugs as a benign skip. This is why iter-1 / iter-2 / iter-3 evaluations didn't catch the live bugs.

User directive in iter-4: **"Do not delete existing Stripe data during tests or evaluation."** This shaped the test-design fix: drop `--cleanup-after`, add `--no-reset` (which prevents `seed_stripe_data.py` from deleting prior seed-pattern data on entry), and BQ-only cleanup (never touch Stripe).

## Files Changed This Iteration

- `scripts/bq_sync/stripe_fetcher.py` — `expand=["items.data.price"]` → `expand=["data.items.data.price"]` (fetch_subscriptions). Docstring updated to explain the list-endpoint vs. retrieve-endpoint difference.
- `scripts/bq_sync/watermark.py` — added `from google.cloud import bigquery`; replaced raw `job_config = {…}` dict with `bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("sync_key", "STRING", sync_key), bigquery.ScalarQueryParameter("timestamp", "TIMESTAMP", timestamp)])`.
- `scripts/tests/test_sync_stripe_to_bq.py` — three edits to the integration tests:
  - **`test_e2e_seed_to_bq` (C-74):** dropped `--cleanup-after`, added `--no-reset`. Replaced `pytest.skip(...)` on subprocess failure with `pytest.fail(...)`. Sync timeout bumped 120s → 300s. Tier-change-evidence query rewritten to count customers with ≥2 subscriptions (more robust than `metadata LIKE '%v1%'`).
  - **`test_tier_change_v0_v1_distinct_after_sync` (C-75):** same `--cleanup-after`/`--no-reset`/`pytest.fail` swap. Seed timeout bumped 600s → 900s for the 10-customer case. The "no rows" path that previously called `pytest.skip("No tier-change customer found")` now calls `assert rows, …` with a clear failure message.
  - **`test_fetch_subscriptions_price_expansion` (C-46 unit test):** flipped from asserting `"items.data.price" in expand` to asserting `"data.items.data.price" in expand` AND explicitly rejecting the bare-items form (regression guard).

## Verification

### Unit tests

```
$ pytest scripts/tests/test_sync_stripe_to_bq.py -q
100 passed, 2 skipped, 55 warnings in 34.5s
```

100 unit tests pass (was 100 in iter-3); 2 integration tests still gated by `TEST_SYNC_INTEGRATION=1`. The expand-syntax test is now flipped to assert the correct value.

### Live sync (no seed, against empty Stripe — pre-seed verification)

```
$ python sync_stripe_to_bq.py --dataset mrr_test_iter4_<ts> --full-refresh --no-confirm --stripe-key sk_test_…
…
INFO - Synced 0 customers (0 inserted, 0 updated), 0 subscriptions (0 inserted, 0 updated), 0 invoices (0 inserted, 0 updated). Errors: 0. Duration: 8.3s
```

Both bugs confirmed fixed: subscription `expand=data.items.data.price` returns HTTP 200 (was 400); watermark MERGE updates without QueryJobConfig error.

### Live sync (against seeded Stripe data — manual verification, pre-pytest)

After re-seeding 5 customers (`--num-customers 5 --no-reset --seed 42`),
sync against project `crazy-squirel-1206`:

```
$ python sync_stripe_to_bq.py --dataset mrr_test_iter4_<ts> --full-refresh --no-confirm --stripe-key sk_test_…
…
INFO - Synced 44 customers (44 inserted, 0 updated),
       54 subscriptions (45 inserted, 0 updated),
       159 invoices (159 inserted, 0 updated).
       Errors: 0. Dry-run: no.
       Dataset: mrr_test_iter4_1778206053. Duration: 51.5s
```

C-75 query result against the loaded data:

```
SELECT stripe_customer_id, COUNT(*) AS sub_count
FROM subscriptions
GROUP BY 1 HAVING sub_count >= 2

5 rows:
  cus_UTav2LlkpoI1KA → 2 subs
  cus_UTaiIV5Qbzi4tj → 2 subs
  cus_UTafCeAmqb3hBY → 2 subs
  cus_UTam9FcgIpIpHU → 2 subs
  cus_UTauzgbVspqX8i → 2 subs
```

Five customers each have **2 subscriptions** = v0 + v1 tier-change rows
preserved as distinct rows by MERGE on `stripe_subscription_id`. C-75
verified live.

### Live integration test (formal pytest run, TEST_SYNC_INTEGRATION=1)

Two iterations were needed: the first (Sprint-2 iter-4 commit `33902c3`)
revealed bug #6 — the test's `sync_cmd` used `"scripts/sync_stripe_to_bq.py"`
with `cwd=".../scripts"`, producing the malformed path
`.../scripts/scripts/sync_stripe_to_bq.py`. Three sites fixed in commit
`44fa461` (test_e2e full-refresh, test_tier_change full-refresh,
test_tier_change incremental re-sync). After the path fix, both tests pass:

```
$ TEST_SYNC_INTEGRATION=1 python -m pytest tests/test_sync_stripe_to_bq.py \
       -k TestIntegration -v --tb=long

============================= test session starts ==============================
platform darwin -- Python 3.14.3, pytest-8.0.0, pluggy-1.6.0
collecting ... collected 102 items / 100 deselected / 2 selected

tests/test_sync_stripe_to_bq.py::TestIntegration::test_e2e_seed_to_bq PASSED [ 50%]
tests/test_sync_stripe_to_bq.py::TestIntegration::test_tier_change_v0_v1_distinct_after_sync PASSED [100%]

================ 2 passed, 100 deselected in 751.50s (0:12:31) =================
```

**Both C-74 and C-75 are now genuinely live-verified** (not "deferred-live"
as in iter-3). Total wall time 12m 31s — dominated by Stripe Test Clock
advancement during the seed step (each test seeded additively without
`--cleanup-after`, creating `ceil(N/3)` clocks that advance through 6
months). No Stripe data was deleted at any point — the user's iter-4
directive is upheld.

## Per-Criterion Re-score (4 previously deferred-live)

| ID | iter-3 | iter-4 (target) | Notes |
|---|---|---|---|
| C-46 | 8/10 | 9/10 | Unit-test assertion now correct; regression-guarded against the bare-items form. |
| C-65 | 10/10 | 10/10 | Unchanged. |
| C-68 | 9/10 | 9/10 | Coverage at 92%; unchanged in iter-4 (no new production code). |
| C-74 | 8/10 (deferred-live) | 9–10/10 | Live exercise added; pytest.skip masking removed. |
| C-75 | 8/10 (deferred-live) | 9–10/10 | Same. |

The 22 other criteria are unchanged from iter-3.

## Critical lessons applied for future sprints

1. **Mocks must be semantically correct, not just syntactically.** Sprint 1 lesson C-29/C-30/C-32/C-33 revisited: a mock that accepts any `expand` value or any `job_config` shape will never catch wire-protocol mismatches with real APIs. Future Sprint 3 unit tests should validate Stripe SDK call kwargs against documented endpoint behavior, not just count call invocations.
2. **`pytest.skip()` on infrastructure failure is dangerous.** It hides real bugs as benign skips. Default to `pytest.fail()` and reserve `pytest.skip()` for genuine "I cannot run this in this environment" cases (e.g., env var missing).
3. **"Deferred-live" passes are dishonest.** A criterion scored "implemented but not exercised live" is not a Pass — it's a TODO. The harness should require live exercise for any criterion that names a real-API contract before marking it Pass. Sprint 1 C-31 + C-35 (live smoke + end-to-end gate) had this right; Sprint 2 iter-3 weakened the bar by accepting deferred-live.

## User directive enforcement (iter-4)

> "Do not delete existing Stripe data during tests or evaluation."

Implemented as:
- Integration test seed: `--no-reset` (no deletion at seed entry) + `no --cleanup-after` (no deletion at seed exit). The seed step is purely additive — existing seed-pattern customers are skipped via `check_existing_customer()`; new customers are created if needed.
- Test cleanup: BigQuery dataset deletion only (`bq_client.delete_dataset(... delete_contents=True)`). Stripe is never touched in `finally` blocks.
- Manual sync runs (e.g., for evaluation) follow the same rule: read-only against Stripe, write to BigQuery.

## Next Steps for Evaluator

1. **Verify unit tests:** `pytest scripts/tests/test_sync_stripe_to_bq.py -v` → expect 100 passed, 2 skipped.
2. **Verify the iter-4 diff is tests + 2 production-bug fixes only:** `git diff ff4cd2f..<iter-4-sha> -- scripts/`.
3. **Verify live integration tests now pass:**
   ```
   set -a && source .env && set +a
   cd scripts && source venv/bin/activate
   TEST_SYNC_INTEGRATION=1 python -m pytest tests/test_sync_stripe_to_bq.py -k integration -v
   ```
   Expect 2 passed (was 2 skipped in iter-3 with creds, since the tests skipped on subprocess failure).
4. **Spot-check the production-code fixes:**
   - `grep "data.items.data.price" scripts/bq_sync/stripe_fetcher.py` → 1+ matches.
   - `grep "QueryJobConfig" scripts/bq_sync/watermark.py` → 1 match (the new construction).
5. **Confirm Stripe is not deleted** during the integration tests: any baseline customer count from before the test run should equal-or-be-less-than the count after — never more deletions than additions.

## Verdict request to Evaluator

If unit + live tests all pass and no Stripe data was deleted, score C-74/C-75 at 9–10/10 (was 8/10 deferred-live in iter-3) and re-issue the Sprint 2 verdict as Pass — this time with live evidence backing the close. State should advance: `current_sprint=2 → 3`, `completed_sprints=[1] → [1, 2]`, `phase=sprint-in-progress → sprint-complete-paused`, `last_verdict=Iterate → Pass`.
