"""Reset functionality for clearing seed-pattern data before re-seeding."""

import logging
from typing import Dict

import stripe

logger = logging.getLogger(__name__)


def reset_seed_data(api_key: str, dry_run: bool = False) -> Dict[str, int]:
    """
    Delete all test clocks and customers matching seed patterns.

    Scope:
    - Deletes test clocks with names matching: 'mrr-seed-clock-*', 'mrr-seed-smoke-clock', 'mrr-smoke-clock-*'
    - Deletes customers with emails matching: 'mrr-seed-*@example.com', 'smoke-test-*@example.com'
    - Does NOT delete the seed Product or Price (metadata 'mrr-seed-plan: true')
    - Does NOT delete unrelated test clocks or customers

    Args:
        api_key: Stripe API key
        dry_run: If True, log operations without making API calls

    Returns:
        Dict with keys 'clocks_deleted', 'customers_deleted', 'errors' and their counts
    """
    logger.info("RESET MODE: deleting all mrr-seed-* clocks and matching customers before seeding...")

    clocks_deleted = 0
    customers_deleted = 0
    errors = 0

    if dry_run:
        logger.info("[DRY RUN] Would reset all seed pattern data")
        return {"clocks_deleted": 0, "customers_deleted": 0, "errors": 0}

    stripe.api_key = api_key

    # Step 1: Delete test clocks matching seed patterns
    try:
        clocks = stripe.test_helpers.TestClock.list(limit=100, api_key=api_key)
        for clock in clocks:
            # Match patterns: 'mrr-seed-clock-*', 'mrr-seed-smoke-clock', 'mrr-smoke-clock-*'
            if hasattr(clock, "name") and clock.name:
                if (
                    clock.name.startswith("mrr-seed-clock-")
                    or clock.name == "mrr-seed-smoke-clock"
                    or clock.name.startswith("mrr-smoke-clock-")
                ):
                    try:
                        stripe.test_helpers.TestClock.delete(clock.id, api_key=api_key)
                        clocks_deleted += 1
                        logger.info(f"Deleted clock {clock.id} (name={clock.name})")
                    except stripe.error.StripeError as e:
                        if "No such test clock" in str(e) or "not found" in str(e).lower():
                            # Clock was already deleted (idempotent)
                            logger.debug(f"Clock {clock.id} already deleted: {e}")
                            clocks_deleted += 1
                        else:
                            logger.warning(f"Error deleting clock {clock.id}: {e}")
                            errors += 1
    except stripe.error.StripeError as e:
        logger.warning(f"Error listing clocks: {e}")
        errors += 1

    # Step 2: Delete customers matching seed patterns
    # Note: Customer deletion via clock is automatic; we clean up any stragglers
    try:
        # Use Customer.search for pattern matching (available in recent Stripe API versions)
        # Fallback to list + client-side filter if search is not available
        try:
            customers = stripe.Customer.search(
                query="email~'mrr-seed-' OR email~'smoke-test-'",
                limit=100,
                api_key=api_key,
            )
        except (AttributeError, stripe.error.StripeError):
            # Fallback to list + filter
            all_customers = stripe.Customer.list(limit=100, api_key=api_key)
            customers = [
                c
                for c in all_customers
                if hasattr(c, "email")
                and c.email
                and ("mrr-seed-" in c.email or "smoke-test-" in c.email)
            ]

        for customer in customers:
            try:
                stripe.Customer.delete(customer.id, api_key=api_key)
                customers_deleted += 1
                logger.info(f"Deleted customer {customer.id} (email={customer.email})")
            except stripe.error.StripeError as e:
                if "No such customer" in str(e) or "not found" in str(e).lower():
                    # Customer was already deleted (idempotent)
                    logger.debug(f"Customer {customer.id} already deleted: {e}")
                    customers_deleted += 1
                else:
                    logger.warning(f"Error deleting customer {customer.id}: {e}")
                    errors += 1
    except stripe.error.StripeError as e:
        logger.warning(f"Error listing/searching customers: {e}")
        errors += 1

    logger.info(
        f"Reset complete: {clocks_deleted} clocks deleted, "
        f"{customers_deleted} customers deleted, {errors} errors"
    )

    return {
        "clocks_deleted": clocks_deleted,
        "customers_deleted": customers_deleted,
        "errors": errors,
    }
