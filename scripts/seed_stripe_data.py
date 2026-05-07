#!/usr/bin/env python3
"""
Stripe Test Data Seeding Script for MRR Dashboard.

Creates 50-100 test customers with realistic subscription data across 6 months
using Stripe Test Clocks to simulate time passage and invoice generation.

Iteration 14 (Sprint 1, C-36 / C-37):
- Subscription start dates are sparsely distributed across months 0-4 (uniform).
- Three monthly tiers — basic ($50), pro ($100), enterprise ($250).
- ~30% of non-past_due customers experience a tier change at month
  ``start_month + Δ`` (Δ ∈ {1,2}), implemented as
  ``cancel_subscription`` followed by ``create_subscription`` at the new tier
  (preserves at-most-1-active-sub-per-customer).
"""

import argparse
import logging
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Load environment variables from .env
from dotenv import load_dotenv

from stripe_seeder.clock_manager import ClockManager
from stripe_seeder.config import load_api_key
from stripe_seeder.customer_factory import CustomerFactory
from stripe_seeder.errors import ClockTimeoutError, InvalidAPIKeyError, PriceCreationError
from stripe_seeder.price_manager import (
    SEED_TIER_ORDER,
    TIER_BASIC,
    TIER_ENTERPRISE,
    TIER_PRO,
    ensure_seed_price,
    ensure_seed_prices,
)
from stripe_seeder.reset import reset_seed_data
from stripe_seeder.summary import print_summary

# Load .env from the project root (one level above scripts/).
dotenv_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Constants
CUSTOMERS_PER_CLOCK = 3  # Stripe limit
DEFAULT_NUM_CUSTOMERS = 75
DEFAULT_SEED = 42
STATUS_ACTIVE = "active"
STATUS_CANCELED = "canceled"
STATUS_PAST_DUE = "past_due"

# Status distribution targets (percentages)
ACTIVE_TARGET_PCT = 70
CANCELED_TARGET_PCT = 20
PAST_DUE_TARGET_PCT = 10

# Status distribution acceptance bounds (percentages) — used by C-5 test
# `test_status_distribution` to verify the seeded RNG actually lands inside
# the contractually-allowed band on a 100-customer sample.
ACTIVE_MIN, ACTIVE_MAX = 65, 75
CANCELED_MIN, CANCELED_MAX = 15, 25
PAST_DUE_MIN, PAST_DUE_MAX = 8, 12

# C-36: sparse start distribution. Customers start in months 0..4 inclusive
# so every subscription has at least one full billing cycle before month 6.
START_MONTH_MIN = 0
START_MONTH_MAX = 4

# Total months to walk per clock. The clock advances 30 days per iteration.
NUM_MONTHS = 6

# Days advanced per clock iteration. Stays well below MAX_ADVANCEMENT_DAYS=60
# in clock_manager.py (C-10).
DAYS_PER_MONTH = 30

# C-37: probability of a tier-change event per non-past_due customer.
# Module-level so tests can monkeypatch to 0.0 to disable tier changes.
TIER_CHANGE_RATE = 0.30

# C-37: tier-change month offset (Δ months after start_month). Must be ≥1
# so the customer has at least one billing cycle on the original tier.
TIER_CHANGE_DELTA_MIN = 1
TIER_CHANGE_DELTA_MAX = 2

# Cancellation window for canceled cohort (without tier change).
# Mirrors the iter-13 / C-7 behavior: canceled customers cancel in months 3-4.
CANCEL_MONTH_MIN_NO_CHANGE = 3
CANCEL_MONTH_MAX_NO_CHANGE = 4


@dataclass(frozen=True)
class TierChange:
    """A scheduled tier-change event for a customer.

    Implemented at runtime as ``cancel_subscription(old_sub_id)`` followed by
    ``create_subscription(price_id=<new_tier_price>, ...)``.
    """
    month: int       # 1..4 — clock-month at which the change happens
    new_tier: str    # one of basic/pro/enterprise; never equals initial_tier


