# Sprint 01 Contract — Data Ingestion & Seeding

> **Purpose:** Bridge the spec's Sprint 1 user stories and the Evaluator's testable behaviors. Negotiated before any code is written.
> Both agents use this contract — no moving goalposts during evaluation.

---

## Contract Amendment — Iteration 14 (2026-05-07): Sparse Subscription Starts + Multi-Tier Pricing with Cancel-and-Recreate Tier Changes

**Triggered by:** User request to increase realism of seeded MRR data:
> "The data generation script should sparsely distribute subscriptions across the 6 month period. There should be some customers who upgrade or downgrade their subscription as well. For example, customers who started with a $50 per month subscription upgrades to $100 per month the next month."

**Root cause (N/A — user-initiated scope expansion):** Prior iterations (≤13) seeded all subscriptions at month 0 of the 6-month window and used a single $50/month price tier. The resulting MRR time-series is flat (cumulative MRR equals Active count × $50 from day 0 onward) and contains no upgrade/downgrade signal. This makes the dashboard's trend-analysis features (Sprint 4) untestable end-to-end.

**Amendment:** Add **C-36** (sparse starts) and **C-37** (tier-change events). Revise **C-2** to relax the iter-12 "exactly 1 subscription per customer" invariant — each customer still has at most 1 ACTIVE subscription at any moment, but a tier change is implemented as cancel-and-recreate, so lifetime sub count is 1 or 2.

---

### C-36 (must, iteration 14) — Sparse subscription start distribution

Each customer's subscription is created when the test clock has advanced to a per-customer `start_month` drawn uniformly from `{0, 1, 2, 3, 4}`. (Months 0–4 inclusive; never month 5, so every subscription has at least one full billing cycle within the 6-month window.)

**Verification:**
- (a) Code review of `scripts/seed_stripe_data.py` confirms a `CustomerPlan.start_month` field assigned via `rng.randint(0, 4)`.
- (b) Per-clock month loop creates each customer's subscription only when the clock has advanced to that customer's `start_month`. Subscriptions are NOT all created at month 0.
- (c) Unit test `test_sparse_start_distribution` asserts that for `num_customers=20, seed=42`, the planned `start_month` values cover at least 3 distinct values in `{0..4}`.
- (d) Unit test `test_orchestrator_creates_sub_at_start_month` asserts the orchestrator does not call `Subscription.create` for a customer until the clock has been advanced to that customer's `start_month`.

---

### C-37 (must, iteration 14) — Multi-tier pricing + tier-change events via cancel-and-recreate

The seed script supports three monthly recurring USD price tiers:

| Tier key     | Amount | Price metadata     |
|---|---|---|
| `basic`      | $50    | `mrr-seed-tier=basic`      |
| `pro`        | $100   | `mrr-seed-tier=pro`        |
| `enterprise` | $250   | `mrr-seed-tier=enterprise` |

All three Prices belong to the single `mrr-seed-plan` Product (created find-or-create per iter-3 / C-29). Tier identity is encoded in **Price metadata**, not Product metadata, so all three Prices share the same Product.

**Sub-tasks:**

- **(a) Tier-aware price resolution.** New helper `ensure_seed_prices(api_key, dry_run) -> dict[str, str]` returns `{"basic": <price_id>, "pro": <price_id>, "enterprise": <price_id>}`. For each tier: `stripe.Price.list(product=<seed_product_id>, ...)` → filter by metadata `mrr-seed-tier == <tier>`; create if absent with `unit_amount=<tier_amount_cents>` and `metadata={"mrr-seed-tier": <tier>}`. The legacy `ensure_seed_price()` (singular) is retained as a thin wrapper returning the basic tier ID for the C-31 smoke test.

- **(b) Initial tier assignment.** Each customer's `initial_tier` is drawn uniformly from `{basic, pro, enterprise}` via the seeded RNG.

- **(c) Tier-change planning.** With probability ≈ 30% (sampled per customer from the seeded RNG), a non-`past_due` customer is scheduled to change tier at month `change_month = start_month + Δ`, where Δ ∈ {1, 2}. If `change_month > 4`, the change is dropped (the customer must have at least 1 month on the new tier, and we cap at month 4 for the same reason as C-36). The new tier is drawn uniformly from `{basic, pro, enterprise} \ {initial_tier}`. **Past-due customers never have a tier change** (they're stuck in collection on the failing card and tier changes don't make sense for them).

- **(d) Tier change is cancel-and-recreate.** At `change_month`, the orchestrator calls `customer_factory.cancel_subscription(old_sub_id)` followed immediately by `customer_factory.create_subscription(customer_id, price_id=<new_tier_price>, idempotency_key=f"seed-sub-{customer_id}-v1")`. The original subscription was created with idempotency key `f"seed-sub-{customer_id}-v0"`. This preserves "at most 1 active subscription per customer at any given moment" while producing a clear MRR-change event in the time series.

- **(e) Final cancellation respects tier-change ordering.** For customers with `status=canceled` AND a scheduled tier change, the final `cancel_month` is set to a value strictly greater than `change_month`. Concretely: `cancel_month = max(change_month + 1, original_cancel_month)`, capped at 5. (If no tier change, `cancel_month` follows the prior iter-13 logic — month 3 or 4.)

**Verification:**
- (a) Unit test `test_ensure_seed_prices_returns_three_tiers` asserts `ensure_seed_prices()` resolves three distinct Price IDs in live mode (Stripe SDK mocked).
- (b) Unit test `test_tier_change_planning_invariants` runs `plan_customer_lifecycle` 200 times with seed=42 and asserts: (i) for plans with `tier_change`, `start_month < tier_change.month`; (ii) for plans with both `tier_change` and `cancel_month`, `tier_change.month < cancel_month`; (iii) ~25–35% of non-past_due plans have a `tier_change`; (iv) zero past_due plans have a `tier_change`.
- (c) Unit test `test_orchestrator_tier_change_cancel_then_create` mocks `Subscription.create` and `Subscription.delete`; runs `seed_stripe_data` with `num_customers=15, seed=42`; asserts that for the (deterministic) tier-change customer, `Subscription.delete(<v0_sub_id>)` is called BEFORE `Subscription.create(...)` with the new tier's price.
- (d) Unit test `test_idempotency_key_versioning` asserts the post-tier-change subscription is created with `idempotency_key="seed-sub-{customer_id}-v1"` (not v0).

---

### C-2 (revised, iteration 14) — At most 1 active subscription per customer at any time; lifetime 1 or 2 subs

**Supersedes the iter-12 wording.** Each customer has **at most 1 ACTIVE subscription at any given instant** within the 6-month window. The customer's lifetime subscription count is:
- **1** if the customer never undergoes a tier change (the v0 subscription, which may end in active/canceled/past_due).
- **2** if the customer undergoes a tier change (v0 canceled at `change_month`; v1 created immediately after at the new tier; v1 ends in active/canceled).

Multiple test clocks remain bounded by Stripe's 3-customer-per-clock limit; clock allocation logic (`num_clocks = ceil(num_customers / CUSTOMERS_PER_CLOCK)`) is unchanged.

**Verification:**
- (a) Code review of `scripts/seed_stripe_data.py` confirms there is never a moment when a customer has two simultaneously-active subscriptions: a tier change always cancels the old sub before creating the new one, in that order, in the same month iteration.
- (b) Unit test `test_active_sub_count_per_customer_invariant` (extends `test_multi_clock_cancellations_isolated`) asserts that for any customer, the number of `Subscription.create` calls equals 1 + (1 if tier_change else 0), and the number of `Subscription.delete` calls equals (1 if tier_change else 0) + (1 if status=='canceled' else 0).
- (c) Idempotency-key contract: `seed-sub-{customer_id}-v0` for initial sub; `seed-sub-{customer_id}-v1` for post-tier-change sub. Idempotency keys MUST be unique within a customer.

---

### Evaluator acknowledgment requested

**Awaiting Evaluator review and acknowledgment of C-36, C-37, and the C-2 revision (iteration 14, 2026-05-07) before final closure of this iteration.**

The pre-existing iter-12 amendment block below (C-2 / C-3 narrowing to "exactly 1 subscription per customer") is now superseded by the iter-14 revision of C-2 above for the active-sub-at-any-time invariant. The "1 subscription per customer per clock-month iteration" semantics still hold as a side-effect.

---

## Contract Amendment — Iteration 12 (2026-05-07): Scope Narrowing — Each Customer Has Exactly One Subscription

**Triggered by:** User decision to simplify billing semantics downstream. "Each customer should have only one subscription."

**Root cause (N/A — user-initiated scope narrowing, not a defect):** Previous iterations allowed 1–3 subscriptions per customer via randomized `num_subs = rng.randint(1, 3)`. This introduces complexity in MRR calculation logic (Sprint 3) where multiple subscriptions per customer require aggregation/rollup. The user has decided to eliminate this multiplicity and enforce exactly 1 subscription per customer.

**Amendment:** Modify **C-2** and **C-3** criteria wording to reflect the new constraint.

---

### C-2 (revised, iteration 12)

**C-2 (must) — Subscription count per customer (narrowed).** Each customer has **exactly 1 subscription** (changed from 1–3 in prior iterations). Multiple test clocks are created to batch customers, respecting Stripe's limit of **3 customers per clock**. Clock allocation logic remains unchanged: `num_clocks = ceil(num_customers / CUSTOMERS_PER_CLOCK)`.

**Verification:** Code review of `scripts/seed_stripe_data.py` confirms:
- (a) `SUBSCRIPTIONS_PER_CUSTOMER = 1` (constant set to 1, not 3).
- (b) Subscription creation loop no longer iterates `for sub_idx in range(num_subs)`. Instead, a single subscription is created per customer with `idempotency_key=f"seed-sub-{customer_id}"` (no `sub_idx` suffix).
- (c) `customer_subscriptions[customer_id]` now holds a single subscription ID string, not a list.
- (d) Unit test `test_orchestration_creates_subscriptions` with `num_customers=6` asserts exactly 6 subscription-create calls (not 6–18 as before).

**Rationale:** Simplifies downstream MRR calculation in Sprint 3. One subscription per customer = one billing lifecycle per customer, eliminating aggregation complexity.

---

### C-3 (revised, iteration 12)

**C-3 (must) — Script enforces subscription limits (revised).** Script enforces the **3-customer-per-clock limit** (unchanged) and the new **1-subscription-per-customer limit**; exits with error if violated.

**Verification:** Unit test `test_clock_allocation_enforces_limits` asserts that the script respects the 3-customer-per-clock limit. The 3-subscription-per-customer limit is now moot (always 1); no explicit enforcement test is needed beyond code review confirming no loop over multiple subscriptions.

---

### Evaluator acknowledgment requested

**Awaiting Evaluator review and acknowledgment of C-2 and C-3 amendments (iteration 12, 2026-05-07) before final closure.**

---

## Contract Amendment — Iteration 3 (2026-05-07)

**Triggered by:** A live-mode run by the user produced `400 No such price: 'price_test_mrr'` from Stripe.

**Root cause:** `scripts/seed_stripe_data.py:217` falls back to the hardcoded string `"price_test_mrr"` when `--price-id` is not supplied. That string is the dry-run mock placeholder; in live mode the Stripe API rejects it. The original contract assumed the Generator would either create a Price at startup or require `--price-id`, but no criterion enforced this — every existing test mocked the Stripe SDK and never resolved the price string against the real API.

**Amendment:** Add new must-criterion **C-29** to the Agreement.

> **C-29 (must) — Live-mode price resolution.** When `--price-id` is omitted in non-dry-run mode, the script MUST find-or-create a recurring USD/month Stripe Product+Price (idempotent across runs, identified by metadata key `mrr-seed-plan` or a fixed Product name) and pass that real Price ID to every `subscription.create` call. The hardcoded placeholder `price_test_mrr` MUST NOT appear as a `price=` value in any live-mode `stripe.Subscription.create` call. Verification: (a) read `seed_stripe_data.py` and confirm the price-resolution helper is invoked when `dry_run=False and price_id is None`; (b) unit test `test_ensure_seed_price_finds_or_creates` that asserts the helper looks up an existing price by metadata first and only creates one if absent; (c) unit test `test_subscription_uses_resolved_price` that asserts `stripe.Subscription.create` is called with the resolved real Price ID when the orchestration runs without `--price-id` in non-dry-run mode.

