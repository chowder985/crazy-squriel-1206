#!/usr/bin/env python3
"""
Stripe Test Data Seeding Script for MRR Dashboard.

Creates 50-100 test customers with realistic subscription data across 6 months
using Stripe Test Clocks to simulate time passage and invoice generation.
"""

import argparse
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Load environment variables from .env
from dotenv import load_dotenv

from stripe_seeder.clock_manager import ClockManager
from stripe_seeder.config import load_api_key
from stripe_seeder.customer_factory import CustomerFactory
from stripe_seeder.errors import ClockTimeoutError, InvalidAPIKeyError, PriceCreationError
from stripe_seeder.price_manager import ensure_seed_price
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
SUBSCRIPTIONS_PER_CUSTOMER = 3
DEFAULT_NUM_CUSTOMERS = 75
DEFAULT_SEED = 42
STATUS_ACTIVE = "active"
STATUS_CANCELED = "canceled"
STATUS_PAST_DUE = "past_due"

# Status distribution targets (percentages)
ACTIVE_MIN, ACTIVE_MAX = 65, 75
CANCELED_MIN, CANCELED_MAX = 15, 25
PAST_DUE_MIN, PAST_DUE_MAX = 8, 12

# Target centerpoints for distribution (sum to 100%)
ACTIVE_TARGET_PCT = 70
CANCELED_TARGET_PCT = 20
PAST_DUE_TARGET_PCT = 10


def determine_customer_status(rng: random.Random) -> str:
    """
    Determine status for a customer based on distribution targets.

    Args:
        rng: Random number generator with seeded state

    Returns:
        One of: 'active', 'canceled', 'past_due'
    """
    rand = rng.randint(1, 100)
    if rand <= ACTIVE_TARGET_PCT:  # 1-70: Active
        return STATUS_ACTIVE
    elif rand <= ACTIVE_TARGET_PCT + CANCELED_TARGET_PCT:  # 71-90: Canceled
        return STATUS_CANCELED
    else:  # 91-100: Past Due
        return STATUS_PAST_DUE


def calculate_status_distribution(num_customers: int, seed: int) -> dict:
    """
    Calculate actual status counts for the given customer count and seed.

    Args:
        num_customers: Total number of customers to seed
        seed: Random seed for reproducibility

    Returns:
        Dict with 'active', 'canceled', 'past_due' counts
    """
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


