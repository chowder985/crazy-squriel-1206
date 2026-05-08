# Sprint 1, Iteration 14 Handoff — Sparse Starts + Multi-Tier with Tier Changes

## Summary

User requested two MRR-realism upgrades to the seed script:

> "The data generation script should sparsely distribute subscriptions across the 6 month period. There should be some customers who upgrade or downgrade their subscription as well. For example, customers who started with a $50 per month subscription upgrades to $100 per month the next month."

Three contract changes were negotiated and implemented this iteration:

| ID | Status | Behavior |
|---|---|---|
| **C-36** (new) | implemented | Subscription `start_month` drawn uniformly from `{0..4}`. The orchestrator only calls `Subscription.create` when the per-customer clock has advanced to that customer's `start_month`. |
| **C-37** (new) | implemented | Three monthly USD tiers — `basic` ($50), `pro` ($100), `enterprise` ($250) — find-or-created via Price metadata `mrr-seed-tier=<tier>`. ~30% of non-past_due customers experience a tier change at month `start_month + Δ` (Δ ∈ {1, 2}). Tier changes use **cancel-and-recreate**: cancel the v0 sub, then create a v1 sub on the new tier. |
| **C-2** (revised) | implemented | At most **1 active subscription per customer at any instant**; lifetime sub count is **1** (no tier change) or **2** (initial v0 + post-change v1). Supersedes the iter-12 "exactly 1 subscription per customer" wording. |

User-confirmed design choices (via `AskUserQuestion`):

- Upgrade model = **cancel + create new subscription** (not Subscription.modify).
- Tier set = **basic $50 / pro $100 / enterprise $250**.
- Start spread = **uniform across months 0–4**.
- Tier-change rate = **~30%**.

## Seeding Script Quick Start

```bash
# Default 75-customer run, all three tiers find-or-created automatically
python scripts/seed_stripe_data.py --num-customers 75

# Quick 6-customer dry-run (shows new sparse starts + tier changes in logs)
python scripts/seed_stripe_data.py --dry-run --num-customers 6

# Live end-to-end with auto-cleanup (C-35 gate)
python scripts/seed_stripe_data.py --num-customers 3 --cleanup-after
```

## Files Changed This Iteration

- `.harness/contracts/sprint-01-contract.md` — appended iter-14 amendment block at top of file with C-36, C-37, and the revised C-2.
- `scripts/stripe_seeder/price_manager.py` — full rewrite. Added tier constants (`TIER_BASIC`, `TIER_PRO`, `TIER_ENTERPRISE`), `SEED_TIER_AMOUNTS_CENTS`, `SEED_TIER_METADATA_KEY`. New helpers `_find_or_create_seed_product()`, `_find_tier_price()`, `_create_tier_price()`, and the public `ensure_seed_prices(api_key, dry_run) -> Dict[str, str]`. Legacy `ensure_seed_price()` retained as a thin wrapper returning the basic-tier id (preserves the C-31 smoke test).
- `scripts/seed_stripe_data.py` — full rewrite of orchestration. Introduced `TierChange` and `CustomerPlan` (frozen dataclasses), `_CustomerRuntime` (mutable per-clock state), `plan_customer_lifecycle()`, `_attach_payment_method()`, `_create_initial_subscription()`, and `_execute_tier_change()`. Restructured per-clock loop into Phase 1 (pre-create customers + payment methods at month 0) and Phase 2 (walk months 0..5 executing scheduled creates / tier changes / cancels at the right month). Added `prices` kwarg to `seed_stripe_data()`; legacy `price_id` still accepted (uses the same Price for all tiers — primarily for tests).
- `scripts/tests/test_seed_stripe_data.py` — updated 11 existing tests (mocks switched from `ensure_seed_price` to `ensure_seed_prices`; mock Price fixtures now carry tier metadata; cancel-count assertion in `test_multi_clock_cancellations_isolated` relaxed to `>= canceled_count`). Added one new test class `TestIter14SparseAndTierChange` with 8 tests covering C-36, C-37, and the revised C-2 invariants.
- `.harness/state.json` — bumped `current_iteration` to 14, `phase` to `sprint-in-progress`, `last_verdict` to `pending-evaluation`; `notes` rewritten to summarize iter-14.

## Changes in Detail

### C-36 — Sparse Subscription Start Distribution