**Acknowledged by:** Evaluator (acknowledgment must be appended after this block before implementation).

### Evaluator acknowledgment of C-29 (2026-05-07)

**Pushback: C-29 requires tightening to cover error handling in Price creation.** The criterion correctly specifies find-or-create behavior (a), idempotent lookup (b), and propagation to subscription.create (c). However, it does not require the script to abort with a clear error if the Price creation itself fails (e.g., invalid currency, rejected by Stripe API). Without this guard, the mock string or a NULL price could leak into subscription.create calls during error paths. **Revised clause needed:** "If Price creation fails, script logs the API error with context and aborts the seeding run (does not fall back to mock or skip the subscription). Unit test (d) `test_price_creation_failure_aborts` mocks `stripe.Product.create` to return an API error; asserts script logs the error message and halts with exit code non-zero." Generator must address before implementation.

### Generator response to acknowledgment (2026-05-07)

**Accepted.** Implementing all four sub-tasks (a, b, c, d). Updated C-29 wording below replaces the original.

### C-29 (final, both agents agreed)

**C-29 (must) — Live-mode price resolution with failure abort.** When `--price-id` is omitted in non-dry-run mode, the script MUST find-or-create a recurring USD/month Stripe Product+Price (idempotent across runs, identified by metadata key `mrr-seed-plan = "true"` or fixed Product name). The hardcoded placeholder `price_test_mrr` MUST NOT appear in any live-mode `stripe.Subscription.create` call.

Sub-tasks:
- **(a) Lookup by metadata:** Script calls `ensure_seed_price(api_key, dry_run=False)` at start of `seed_stripe_data()`. The helper searches existing Prices using `stripe.Product.list(metadata={"mrr-seed-plan": "true"}, limit=100)` then `stripe.Price.list(product=product_id, recurring=...)` to find an existing recurring USD/month Price. If found, returns its ID and logs "Resolved seed Price: <ID> (existing)".

- **(b) Fallback: create if absent.** If no existing Price found, helper creates a new Product with `metadata={"mrr-seed-plan": "true"}` and name "MRR Seed Plan", then creates a recurring USD/month Price ($50/month, 5000 cents) attached to that Product. Logs "Resolved seed Price: <ID> (newly created)".

- **(c) Propagation:** Resolved `price_id` is passed to all subsequent `customer_factory.create_subscription(customer_id, price_id=<resolved>, ...)` calls. Grep of `seed_stripe_data.py` confirms no `"price_test_mrr"` string appears in the live path.

- **(d) Abort on Price creation failure.** If `stripe.Price.create` or `stripe.Product.create` raises `StripeError` (or any API error) during `ensure_seed_price`, the script logs the error message and the offending parameters (currency, amount, product_name) and calls `sys.exit(1)`. It does NOT fall back to the mock string and does NOT silently continue. Verification: unit test `test_price_creation_failure_aborts` mocks `stripe.Product.create` to raise `stripe.error.InvalidRequestError("Invalid product metadata")`. Asserts: (i) `seed_stripe_data(api_key, dry_run=False, price_id=None)` raises `SystemExit(1)` (or equivalent non-zero exit); (ii) no subsequent `stripe.Subscription.create` was invoked; (iii) log output contains the error message and parameters (e.g., "Failed to resolve seed Price: InvalidRequestError...").

**Verification:** Unit test `test_ensure_seed_price_finds_existing` asserts lookup-then-return on existing Price. Unit test `test_ensure_seed_price_creates_when_absent` asserts create-Product-then-Price on new run. Unit test `test_subscription_uses_resolved_price` runs full orchestration without `--price-id` in non-dry-run mode; asserts every `stripe.Subscription.create` call uses the resolved real Price ID, never `"price_test_mrr"`. Unit test `test_price_creation_failure_aborts` (d) per above.

**Both agents have signed C-29. Generator proceeding to implementation.**

---

## Contract Amendment — Iteration 4 (2026-05-07)

**Triggered by:** A live-mode run by the user produced `400 invalid_request_error: Received unknown parameter: metadata` from Stripe on `GET /v1/products?metadata[mrr-seed-plan]=true`.

**Root cause:** C-29 sub-task (a) prescribed `stripe.Product.list(metadata={...})` as the lookup mechanism. **The Stripe API does not support `metadata[]` filtering on the `/v1/products` LIST endpoint** — that filter is only valid on the dedicated **search** endpoint and on object retrieval. Both Generator and Evaluator signed C-29 without consulting Stripe's API reference; mocked unit tests accepted any kwargs and never exercised the real API. Same class of failure as iteration 3 (mocked-tests-passed-but-live-API-rejected).

**Process learning:** C-29 sub-task (b) implicitly assumed metadata filtering worked on list. Future amendments touching live external APIs MUST cite the documented endpoint contract (URL, supported parameters) before signing.

**Amendment:** Add two new must-criteria.

> **C-30 (must) — Stripe API contract correctness for Price lookup.** The lookup mechanism in `ensure_seed_price` MUST use a Stripe API call that is documented to support metadata-based filtering. Acceptable implementations:
> - **Option A (preferred):** `stripe.Product.search(query="metadata['mrr-seed-plan']:'true' AND active:'true'")` — Stripe's search endpoint explicitly supports metadata queries (https://docs.stripe.com/api/products/search).
> - **Option B (fallback):** `stripe.Product.list(active=True, limit=100)` then filter the returned page client-side by `product.metadata.get("mrr-seed-plan") == "true"`. Requires handling pagination if >100 products exist (use `auto_paging_iter()` or paginate explicitly).
> - **Option C (simplest):** Look up by fixed product `name="MRR Seed Plan"`. Idempotency relies on the name being unique within the test account; document this caveat.
>
> The chosen implementation MUST NOT use `stripe.Product.list(metadata=...)` — that call returns a 400. Verification: (a) read `price_manager.py` and confirm the lookup uses Product.search OR a client-side filter on a list response; the bare keyword arg `metadata=` MUST NOT appear on a `Product.list(...)` call. (b) Unit test `test_lookup_uses_documented_endpoint` asserts the chosen API call (search or list+filter) is invoked, NOT `Product.list(metadata=...)`. (c) The mocked test for the find-existing path must mock the SAME endpoint the production code uses (so a future contract drift is caught — a mock of `Product.list` is invalid evidence if production uses `Product.search`).

> **C-31 (must) — Opt-in live-API smoke test.** Add a separate test file (e.g., `scripts/tests/test_live_smoke.py`) containing one or more tests gated by `os.environ.get("RUN_LIVE_TESTS") == "1"`. When the env var is unset, the tests are SKIPPED with a clear reason (use `pytest.skip(...)` or `@pytest.mark.skipif(...)`). When set, each test exercises ONE live Stripe API call this sprint depends on, against the user's `sk_test_*` key, asserting the call returns a non-error response. Required smoke tests for Sprint 1:
>
> - `test_smoke_ensure_seed_price_idempotent` — calls `ensure_seed_price(api_key, dry_run=False)` twice; asserts both calls return the same Price ID; cleans up the created Product+Price (or marks them inactive) at the end.
> - `test_smoke_subscription_create_with_resolved_price` — resolves the Price, creates one customer + one subscription against a fresh test clock, asserts the subscription is `active`; cleans up the clock at the end.
>
> Verification: (a) running `pytest scripts/tests/test_live_smoke.py` without `RUN_LIVE_TESTS` set produces "skipped" status for both tests; (b) the test file imports the actual module under test (not a mock) and uses `os.environ["STRIPE_API_KEY"]`; (c) README is updated with a "Smoke testing" section showing `RUN_LIVE_TESTS=1 pytest scripts/tests/test_live_smoke.py -v`. The Evaluator does NOT need to run the live smoke tests during grading — the existence + skip-when-unset behavior is the testable surface; live execution is the user's responsibility before they trust a future iteration.

**Acknowledged by:** Evaluator (acknowledgment must be appended after this block before implementation).

### Evaluator acknowledgment of C-30 + C-31 (2026-05-07)

**Acknowledged.** Both criteria are tightened and testable.