def seed_stripe_data(
    api_key: str,
    num_customers: int = DEFAULT_NUM_CUSTOMERS,
    seed: int = DEFAULT_SEED,
    dry_run: bool = False,
    price_id: str = None,
) -> dict:
    """
    Main seeding orchestration logic.

    Args:
        api_key: Stripe API key
        num_customers: Number of customers to create (default 75)
        seed: Random seed for reproducibility (default 42)
        dry_run: If True, log operations without making API calls
        price_id: Optional Stripe Price ID; if not provided, will be created

    Returns:
        Dict with seeding results (customer_count, active_count, etc.)
    """
    logger.info(f"Starting Stripe test data seeding for {num_customers} customers")
    logger.info(f"Using random seed {seed} for reproducibility")

    # Resolve price_id at startup (find-or-create in live mode, placeholder in dry_run)
    if price_id is None:
        try:
            price_id = ensure_seed_price(api_key, dry_run=dry_run)
        except PriceCreationError as e:
            logger.error(f"Failed to resolve seed Price: {e}")
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

    # Seeded RNG for deterministic status distribution
    rng = random.Random(seed)

    # Track results
    created_customers = 0
    status_counts = {"active": 0, "canceled": 0, "past_due": 0}
    error_count = customer_factory.error_count

    # Track subscriptions per customer for limit enforcement and cancellation scheduling
    customer_subscriptions: dict = {}  # customer_id -> list of sub_ids
    cancellations_per_month: dict = {}  # month -> list of (customer_id, sub_id) to cancel

    # Iterate through batches
    for clock_idx in range(num_clocks):
        # Create clock for this batch with a deterministic name for cleanup
        clock_frozen_time = start_date
        clock_name = f"mrr-seed-clock-{clock_idx:03d}"
        clock = clock_manager.create_clock(clock_frozen_time, name=clock_name)
        clock_id = clock.id if hasattr(clock, "id") else "clock_dryrun_001"

        logger.info(f"Created clock {clock_id} with name {clock_name}")

        # Determine how many customers in this batch (up to 3)
        batch_start = clock_idx * CUSTOMERS_PER_CLOCK
        batch_end = min(batch_start + CUSTOMERS_PER_CLOCK, num_customers)
        batch_size = batch_end - batch_start

        logger.info(f"Processing batch {clock_idx + 1}/{num_clocks} ({batch_size} customers)")

        # Create customers in this batch and their subscriptions
        for cust_idx in range(batch_start, batch_end):
            email = f"mrr-seed-{cust_idx + 1:03d}@example.com"
            name = f"Test Customer {cust_idx + 1:03d}"

            # Check for existing customer
            if customer_factory.check_existing_customer(email):
                logger.info(f"Customer {email} already exists, skipping")
                continue

            # Create customer
            customer = customer_factory.create_customer(email, name, clock_id)
            if not customer:
                error_count += 1
                logger.warning(f"Failed to create customer {email}")
                continue

            created_customers += 1
            customer_id = customer.id if hasattr(customer, "id") else "cus_dryrun_001"
            customer_subscriptions[customer_id] = []

            # Determine status for this customer
            status = determine_customer_status(rng)
            status_counts[status] += 1

            # Attach payment method based on status
            if status == STATUS_PAST_DUE:
                # Past-due customers get the failing card token
                pm_id = "pm_card_chargeCustomerFail"
                pm_result = customer_factory.attach_payment_method(customer_id, pm_id)
                if pm_result:
                    # Set as default payment method for invoicing
                    if customer_factory.set_default_payment_method(customer_id, pm_id):
                        logger.info(
                            f"Customer {customer_id} marked for past-due "
                            f"with pm_card_chargeCustomerFail and set as default"
                        )
                    else:
                        error_count += 1
                        logger.warning(
                            f"Failed to set default payment method for customer {customer_id}; "
                            f"skipping subscription creation"
                        )
                        continue
            else:
                # Active and canceled customers get normal test card
                pm_id = "pm_card_visa"
                pm_result = customer_factory.attach_payment_method(customer_id, pm_id)
                if pm_result:
                    # Set as default payment method for invoicing
                    if customer_factory.set_default_payment_method(customer_id, pm_id):
                        logger.info(f"Customer {customer_id} attached normal payment method")
                    else:
                        error_count += 1
                        logger.warning(
                            f"Failed to set default payment method for customer {customer_id}; "
                            f"skipping subscription creation"
                        )
                        continue

            # Create 1-3 subscriptions per customer (deterministic from RNG)
            num_subs = rng.randint(1, min(3, SUBSCRIPTIONS_PER_CUSTOMER))
            for sub_idx in range(num_subs):
                idempotency_key = f"seed-sub-{customer_id}-{sub_idx}"
                subscription = customer_factory.create_subscription(
                    customer_id=customer_id,
                    price_id=price_id,
                    test_clock_id=clock_id,
                    idempotency_key=idempotency_key,
                )
                if subscription:
                    sub_id = subscription.id if hasattr(subscription, "id") else f"sub_dryrun_{sub_idx}"
                    customer_subscriptions[customer_id].append(sub_id)
                    logger.info(f"Created subscription {sub_id} for customer {customer_id}")

                    # Schedule cancellation for canceled cohort at month 3 or 4
                    if status == STATUS_CANCELED:
                        cancel_month = rng.randint(3, 4)
                        if cancel_month not in cancellations_per_month:
                            cancellations_per_month[cancel_month] = []
                        cancellations_per_month[cancel_month].append((customer_id, sub_id))
                        logger.info(
                            f"Scheduled subscription {sub_id} for cancellation at month {cancel_month}"
                        )
                else:
                    error_count += 1
                    logger.warning(f"Failed to create subscription for customer {customer_id}")

        # Advance clock through time (1 month intervals, 6 total)
        try:
            for month in range(1, 7):
                # Cancel subscriptions scheduled for this month
                if month in cancellations_per_month:
                    for customer_id, sub_id in cancellations_per_month[month]:
                        cancel_result = customer_factory.cancel_subscription(sub_id)
                        if cancel_result:
                            logger.info(f"Canceled subscription {sub_id} at month {month}")
                        else:
                            error_count += 1

                # Advance clock
                days_forward = 30  # ~1 month
                clock_manager.advance_clock(clock_id, days_forward)
                clock_manager.poll_clock_ready(clock_id)
                logger.info(f"Clock {clock_id} advanced to month {month}")
        except ClockTimeoutError as e:
            logger.error(f"Clock timeout for {clock_id}: {e}")
            error_count += 1

    # Print summary
    print_summary(
        num_customers=created_customers,
        active_count=status_counts["active"],
        canceled_count=status_counts["canceled"],
        past_due_count=status_counts["past_due"],
        start_date=start_date,
        end_date=end_date,
        clock_count=num_clocks,
        error_count=error_count,
    )

    return {
        "customer_count": created_customers,
        "active_count": status_counts["active"],
        "canceled_count": status_counts["canceled"],
        "past_due_count": status_counts["past_due"],
        "start_date": start_date,
        "end_date": end_date,
        "clock_count": num_clocks,
        "error_count": error_count,
    }


def cleanup_clocks(api_key: str, dry_run: bool = False) -> None:
    """
    Delete all test clocks matching the seeding pattern.

    Args:
        api_key: Stripe API key
        dry_run: If True, log operations without making API calls
    """
    logger.info("Cleaning up test clocks...")
    clock_manager = ClockManager(api_key, dry_run=dry_run)

    # List clocks matching pattern
    pattern = "mrr-seed-clock-"
    matching_clocks = clock_manager.list_clocks_by_pattern(pattern)

    if not matching_clocks:
        logger.info("No test clocks found matching pattern")
        return

    logger.info(f"Found {len(matching_clocks)} clocks to delete")

    # Prompt for confirmation
    response = input(f"Delete {len(matching_clocks)} test clocks? (y/N): ")
    if response.lower() != "y":
        logger.info("Cleanup canceled")
        return

    # Delete clocks
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
        help="Stripe Price ID to use for subscriptions. If not provided, will create a test price.",
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

    args = parser.parse_args()

    try:
        # Load and validate API key
        api_key = load_api_key(args.api_key)

        if args.cleanup:
            cleanup_clocks(api_key, dry_run=args.dry_run)
        else:
            # Perform seeding
            result = seed_stripe_data(
                api_key=api_key,
                num_customers=args.num_customers,
                seed=args.seed,
                dry_run=args.dry_run,
                price_id=args.price_id,
            )

            # Exit with success
            sys.exit(0)

    except InvalidAPIKeyError as e:
        logger.error(f"API Key Error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
