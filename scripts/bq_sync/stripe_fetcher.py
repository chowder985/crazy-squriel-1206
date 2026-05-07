"""Fetch Stripe data with rate-limit retry logic."""

import logging
import time
from typing import Iterator, Any

import stripe

from .errors import StripeAPIError

logger = logging.getLogger(__name__)

# Rate limit retry configuration (C-48)
MAX_RETRIES = 5
BACKOFF_MULTIPLIER = [1, 2, 4, 8, 16]  # seconds


def _retry_on_rate_limit(fn, *args, **kwargs) -> Any:
    """
    Retry a Stripe API call up to MAX_RETRIES times on rate limit (429).

    On 5th failure (429), logs WARN and returns None (caller skips object).
    On other errors (4xx, 5xx, timeout), raises StripeAPIError (aborts sync).

    Args:
        fn: Stripe API function to call
        *args: Positional args for fn
        **kwargs: Keyword args for fn

    Returns:
        API response or None if rate limit exhausted

    Raises:
        StripeAPIError: On non-429 errors
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except stripe.error.RateLimitError as e:
            if attempt >= MAX_RETRIES:
                logger.warning(f"Rate limit exhausted after {MAX_RETRIES} retries; skipping object")
                return None
            wait_time = BACKOFF_MULTIPLIER[attempt]
            logger.warning(f"Rate limit (429); retry {attempt + 1}/{MAX_RETRIES} after {wait_time}s")
            time.sleep(wait_time)
        except (stripe.error.APIError, stripe.error.APIConnectionError) as e:
            logger.error(f"Stripe API error: {type(e).__name__}: {e}")
            raise StripeAPIError(f"Stripe API error: {e}") from e


def fetch_customers(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all customers from Stripe with pagination (C-45).

    Calls stripe.Customer.list(limit=100) with auto_paging_iter().
    Skips live-mode customers (livemode=True).

    Args:
        api_key: Stripe API key
        dry_run: If True, return empty iterator

    Yields:
        Customer objects (dicts)
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for customers")
        return

    stripe.api_key = api_key
    try:
        for customer in stripe.Customer.list(limit=100).auto_paging_iter():
            if customer.livemode:
                logger.debug(f"Skipping live-mode customer {customer.id}")
                continue
            yield customer
    except Exception as e:
        logger.error(f"Failed to fetch customers: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch customers failed: {e}") from e


def fetch_subscriptions(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all subscriptions from Stripe with price expansion (C-46).

    Calls stripe.Subscription.list(limit=100, expand=['items.data.price']).
    Validates len(items) >= 1 before processing.

    Args:
        api_key: Stripe API key
        dry_run: If True, return empty iterator

    Yields:
        Subscription objects (dicts)
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for subscriptions")
        return

    stripe.api_key = api_key
    try:
        for subscription in stripe.Subscription.list(
            limit=100,
            expand=["items.data.price"]
        ).auto_paging_iter():
            if subscription.livemode:
                logger.debug(f"Skipping live-mode subscription {subscription.id}")
                continue

            # Validate items (C-46)
            if not subscription.items or len(subscription.items.data) == 0:
                logger.warning(f"Subscription {subscription.id} has no items; skipping")
                continue

            yield subscription
    except Exception as e:
        logger.error(f"Failed to fetch subscriptions: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch subscriptions failed: {e}") from e


def fetch_invoices(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all invoices from Stripe (C-47).

    Calls stripe.Invoice.list(limit=100) with auto_paging_iter().

    Args:
        api_key: Stripe API key
        dry_run: If True, return empty iterator

    Yields:
        Invoice objects (dicts)
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for invoices")
        return

    stripe.api_key = api_key
    try:
        for invoice in stripe.Invoice.list(limit=100).auto_paging_iter():
            if invoice.livemode:
                logger.debug(f"Skipping live-mode invoice {invoice.id}")
                continue
            yield invoice
    except Exception as e:
        logger.error(f"Failed to fetch invoices: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch invoices failed: {e}") from e
