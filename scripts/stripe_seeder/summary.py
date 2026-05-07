"""Summary output and reporting."""

import logging
from datetime import datetime
from typing import Dict

logger = logging.getLogger(__name__)


def print_summary(
    num_customers: int,
    active_count: int,
    canceled_count: int,
    past_due_count: int,
    start_date: datetime,
    end_date: datetime,
    clock_count: int,
    error_count: int,
) -> None:
    """
    Print a formatted summary of the seeding run.

    Args:
        num_customers: Total customers created
        active_count: Number of active subscriptions
        canceled_count: Number of canceled subscriptions
        past_due_count: Number of past-due subscriptions
        start_date: Start date of the seeding window
        end_date: End date of the seeding window
        clock_count: Number of test clocks created
        error_count: Number of errors encountered
    """
    print("\n" + "=" * 70)
    print("STRIPE TEST DATA SEEDING SUMMARY")
    print("=" * 70)
    print(f"Seeded {num_customers} customers")
    print(f"  Active:    {active_count} ({active_count*100//num_customers if num_customers > 0 else 0}%)")
    print(f"  Canceled:  {canceled_count} ({canceled_count*100//num_customers if num_customers > 0 else 0}%)")
    print(f"  Past Due:  {past_due_count} ({past_due_count*100//num_customers if num_customers > 0 else 0}%)")
    print(f"\nDate range: {start_date.strftime('%b %d, %Y')} – {end_date.strftime('%b %d, %Y')}")
    print(f"Test clocks created: {clock_count}")
    print(f"Errors encountered: {error_count}")
    print("=" * 70 + "\n")
    logger.info(
        f"Seeding complete: {num_customers} customers, "
        f"{active_count} active, {canceled_count} canceled, {past_due_count} past due. "
        f"Errors: {error_count}"
    )
