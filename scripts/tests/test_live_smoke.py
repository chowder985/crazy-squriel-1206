"""
Live-API smoke tests for Sprint 1.

These tests exercise the actual Stripe API against the user's sk_test_* key.
They are gated by the RUN_LIVE_TESTS=1 environment variable. When unset,
they are SKIPPED.

Usage:
    RUN_LIVE_TESTS=1 STRIPE_API_KEY=sk_test_... pytest scripts/tests/test_live_smoke.py -v

Always cleans up created resources where possible.
"""

import os
import pytest
import stripe
import time

from stripe_seeder.price_manager import ensure_seed_price


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
    customer = None
    try:
        # Create a fresh customer with NO payment method (C-32 requirement).
        customer = stripe.Customer.create(
            email="smoke-test@example.com",
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

        # Advance the clock 1 month to generate invoices.
        stripe.test_helpers.TestClock.advance(
            clock.id,
            frozen_time=int(time.time()) + 2592000,
        )

        # Create a subscription using the resolved Price.
        sub = stripe.Subscription.create(
            customer=customer.id,
            items=[{"price": price_id}],
        )
        assert sub.status in {"active", "trialing", "incomplete"}, (
            f"Expected active/trialing/incomplete subscription, got {sub.status}"
        )
    finally:
        # Cleanup: delete the test clock (cascades to customer + subscription).
        stripe.test_helpers.TestClock.delete(clock.id)
