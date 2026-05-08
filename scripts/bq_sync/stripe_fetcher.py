"""Fetch Stripe data with rate-limit retry logic.

Iter-4 note (2026-05-07): Stripe's *list* endpoints exclude objects attached
to a Test Clock by default. ``stripe.Customer.list()`` and
``stripe.Subscription.list()`` only return non-test-clock objects unless a
``test_clock=<clock_id>`` filter is passed; ``stripe.Invoice.list()`` does
not accept ``test_clock`` at all and must be filtered by ``customer=<cid>``
to capture test-clock invoices. The Sprint 1 iter-13 contract note flagged
this for downstream sprints; iter-4 implements the fix here:

- ``_list_test_clock_ids()`` enumerates all test clocks once.
- ``fetch_customers()`` unions the default list with per-clock list (deduped).
- ``fetch_subscriptions()`` does the same, plus ``status='all'`` so canceled
  v0 subscriptions from Sprint 1 iter-14 cancel-and-recreate tier changes
  are included (default ``status`` excludes canceled).
- ``fetch_invoices()`` unions the default list with a per-customer list, where
  the customer set comes from the same test-clock-aware enumeration.
"""

import logging
import time
from typing import Any, Iterator, List, Set

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


def _list_test_clock_ids(api_key: str) -> List[str]:
    """Return the IDs of every test clock in the Stripe account (iter-4).

    Stripe's *list* endpoints exclude test-clock-attached objects unless the
    caller passes ``test_clock=<clock_id>``. This helper lets the per-entity
    fetchers union the default list with per-clock lists.
    """
    stripe.api_key = api_key
    try:
        return [
            clock.id
            for clock in stripe.test_helpers.TestClock.list(limit=100).auto_paging_iter()
        ]
    except Exception as e:
        logger.error(f"Failed to list test clocks: {type(e).__name__}: {e}")
        raise StripeAPIError(f"List test clocks failed: {e}") from e


def fetch_customers(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all customers from Stripe with pagination (C-45).

    Issues the default ``stripe.Customer.list(limit=100)`` AND a per-test-clock
    ``stripe.Customer.list(limit=100, test_clock=<id>)`` for every test clock
    in the account, deduplicating by ``customer.id``. This is required because
    Stripe omits test-clock customers from the default list (see iter-4 note
    at module top).

    Skips live-mode customers (livemode=True).
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for customers")
        return

    stripe.api_key = api_key
    seen: Set[str] = set()
    try:
        # Default scope (non-test-clock customers).
        for customer in stripe.Customer.list(limit=100).auto_paging_iter():
            if customer.livemode:
                logger.debug(f"Skipping live-mode customer {customer.id}")
                continue
            if customer.id in seen:
                continue
            seen.add(customer.id)
            yield customer

        # Per-test-clock scope.
        for clock_id in _list_test_clock_ids(api_key):
            for customer in stripe.Customer.list(
                limit=100, test_clock=clock_id
            ).auto_paging_iter():
                if customer.livemode:
                    continue
                if customer.id in seen:
                    continue
                seen.add(customer.id)
                yield customer
    except StripeAPIError:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch customers: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch customers failed: {e}") from e


def fetch_subscriptions(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all subscriptions from Stripe with price expansion (C-46).

    Calls stripe.Subscription.list(limit=100, status='all',
    expand=['data.items.data.price']) for both the default scope and each
    test clock, deduplicating by ``subscription.id``. ``status='all'`` is
    required to include canceled v0 subscriptions from Sprint 1 iter-14
    cancel-and-recreate tier changes.

    The outer ``data.`` prefix on the expand path is required by Stripe's
    *list* endpoint (the response wraps the page in ``data: [...]``); the
    bare ``items.data.price`` form is only valid on retrieve.

    Validates ``len(items) >= 1`` before yielding (C-46).
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for subscriptions")
        return

    stripe.api_key = api_key
    seen: Set[str] = set()

    def _consume(iterable):
        for subscription in iterable:
            if subscription.livemode:
                logger.debug(f"Skipping live-mode subscription {subscription.id}")
                continue
            # Stripe's Subscription object extends dict; ``subscription.items``
            # returns the inherited ``dict.items`` method, NOT the
            # SubscriptionItemList. Use bracket access for real Stripe
            # objects, falling back to attribute access for unit-test mocks.
            if isinstance(subscription, dict):
                sub_items = subscription.get("items")
                sub_items_data = sub_items.get("data") if isinstance(sub_items, dict) else None
            else:
                sub_items = getattr(subscription, "items", None)
                sub_items_data = getattr(sub_items, "data", None) if sub_items is not None else None
            if not sub_items_data or len(sub_items_data) == 0:
                logger.warning(
                    f"Subscription {subscription.id} has no items; skipping"
                )
                continue
            if subscription.id in seen:
                continue
            seen.add(subscription.id)
            yield subscription

    try:
        # Default scope.
        yield from _consume(
            stripe.Subscription.list(
                limit=100,
                status="all",
                expand=["data.items.data.price"],
            ).auto_paging_iter()
        )

        # Per-test-clock scope.
        for clock_id in _list_test_clock_ids(api_key):
            yield from _consume(
                stripe.Subscription.list(
                    limit=100,
                    status="all",
                    expand=["data.items.data.price"],
                    test_clock=clock_id,
                ).auto_paging_iter()
            )
    except StripeAPIError:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch subscriptions: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch subscriptions failed: {e}") from e


def fetch_invoices(api_key: str, dry_run: bool = False) -> Iterator[dict]:
    """
    Fetch all invoices from Stripe (C-47).

    ``stripe.Invoice.list`` does NOT accept a ``test_clock`` filter, so to
    capture test-clock invoices we must filter by ``customer=<cid>``. This
    function unions the default-scope list with per-customer lists, where
    the customer set is enumerated via the same test-clock-aware logic as
    ``fetch_customers()`` (default + per-clock customers, deduped).
    """
    if dry_run:
        logger.info("Dry-run: skipping Stripe API fetch for invoices")
        return

    stripe.api_key = api_key
    seen_invoices: Set[str] = set()
    seen_customers: Set[str] = set()
    try:
        # Default invoice scope (non-test-clock).
        for invoice in stripe.Invoice.list(limit=100).auto_paging_iter():
            if invoice.livemode:
                logger.debug(f"Skipping live-mode invoice {invoice.id}")
                continue
            if invoice.id in seen_invoices:
                continue
            seen_invoices.add(invoice.id)
            yield invoice

        # Build a customer set covering both default and test-clock scopes.
        for customer in stripe.Customer.list(limit=100).auto_paging_iter():
            if customer.livemode:
                continue
            seen_customers.add(customer.id)
        for clock_id in _list_test_clock_ids(api_key):
            for customer in stripe.Customer.list(
                limit=100, test_clock=clock_id
            ).auto_paging_iter():
                if customer.livemode:
                    continue
                seen_customers.add(customer.id)

        # Per-customer invoice scope (covers test-clock invoices).
        for cid in seen_customers:
            for invoice in stripe.Invoice.list(
                limit=100, customer=cid
            ).auto_paging_iter():
                if invoice.livemode:
                    continue
                if invoice.id in seen_invoices:
                    continue
                seen_invoices.add(invoice.id)
                yield invoice
    except StripeAPIError:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch invoices: {type(e).__name__}: {e}")
        raise StripeAPIError(f"Fetch invoices failed: {e}") from e