@dataclass(frozen=True)
class CustomerPlan:
    """The full deterministic lifecycle for one seed customer.

    Built up-front from the seeded RNG before any API call. The orchestrator
    then walks per-clock months and executes whichever events the plan
    schedules in the current month iteration.
    """
    cust_idx: int                 # 0-based index across the entire run
    email: str
    name: str
    status: str                   # active | canceled | past_due
    start_month: int              # 0..4 inclusive
    initial_tier: str             # basic | pro | enterprise
    tier_change: Optional[TierChange]
    cancel_month: Optional[int]   # only for status=canceled


def determine_customer_status(rng: random.Random) -> str:
    """Pick a status using the configured 70/20/10 distribution."""
    rand = rng.randint(1, 100)
    if rand <= ACTIVE_TARGET_PCT:                          # 1-70: Active
        return STATUS_ACTIVE
    if rand <= ACTIVE_TARGET_PCT + CANCELED_TARGET_PCT:    # 71-90: Canceled
        return STATUS_CANCELED
    return STATUS_PAST_DUE                                 # 91-100: Past Due


def calculate_status_distribution(num_customers: int, seed: int) -> dict:
    """Return ``{'active','canceled','past_due'}`` counts for a given seed."""
    rng = random.Random(seed)
    active = canceled = past_due = 0
    for _ in range(num_customers):
        status = determine_customer_status(rng)
        if status == STATUS_ACTIVE:
            active += 1
        elif status == STATUS_CANCELED:
            canceled += 1
        else:
            past_due += 1
    return {"active": active, "canceled": canceled, "past_due": past_due}


def plan_customer_lifecycle(
    cust_idx: int,
    rng: random.Random,
    *,
    tier_change_rate: Optional[float] = None,
) -> CustomerPlan:
    """Build a deterministic ``CustomerPlan`` from the seeded RNG (C-36, C-37).

    The RNG draws happen in a fixed order so seed reproducibility is preserved:
    status -> start_month -> initial_tier -> tier_change_roll ->
    tier_change_delta -> tier_change_target_tier -> cancel_offset.

    Args:
        cust_idx: zero-based index identifying this customer in the run.
        rng: shared seeded RNG (advances across all customers).
        tier_change_rate: optional override for ``TIER_CHANGE_RATE`` (used in
            tests to disable tier changes deterministically).

    Returns:
        A frozen ``CustomerPlan`` describing the customer's full lifecycle.
    """
    if tier_change_rate is None:
        tier_change_rate = TIER_CHANGE_RATE

    email = f"mrr-seed-{cust_idx + 1:03d}@example.com"
    name = f"Test Customer {cust_idx + 1:03d}"

    status = determine_customer_status(rng)
    start_month = rng.randint(START_MONTH_MIN, START_MONTH_MAX)
    initial_tier = rng.choice(SEED_TIER_ORDER)

    # Tier-change roll. Past-due customers never change tier (C-37 sub-task c).
    tier_change_roll = rng.random()
    tier_change_delta = rng.randint(TIER_CHANGE_DELTA_MIN, TIER_CHANGE_DELTA_MAX)
    other_tiers = [t for t in SEED_TIER_ORDER if t != initial_tier]
    new_tier_pick = rng.choice(other_tiers)

    tier_change: Optional[TierChange] = None
    if status != STATUS_PAST_DUE and tier_change_roll < tier_change_rate:
        change_month = start_month + tier_change_delta
        # Must leave at least one full billing cycle on the new tier within
        # the 6-month window (cap at month 4, same as start_month cap).
        if change_month <= START_MONTH_MAX:
            tier_change = TierChange(month=change_month, new_tier=new_tier_pick)

    # Cancellation scheduling — only for status=canceled.
    cancel_month: Optional[int] = None
    if status == STATUS_CANCELED:
        cancel_offset = rng.randint(
            CANCEL_MONTH_MIN_NO_CHANGE, CANCEL_MONTH_MAX_NO_CHANGE
        )
        cancel_month = cancel_offset
        # If the customer had a tier change, the final cancel must come
        # strictly after it (C-37 sub-task e).
        if tier_change is not None and cancel_month <= tier_change.month:
            cancel_month = min(tier_change.month + 1, NUM_MONTHS - 1)

    return CustomerPlan(
        cust_idx=cust_idx,
        email=email,
        name=name,
        status=status,
        start_month=start_month,
        initial_tier=initial_tier,
        tier_change=tier_change,
        cancel_month=cancel_month,
    )


