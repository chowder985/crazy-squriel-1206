"""
Live-API smoke tests for Sprint 1.

These tests exercise the actual Stripe API against the user's sk_test_* key.
They are gated by the RUN_LIVE_TESTS=1 environment variable. When unset,
they are SKIPPED.

Usage:
    RUN_LIVE_TESTS=1 STRIPE_API_KEY=sk_test_... pytest scripts/tests/test_live_smoke.py -v

Always cleans up created resources where possible.
"""

import logging
import os
import pytest
import stripe
import time

from stripe_seeder.clock_manager import ClockManager
from stripe_seeder.errors import ClockTimeoutError
from stripe_seeder.price_manager import ensure_seed_price

logger = logging.getLogger(__name__)


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="Live smoke tests require RUN_LIVE_TESTS=1 and a real STRIPE_API_KEY",
)


@pytest.fixture
def api_key():
    key = os.environ.get("STRIPE_API_KEY")
    if not key or not key.startswith("sk_test_"):
        pytest.skip("STRIPE_API_KEY missing or not a test key")
    return key


def test_smoke_ensure_seed_price_idempotent(api_key):
    """C-31: Calling ensure_seed_price twice returns the same Price ID."""
    first = ensure_seed_price(api_key, dry_run=False)
    second = ensure_seed_price(api_key, dry_run=False)
    assert first == second, "ensure_seed_price should be idempotent"
    # Note: No cleanup here — leaving the seed product/price is intentional.
    # Subsequent seeding runs and CI smoke runs reuse it.


def test_smoke_subscription_create_with_resolved_price(api_key):
    """C-31 (tightened): Resolved Price + attach + default-PM set + subscription create."""
    stripe.api_key = api_key
    price_id = ensure_seed_price(api_key, dry_run=False)

    # Create a fresh test clock for isolation.
    clock = stripe.test_helpers.TestClock.create(
        frozen_time=int(time.time()),
        name="mrr-seed-smoke-clock",
    )
    clock_manager = ClockManager(api_key, dry_run=False)
    customer = None
    try:
        # Create a fresh customer with NO payment method (C-32 requirement).
        # Use a unique email per run to avoid collisions on re-runs.
        unique_email = f"smoke-test-{int(time.time())}@example.com"
        customer = stripe.Customer.create(
            email=unique_email,
            name="Smoke Test Customer",
            test_clock=clock.id,
        )

        # Attach a test card payment method (C-32 requirement).
        pm = stripe.PaymentMethod.attach(
            "pm_card_visa",
            customer=customer.id,
        )

        # Set the payment method as default for invoicing (C-32 requirement).
        stripe.Customer.modify(
            customer.id,
            invoice_settings={"default_payment_method": pm.id},
        )

        # Create a subscription using the resolved Price.
        # No clock advancement needed for this smoke test; the resolved price
        # is all that's needed to verify the end-to-end flow (C-31).
        sub = stripe.Subscription.create(
            customer=customer.id,
            items=[{"price": price_id}],
        )
        assert sub.status in {"active", "trialing", "incomplete"}, (
            f"Expected active/trialing/incomplete subscription, got {sub.status}"
        )
    finally:
        # Cleanup: poll clock to ensure it's ready before deletion (hygiene + safety).
        # If clock is still advancing, wait for it to complete before deleting.
        try:
            clock_manager.poll_clock_ready(clock.id)
        except ClockTimeoutError:
            # Best-effort: log warning and continue with deletion anyway.
            logger.warning(f"Clock {clock.id} did not reach ready before cleanup timeout")

        # Delete the test clock (cascades to customer + subscription).
        stripe.test_helpers.TestClock.delete(clock.id)