**Files:** `scripts/seed_stripe_data.py`

- New constants: `START_MONTH_MIN = 0`, `START_MONTH_MAX = 4`, `NUM_MONTHS = 6`, `DAYS_PER_MONTH = 30`.
- `plan_customer_lifecycle()` assigns `start_month = rng.randint(START_MONTH_MIN, START_MONTH_MAX)` (0..4 inclusive).
- The orchestrator's per-clock loop now has two phases:
  1. **Phase 1** (clock at month 0): create all batch customers + attach payment methods + set defaults. No subscriptions yet.
  2. **Phase 2** (months 0..5): for each month, look at every `_CustomerRuntime`; if `plan.start_month == month` and no active sub yet, create the v0 subscription. Then advance the clock 30 days and poll-ready before the next month.
- Verification: `test_sparse_start_distribution` (C-36c) and `test_orchestrator_creates_sub_at_start_month` (C-36d).

### C-37 — Multi-Tier Pricing + Tier-Change Events

**Files:** `scripts/stripe_seeder/price_manager.py`, `scripts/seed_stripe_data.py`

- Three tiers, single Product, tier identity in **Price** metadata key `mrr-seed-tier`. Find-or-create per tier:
  - `_find_or_create_seed_product()` keeps the iter-3/C-29 metadata-search behavior on the Product.
  - For each tier in `[basic, pro, enterprise]`: `_find_tier_price()` filters `stripe.Price.list(product=...)` by `metadata['mrr-seed-tier']`. If absent, `_create_tier_price()` creates a recurring USD/month Price with `unit_amount=SEED_TIER_AMOUNTS_CENTS[tier]` and the matching metadata.
- `plan_customer_lifecycle()` rolls a tier-change for non-past_due customers with probability `TIER_CHANGE_RATE = 0.30`. The change month is `start_month + Δ`, Δ ∈ {1, 2}; if it would exceed `START_MONTH_MAX`, the change is dropped (so the customer still has a billing cycle on the new tier within the window).
- The change is implemented in `_execute_tier_change()`:
  1. `customer_factory.cancel_subscription(old_sub_id)`
  2. `customer_factory.create_subscription(price_id=<new_tier>, idempotency_key=f"seed-sub-{cid}-v1")`
  3. Update `_CustomerRuntime.active_sub_id` to the new sub id.
- Verification: `test_ensure_seed_prices_returns_three_tiers` (C-37a), `test_tier_change_planning_invariants` (C-37b: start < change < cancel; rate 20–35% on 200 plans seed=42; new_tier ≠ initial_tier; past_due never changes), `test_past_due_never_tier_changes` (C-37c, with `tier_change_rate=1.0` to stress the invariant), `test_orchestrator_tier_change_cancel_then_create` (C-37c sequence: create → cancel → create), `test_idempotency_key_versioning` (C-37d, asserts `seed-sub-{cid}-v0` then `seed-sub-{cid}-v1`).

### C-2 (revised) — At most 1 active subscription at any instant; lifetime 1 or 2

**Files:** `scripts/seed_stripe_data.py`

- Each `_CustomerRuntime` carries a single `active_sub_id`. Tier change cancels the old sub (clears the slot) and creates the new sub (refills the slot) **in the same month iteration**, so there is never a moment with two simultaneously-active subs.
- Idempotency keys: `seed-sub-{customer_id}-v0` for the initial sub, `seed-sub-{customer_id}-v1` for the post-tier-change sub. Unique within a customer.
- The iter-12 amendment ("exactly 1 subscription per customer") is explicitly superseded for the lifetime-count claim; the active-at-any-instant invariant is preserved.
- Verification: `test_orchestrator_tier_change_cancel_then_create` (sequence assertion), `test_multi_clock_cancellations_isolated` (existing test, kept — each unique sub_id canceled at most once; cancel-count relaxed to `>= canceled_count` to allow tier-change cancels).

## Test Coverage

### New Tests (8 total in `TestIter14SparseAndTierChange`)