# Internal per-clock runtime state for one customer.
@dataclass
class _CustomerRuntime:
    plan: CustomerPlan
    customer_id: Optional[str] = None
    active_sub_id: Optional[str] = None
    pm_attached: bool = False  # True once payment method + default-PM are set


def _attach_payment_method(
    customer_factory: CustomerFactory,
    customer_id: str,
    status: str,
) -> bool:
    """Attach the appropriate test PM and set it as default. Returns True on success."""
    pm_token = (
        "pm_card_chargeCustomerFail"
        if status == STATUS_PAST_DUE
        else "pm_card_visa"
    )
    pm_result = customer_factory.attach_payment_method(customer_id, pm_token)
    if not pm_result:
        return False
    if not customer_factory.set_default_payment_method(customer_id, pm_result.id):
        return False
    if status == STATUS_PAST_DUE:
        logger.info(
            f"Customer {customer_id} marked for past-due "
            f"with pm_card_chargeCustomerFail and set as default"
        )
    else:
        logger.info(f"Customer {customer_id} attached normal payment method")
    return True


def _create_initial_subscription(
    customer_factory: CustomerFactory,
    runtime: "_CustomerRuntime",
    prices: Dict[str, str],
    clock_id: str,
) -> Optional[str]:
    """Create the v0 subscription for ``runtime`` and return its sub_id."""
    plan = runtime.plan
    price_id = prices[plan.initial_tier]
    idempotency_key = f"seed-sub-{runtime.customer_id}-v0"
    subscription = customer_factory.create_subscription(
        customer_id=runtime.customer_id,
        price_id=price_id,
        test_clock_id=clock_id,
        idempotency_key=idempotency_key,
    )
    if not subscription:
        logger.warning(
            f"Failed to create v0 subscription for customer {runtime.customer_id}"
        )
        return None
    sub_id = subscription.id if hasattr(subscription, "id") else "sub_dryrun_001"
    logger.info(
        f"Created v0 subscription {sub_id} for customer {runtime.customer_id} "
        f"on tier '{plan.initial_tier}' (start_month={plan.start_month})"
    )
    return sub_id


def _execute_tier_change(
    customer_factory: CustomerFactory,
    runtime: "_CustomerRuntime",
    prices: Dict[str, str],
    clock_id: str,
) -> Optional[str]:
    """Cancel v0 sub then create v1 sub on the new tier (C-37 sub-task d).

    Returns the new sub_id on success, or None on any failure (caller
    increments error_count). Order of operations is enforced: cancel first,
    then create.
    """
    plan = runtime.plan
    change = plan.tier_change
    assert change is not None  # caller has already checked

    old_sub_id = runtime.active_sub_id
    cancel_result = customer_factory.cancel_subscription(old_sub_id)
    if not cancel_result:
        logger.warning(
            f"Failed to cancel v0 subscription {old_sub_id} during tier change "
            f"for customer {runtime.customer_id}; tier change aborted"
        )
        return None
    logger.info(
        f"Canceled v0 subscription {old_sub_id} at month {change.month} "
        f"as part of tier change ({plan.initial_tier} -> {change.new_tier}) "
        f"for customer {runtime.customer_id}"
    )

    new_price_id = prices[change.new_tier]
    new_idempotency_key = f"seed-sub-{runtime.customer_id}-v1"
    new_subscription = customer_factory.create_subscription(
        customer_id=runtime.customer_id,
        price_id=new_price_id,
        test_clock_id=clock_id,
        idempotency_key=new_idempotency_key,
    )
    if not new_subscription:
        logger.warning(
            f"Failed to create v1 subscription on tier '{change.new_tier}' "
            f"for customer {runtime.customer_id} after canceling v0"
        )
        return None
    new_sub_id = (
        new_subscription.id if hasattr(new_subscription, "id") else "sub_dryrun_001"
    )
    logger.info(
        f"Created v1 subscription {new_sub_id} on tier '{change.new_tier}' "
        f"for customer {runtime.customer_id} (tier change at month {change.month})"
    )
    return new_sub_id