**C-30 verification:** Confirmed via Stripe API reference (https://docs.stripe.com/api/products/search) that the search endpoint supports metadata queries in the query language (e.g., `metadata['mrr-seed-plan']:'true' AND active:'true'`). Option A is correct and documented; the criterion explicitly forbids the broken `Product.list(metadata=...)` call. Unit test `test_lookup_uses_documented_endpoint` provides concrete verification that production code uses the documented API call, not a mock workaround.

**C-31 verification:** Env-var gate (`RUN_LIVE_TESTS=1`) is clearly specified for both skip condition (unset) and run condition (set). Two smoke tests are concrete and cover the critical paths: (1) price idempotency across re-runs, (2) subscription creation with resolved price. Cleanup is specified for both tests (mark Product+Price inactive or delete; delete test clock). The criterion correctly notes that the Evaluator only verifies skip-when-unset behavior during grading — live execution is the user's responsibility.

**Minor observation (non-blocking):** C-30 sub-task (c) requires the mock to match the production endpoint. This is strong but enforcement depends on Evaluator code review during grading — the unit test name alone does not verify the mock is correct. Recommend Generator double-check mock setup during implementation (e.g., if using `unittest.mock`, verify the patch path targets `stripe.Product.search` not `stripe.Product.list`). C-31 is cleanly specified with no ambiguity on cleanup scope.

**Both criteria are ready for implementation.**

---

## Contract Amendment — Iteration 5 (2026-05-07)

**Triggered by:** User's live-mode run of `scripts/seed_stripe_data.py` on 2026-05-07 produced:
```
stripe.error.InvalidRequestError: Request req_PewMuKhBfs6xqo: 
This customer has no attached payment source or default payment method. 
Please consider adding a default payment method.
```

This error occurred on every `Subscription.create` call, blocking all subscription creation. The script had previously passed iteration 4 evaluation (31/31 criteria ≥7/10) with mocked Stripe SDK tests, yet failed immediately in production.

**Root cause:** `scripts/stripe_seeder/customer_factory.py` (lines 241–256) calls `stripe.PaymentMethod.attach(pm_id, customer=customer_id)` to attach a payment method to a customer. **However, attaching a PaymentMethod does NOT automatically set it as the customer's default.** Stripe's subscription-creation flow requires either: (a) `customer.invoice_settings.default_payment_method` to be set on the Customer object, OR (b) `default_payment_method` to be passed explicitly to `Subscription.create()`. Neither condition is met in the current code.

The mocked unit tests (`unittest.mock.MagicMock`) accept any kwargs and do not validate the actual Stripe API contract. They passed, but the live API rejects the call. This is the third instance of this class of failure (see iterations 3 and 4 amendments): mocked tests accepting mock behavior that the real API forbids.

**Process learning:** C-31 (`test_smoke_subscription_create_with_resolved_price` live smoke test) was introduced in iteration 4 to catch exactly this scenario. However, C-31 specifies that the smoke test is SKIPPED when `RUN_LIVE_TESTS` is unset. The user did not run the live smoke tests before declaring iteration 4 complete; the Evaluator's Pass verdict was based only on the mocked unit tests and code review. **Future contract closure must be conditional: a "Pass" verdict on any sprint with live Stripe API calls is invalid until the user explicitly runs the live smoke tests and confirms they pass.**

**Amendment:** Add new must-criterion **C-32** covering default payment method propagation, and tighten C-31 to gate Sprint 1 closure on live smoke test execution.

---

### C-32 (must) — Default Payment Method Propagation

**Behavior:** Immediately after `PaymentMethod.attach(pm_id, customer=customer_id, api_key=...)` succeeds in `customer_factory.py`, the script MUST call:
```python
stripe.Customer.modify(
    customer_id,
    invoice_settings={"default_payment_method": pm_id},
    api_key=self.api_key,
)
```
This sets the attached payment method as the customer's default, ensuring Stripe's subscription-creation flow has a valid default source to charge.

**Sub-tasks:**

- **(a) Code: Default-PM propagation.** In `scripts/stripe_seeder/customer_factory.py`, immediately after line 256 (after `PaymentMethod.attach` call succeeds), add a call to `stripe.Customer.modify` with `invoice_settings={"default_payment_method": pm_id}`. The call MUST include `api_key=self.api_key` to use the instance's key. Implementation can be inline or extracted to a helper method (e.g., `_set_default_payment_method(customer_id, pm_id)`).

- **(b) Mock matches production.** Unit test `test_default_payment_method_set_on_customer` (new) mocks both `stripe.PaymentMethod.attach` and `stripe.Customer.modify`. The test verifies that: (i) `PaymentMethod.attach` is called with correct arguments; (ii) immediately after, `Customer.modify` is called with `customer_id` and `invoice_settings={"default_payment_method": <pm_id>}`; (iii) the mock call order is enforced (attach before modify, never modify alone). Verification: code review confirms both mocks are set up and the call order is checked.

- **(c) End-to-end live evidence.** The existing C-31 smoke test `test_smoke_subscription_create_with_resolved_price` is tightened:
  - Explicitly create a fresh customer with no payment method.
  - Call `stripe.PaymentMethod.attach(pm_card_visa, customer=customer_id)` to attach a test card.
  - Call `stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id})` to set default.
  - Create a test clock and advance it 1 month.
  - Call `stripe.Subscription.create(customer_id=customer_id, price=resolved_price_id, collection_method='send_invoice')` (or `'charge_automatically'`).
  - Assert returned subscription has `status in ('active', 'trialing', 'past_due')` — i.e., subscription was successfully created without the "no default payment method" error.
  - Cleanup: delete the test clock; delete the customer.

- **(d) Failure handling.** If `stripe.Customer.modify` raises `StripeError` (or any exception) during the default-PM-setting step, the script logs the error with full context (customer_id, pm_id, error_type, error_message) and MUST skip subscription creation for that customer (increment error_count, log "Skipping subscription creation for customer X due to payment method setup failure"). Do NOT proceed to `Subscription.create` if default-PM setup fails. Unit test `test_default_pm_set_failure_skips_subscription` (new) mocks `stripe.Customer.modify` to raise `stripe.error.StripeError("Invalid payment method")`. Asserts: (i) `Customer.modify` is called; (ii) exception is caught and logged; (iii) the NEXT call to `Subscription.create` is NOT invoked for that customer; (iv) error_count is incremented.

---

### C-31 Tightening — Make Live Smoke Tests the Gate

**Amendment to C-31 (added in iteration 4):** Sprint 1 closure is now conditional on the user successfully running the live smoke tests.

- **New requirement:** The Evaluator's "Pass" verdict is only valid if the user has run `RUN_LIVE_TESTS=1 pytest scripts/tests/test_live_smoke.py -v` and posted the stdout (showing both smoke tests passed) into the `.harness/evaluations/sprint-01-evaluation.md` file in a new section titled "## Live Smoke Test Evidence (Required for Pass)" before final closure.

- **Rationale:** Iterations 3, 4, and now 5 have each surfaced mocked-tests-pass-but-live-API-rejects failures. The mocked unit tests provide confidence in logic, but the Stripe SDK's mocking layer accepts any kwargs and does not validate against the live API contract. The two smoke tests (C-31) were introduced to catch this exact scenario but were gated as optional (skipped if `RUN_LIVE_TESTS` unset). Making them mandatory before Pass closure ensures the user runs a real end-to-end flow before declaring the sprint complete.

- **Verification:** In the final evaluation document for Sprint 1, the Evaluator will confirm:
  1. Both `test_smoke_ensure_seed_price_idempotent` and `test_smoke_subscription_create_with_resolved_price` show "PASSED" status in the pytest output.
  2. The stdout shows no test skips (if tests were skipped, RUN_LIVE_TESTS was not set).
  3. Cleanup sections show the test clocks and products created by the smoke tests were deleted.

---

### Evaluator acknowledgment of C-32 + C-31 tightening (2026-05-07)

**Review Point 1 — C-32 sub-task (a) API signature specificity:** Acknowledged. The amendment specifies the exact Python call signature with all kwargs: `stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": pm_id}, api_key=self.api_key)`. This matches the documented Stripe API (https://stripe.com/docs/api/customers/update). The nested structure of `invoice_settings` is explicit and cannot be misinterpreted.

**Review Point 2 — C-32 sub-task (b) mock targeting and assertion rigor:** Acknowledged. The test `test_default_payment_method_set_on_customer` (i) names both endpoints to mock (PaymentMethod.attach and Customer.modify), (ii) asserts exact kwargs including `invoice_settings={"default_payment_method": <pm_id>}` on the Customer.modify call, and (iii) enforces call order (attach must precede modify). This prevents the iteration-3/4 pattern where mocks accepted any kwargs and never validated against the real API contract.

**Review Point 3 — C-32 sub-task (c) live smoke test detail:** Acknowledged. The smoke test explicitly walks the full customer-creation→attach→modify→subscription-creation path, asserts subscription.status is non-error, and specifies cleanup of both test clock and customer. The test uses actual PaymentMethod.attach and Customer.modify calls (not mocks) against the live Stripe test key, providing concrete evidence that the API contract is satisfied.

**Review Point 4 — C-32 sub-task (d) failure handling and coverage:** Acknowledged. The requirement is clear: on Customer.modify failure, log with full context (customer_id, pm_id, error_type, error_message), skip subscription creation for that customer, increment error_count, and continue. The unit test `test_default_pm_set_failure_skips_subscription` mocks the failure, asserts the exception is logged, and crucially asserts that Subscription.create is NOT called for that customer. This prevents silent failures or half-completed states.

**Review Point 5 — C-31 tightening gate and artifact requirement:** Acknowledged. The amendment makes Sprint 1 Pass conditional on live test execution. Specifically:
- User runs: `RUN_LIVE_TESTS=1 pytest scripts/tests/test_live_smoke.py -v`
- User posts stdout to `.harness/evaluations/sprint-01-evaluation.md` under section "## Live Smoke Test Evidence (Required for Pass)"
- Evaluator verifies both smoke tests show "PASSED", no skips, and cleanup confirmed.
- This gate prevents the Evaluator from issuing a Pass verdict based only on mocked tests.

**Review Point 6 — Process learning and API reference:** Acknowledged. The amendment identifies the recurring pattern (iterations 3, 4, 5 are all mocked-pass-but-live-reject failures), cites the underlying Stripe behavior (payment-method-priority chain at https://stripe.com/docs/billing/subscriptions/payment-methods-setting#payment-method-priority), and explains why C-31 was insufficient (optional skip when RUN_LIVE_TESTS unset). The fix is proportional: make live test execution a gate, not an optional verification step.

**Both criteria are ready for implementation.**

---

## Contract Amendment — Iteration 8 (2026-05-07)

**Triggered by:** Fifth instance of mock-vs-live drift. Evaluator's code review of iteration 8 fixes identified a recurring pattern requiring a new mandatory criterion.

**Root cause analysis (iterations 3–8):**

| Iteration | Bug | Mock Failure | Live Failure |
|---|---|---|---|
| **3 (C-29)** | Hardcoded price placeholder | Mock accepted any price string | 400 "No such price" |
| **4 (C-30)** | Wrong Stripe endpoint | Mock accepted `metadata=` on list | 400 "unknown parameter" |
| **5 (C-32)** | Missing Customer.modify call | Mock didn't validate call sequence | 400 "no attached payment source" |
| **7** | Clock advance without polling | Mock returned ready immediately | 429 "clock advancing" |
| **8 (TODAY)** | PM token vs. attached PM ID | Mock `.id = input_token` (should be distinct) | 400 "payment method not attached" |

**Pattern:** Unit tests mock the Stripe SDK too permissively. Mock objects don't enforce the actual API contract (e.g., that `.id` is different from input tokens, that call sequences are correct, that endpoints are the documented ones). Tests pass with mocks but fail on live API.

**Amendment:** Add new must-criterion **C-33** to enforce semantic correctness in all Stripe-mocked tests.

---

### C-33 (must) — Mock-vs-production semantic correctness for ID flows

**Behavior:** Any unit test mocking a Stripe API call that returns an object with an `.id` field MUST:

1. **Set the mock's `.id` to a value DISTINCT from any input token, parameter name, or hardcoded constant** used by the production code calling that API.
   - Example violation: Mocking `PaymentMethod.attach(pm_id="pm_card_visa")` with `mock.return_value.id = "pm_card_visa"` (same as input).
   - Example correct: `mock.return_value.id = "pm_1RealAttached001"` (different from input).

2. **Assert that production code passes the mock's returned `.id` to downstream calls, NOT the input.**
   - Example violation: Asserting `Customer.modify(invoice_settings={"default_payment_method": "pm_card_visa"})` (input token).
   - Example correct: Asserting `Customer.modify(invoice_settings={"default_payment_method": "pm_1RealAttached001"})` (mock's `.id`).

3. **Include an integration test exercising the full orchestrator** (not just mocking the individual function in isolation) to verify the ID is propagated correctly through the call chain.
   - Example: `test_orchestrator_passes_attached_pm_id_to_set_default()` runs `seed_stripe_data()` end-to-end with mocked Stripe calls, then asserts that `Customer.modify()` was called with the orchestrator-computed ID (not a hardcoded constant).

**Verification (for Sprint 1):**
- Code review of all Stripe-mocked unit tests in `scripts/tests/test_seed_stripe_data.py` to confirm:
  - No mock's `.id` equals an input constant (e.g., `INPUT_TOKEN = "pm_card_visa"` and `mock.id = "pm_card_visa"` is a violation)
  - Unit test `test_default_payment_method_set_on_customer` confirms mock `.id` differs from `INPUT_TOKEN`
  - Unit test `test_orchestrator_passes_attached_pm_id_to_set_default` exercises full orchestrator and verifies ID propagation through call chain
- For future sprints: Apply the same verification to any new Stripe-mocked tests.

**Rationale:** The pattern across iterations 3–8 shows that mocks are a necessary tool (they speed up unit tests), but they must enforce the real API contract. By requiring distinct `.id` values and integration-level verification, we catch the class of bugs where production code passes the wrong ID (token vs. PM ID, constant vs. resolved value, input vs. computed result).

---

### Evaluator acknowledgment of C-33 (2026-05-07)

**Acknowledged.** The criterion addresses a recurring failure mode across 5 iterations. The three sub-requirements are concrete and testable:

1. **Distinct mock `.id` values** prevent the token-as-id antipattern (already fixed in iteration 8: `ATTACHED_PM_ID = "pm_1AttachedTest001"` is distinct from `INPUT_TOKEN = "pm_card_visa"`).

2. **Assertion on the mock's `.id` (not input)** ensures production code wires the correct value downstream (iteration 8 unit test checks that `Customer.modify` is called with the mock's `.id`).

3. **Orchestrator integration test** catches wiring bugs where the mock works in isolation but the orchestrator passes the wrong ID (iteration 8's `test_orchestrator_passes_attached_pm_id_to_set_default` verifies end-to-end).

**Verification for iteration 8:**
- Code review confirms `test_default_payment_method_set_on_customer` has `ATTACHED_PM_ID = "pm_1AttachedTest001"` (distinct from `INPUT_TOKEN = "pm_card_visa"`) and asserts `Customer.modify` receives `ATTACHED_PM_ID`.
- Code review confirms `test_orchestrator_passes_attached_pm_id_to_set_default` runs full `seed_stripe_data()` orchestrator and asserts `Customer.modify` was called with the mocked ID.
- Production code (iteration 8) passes `pm_result.id` (not `pm_token`) to `set_default_payment_method()`.

**C-33 is ready for enforcement starting with iteration 8.**

---

## Contract Amendment — Iteration 9 (2026-05-07)

**Triggered by:** Sixth instance of mock-vs-live drift. Live seed run after iter-8 passed produced:
```
The frozen time of this clock is 1762590427 (2025-11-08 08:27:07 UTC).
You can only advance it up to 1767860827 (2026-01-08 08:27:07 UTC).
You can only advance a test clock up to two intervals from the current frozen time at a time...
```

**Root cause:** `scripts/stripe_seeder/clock_manager.py:98-104` computes the new `frozen_time` as `datetime.now() + days_forward`, not as `current_clock.frozen_time + days_forward`. The test clock's current frozen_time is `start_date` (180 days ago), not `datetime.now()`. The first advance call requested `NOW + 30 days`, which violates Stripe's per-call max (2 months from clock's CURRENT state). The unit test `test_advancement_interval_le_2_months` (C-10) validated `days_forward <= 60` structurally but never verified the delta from the clock's actual frozen_time. Same class as iter-3..8: mocks accept any kwargs, live API rejects the invalid request.

**Amendment:** Add new must-criterion **C-34** to extend C-33's enforcement to state-derived parameters (not just ID propagation).

---

### C-34 (must) — Mock-vs-production correctness for state-derived parameters

**Behavior:** Any unit test mocking a Stripe API call whose production caller computes a parameter from prior API state MUST:

1. **Mock the prior state-returning call to return an ARBITRARY NON-DEFAULT value** (not 0, not `time.time()`, not the literal input parameter, not the current date/time).
   - Example: Mocking `TestClock.retrieve()` to return `MagicMock(frozen_time=1700000000, ...)` (arbitrary fixed timestamp, distinct from `datetime.now()`).
   - Example: Mocking `Subscription.retrieve()` to return a subscription with `items=[Item1, Item2]` (not empty, not the same items passed to create).

2. **Assert that production code computes the downstream parameter from the mock's returned value, NOT from datetime.now() or other live state.**
   - Example violation: Asserting `TestClock.advance(frozen_time=<some_value_from_datetime_now>)` when mock returns `1700000000`.
   - Example correct: Asserting `TestClock.advance(frozen_time=1700000000 + 30*86400)` (computed from mock's frozen_time).

3. **Test the assertion to be falsifiable:** Pre-fix code (computing the parameter from datetime.now() instead of mock state) must make the assertion FAIL. The test should fail if production reverts to using live state instead of the mock.

**Verification (for Sprint 1):**
- Code review of all Stripe-mocked unit tests in `scripts/tests/test_seed_stripe_data.py` to confirm:
  - Any test mocking a state-returning call (e.g., `TestClock.retrieve`, `Subscription.retrieve`, `Invoice.retrieve`) uses a mocked return value that is NOT default/zero/current-time.
  - Unit test `test_advancement_interval_le_2_months` (C-10) mocks `TestClock.retrieve()` to return `frozen_time=1700000000` (arbitrary, fixed), then asserts `TestClock.advance()` is called with `frozen_time=1700000000 + 30*86400` (computed from mock, not `datetime.now()`).
  - The test assertion will FAIL if production uses `datetime.now() + 30 days` instead of `mock.frozen_time + 30 days`.
- For future sprints: Apply the same verification to any new Stripe-mocked tests involving state computation (e.g., `Subscription.update(items=existing_sub.items + new_item)`).

**Rationale:** The pattern across iterations 3–9 shows that even with C-33 (semantic correctness for ID propagation), tests can still mock state-returning calls too permissively. C-34 extends the rule to include computed parameters derived from prior API state. By requiring arbitrary mock values and assertions on computed results, we catch bugs where production code uses live state (datetime.now(), global variables, implicit assumptions) instead of the mock's returned state.

---

### Evaluator acknowledgment of C-34 (pending iteration-9 evaluation)

Awaiting Evaluator review and acknowledgment before finalization.

---

## 1. Scope

**In scope:**
- Python script (`scripts/seed_stripe_data.py`) that uses Stripe Test Clocks to populate 50–100 test customers across 6 months of billing history
- Customers distributed across multiple test clocks (respecting 3-customer-per-clock and 3-subscription-per-customer limits)
- Realistic subscription statuses: ~70% Active, ~20% Canceled, ~10% Past Due
- Time advancement in monthly intervals, polling for clock.ready before proceeding
- Cancellations partway through 6-month window (month 3–4) for historical churn signal
- Payment failures for Past Due subscriptions using `pm_card_chargeCustomerFail` token
- Re-run safety: idempotent via deterministic naming or idempotency keys; checks before creating
- Environment variable loading: `STRIPE_API_KEY` from .env (via python-dotenv) or CLI argument
- Error handling: rate-limit backoff, clear error messages with context
- Summary output: script prints final statistics (customer count, status breakdown, date range, clock count, any errors)
- Unit tests with mocked Stripe SDK covering happy path and error scenarios
- README instructions: prerequisites, install, run command, expected output, cleanup

**Explicitly out of scope (deferred to later sprints):**
- BigQuery integration
- React UI or dev server
- MRR calculation logic
- API endpoints or backend application code
- ETL sync pipeline
- Live Stripe calls from the harness (live script runs require user's own STRIPE_API_KEY)

---

## 2. Definition of Done

A developer can run `python scripts/seed_stripe_data.py --api-key <test-key>` (or export STRIPE_API_KEY) and within 3–5 minutes have a populated Stripe test account with 50–100 test customers, each with 1–3 active/canceled/past-due subscriptions spanning 6 months of billing history. The script is idempotent (re-running does not duplicate customers), handles rate limits gracefully, and prints a summary showing customer counts by status, date range covered, test clock count, and any errors encountered. The README explains how to use the script and clean up afterward.

---

## 3. Affected Surfaces

| Layer | Files / paths | Net new vs change |
|---|---|---|
| Scripts | `scripts/seed_stripe_data.py` | new |
| Tests | `tests/test_seed_stripe_data.py` | new |
| Config | `.env.example`, `.gitignore` (verify .env is ignored) | modify |
| Documentation | `README.md`, `docs/SEEDING.md` (optional) | new + modify |

---

## 4. Testable Criteria (28 total)

> Each criterion is an observable behavior. Verification is via code review, unit tests (mocked Stripe), or script dry-run inspection.
> **Criticality:** `must` (script is broken without it) or `should` (nice-to-have but not blocking).

### Functionality (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-1 | Script creates 50–100 unique test customers with deterministic names (e.g., `mrr-seed-001@example.com` through `mrr-seed-100@example.com`) | Unit test `test_customer_count` | must |
| C-2 | **[Iter-12 Narrowed]** Each customer has **exactly 1 subscription**; multiple clocks created to batch customers (max 3 per clock). | Code review: batching logic; unit test `test_clock_capacity` and `test_orchestration_creates_subscriptions` | must |
| C-3 | **[Iter-12 Narrowed]** Script enforces 3-customer-per-clock limit; exits with error if violated. (3-subscription-per-customer limit now moot: always 1) | Unit test `test_clock_allocation_enforces_limits` | must |
| C-4 | Subscriptions span 6-month date range (e.g., Jan 1 – Jun 30, 2026) | Code review: date calculation; unit test `test_date_range` | must |
| C-5 | Status mix: Active 65–75%, Canceled 15–25%, Past Due 8–12% (verified on ≥100 customers) | Unit test `test_status_distribution`; CLI summary output | must |
| C-6 | Active subscriptions advanced 6 months and remain active at end | Code review: advancement logic; unit test `test_active_subscription_lifecycle` | must |
| C-7 | Canceled subscriptions canceled at month 3–4 of 6-month window | Code review: cancellation timing; unit test `test_cancellation_timing` | must |
| C-8 | Past Due subscriptions fail renewal via `pm_card_chargeCustomerFail` token; resulting invoice status is 'open' or 'uncollectible' | Unit test `test_past_due_payment_failure` | must |
| C-13 | Script uses deterministic email pattern `mrr-seed-{i:03d}@example.com` to check for existing customers via `stripe.Customer.list(email=<email>)`. If found, skips creation and logs | Unit test `test_idempotent_customer_creation` | must |
| C-14 | Re-running script does not create duplicate customers or subscriptions | Unit test: seeding twice verifies customer count unchanged on second run | must |
| C-15 | **[Iter-12 Updated]** Uses Stripe idempotency keys for subscription creation (e.g., `idempotency_key=f"seed-sub-{customer_id}"`, no sub_idx suffix) to prevent duplicates | Code review: idempotency key usage; unit test `test_subscription_idempotency_key` | must |
| C-20 | Script prints final summary: customer count, breakdown by status (Active/Canceled/Past Due), date range, test clock count, and error count | Code review: summary printing logic; dry-run output inspection | must |
| C-25 | Script accepts `--cleanup` flag; lists and deletes all test clocks with name pattern `mrr-seed-clock-*`, prompts for confirmation, logs count deleted | Unit test `test_cleanup_deletes_clocks` | should |
| C-27 | For each subscription, invoices exist for all 6 billing cycles (or fewer if canceled). Unit test `test_invoices_cover_all_months` verifies period_start dates span Jan–Jun | Unit test `test_invoices_cover_all_months` | must |

### Stripe API Constraints (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-9 | After clock advancement, script polls `clock.status` every 1 second (max 30 seconds) until ready. On timeout, logs error and aborts remaining operations on that clock | Unit test `test_clock_polling_timeout` | must |
| C-10 | Clock advancement uses ≤2-month intervals (respects Stripe's shortest billing period limit). Default: 1 month per call | Unit test `test_advancement_interval_le_2_months` | must |
| C-11 | Script retries 429 responses up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s). On 6th failure, logs error and continues with next customer | Unit test `test_rate_limit_retry_and_continue` | must |
| C-12 | Script validates Stripe API responses; logs/returns clear errors if response is invalid (e.g., missing required field) | Code review: validation logic; unit test `test_invalid_api_response` | must |

### Idempotency & Safety (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-28 | If script exhausts retries on a single API call, logs error with context and continues with next customer (does not halt). Final summary reports total error count | Unit test `test_rate_limit_permanent_failure` | must |

### Environment & Configuration (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-16 | Script loads `STRIPE_API_KEY` from environment variable (via os.environ or python-dotenv) | Code review: `scripts/seed_stripe_data.py` load logic; unit test `test_load_api_key_from_env` | must |
| C-17 | Script accepts `--api-key` CLI flag as alternative to environment variable | Code review: argparse usage; unit test `test_cli_flag_override` | should |
| C-18 | `.env.example` documents required variables; `.gitignore` includes `.env` | Code review: file inspection | must |
| C-19 | API key is NEVER logged, printed, or leaked in error messages. Unit test `test_api_key_not_logged` captures logger output, asserts no 'sk_test', 'sk_live', or literal api_key string | Unit test `test_api_key_not_logged`; code review: grep for print/logger calls | must |
| C-24 | Script validates `STRIPE_API_KEY` prefix at startup; aborts with error if key starts with 'sk_live_' | Unit test `test_live_key_rejected` | must |

### Output & Summary (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-21 | Summary output is clear and human-readable (e.g., "Seeded 75 customers: 52 Active, 15 Canceled, 8 Past Due. Date range: Jan 1 – Jun 30, 2026. Created 25 test clocks. Errors: 0.") | Code review: formatting; manual run inspection | should |

### Testing (Must-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-22 | Unit test file `tests/test_seed_stripe_data.py` includes ≥8 named tests: `test_customer_count`, `test_clock_allocation_enforces_limits`, `test_status_distribution`, `test_idempotent_customer_creation`, `test_rate_limit_retry_and_continue`, `test_clock_polling_timeout`, `test_past_due_payment_failure`, `test_api_key_not_logged`. All use mocked Stripe SDK | Code review: test file inspection | must |

### Documentation (Should-haves)

| ID | Behavior | Verification | Criticality |
|---|---|---|---|
| C-23 | README.md includes: (1) Prerequisites (Python 3.9+, Stripe test account, API key), (2) Install, (3) Run, (4) Expected output (sample summary), (5) Cleanup (`--cleanup` flag or manual) | Code review: README.md sections | should |
| C-26 | Script `--help` documents all flags: `--api-key KEY`, `--num-customers N` (default 75), `--cleanup`, `--dry-run` | Unit test `test_help_output`; manual `--help` inspection | should |

---

## 5. Negotiation Log

### Round 1 — Generator proposes (2026-05-06)

**Summary:**
This contract defines a Python data seeding script for Stripe Test Clocks covering Sprint 1. The scope is limited to the script, tests, and documentation — no application code or UI. The criteria (23 total) are organized by functional area: core functionality (8 criteria), API constraint handling (4), idempotency/safety (3), environment/configuration (4), output/summary (2), testing (1), and documentation (1).

**Rationale:**
- Stripe Test Clock constraints are baked into C-3, C-9, C-10 to ensure the Evaluator understands the API limits upfront.
- Idempotency is emphasized (C-13, C-14, C-15) because re-running the script is a stated requirement.
- Status distribution (C-5) and lifecycle handling (C-6, C-7, C-8) are must-haves; summary output (C-20) is also must-have because it's the primary verification mechanism for live runs.
- All criteria are testable via code review, unit tests with mocking, or script output inspection — no live Stripe calls required for harness evaluation.
- Rubric: **Full-stack**, but Frontend Quality and Design Quality dimensions do NOT apply to Sprint 1 (no UI). Applicable dimensions: **Functionality** (core script behavior), **Code Quality** (clean, idiomatic Python), **Robustness/Error Handling** (rate limits, validation, graceful failure), **Security/Secrets** (no leaked API keys), **Documentation** (README clarity), **Test Coverage** (≥80% of seeding logic).

**Affected surfaces:**
- `scripts/seed_stripe_data.py` — new
- `tests/test_seed_stripe_data.py` — new
- `.env.example`, `.gitignore` — modified
- `README.md` or `docs/SEEDING.md` — new/modified

**Awaiting Evaluator review and feedback.**

---

### Round 2 — Evaluator review (2026-05-06)

**Assessment:** 23 criteria is a solid count. However, I identified 10 criteria needing pushback or clarification, and 5 new criteria missing from the contract. Below is my detailed feedback.

**ACCEPT as-is:**
- **C-1, C-2, C-4, C-6, C-7:** Clear behavioral specs with concrete verification targets (code locations or unit test names). Testable without ambiguity.
- **C-16, C-18:** Environment variable loading and .gitignore are straightforward.
- **C-20:** Summary output is must-have and well-specified.

**REJECT — too vague or incomplete:**

1. **C-3 — "respects Stripe Test Clock limits"** — Needs enforcement:
   - Specify: "Script exits with error if attempting to create >3 customers on a single clock or >3 subscriptions per customer."
   - Current verification "dry-run output shows clock count" is not enough; need a unit test that asserts clock allocation respects the 3-customer and 3-subscription limits.
   - **Revised:** "Script enforces 3-customer-per-clock and 3-subscription-per-customer limits; unit test `test_clock_allocation_enforces_limits` verifies allocation rejects over-capacity assignments."

2. **C-5 — Status distribution tolerance** — Verification is vague:
   - Current: "unit test `test_status_distribution` verifies counts." **What counts? With what tolerance?**
   - **Revised:** "Unit test `test_status_distribution` with ≥100 customers verifies: Active ≥65 and ≤75, Canceled ≥15 and ≤25, Past Due ≥8 and ≤12 (tolerances ±5%)."

3. **C-8 — Past Due mechanism** — Lacks proof of actual failure:
   - Current: "unit test `test_past_due_payment_failure`" says nothing about HOW failure is validated.
   - **Revised:** "Unit test `test_past_due_payment_failure` mocks clock advancement and invoice creation; asserts that for customers with `pm_card_chargeCustomerFail` token, after clock advancement, returned invoice has status='open' or 'uncollectible' (failure detected)."

4. **C-9 — Clock polling** — Needs max wait and backoff detail:
   - Current: "polls `clock.status` until it reaches `"ready"`" — but for how long? What if it never becomes ready?
   - **Revised:** "After clock advancement, script polls `clock.status` every 1 second (max 30 seconds) until status='ready'. If timeout, logs error and aborts. Unit test `test_clock_polling_timeout` asserts timeout behavior."

5. **C-10 — Advancement interval size** — Verification missing:
   - Current: "unit test `test_advancement_interval_size`" — what size? 1 month? 2 months?
   - **Revised:** "Script advances clock in ≤2-month intervals (respecting Stripe's requirement for shortest billing period max). Unit test `test_advancement_interval_gte_2_months` verifies all advancement calls use delta ≤2 months."

6. **C-11 — Rate limit backoff** — Max retries and ultimate failure behavior unspecified:
   - Current: "e.g., 3 retries with 1s, 2s, 4s delays" — is that prescriptive or illustrative? What happens on 4th failure?
   - **Revised:** "Script retries 429 responses up to 3 times with exponential backoff (1s, 2s, 4s). On 4th failure, logs error and continues with next customer (does not halt entire script). Unit test `test_rate_limit_retry_and_continue` asserts this behavior."

7. **C-13 — Idempotency key definition** — Dedup strategy unclear:
   - Current: "by email or idempotent key" — which one? Email lookup is different from idempotency key usage.
   - **Revised:** "Script uses deterministic email pattern (`seed-customer-NNN@example.com`) to check for existing customers via `stripe.Customer.list(email=<email>)` before creation. If found, skips creation and logs. Unit test `test_idempotent_customer_creation` verifies lookup + skip behavior."

8. **C-19 — API key leakage check** — Needs test method:
   - Current: "Code review: full script grep for `api_key` usage" — this is manual; needs a concrete test.
   - **Revised:** "Code review: grep `scripts/seed_stripe_data.py` for `print`, `logger.info`, `logger.warning`, `logger.error` statements; none should include `api_key` variable. Unit test `test_api_key_not_logged` mocks logger and stripe API calls, runs script, asserts no log call contains 'sk_test' or 'sk_live'."

9. **C-22 — Test coverage specificity** — Needs explicit test list:
   - Current: "test count ≥5" is vague. Which 5 scenarios?
   - **Revised:** "Unit test file includes ≥8 tests: `test_happy_path_seeding`, `test_customer_count`, `test_clock_capacity`, `test_idempotent_customer_creation`, `test_rate_limit_backoff`, `test_clock_polling`, `test_status_distribution`, `test_past_due_payment_failure`. All use mocked Stripe SDK."

10. **C-23 — Documentation scope** — Needs bullet clarity:
    - Current: "explains: prerequisites, install, run, expected output, and cleanup" — what format for cleanup?
    - **Revised:** "README.md or docs/SEEDING.md includes sections: (1) Prerequisites (Python 3.9+, Stripe test account, API key retrieval), (2) Install (`pip install -r requirements.txt`), (3) Run (`python scripts/seed_stripe_data.py --api-key sk_test_... or export STRIPE_API_KEY`), (4) Expected output (sample summary text showing 75 customers, 52 Active, 15 Canceled, 8 Past Due, 25 clocks), (5) Cleanup (`python scripts/seed_stripe_data.py --cleanup` or manual: `stripe test_helpers.testClock.list() | delete all`)."

**ADD — Missing criteria:**

11. **C-24 — Test mode enforcement (NEW, must):**
    - **Behavior:** Script refuses to run if `STRIPE_API_KEY` is a live key (`sk_live_*`); aborts with error message.
    - **Verification:** Code review: `scripts/seed_stripe_data.py` validates key prefix; unit test `test_live_key_rejected` asserts abort on `sk_live_*`.
    - **Rationale:** Accidental live-key usage is catastrophic; must guard against it.

12. **C-25 — Cleanup / delete test clocks support (NEW, should):**
    - **Behavior:** Script accepts `--cleanup` flag; lists all test clocks created with deterministic metadata (tag or name pattern), deletes them, and logs count deleted.
    - **Verification:** Code review: argparse handles `--cleanup`; unit test `test_cleanup_deletes_clocks` mocks clock.delete, asserts correct IDs deleted.
    - **Rationale:** Re-run idempotency is easier if user can wipe clocks between runs.

13. **C-26 — CLI flags documentation (NEW, should):**
    - **Behavior:** Script prints help (`--help`) showing: `--api-key KEY`, `--num-customers N` (default 75), `--cleanup` (no argument), `--dry-run` (no argument, prints summary without API calls).
    - **Verification:** Code review: argparse definitions; unit test `test_help_output` asserts all flags present in help text.
    - **Rationale:** User ergonomics and non-destructive testing.

14. **C-27 — All invoices span 6 months (NEW, must):**
    - **Behavior:** For each subscription across each customer, invoices exist for all 6 billing cycles (month 1, 2, 3, 4, 5, 6 of the window), not just start and end dates. This ensures historical MRR dashboard has data for every month.
    - **Verification:** Unit test `test_invoices_cover_all_months` mocks subscription creation and clock advancement; asserts that after seeding, querying invoices for a subscription returns invoices with period_start spanning Jan, Feb, Mar, Apr, May, Jun.
    - **Rationale:** Spec's "6 months of billing history" means continuous history, not just anchor points.

15. **C-28 — Rate limit failure handling (NEW, must):**
    - **Behavior:** If script exhausts retries on a single API call, it logs the error with context (endpoint, customer_id, attempt count) and continues with the next customer. Script does not halt; final summary reports count of errors encountered.
    - **Verification:** Unit test `test_rate_limit_permanent_failure` mocks stripe.Subscription.create to return 429 four times; asserts script logs error, increments error counter, continues. Final summary includes "Errors: 1."
    - **Rationale:** Robustness; script should not abort on transient failures.

**CLARIFICATIONS NEEDED:**

- **C-9 and C-10 interaction:** If clock advancement must be ≤2 months and polling adds 1 second per iteration, how many advance calls are needed for 6 months? (Answer: 3 calls minimum, possibly more if polling is slow.) Add a note to spec: "E.g., month 1 → 2: advance 1 month, poll until ready. month 2 → 4: advance 2 months, poll until ready. month 4 → 6: advance 2 months, poll until ready."

- **C-3 and batching:** With 50–100 customers and 3-per-clock limit, script must create 17–34 clocks. Does it create all clocks upfront, or create clocks on-demand as batches fill? Specify in code: "Script batches customers into groups of 3; on each new group, creates a new clock (if needed), advances it, polls, then creates subscriptions for that batch."

---

**VERDICT:** The contract is **75% solid** (10 of 23 criteria accept as-is) but needs **critical corrections** in specificity and **5 new criteria** for complete coverage. Missing are: test mode enforcement, cleanup support, invoice coverage verification, and robust failure handling. Most pushback is "too vague" — the concepts are right, but verification is handwavy.

**RECOMMENDATION:** Generator, please address the 10 rejections above (rewrite C-3, C-5, C-8, C-9, C-10, C-11, C-13, C-19, C-22, C-23) and add the 5 new criteria (C-24 through C-28). Then write Round 3 with revised contract. This will bring the contract to **~30 criteria**, which is appropriate for a script with multiple Stripe API interactions, state management (clocks, subscriptions), error handling, and testing rigor.

---

## 6. Threshold Applied

- **Per-criterion threshold:** 7/10 (from grading rubric; standard for full-stack work)
- **Iteration cap:** 15 per sprint
- **Escalation:** If iteration cap is hit without all criteria ≥7/10, Generator writes escalation file halting the sprint

---

## 7. Rubric Selection

- [x] **Full-stack rubric** (Python script + unit tests, no UI)
- [ ] Frontend rubric (N/A — no UI in Sprint 1)
- [ ] Design Fidelity (N/A — no Figma design in Sprint 1)

### Rubric Dimensions Applied to Sprint 1

| Dimension | Applied? | Notes |
|---|---|---|
| **Functionality** | Yes | Core script behavior: customer/subscription creation, status distribution, time advancement, rate-limit handling |
| **Code Quality** | Yes | Clean Python, proper structure, DRY principle, no hardcoded values, proper naming |
| **Robustness & Error Handling** | Yes | Rate-limit backoff, validation of API responses, clear error messages, graceful failure modes |
| **Security & Secrets** | Yes | No leaked API keys, proper use of environment variables, .gitignore prevents .env commit |
| **Documentation** | Yes | README with setup/run/cleanup instructions, inline code comments where complex |
| **Test Coverage** | Yes | Unit tests with mocking; target 80%+ coverage of script logic |
| **Frontend Quality** | No | N/A — no UI |
| **Design Fidelity** | No | N/A — no Figma design |

---

Round 2 — Evaluator review complete. Generator: please address the items above and write Round 3.

---

## Round 3 — Generator response (2026-05-06)

**Assessment:** The Evaluator's feedback is well-founded. I accept all 10 rejections with the proposed rewrites and all 5 new criteria. Below is my response to each item, followed by the final Agreement block.

### Response to Rejected Criteria

**C-3 — Clock allocation enforcement:**
- **Accept Evaluator rewrite.** The revised criterion is clearer: enforce limits and add a specific unit test.
- **Proposed final wording:** "Script enforces 3-customer-per-clock and 3-subscription-per-customer limits; exits with error if violated. Unit test `test_clock_allocation_enforces_limits` verifies batching logic rejects over-capacity assignments."
- **Verification:** Code review + unit test `test_clock_allocation_enforces_limits`

**C-5 — Status distribution with bounds:**
- **Accept Evaluator proposal.** Percentages (Active 65–75%, Canceled 15–25%, Past Due 8–12%) are loose enough for randomness but tight enough to catch misconfigurations.
- **Proposed final wording:** "Status mix meets: Active 65–75%, Canceled 15–25%, Past Due 8–12% (verified on ≥100 customers). Unit test `test_status_distribution` asserts these bounds; CLI summary shows actual counts."
- **Verification:** Unit test `test_status_distribution`

**C-8 — Past Due proof via invoice status:**
- **Accept Evaluator clarification.** Must assert invoice status after payment failure.
- **Proposed final wording:** "Past Due subscriptions fail renewal via `pm_card_chargeCustomerFail` token; unit test `test_past_due_payment_failure` mocks clock advancement and verifies resulting invoice status is 'open' or 'uncollectible' (payment failed)."
- **Verification:** Unit test `test_past_due_payment_failure`

**C-9 — Polling timeout with bounds and abort:**
- **Accept Evaluator specification.** 30s timeout, 1s interval, abort on timeout is operationally sound.
- **Proposed final wording:** "After clock advancement, script polls `clock.status` every 1 second, max 30 seconds total. On timeout (status never reaches 'ready'), logs error and aborts remaining operations on that clock. Unit test `test_clock_polling_timeout` asserts timeout behavior."
- **Verification:** Unit test `test_clock_polling_timeout`

**C-10 — Advancement interval ≤2 months:**
- **Accept Evaluator proposal.** Default is 1 month per call (under 2-month max); test verifies no call exceeds 2 months.
- **Proposed final wording:** "Script advances clock in ≤2-month intervals (respecting Stripe's shortest billing period requirement). Default: 1 month per advancement call. Unit test `test_advancement_interval_gte_2_months` verifies all advancement calls use delta ≤2 months."
- **Note:** Test name should be `test_advancement_interval_le_2_months` (less-than-or-equal).
- **Verification:** Unit test `test_advancement_interval_le_2_months`

**C-11 — Rate limit retry count and continuation:**
- **Accept Evaluator specification.** Max 5 retries (1s, 2s, 4s, 8s, 16s exponential backoff); on 6th failure, log + continue.
- **Proposed final wording:** "Script retries 429 responses up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s). On 6th failure, logs error with context and continues with next customer (does not halt entire script). Unit test `test_rate_limit_retry_and_continue` mocks 6 consecutive 429s."
- **Verification:** Unit test `test_rate_limit_retry_and_continue`

**C-13 — Email-based dedup with deterministic pattern:**
- **Accept Evaluator specification.** Email pattern `mrr-seed-{i:03d}@example.com` + lookup before create.
- **Proposed final wording:** "Script uses deterministic email pattern `mrr-seed-{i:03d}@example.com` (e.g., `mrr-seed-001@example.com`, `mrr-seed-002@example.com`) to check for existing customers via `stripe.Customer.list(email=<email>)` before creation. If found, skips creation and logs. Unit test `test_idempotent_customer_creation` simulates re-run and verifies lookup + skip behavior."
- **Verification:** Unit test `test_idempotent_customer_creation`

**C-19 — API key leakage unit test:**
- **Accept Evaluator clarification.** Unit test that captures log output and asserts no API key leakage is cleaner than manual grep.
- **Proposed final wording:** "Unit test `test_api_key_not_logged` runs seed logic with mocked stripe SDK, captures all logger output, and asserts no log line contains 'sk_test', 'sk_live', or the literal api_key string. Code review: grep `scripts/seed_stripe_data.py` confirms no print/logger calls include api_key variable."
- **Verification:** Unit test `test_api_key_not_logged`

**C-22 — Explicit test list (8 tests):**
- **Accept Evaluator list.** I will ensure all 8 tests exist with these exact names.
- **Proposed final wording:** "Unit test file `tests/test_seed_stripe_data.py` includes ≥8 named tests covering: `test_customer_count`, `test_clock_allocation_enforces_limits`, `test_status_distribution`, `test_idempotent_customer_creation`, `test_rate_limit_retry_and_continue`, `test_clock_polling_timeout`, `test_past_due_payment_failure`, `test_api_key_not_loaded`. All use mocked Stripe SDK (pytest-mock or unittest.mock)."
- **Note:** Adding the 8 rejected-criterion tests. Will combine with new-criterion tests for total count.
- **Verification:** Code review + test file inspection

**C-23 — Cleanup flag and documentation:**
- **Accept Evaluator revision.** `--cleanup` flag + detailed README sections.
- **Proposed final wording:** "README.md includes sections: (1) Prerequisites (Python 3.9+, Stripe test account, API key retrieval), (2) Install (`pip install -r requirements.txt`), (3) Run command (`python scripts/seed_stripe_data.py --api-key sk_test_... or export STRIPE_API_KEY`), (4) Expected output (sample summary: 75 customers, 52 Active, 15 Canceled, 8 Past Due, 25 clocks), (5) Cleanup (`python scripts/seed_stripe_data.py --cleanup` or manual Stripe dashboard deletion)."
- **Verification:** Code review: README.md inspection

### Response to New Criteria

**C-24 — Live key rejection (NEW, must):**
- **Accept Evaluator addition.** Critical safeguard.
- **Proposed final wording:** "Script validates `STRIPE_API_KEY` prefix at startup; aborts with error message if key starts with 'sk_live_' (live mode). Unit test `test_live_key_rejected` asserts abort on `sk_live_*` key."
- **Verification:** Unit test `test_live_key_rejected`

**C-25 — Cleanup flag support (NEW, should):**
- **Accept Evaluator addition.** Useful for re-run hygiene.
- **Proposed final wording:** "Script accepts `--cleanup` flag; lists all test clocks with name pattern `mrr-seed-clock-*`, prompts for confirmation, deletes them via Stripe API DELETE endpoint, and logs count deleted. Unit test `test_cleanup_deletes_clocks` mocks clock.delete and asserts correct IDs deleted."
- **Verification:** Unit test `test_cleanup_deletes_clocks`

**C-26 — CLI flags documentation (NEW, should):**
- **Accept Evaluator addition.** User ergonomics.
- **Proposed final wording:** "Script `--help` output documents all flags: `--api-key KEY` (override STRIPE_API_KEY), `--num-customers N` (default 75), `--cleanup` (delete test clocks), `--dry-run` (print summary, no API calls). Unit test `test_help_output` asserts all flags present."
- **Verification:** Unit test `test_help_output`

**C-27 — All invoices span 6 months (NEW, must):**
- **Accept Evaluator addition.** Critical for "6 months of billing history" promise.
- **Proposed final wording:** "For each subscription, invoices exist for all 6 billing cycles (or fewer if subscription canceled before month 6). Unit test `test_invoices_cover_all_months` mocks subscription creation and clock advancement; asserts queried invoices have period_start dates spanning Jan, Feb, Mar, Apr, May, Jun (or subset if canceled)."
- **Verification:** Unit test `test_invoices_cover_all_months`

**C-28 — Rate limit permanent failure (NEW, must):**
- **Accept Evaluator addition.** Robustness for script continuation.
- **Proposed final wording:** "If script exhausts retries on a single API call (after 5 retries on 429), logs error with context (endpoint, customer_id, attempt count) and continues with next customer. Final summary reports total error count. Unit test `test_rate_limit_permanent_failure` mocks 6 consecutive 429s and asserts script logs error, increments counter, and continues."
- **Verification:** Unit test `test_rate_limit_permanent_failure`

### Clarifications

- **C-9 / C-10 interaction:** With 2-month max advancement and 1 month per call for 6 months, script needs 3–4 advancement calls per clock (month 1→2→4→6 or 1→3→5→6, depending on implementation). Polling adds ~1–5 seconds per advancement call (1s per poll, max 30 polls). This is acceptable.
- **C-3 / batching:** Script batches customers 3 per clock. On each new batch, creates a new clock (if needed), initializes it to start_date (e.g., Jan 1, 2026), advances and polls, then creates subscriptions for that batch.

---

## Round 4 — Evaluator sign-off

**Assessment:** The Agreement block (immediately below) faithfully reflects all 10 Round 2 rejections and all 5 new criteria. Each rewritten criterion includes the exact specificity I demanded:

- **C-3:** Enforce 3-per-clock limit + unit test checking over-capacity rejection. ✓
- **C-5:** Active 65–75%, Canceled 15–25%, Past Due 8–12% bounds on ≥100 customers. ✓
- **C-8:** Invoice status 'open' or 'uncollectible' proof. ✓
- **C-9:** 1s interval, 30s max, abort on timeout. ✓
- **C-10:** ≤2-month intervals, unit test `test_advancement_interval_le_2_months`. ✓
- **C-11:** 5 retries (1s, 2s, 4s, 8s, 16s), on 6th failure log + continue. ✓
- **C-13:** Email pattern `mrr-seed-{i:03d}@example.com`, lookup, skip behavior. ✓
- **C-19:** Unit test capturing logs + assertions for 'sk_test', 'sk_live', literal key. ✓
- **C-22:** 8 specific test names, all present. ✓
- **C-23:** 5 README sections + cleanup flag. ✓
- **C-24:** Live key rejection (`sk_live_*`), abort. ✓
- **C-25:** Cleanup flag, pattern `mrr-seed-clock-*`, confirmation, count logged. ✓
- **C-26:** Help output with all 4 flags documented. ✓
- **C-27:** Invoices span Jan–Jun, period_start verification. ✓
- **C-28:** Permanent failure: log context, continue, summary reports errors. ✓

**Criterion count:** 28 (within 25–28 target). No weasel words. All verification methods are concrete (test names, file:line, CLI output). Rubric dimensions are correct (no Frontend Quality or Design Fidelity). Ready for implementation.

## Agreement (Final Canonical Criteria)

| ID | Criticality | Behavior | Verification | Rubric Dimension |
|---|---|---|---|---|
| C-1 | must | Script creates 50–100 unique test customers with deterministic names (e.g., `mrr-seed-001@example.com` through `mrr-seed-100@example.com`) | Unit test `test_customer_count` | Functionality |
| C-2 | must | Each customer has 1–3 subscriptions; multiple clocks created to batch customers (max 3 per clock, max 3 subscriptions per customer) | Code review: batching logic; unit test `test_clock_capacity` | Functionality |
| C-3 | must | Script enforces 3-customer-per-clock and 3-subscription-per-customer limits; exits with error if violated | Unit test `test_clock_allocation_enforces_limits` | Functionality |
| C-4 | must | Subscriptions span 6-month date range (e.g., Jan 1 – Jun 30, 2026) | Code review: date calculation; unit test `test_date_range` | Functionality |
| C-5 | must | Status mix: Active 65–75%, Canceled 15–25%, Past Due 8–12% (verified on ≥100 customers) | Unit test `test_status_distribution`; CLI summary output | Functionality |
| C-6 | must | Active subscriptions advanced 6 months and remain active at end | Code review: advancement logic; unit test `test_active_subscription_lifecycle` | Functionality |
| C-7 | must | Canceled subscriptions canceled at month 3–4 of 6-month window | Code review: cancellation timing; unit test `test_cancellation_timing` | Functionality |
| C-8 | must | Past Due subscriptions fail renewal via `pm_card_chargeCustomerFail` token; resulting invoice status is 'open' or 'uncollectible' | Unit test `test_past_due_payment_failure` | Functionality |
| C-9 | must | After clock advancement, script polls `clock.status` every 1 second (max 30 seconds) until ready. On timeout, logs error and aborts remaining operations on that clock | Unit test `test_clock_polling_timeout` | Robustness & Error Handling |
| C-10 | must | Clock advancement uses ≤2-month intervals (respects Stripe's shortest billing period limit). Default: 1 month per call | Unit test `test_advancement_interval_le_2_months` | Robustness & Error Handling |
| C-11 | must | Script retries 429 responses up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s). On 6th failure, logs error and continues with next customer | Unit test `test_rate_limit_retry_and_continue` | Robustness & Error Handling |
| C-12 | must | Script validates Stripe API responses; logs/returns clear errors if response is invalid (e.g., missing required field) | Code review: validation logic; unit test `test_invalid_api_response` | Robustness & Error Handling |
| C-13 | must | Script uses deterministic email pattern `mrr-seed-{i:03d}@example.com` to check for existing customers via `stripe.Customer.list(email=<email>)`. If found, skips creation and logs | Unit test `test_idempotent_customer_creation` | Functionality |
| C-14 | must | Re-running script does not create duplicate customers or subscriptions | Unit test: seeding twice verifies customer count unchanged on second run | Functionality |
| C-15 | must | Uses Stripe idempotency keys for subscription creation (e.g., `idempotency_key=f"seed-sub-{customer_id}-{i}"`) to prevent duplicates | Code review: idempotency key usage; unit test `test_subscription_idempotency_key` | Functionality |
| C-16 | must | Script loads `STRIPE_API_KEY` from environment variable (via os.environ or python-dotenv) | Code review: `scripts/seed_stripe_data.py` load logic; unit test `test_load_api_key_from_env` | Security & Secrets |
| C-17 | should | Script accepts `--api-key` CLI flag as alternative to environment variable | Code review: argparse usage; unit test `test_cli_flag_override` | Documentation |
| C-18 | must | `.env.example` documents required variables; `.gitignore` includes `.env` | Code review: file inspection | Security & Secrets |
| C-19 | must | API key is NEVER logged, printed, or leaked in error messages. Unit test `test_api_key_not_logged` captures logger output, asserts no 'sk_test', 'sk_live', or literal api_key string | Unit test `test_api_key_not_logged`; code review: grep for print/logger calls | Security & Secrets |
| C-20 | must | Script prints final summary: customer count, breakdown by status (Active/Canceled/Past Due), date range, test clock count, and error count | Code review: summary printing logic; dry-run output inspection | Functionality |
| C-21 | should | Summary output is clear and human-readable (e.g., "Seeded 75 customers: 52 Active, 15 Canceled, 8 Past Due. Date range: Jan 1 – Jun 30, 2026. Created 25 test clocks. Errors: 0.") | Code review: formatting; manual run inspection | Functionality |
| C-22 | must | Unit test file `tests/test_seed_stripe_data.py` includes ≥8 named tests: `test_customer_count`, `test_clock_allocation_enforces_limits`, `test_status_distribution`, `test_idempotent_customer_creation`, `test_rate_limit_retry_and_continue`, `test_clock_polling_timeout`, `test_past_due_payment_failure`, `test_api_key_not_logged`. All use mocked Stripe SDK | Code review: test file inspection | Test Coverage |
| C-23 | should | README.md includes: (1) Prerequisites (Python 3.9+, Stripe test account, API key), (2) Install, (3) Run, (4) Expected output (sample summary), (5) Cleanup (`--cleanup` flag or manual) | Code review: README.md sections | Documentation |
| C-24 | must | Script validates `STRIPE_API_KEY` prefix at startup; aborts with error if key starts with 'sk_live_' | Unit test `test_live_key_rejected` | Security & Secrets |
| C-25 | should | Script accepts `--cleanup` flag; lists and deletes all test clocks with name pattern `mrr-seed-clock-*`, prompts for confirmation, logs count deleted | Unit test `test_cleanup_deletes_clocks` | Functionality |
| C-26 | should | Script `--help` documents all flags: `--api-key KEY`, `--num-customers N` (default 75), `--cleanup`, `--dry-run` | Unit test `test_help_output`; manual `--help` inspection | Documentation |
| C-27 | must | For each subscription, invoices exist for all 6 billing cycles (or fewer if canceled). Unit test `test_invoices_cover_all_months` verifies period_start dates span Jan–Jun | Unit test `test_invoices_cover_all_months` | Functionality |
| C-28 | must | If script exhausts retries on a single API call, logs error with context and continues with next customer (does not halt). Final summary reports total error count | Unit test `test_rate_limit_permanent_failure` | Robustness & Error Handling |
| **C-29** | **must** | **Live-mode price resolution with failure abort.** When `--price-id` is omitted in non-dry-run mode, the script MUST find-or-create a recurring USD/month Stripe Product+Price (idempotent across runs, identified by metadata key `mrr-seed-plan = "true"`). (a) Lookup by metadata: Script calls `ensure_seed_price()` at start; searches by metadata and returns existing Price if found, logging "Resolved seed Price: <ID> (existing)". (b) Fallback: If no existing Price found, creates Product + Price ($50/month), logs "Resolved seed Price: <ID> (newly created)". (c) Propagation: Resolved price_id passed to all subscription.create calls. (d) Abort on failure: If Price/Product creation fails, logs error and calls sys.exit(1). | Unit tests: `test_ensure_seed_price_finds_existing`, `test_ensure_seed_price_creates_when_absent`, `test_subscription_uses_resolved_price`, `test_price_creation_failure_aborts` | Functionality |
| **C-30** | **must** | **Stripe API contract correctness for Price lookup.** The lookup mechanism MUST use `stripe.Product.search(query="metadata['mrr-seed-plan']:'true' AND active:'true'")` (documented endpoint supporting metadata queries). MUST NOT use `stripe.Product.list(metadata=...)` (unsupported by Stripe API). Verification: (a) Code review: `price_manager.py` uses Product.search with metadata query. (b) Unit test `test_lookup_uses_documented_endpoint` asserts Product.search is called, Product.list(metadata=...) is NOT called. (c) Mocks in unit tests patch the correct endpoint. | Code review + unit test `test_lookup_uses_documented_endpoint` | Functionality |
| **C-31** | **must** | **Opt-in live-API smoke test gated by RUN_LIVE_TESTS=1.** (a) Module-level skipif: tests skip when `os.environ.get("RUN_LIVE_TESTS") != "1"`. (b) `test_smoke_ensure_seed_price_idempotent`: calls `ensure_seed_price()` twice; asserts both return the same Price ID. (c) `test_smoke_subscription_create_with_resolved_price`: full flow (create customer → attach PM → set default PM → create subscription); asserts subscription.status in ('active', 'trialing'). (d) Cleanup in finally block. (e) README documents with `RUN_LIVE_TESTS=1 pytest scripts/tests/test_live_smoke.py -v`. | Test file inspection: `test_live_smoke.py` exists + skipif gate; manual skip verification when RUN_LIVE_TESTS unset; README section present | Functionality |
| **C-32** | **must** | **Default payment method propagation.** (a) Code: `set_default_payment_method(customer_id, payment_method_id)` method exists in `customer_factory.py`; calls `stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": payment_method_id}, api_key=self.api_key)`; returns bool. (b) Mock semantic correctness: Unit test `test_default_payment_method_set_on_customer` mocks PaymentMethod.attach to return `.id` DISTINCT from input token (e.g., INPUT_TOKEN="pm_card_visa", mock.id="pm_1AttachedTest001"); asserts Customer.modify is called with the attached ID (not token). (c) Orchestrator integration test: `test_orchestrator_passes_attached_pm_id_to_set_default` runs full `seed_stripe_data()` with mocked Stripe calls; asserts Customer.modify received the attached PM ID. (d) Failure handling: If Customer.modify raises StripeError, log error with context, increment error_count, skip subscription creation for that customer. Unit test `test_default_pm_set_failure_skips_subscription` mocks failure and asserts Subscription.create is NOT called. | Unit tests: `test_default_payment_method_set_on_customer`, `test_default_pm_set_failure_skips_subscription`, `test_orchestrator_passes_attached_pm_id_to_set_default`; code review | Functionality |
| **C-33** | **must** | **Mock-vs-production semantic correctness for ID flows.** Any unit test mocking a Stripe API call returning an object with `.id` field MUST: (1) Set mock's `.id` to a value DISTINCT from any input token/parameter/constant (e.g., INPUT_TOKEN="pm_card_visa" and mock.id="pm_1Test001" are distinct). (2) Assert production code passes mock's `.id` to downstream calls, NOT the input (e.g., assert `Customer.modify(invoice_settings={"default_payment_method": "pm_1Test001"})`, not the token). (3) Include orchestrator integration test verifying ID propagates through full call chain. | Code review of `scripts/tests/test_seed_stripe_data.py`: all Stripe-mocked tests have distinct `.id` values; C-32 unit and integration tests enforce correct assertion; no test passes input constant to downstream calls | Test Coverage |

---

## Contract Amendment — Iteration 10 (2026-05-07)

**Triggered by:** Defensive hardening. After 6 recurring mock-vs-live regressions across iterations 3–9, the user requested a permanent end-to-end gate to prevent future Stripe-touching sprints from shipping without a real-API smoke test.

**Amendment:** Add new must-criterion **C-35** and tighten C-31's language.

> **C-35 (must) — End-to-end live seed gate.** For Sprint 1 (and any future Stripe-touching sprint), the Pass verdict is conditional on the Evaluator successfully running:
> 
>     set -a && source .env && set +a
>     python scripts/seed_stripe_data.py --num-customers 3 --cleanup-after
> 
> The command MUST exit 0 AND produce stdout/stderr containing zero `ERROR` log lines AND finish by reporting "Cleanup-after complete: X clocks deleted, Y failed" in the summary (where X ≥ 1 and Y = 0). The full stdout MUST be embedded in `.harness/evaluations/sprint-NN-evaluation.md` under section "## Live End-to-End Seed Evidence (C-35)". Verification: this evaluation file's iter-10 section is the canonical first instance.
> 
> **Sub-tasks:**
> - **(a) CLI flag:** Script accepts `--cleanup-after` flag (default False). Mutually compatible with `--num-customers` and `--dry-run`.
> - **(b) Cleanup orchestration:** `seed_stripe_data(cleanup_after=True)` maintains local list `created_clock_ids` tracking only clocks created in THIS run. Cleanup is wrapped in try/finally so it runs even on exception.
> - **(c) Deletion:** For each clock_id in created_clock_ids, calls `clock_manager.delete_clock(clock_id)` with no confirmation prompt. Logs success ("Cleaned up clock <ID>") or failure ("Failed to clean up clock <ID>: <err>").
> - **(d) Summary:** Final orchestration summary includes "Cleanup-after complete: X clocks deleted, Y failed" when flag is set.
> - **(e) Unit tests:** `test_cleanup_after_deletes_only_run_clocks` asserts clocks created in this run are deleted, pre-existing clocks are not. `test_cleanup_after_runs_even_on_exception` asserts cleanup runs even if exception occurs. `test_cleanup_after_flag_default_off` asserts delete is NOT called when flag is False (backward compatibility).
> 
> **Also tighten C-31:** Change final sentence from "The Evaluator does NOT need to run the live smoke tests during grading" to "C-31 (smoke pytest) AND C-35 (full seed cycle with cleanup) are BOTH required for Stripe-touching sprint Pass."

**Acknowledged by:** Generator (implementing all sub-tasks and tightening C-31).

### C-35 and C-31 (both agreed)

**C-35 (must) — End-to-end live seed gate:** Script accepts `--cleanup-after` flag; tracks clocks created in this run; deletes them in finally block with zero confirmation prompts; logs summary "Cleanup-after complete: X clocks deleted, Y failed". Unit tests: `test_cleanup_after_deletes_only_run_clocks`, `test_cleanup_after_runs_even_on_exception`, `test_cleanup_after_flag_default_off`.

**C-31 (tightened) — Opt-in live-API smoke test gated by RUN_LIVE_TESTS=1:** ... [same as above, with final clause changed to] ... "C-31 (smoke pytest) AND C-35 (full seed cycle) are BOTH required for Stripe-touching sprint Pass."

**Both agents have signed the amendment. Generator proceeding to implementation.**

---

## Final Agreement (34 criteria)

| ID | Criticality | Behavior | Verification | Rubric Dimension |
|---|---|---|---|---|
| C-1 | must | Script creates 50–100 unique test customers with deterministic names (e.g., `mrr-seed-001@example.com` through `mrr-seed-100@example.com`) | Unit test `test_customer_count` | Functionality |
| C-2 | must | Each customer has 1–3 subscriptions; multiple clocks created to batch customers (max 3 per clock, max 3 subscriptions per customer) | Code review: batching logic; unit test `test_clock_capacity` | Functionality |
| C-3 | must | Script enforces 3-customer-per-clock and 3-subscription-per-customer limits; exits with error if violated | Unit test `test_clock_allocation_enforces_limits` | Functionality |
| C-4 | must | Subscriptions span 6-month date range (e.g., Jan 1 – Jun 30, 2026) | Code review: date calculation; unit test `test_date_range` | Functionality |
| C-5 | must | Status mix: Active 65–75%, Canceled 15–25%, Past Due 8–12% (verified on ≥100 customers) | Unit test `test_status_distribution`; CLI summary output | Functionality |
| C-6 | must | Active subscriptions advanced 6 months and remain active at end | Code review: advancement logic; unit test `test_active_subscription_lifecycle` | Functionality |
| C-7 | must | Canceled subscriptions canceled at month 3–4 of 6-month window | Code review: cancellation timing; unit test `test_cancellation_timing` | Functionality |
| C-8 | must | Past Due subscriptions fail renewal via `pm_card_chargeCustomerFail` token; resulting invoice status is 'open' or 'uncollectible' | Unit test `test_past_due_payment_failure` | Functionality |
| C-9 | must | After clock advancement, script polls `clock.status` every 1 second (max 30 seconds) until ready. On timeout, logs error and aborts remaining operations on that clock | Unit test `test_clock_polling_timeout` | Robustness & Error Handling |
| C-10 | must | Clock advancement uses ≤2-month intervals (respects Stripe's shortest billing period limit). Default: 1 month per call | Unit test `test_advancement_interval_le_2_months` | Robustness & Error Handling |
| C-11 | must | Script retries 429 responses up to 5 times with exponential backoff (1s, 2s, 4s, 8s, 16s). On 6th failure, logs error and continues with next customer | Unit test `test_rate_limit_retry_and_continue` | Robustness & Error Handling |
| C-12 | must | Script validates Stripe API responses; logs/returns clear errors if response is invalid (e.g., missing required field) | Code review: validation logic; unit test `test_invalid_api_response` | Robustness & Error Handling |
| C-13 | must | Script uses deterministic email pattern `mrr-seed-{i:03d}@example.com` to check for existing customers via `stripe.Customer.list(email=<email>)`. If found, skips creation and logs | Unit test `test_idempotent_customer_creation` | Functionality |
| C-14 | must | Re-running script does not create duplicate customers or subscriptions | Unit test: seeding twice verifies customer count unchanged on second run | Functionality |
| C-15 | must | Uses Stripe idempotency keys for subscription creation (e.g., `idempotency_key=f"seed-sub-{customer_id}-{i}"`) to prevent duplicates | Code review: idempotency key usage; unit test `test_subscription_idempotency_key` | Functionality |
| C-16 | must | Script loads `STRIPE_API_KEY` from environment variable (via os.environ or python-dotenv) | Code review: `scripts/seed_stripe_data.py` load logic; unit test `test_load_api_key_from_env` | Security & Secrets |
| C-17 | should | Script accepts `--api-key` CLI flag as alternative to environment variable | Code review: argparse usage; unit test `test_cli_flag_override` | Documentation |
| C-18 | must | `.env.example` documents required variables; `.gitignore` includes `.env` | Code review: file inspection | Security & Secrets |
| C-19 | must | API key is NEVER logged, printed, or leaked in error messages. Unit test `test_api_key_not_logged` captures logger output, asserts no 'sk_test', 'sk_live', or literal api_key string | Unit test `test_api_key_not_logged`; code review: grep for print/logger calls | Security & Secrets |
| C-20 | must | Script prints final summary: customer count, breakdown by status (Active/Canceled/Past Due), date range, test clock count, and error count | Code review: summary printing logic; dry-run output inspection | Functionality |
| C-21 | should | Summary output is clear and human-readable (e.g., "Seeded 75 customers: 52 Active, 15 Canceled, 8 Past Due. Date range: Jan 1 – Jun 30, 2026. Created 25 test clocks. Errors: 0.") | Code review: formatting; manual run inspection | Functionality |
| C-22 | must | Unit test file `tests/test_seed_stripe_data.py` includes ≥8 named tests: `test_customer_count`, `test_clock_allocation_enforces_limits`, `test_status_distribution`, `test_idempotent_customer_creation`, `test_rate_limit_retry_and_continue`, `test_clock_polling_timeout`, `test_past_due_payment_failure`, `test_api_key_not_logged`. All use mocked Stripe SDK | Code review: test file inspection | Test Coverage |
| C-23 | should | README.md includes: (1) Prerequisites (Python 3.9+, Stripe test account, API key), (2) Install, (3) Run, (4) Expected output (sample summary), (5) Cleanup (`--cleanup` flag or manual) | Code review: README.md sections | Documentation |
| C-24 | must | Script validates `STRIPE_API_KEY` prefix at startup; aborts with error if key starts with 'sk_live_' | Unit test `test_live_key_rejected` | Security & Secrets |
| C-25 | should | Script accepts `--cleanup` flag; lists and deletes all test clocks with name pattern `mrr-seed-clock-*`, prompts for confirmation, logs count deleted | Unit test `test_cleanup_deletes_clocks` | Functionality |
| C-26 | should | Script `--help` documents all flags: `--api-key KEY`, `--num-customers N` (default 75), `--cleanup`, `--dry-run` | Unit test `test_help_output`; manual `--help` inspection | Documentation |
| C-27 | must | For each subscription, invoices exist for all 6 billing cycles (or fewer if canceled). Unit test `test_invoices_cover_all_months` verifies period_start dates span Jan–Jun | Unit test `test_invoices_cover_all_months` | Functionality |
| C-28 | must | If script exhausts retries on a single API call, logs error with context and continues with next customer (does not halt). Final summary reports total error count | Unit test `test_rate_limit_permanent_failure` | Robustness & Error Handling |
| C-29 | must | Live-mode price resolution with failure abort. When `--price-id` is omitted in non-dry-run mode, script finds-or-creates recurring USD/month Stripe Product+Price (idempotent, identified by metadata key `mrr-seed-plan = "true"`). Unit tests: `test_ensure_seed_price_finds_existing`, `test_ensure_seed_price_creates_when_absent`, `test_subscription_uses_resolved_price`, `test_price_creation_failure_aborts` | Code review + unit tests | Functionality |
| C-30 | must | Stripe API contract correctness for Price lookup. Lookup MUST use `stripe.Product.search(query="metadata['mrr-seed-plan']:'true' AND active:'true'")` (documented endpoint). MUST NOT use `stripe.Product.list(metadata=...)` (unsupported). Unit test `test_lookup_uses_documented_endpoint` asserts Product.search is called, Product.list(metadata=...) is NOT called. | Code review + unit test | Functionality |
| C-31 | must | Opt-in live-API smoke test gated by RUN_LIVE_TESTS=1. (a) Tests skip when env var unset. (b) `test_smoke_ensure_seed_price_idempotent`: calls `ensure_seed_price()` twice; asserts same Price ID returned. (c) `test_smoke_subscription_create_with_resolved_price`: full flow (create customer → attach PM → set default PM → create subscription); asserts subscription.status in ('active', 'trialing'). (d) Cleanup in finally block. (e) README documents command. **C-31 (smoke pytest) AND C-35 (full seed cycle) are BOTH required for Stripe-touching sprint Pass.** | Test file inspection + README section | Functionality |
| C-32 | must | Default payment method propagation. `set_default_payment_method(customer_id, payment_method_id)` in customer_factory.py calls `stripe.Customer.modify(customer_id, invoice_settings={"default_payment_method": payment_method_id}, api_key=self.api_key)`; returns bool. Unit tests with distinct `.id` values and integration test asserting ID propagates through call chain. | Unit tests + code review | Functionality |
| C-33 | must | Mock-vs-production semantic correctness for ID flows. Any unit test mocking Stripe API call returning object with `.id` field MUST: (1) Set mock's `.id` to value DISTINCT from input token/parameter. (2) Assert production code passes mock's `.id` to downstream calls, NOT input. (3) Include orchestrator integration test verifying ID propagates through full call chain. | Code review of test file + unit/integration tests | Test Coverage |
| **C-35** | **must** | **End-to-end live seed gate.** Script accepts `--cleanup-after` flag (default False). `seed_stripe_data(cleanup_after=True)` maintains local list `created_clock_ids` tracking only clocks created in THIS run. Cleanup wrapped in try/finally. For each clock_id in list, calls `clock_manager.delete_clock(clock_id)` with no confirmation. Logs success ("Cleaned up clock <ID>") or failure ("Failed to clean up clock <ID>: <err>"). Final summary includes "Cleanup-after complete: X clocks deleted, Y failed" when flag is set. | Unit tests: `test_cleanup_after_deletes_only_run_clocks`, `test_cleanup_after_runs_even_on_exception`, `test_cleanup_after_flag_default_off` | Robustness & Error Handling |

---

**Final agreement reached. All 34 criteria are specific, testable, and ready for implementation. Generator proceeding to iteration-10 implementation (C-35 end-to-end gate).**

### Evaluator acknowledgment of C-35 (2026-05-07, iteration 10)

Acknowledged. C-35 end-to-end live seed gate is implementable and clearly specified.

**C-35 verification (iteration 10 execution):**
- Production code confirms: (1) `--cleanup-after` argparse flag present (line 418-421), (2) `seed_stripe_data(cleanup_after: bool = False)` signature correct (line 108), (3) `created_clock_ids` local list tracks run-scoped clocks (line 162), (4) cleanup in finally block (lines 294-311), (5) no confirmation prompt, (6) final summary includes "Cleanup-after complete: 1 clocks deleted, 0 failed" (line 311).
- Unit tests confirm: TestCleanupAfter class with three tests (lines 996–1151): `test_cleanup_after_deletes_only_run_clocks`, `test_cleanup_after_runs_even_on_exception`, `test_cleanup_after_flag_default_off`.
- Live execution confirms: Full seed run with `--num-customers 3 --cleanup-after` completed with exit code 0, zero ERROR log lines, and clock successfully deleted (verified via `stripe.test_helpers.TestClock.list()`).

**C-31 and C-35 together form the permanent Stripe-touching sprint gate:**
- C-31 (live smoke tests): 2 PASSED when `RUN_LIVE_TESTS=1` (verified).
- C-35 (full seed cycle + cleanup): Exit 0, summary line correct, cleanup verified.

**C-35 is ready for codification — applies to current and future Stripe-touching sprints.**

---


## Implementation Note — Iteration 13: Stripe test-clock date-field semantics (Documentation)

**Added:** 2026-05-07 (iteration 13, not a contract amendment — informational note for downstream consumers).

The seeded data exhibits a documented Stripe Test Clock limitation: some timestamp fields are advanced by the test clock (simulated), while others remain at real wall-clock time (not simulated). This is **expected behavior and correct** — no action required.

**For downstream consumers (Sprint 2 BigQuery ETL, Sprint 3 MRR calculations, Sprint 4 dashboard):**

- **Use Invoice fields for time-series MRR analysis:** `Invoice.period_start`, `Invoice.period_end`, `Invoice.status_transitions.paid_at` (all simulated correctly).
- **Avoid Charge fields for historical analysis:** `Charge.created` will show today's date even for invoices dated 6 months in the past (this is correct — payments settle in real time, invoices settle in simulated time).
- **Always include parent filters when listing invoices:** `stripe.Invoice.list(subscription="...")` or `stripe.Invoice.list(customer="...")`. Without a parent filter, Stripe omits test-clock-generated invoices.

Full documentation appended to `README.md` section "## Stripe test-clock limitations and date-field semantics" with reference URLs (Stripe API docs).

**No contract criterion was modified or added for this documentation.** It clarifies downstream constraints for existing criteria (C-31, C-35) and does not change Pass/Fail thresholds.