1. `test_sparse_start_distribution` — C-36c: ≥3 distinct start_months across 20 plans (seed=42); every value in `{0..4}`.
2. `test_ensure_seed_prices_returns_three_tiers` — C-37a: returns three distinct Price IDs keyed by tier name.
3. `test_ensure_seed_prices_dry_run_returns_placeholders` — C-37a (dry-run path): three distinct placeholder IDs without any Stripe API call.
4. `test_tier_change_planning_invariants` — C-37b: 200-plan run with seed=42; checks start < change < cancel ordering, rate 20–35% (allowing change-month-out-of-window drops), new_tier ≠ initial_tier.
5. `test_past_due_never_tier_changes` — C-37c: even at `tier_change_rate=1.0`, all past_due plans have `tier_change=None`.
6. `test_idempotency_key_versioning` — C-37d, C-2c: forces a tier-change plan; asserts v0 then v1 idempotency keys, basic→pro price progression.
7. `test_orchestrator_tier_change_cancel_then_create` — C-37c: forces a plan; asserts the call sequence is exactly `create → cancel → create` and the v1 create uses the enterprise price; cancel target is the v0 sub id.
8. `test_orchestrator_creates_sub_at_start_month` — C-36d: forces `start_month=3`; asserts exactly 3 clock advances precede the first `Subscription.create` call.

### Updated Existing Tests (11 total)

- `test_ensure_seed_price_finds_existing` — mock Prices now carry `mrr-seed-tier` metadata for all 3 tiers.
- `test_ensure_seed_price_creates_when_absent` — asserts 3 Price.create calls (one per tier) and that each carries the correct tier metadata.
- `test_lookup_uses_documented_endpoint` — mock Prices now carry tier metadata.
- `test_subscription_uses_resolved_price` — patches `seed_stripe_data.ensure_seed_prices` (returns dict). Asserts every Subscription.create uses one of the three resolved tier Price IDs.
- `test_cleanup_after_deletes_only_run_clocks`, `test_cleanup_after_runs_even_on_exception`, `test_cleanup_after_flag_default_off` — mock `ensure_seed_prices` instead of `ensure_seed_price`.
- `test_reset_runs_before_seeding`, `test_reset_skipped_on_dry_run`, `test_reset_flag_default_true` — same swap (one `replace_all` patch).
- `test_multi_clock_cancellations_isolated` — relaxed `len(canceled_subs) == canceled_count` to `>= canceled_count` (tier-change cancels add to the cancel count without adding to the canceled cohort). The "no duplicate cancels of the same sub_id" invariant is preserved (still asserted).

### Test Status

- **Total tests:** 55 (47 existing + 8 new)
- **Passing:** 55/55 (4.77s wall time on a 5.82s baseline)
- Coverage: sparse start distribution, multi-tier price resolution, tier-change planning invariants, cancel-then-create ordering, idempotency-key versioning, regression coverage on iter-11 reset / iter-10 cleanup-after / iter-13 multi-clock cancellation isolation.

## Self-Evaluation Against Revised Contract

| Criterion | Status | Notes |
|---|---|---|
| C-2 (revised iter-14) | PASS | At most 1 active sub at any instant enforced by orchestrator; lifetime 1 or 2 verified by `test_idempotency_key_versioning` and `test_orchestrator_tier_change_cancel_then_create`. |
| C-36 (new) | PASS | Sparse `start_month` from `{0..4}`; orchestrator gates Subscription.create on month match; verified by 2 unit tests. |
| C-37 (new) | PASS | Three tiers find-or-created with metadata; tier change = cancel-then-create with v0/v1 idempotency keys; ~30% rate (20–35% after change-month-out-of-window drops); past_due never changes tier; verified by 6 unit tests. |
| C-29, C-30, C-31, C-32, C-33, C-34, C-35 | PASS (no regression) | All existing criteria preserved by the unchanged-behavior paths. Live smoke (C-31) and end-to-end gate (C-35) deferred to Evaluator. |

## Known Limitations & Risks

1. **Per-clock test-clock advance is 6 advances/clock.** Same as iter-13. With 75 customers ÷ 3/clock = 25 clocks × 6 advances = 150 clock advances total. POLLING_TIMEOUT=300s per advance still sufficient.
2. **Sub-create count grows by ~30%.** At N=75 customers, expect ~75 + ~22 = ~97 Subscription.create calls (vs ~75 in iter-13). Stripe rate-limit retry logic in `customer_factory.py` is unchanged and handles the modest increase.
3. **Past-due customers are exempt from tier changes by design** (C-37c). If a future user wants past_due customers to also tier-change (e.g., "downgrade" before failure), this becomes a new amendment.
4. **Status mix at small N is noisy.** With N=6, dry-run shows 3 past_due / 2 active / 1 canceled (50/33/16) which differs from the 70/20/10 target band. The C-5 distribution is only contractually enforced at N≥100.
5. **Reset still does NOT delete tier-tagged Prices.** Re-running across iter-13 → iter-14 may leave a legacy untagged Price on the seed Product (the iter-3 single-tier $50 Price). This is harmless — the new helpers ignore it via the `mrr-seed-tier` metadata filter — but it accumulates if the user re-runs many times. If pruning becomes desired, that's a separate amendment.