def seed_stripe_data(
    api_key: str,
    num_customers: int = DEFAULT_NUM_CUSTOMERS,
    seed: int = DEFAULT_SEED,
    dry_run: bool = False,
    price_id: Optional[str] = None,
    prices: Optional[Dict[str, str]] = None,
    cleanup_after: bool = False,
    reset: bool = True,
) -> dict:
    """Main seeding orchestration logic.

    Args:
        api_key: Stripe API key.
        num_customers: Number of customers to create (default 75).
        seed: Random seed for reproducibility (default 42).
        dry_run: If True, log operations without making API calls.
        price_id: Optional Stripe Price ID. If provided alone (without
            ``prices``), it is used for ALL three tiers (legacy single-tier
            behavior — primarily for tests that short-circuit price
            resolution). New callers should use ``prices`` directly.
        prices: Optional dict ``{tier: price_id}`` overriding live resolution.
        cleanup_after: If True, automatically delete all clocks created in this run.
        reset: If True (default), delete all seed-pattern data before seeding.

    Returns:
        Dict with seeding results (customer_count, status counts, etc.).
    """
    # Reset seed-pattern data before seeding (if enabled)
    if reset and not dry_run:
        reset_seed_data(api_key, dry_run=False)

    logger.info(f"Starting Stripe test data seeding for {num_customers} customers")
    logger.info(f"Using random seed {seed} for reproducibility")

    # Resolve tier prices.
    if prices is None:
        if price_id is not None:
            # Legacy single-price path: use the same Price for all tiers.
            # Tests pass price_id="price_test" to short-circuit live resolution;
            # the resulting "tier change" will be a no-op pricewise but still
            # exercises the cancel+create code path.
            prices = {tier: price_id for tier in SEED_TIER_ORDER}
            logger.info(
                f"Using legacy single price_id={price_id} for all tiers"
            )
        else:
            try:
                prices = ensure_seed_prices(api_key, dry_run=dry_run)
            except PriceCreationError as e:
                logger.error(f"Failed to resolve seed Prices: {e}")
                sys.exit(1)

    # Initialize managers
    clock_manager = ClockManager(api_key, dry_run=dry_run)
    customer_factory = CustomerFactory(api_key, dry_run=dry_run)

    # Calculate time windows
    end_date = datetime.now()
    start_date = end_date - timedelta(days=180)  # 6 months back
    logger.info(f"Seeding window: {start_date.date()} to {end_date.date()}")

    # Batch customers into clocks (3 per clock max)
    num_clocks = (num_customers + CUSTOMERS_PER_CLOCK - 1) // CUSTOMERS_PER_CLOCK
    logger.info(f"Will create {num_clocks} test clocks for {num_customers} customers")

    # Seeded RNG for deterministic plans across the entire run.
    rng = random.Random(seed)

    # Pre-plan ALL customers up-front so the RNG order is stable and decoupled
    # from per-clock loop control flow.
    all_plans: List[CustomerPlan] = [
        plan_customer_lifecycle(idx, rng) for idx in range(num_customers)
    ]

    # Aggregate results
    created_customers = 0
    status_counts = {STATUS_ACTIVE: 0, STATUS_CANCELED: 0, STATUS_PAST_DUE: 0}
    error_count = customer_factory.error_count

    # Track clocks created in this run for cleanup_after
    created_clock_ids: List[str] = []

    try:
        for clock_idx in range(num_clocks):
            batch_start = clock_idx * CUSTOMERS_PER_CLOCK
            batch_end = min(batch_start + CUSTOMERS_PER_CLOCK, num_customers)
            batch_size = batch_end - batch_start
            batch_plans = all_plans[batch_start:batch_end]

            # Create the clock at start_date (month 0).
            clock_name = f"mrr-seed-clock-{clock_idx:03d}"
            clock = clock_manager.create_clock(start_date, name=clock_name)
            clock_id = clock.id if hasattr(clock, "id") else "clock_dryrun_001"
            if cleanup_after and not dry_run:
                created_clock_ids.append(clock_id)
            logger.info(f"Created clock {clock_id} with name {clock_name}")
            logger.info(
                f"Processing batch {clock_idx + 1}/{num_clocks} ({batch_size} customers)"
            )

            # Phase 1: pre-create all customers in this batch + attach payment
            # methods. The clock is at month 0; customer.created reflects that.
            runtimes: List[_CustomerRuntime] = []
            for plan in batch_plans:
                if customer_factory.check_existing_customer(plan.email):
                    logger.info(f"Customer {plan.email} already exists, skipping")
                    continue

                customer = customer_factory.create_customer(
                    plan.email, plan.name, clock_id
                )
                if not customer:
                    error_count += 1
                    logger.warning(f"Failed to create customer {plan.email}")
                    continue

                created_customers += 1
                customer_id = (
                    customer.id if hasattr(customer, "id") else "cus_dryrun_001"
                )
                status_counts[plan.status] += 1

                runtime = _CustomerRuntime(plan=plan, customer_id=customer_id)
                runtimes.append(runtime)

                if not _attach_payment_method(
                    customer_factory, customer_id, plan.status
                ):
                    error_count += 1
                    logger.warning(
                        f"Failed to attach/default payment method for customer "
                        f"{customer_id}; skipping subscription creation"
                    )
                    # leave runtime.pm_attached = False; orchestrator will
                    # skip subscription creation for this customer.
                    continue
                runtime.pm_attached = True

            # Phase 2: walk months 0..NUM_MONTHS-1, executing scheduled events.
            try:
                for month in range(NUM_MONTHS):
                    # 2a. Subscription creates for plans with start_month == month.
                    for runtime in runtimes:
                        if (
                            runtime.pm_attached
                            and runtime.active_sub_id is None
                            and runtime.plan.start_month == month
                        ):
                            sub_id = _create_initial_subscription(
                                customer_factory, runtime, prices, clock_id
                            )
                            if sub_id is None:
                                error_count += 1
                            else:
                                runtime.active_sub_id = sub_id

                    # 2b. Tier changes for plans with tier_change.month == month.
                    for runtime in runtimes:
                        change = runtime.plan.tier_change
                        if (
                            change is not None
                            and change.month == month
                            and runtime.active_sub_id is not None
                        ):
                            new_sub_id = _execute_tier_change(
                                customer_factory, runtime, prices, clock_id
                            )
                            if new_sub_id is None:
                                error_count += 1
                            else:
                                runtime.active_sub_id = new_sub_id

                    # 2c. Cancellations for plans with cancel_month == month.
                    for runtime in runtimes:
                        if (
                            runtime.plan.cancel_month == month
                            and runtime.active_sub_id is not None
                        ):
                            cancel_result = customer_factory.cancel_subscription(
                                runtime.active_sub_id
                            )
                            if cancel_result:
                                logger.info(
                                    f"Canceled subscription {runtime.active_sub_id} "
                                    f"at month {month} (final cancel for "
                                    f"customer {runtime.customer_id})"
                                )
                                runtime.active_sub_id = None
                            else:
                                error_count += 1

                    # 2d. Advance the clock to the next month boundary.
                    clock_manager.advance_clock(clock_id, DAYS_PER_MONTH)
                    clock_manager.poll_clock_ready(clock_id)
                    logger.info(
                        f"Clock {clock_id} advanced past month {month + 1}"
                    )
            except ClockTimeoutError as e:
                logger.error(f"Clock timeout for {clock_id}: {e}")
                error_count += 1
    finally:
        # Cleanup clocks created in this run if cleanup_after is enabled
        if cleanup_after and created_clock_ids:
            cleanup_count = 0
            cleanup_failed = 0
            for clock_id in created_clock_ids:
                try:
                    if clock_manager.delete_clock(clock_id):
                        cleanup_count += 1
                        logger.info(f"Cleaned up clock {clock_id}")
                    else:
                        cleanup_failed += 1
                        logger.warning(f"Failed to clean up clock {clock_id}")
                except Exception as e:
                    cleanup_failed += 1
                    logger.warning(f"Failed to clean up clock {clock_id}: {e}")
            logger.info(
                f"Cleanup-after complete: {cleanup_count} clocks deleted, "
                f"{cleanup_failed} failed"
            )

    # Print summary
    print_summary(
        num_customers=created_customers,
        active_count=status_counts[STATUS_ACTIVE],
        canceled_count=status_counts[STATUS_CANCELED],
        past_due_count=status_counts[STATUS_PAST_DUE],
        start_date=start_date,
        end_date=end_date,
        clock_count=num_clocks,
        error_count=error_count,
    )

    return {
        "customer_count": created_customers,
        "active_count": status_counts[STATUS_ACTIVE],
        "canceled_count": status_counts[STATUS_CANCELED],
        "past_due_count": status_counts[STATUS_PAST_DUE],
        "start_date": start_date,
        "end_date": end_date,
        "clock_count": num_clocks,
        "error_count": error_count,
    }


def cleanup_clocks(api_key: str, dry_run: bool = False) -> None:
    """Delete all test clocks matching the seeding pattern."""
    logger.info("Cleaning up test clocks...")
    clock_manager = ClockManager(api_key, dry_run=dry_run)

    pattern = "mrr-seed-clock-"
    matching_clocks = clock_manager.list_clocks_by_pattern(pattern)

    if not matching_clocks:
        logger.info("No test clocks found matching pattern")
        return

    logger.info(f"Found {len(matching_clocks)} clocks to delete")

    response = input(f"Delete {len(matching_clocks)} test clocks? (y/N): ")
    if response.lower() != "y":
        logger.info("Cleanup canceled")
        return

    deleted_count = 0
    for clock_id in matching_clocks:
        if clock_manager.delete_clock(clock_id):
            deleted_count += 1

    logger.info(f"Deleted {deleted_count} test clocks")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Seed Stripe test data for MRR Dashboard",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python seed_stripe_data.py --api-key sk_test_xxx
  export STRIPE_API_KEY=sk_test_xxx && python seed_stripe_data.py
  python seed_stripe_data.py --dry-run --num-customers 100
  python seed_stripe_data.py --cleanup
        """,
    )

    parser.add_argument(
        "--api-key",
        help="Stripe API key (test mode required). Overrides STRIPE_API_KEY env var.",
    )
    parser.add_argument(
        "--num-customers",
        type=int,
        default=DEFAULT_NUM_CUSTOMERS,
        help=f"Number of test customers to create (default: {DEFAULT_NUM_CUSTOMERS})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for reproducibility (default: {DEFAULT_SEED})",
    )
    parser.add_argument(
        "--price-id",
        help="Stripe Price ID to use for ALL tiers (legacy single-tier mode). "
             "If omitted, three tier prices are find-or-created.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the seeding process without making API calls",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete all test clocks matching the seeding pattern",
    )
    parser.add_argument(
        "--cleanup-after",
        action="store_true",
        help="Automatically delete all clocks created in this run after seeding completes",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=True,
        dest="reset",
        help="Delete all seed-pattern data before seeding (default: True)",
    )
    parser.add_argument(
        "--no-reset",
        action="store_false",
        dest="reset",
        help="Do NOT delete seed-pattern data before seeding (preserves prior runs)",
    )

    args = parser.parse_args()

    try:
        api_key = load_api_key(args.api_key)

        if args.cleanup:
            cleanup_clocks(api_key, dry_run=args.dry_run)
        else:
            seed_stripe_data(
                api_key=api_key,
                num_customers=args.num_customers,
                seed=args.seed,
                dry_run=args.dry_run,
                price_id=args.price_id,
                cleanup_after=args.cleanup_after,
                reset=args.reset,
            )
            sys.exit(0)

    except InvalidAPIKeyError as e:
        logger.error(f"API Key Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