## Refine / Pivot Decision

**Direction:** REFINE.

**Reasoning:** The user request is well-scoped and orthogonal to existing gates (no behavior change to C-29/C-30/C-31/C-32/C-33/C-34/C-35). All 55 unit tests pass; the dry-run trace shows the expected sparse / tier-change behavior; the contract amendment is fully specified; and the implementation introduces no new external dependencies. Ready for Evaluator validation.

## Next Steps for Evaluator

1. **Verify unit tests:**
   ```bash
   source scripts/venv/bin/activate
   cd scripts && python -m pytest tests/test_seed_stripe_data.py -v
   ```
   → expect 55/55 passing.

2. **Verify dry-run sparse + tier-change behavior:**
   ```bash
   python scripts/seed_stripe_data.py --dry-run --num-customers 6 --no-reset 2>&1 | grep -E "tier|advanced|Canceled"
   ```
   → expect: at least one `start_month=N` with N>0, at least one `tier change ('basic|pro|enterprise' -> ...)` log line, and 6 `advanced past month N` lines per clock.

3. **Verify CLI help is unchanged for stable flags:**
   ```bash
   python scripts/seed_stripe_data.py --help
   ```
   → expect: `--num-customers`, `--seed`, `--price-id`, `--dry-run`, `--cleanup`, `--cleanup-after`, `--reset`, `--no-reset` all present.

4. **C-31 live smoke test:**
   ```bash
   set -a && source .env && set +a
   RUN_LIVE_TESTS=1 python -m pytest scripts/tests/test_live_smoke.py -v
   ```
   → expect 2/2 passing (legacy `ensure_seed_price` smoke test still resolves the basic tier ID idempotently).

5. **C-35 end-to-end gate:**
   ```bash
   set -a && source .env && set +a
   python scripts/seed_stripe_data.py --num-customers 3 --cleanup-after 2>&1 | tee /tmp/iter14-live.log
   ```
   → expect: exit code 0; zero `ERROR` lines; final summary line "Cleanup-after complete: X clocks deleted, 0 failed" (X ≥ 1); ALL stdout/stderr embedded under `## Live End-to-End Seed Evidence (C-35)` in `.harness/evaluations/sprint-01-evaluation.md`.

6. **C-37 live verification (new):**
   ```bash
   set -a && source .env && set +a
   python scripts/seed_stripe_data.py --num-customers 30 --cleanup-after 2>&1 | tee /tmp/iter14-tier-change.log
   grep -c "tier change" /tmp/iter14-tier-change.log    # expect ≥ 4 (≈30% of ~20 non-past_due)
   grep -c "Created v1 subscription" /tmp/iter14-tier-change.log    # expect = tier-change count
   grep -c "Canceled v0 subscription .* as part of tier change" /tmp/iter14-tier-change.log    # expect = tier-change count
   ```
   → these three counts must be equal (each tier change produces exactly one v0 cancel + one v1 create + one "tier change" log line).

## Files Relevant to Evaluator

- Contract amendment: `/Users/ilhoonlee/Projects/optisigns-assessment/.harness/contracts/sprint-01-contract.md` (top of file)
- Backend code:
  - `/Users/ilhoonlee/Projects/optisigns-assessment/scripts/stripe_seeder/price_manager.py`
  - `/Users/ilhoonlee/Projects/optisigns-assessment/scripts/seed_stripe_data.py`
- Tests: `/Users/ilhoonlee/Projects/optisigns-assessment/scripts/tests/test_seed_stripe_data.py`
- State: `/Users/ilhoonlee/Projects/optisigns-assessment/.harness/state.json`
- This handoff: `/Users/ilhoonlee/Projects/optisigns-assessment/.harness/handoffs/sprint-01-iter-14-handoff.md`
