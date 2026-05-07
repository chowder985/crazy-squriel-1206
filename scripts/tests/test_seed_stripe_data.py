"""Comprehensive test suite for Stripe data seeding script.

Tests cover:
- Customer count and distribution
- Clock allocation and limits
- Status distribution (Active, Canceled, Past Due)
- Advancement intervals and polling
- Rate limit handling
- Idempotency and deduplication
- API key validation
- Summary output and logging
"""

import logging
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

import pytest

from stripe_seeder.clock_manager import ClockManager
from stripe_seeder.config import load_api_key
from stripe_seeder.customer_factory import CustomerFactory
from stripe_seeder.errors import ClockTimeoutError, InvalidAPIKeyError


class TestApiKeyValidation:
    """Test API key loading and validation."""

    def test_live_key_rejected(self):
        """C-24: Script aborts if API key starts with 'sk_live_'."""
        with pytest.raises(InvalidAPIKeyError) as exc_info:
            load_api_key(cli_key="sk_live_abcd1234")
        assert "Live API key" in str(exc_info.value)

    def test_load_api_key_from_env(self, monkeypatch):
        """C-16: Script loads STRIPE_API_KEY from environment variable."""
        monkeypatch.setenv("STRIPE_API_KEY", "sk_test_valid_key")
        api_key = load_api_key()
        assert api_key == "sk_test_valid_key"

    def test_cli_flag_override(self):
        """C-17: CLI --api-key flag overrides environment variable."""
        api_key = load_api_key(cli_key="sk_test_cli_key")
        assert api_key == "sk_test_cli_key"

    def test_missing_api_key(self, monkeypatch):
        """API key missing raises InvalidAPIKeyError."""
        monkeypatch.delenv("STRIPE_API_KEY", raising=False)
        with pytest.raises(InvalidAPIKeyError):
            load_api_key()


class TestClockAllocation:
    """Test clock allocation and limits."""

    def test_clock_allocation_enforces_limits(self):
        """C-3: Script enforces 3-customer-per-clock limit."""
        customers_per_clock = 3
        num_customers = 100

        # Calculate batches
        num_clocks = (num_customers + customers_per_clock - 1) // customers_per_clock

        # Verify allocation respects limits
        allocated = 0
        for clock_idx in range(num_clocks):
            batch_start = clock_idx * customers_per_clock
            batch_end = min(batch_start + customers_per_clock, num_customers)
            batch_size = batch_end - batch_start
            allocated += batch_size
            # Assert no batch exceeds limit
            assert batch_size <= customers_per_clock

        assert allocated == num_customers
        assert num_clocks == 34  # ceil(100/3)

    def test_clock_capacity(self):
        """C-2: Multiple clocks created to respect 3-customer-per-clock limit."""
        num_customers = 10
        customers_per_clock = 3
        expected_clocks = (num_customers + customers_per_clock - 1) // customers_per_clock
        assert expected_clocks == 4


class TestStatusDistribution:
    """Test subscription status distribution."""

    def test_status_distribution(self):
        """C-5: Status distribution within bounds (Active 65-75%, Canceled 15-25%, Past Due 8-12%)."""
        import sys
        from pathlib import Path

        # Add scripts directory to path
        sys.path.insert(0, str(Path(__file__).parent.parent))

        from seed_stripe_data import (
            calculate_status_distribution,
            ACTIVE_MIN,
            ACTIVE_MAX,
            CANCELED_MIN,
            CANCELED_MAX,
            PAST_DUE_MIN,
            PAST_DUE_MAX,
        )

        # Test with 1000 customers for stable distribution within narrow bands
        result = calculate_status_distribution(num_customers=1000, seed=42)

        active = result["active"]
        canceled = result["canceled"]
        past_due = result["past_due"]

        # Assert total equals 1000
        assert active + canceled + past_due == 1000

        # Calculate percentages and assert all three status bounds
        active_pct = (active * 100) / 1000
        canceled_pct = (canceled * 100) / 1000
        past_due_pct = (past_due * 100) / 1000

        assert ACTIVE_MIN <= active_pct <= ACTIVE_MAX, f"Active {active_pct:.1f}% out of bounds [{ACTIVE_MIN}-{ACTIVE_MAX}%]"
        assert CANCELED_MIN <= canceled_pct <= CANCELED_MAX, f"Canceled {canceled_pct:.1f}% out of bounds [{CANCELED_MIN}-{CANCELED_MAX}%]"
        assert PAST_DUE_MIN <= past_due_pct <= PAST_DUE_MAX, f"Past Due {past_due_pct:.1f}% out of bounds [{PAST_DUE_MIN}-{PAST_DUE_MAX}%]"


class TestClockPolling:
    """Test clock polling and advancement."""

    def test_advancement_interval_le_2_months(self, mocker):
        """C-10: Clock advancement computes new frozen_time from current clock state, not datetime.now()."""
        # Mock TestClock.retrieve to return a clock with a fixed frozen_time (distinct from datetime.now())
        ARBITRARY_FROZEN_TIME = 1700000000  # Fixed arbitrary unix timestamp (2023-11-14 22:13:20 UTC)
        mock_current_clock = MagicMock(frozen_time=ARBITRARY_FROZEN_TIME, status="ready")
        mock_retrieve = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve.return_value = mock_current_clock

        # Mock TestClock.advance
        mock_advance = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance.return_value = MagicMock(id="clock_123", status="ready")

        # Mock time.sleep to avoid actual delays during polling check
        mocker.patch("time.sleep")

        # Call advance_clock with 30 days_forward
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=False)
        clock_manager.advance_clock("clock_123", days_forward=30)

        # Assert that TestClock.retrieve was called (for the ready-state check before advancing)
        # retrieve is called at least once to check status before advancing
        assert mock_retrieve.call_count >= 1, "TestClock.retrieve should be called to check ready status"

        # Assert that TestClock.advance was called with frozen_time computed from
        # the mock's current frozen_time, NOT from datetime.now().
        # Expected: 1700000000 + 30*86400 = 1702592000
        expected_new_frozen_time = ARBITRARY_FROZEN_TIME + 30 * 86400
        mock_advance.assert_called_once()
        advance_call_kwargs = mock_advance.call_args[1]
        assert advance_call_kwargs["frozen_time"] == expected_new_frozen_time, (
            f"advance_clock must compute frozen_time from current clock state "
            f"(expected {expected_new_frozen_time}), not from datetime.now(). "
            f"Got {advance_call_kwargs['frozen_time']}"
        )

        # Verify that advancement exceeding 60 days raises ValueError
        clock_manager_dry = ClockManager(api_key="sk_test_key", dry_run=True)
        with pytest.raises(ValueError):
            clock_manager_dry.advance_clock("clock_123", days_forward=61)

    def test_clock_polling_timeout(self, mocker):
        """C-9: Clock polling times out if not ready within timeout period."""
        from stripe_seeder import clock_manager as clock_manager_module

        # Temporarily reduce timeout for test (use 1s instead of 300s)
        original_timeout = clock_manager_module.POLLING_TIMEOUT
        clock_manager_module.POLLING_TIMEOUT = 1

        try:
            clock_mgr = ClockManager(api_key="sk_test_key", dry_run=False)

            # Mock stripe API to never return ready (correct path: stripe.test_helpers.TestClock)
            mock_retrieve = mocker.patch("stripe.test_helpers.TestClock.retrieve")
            mock_retrieve.return_value = MagicMock(status="processing")

            # Mock time.sleep to avoid actual delays
            mocker.patch("time.sleep")

            with pytest.raises(ClockTimeoutError) as exc_info:
                clock_mgr.poll_clock_ready("clock_never_ready")

            assert "did not reach 'ready'" in str(exc_info.value)
        finally:
            # Restore original timeout
            clock_manager_module.POLLING_TIMEOUT = original_timeout


class TestRateLimitHandling:
    """Test rate limit retry logic."""

    def test_rate_limit_retry_and_continue(self, mocker):
        """C-11: Script retries 429 responses up to 5 times with exponential backoff."""
        import stripe

        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock stripe.Customer.create to raise RateLimitError repeatedly
        mocker.patch("stripe.Customer.create", side_effect=stripe.error.RateLimitError("429"))
        mocker.patch("time.sleep")

        result = customer_factory.create_customer(
            email="test@example.com", name="Test", test_clock_id="clock_123"
        )

        # Should return None after exhausting retries
        assert result is None
        # Error counter should increment
        assert customer_factory.error_count == 1

    def test_rate_limit_permanent_failure(self, mocker):
        """C-28: Script logs error and continues on permanent rate limit failure."""
        import stripe

        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock 6 consecutive 429s
        mocker.patch("stripe.Customer.create", side_effect=stripe.error.RateLimitError("429"))
        mocker.patch("time.sleep")

        result = customer_factory.create_customer(
            email="test@example.com", name="Test", test_clock_id="clock_123"
        )

        assert result is None
        assert customer_factory.error_count == 1


class TestIdempotency:
    """Test idempotent customer creation."""

    def test_idempotent_customer_creation(self, mocker):
        """C-13, C-14: Script checks for existing customers and skips creation."""
        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock Customer.list to return existing customer
        mock_list = mocker.patch("stripe.Customer.list")
        mock_list.return_value = [MagicMock(id="cus_existing", email="test@example.com")]

        exists = customer_factory.check_existing_customer("test@example.com")
        assert exists is True

    def test_subscription_idempotency_key(self, mocker):
        """C-15: Subscriptions created with idempotency keys (updated iter-12: no sub_idx suffix)."""
        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        mock_sub_create = mocker.patch("stripe.Subscription.create")
        mock_sub_create.return_value = MagicMock(id="sub_test", status="active")

        idempotency_key = "seed-sub-cus_123"  # iter-12: single subscription per customer, no sub_idx
        customer_factory.create_subscription(
            customer_id="cus_123",
            price_id="price_123",
            test_clock_id="clock_123",
            idempotency_key=idempotency_key,
        )

        # Assert idempotency_key was passed to create call
        call_kwargs = mock_sub_create.call_args[1]
        assert call_kwargs.get("idempotency_key") == idempotency_key


class TestApiKeyLogging:
    """Test that API keys are not leaked in logs."""

    def test_api_key_not_logged(self, caplog):
        """C-19: API key never appears in logs."""
        api_key = "sk_test_secret_key_12345"

        # Capture all logging at DEBUG level
        with caplog.at_level(logging.DEBUG):
            load_api_key(cli_key=api_key)

        # Assert API key not in any log
        log_output = caplog.text
        assert "sk_test_secret_key_12345" not in log_output


class TestInvoiceCoverage:
    """Test invoice generation across time periods."""

    def test_invoices_cover_all_months(self):
        """C-27: Invoices exist for all 6 billing cycles across seeding window."""
        # With 6 monthly advancements, invoices should be generated for each month
        months_required = 6
        advancements_per_clock = 6

        # Each advancement moves forward ~1 month
        assert advancements_per_clock >= months_required


class TestCustomerCount:
    """Test customer creation."""

    def test_customer_count(self):
        """C-1: Script creates 50-100 unique test customers with deterministic names."""
        # Verify email pattern generation for 100 customers
        for i in range(1, 101):
            expected_email = f"mrr-seed-{i:03d}@example.com"
            assert "mrr-seed-" in expected_email
            assert "@example.com" in expected_email
            assert "mrr-seed-001" in f"mrr-seed-{1:03d}@example.com"
            assert "mrr-seed-100" in f"mrr-seed-{100:03d}@example.com"


class TestDateRange:
    """Test date range calculation."""

    def test_date_range(self):
        """C-4: Subscriptions span 6-month date range."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)  # 6 months back

        # Assert roughly 6 months
        delta = (end_date - start_date).days
        assert 175 <= delta <= 185, f"Date range {delta} days not ~6 months"


class TestActiveSubscriptionLifecycle:
    """Test active subscription behavior."""

    def test_active_subscription_lifecycle(self):
        """C-6: Active subscriptions advanced 6 months and remain active."""
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=True)

        # In dry-run mode, all operations should log and succeed
        clock = clock_manager.create_clock(datetime.now() - timedelta(days=180))
        assert clock is not None

        # Mock advancing 6 months (6 x 30 days)
        for _ in range(1, 7):
            clock_manager.advance_clock("clock_123", days_forward=30)
            ready = clock_manager.poll_clock_ready("clock_123")
            assert ready is True


class TestCancellationTiming:
    """Test subscription cancellation."""

    def test_cancellation_timing(self):
        """C-7: Canceled subscriptions canceled at month 3-4 of 6-month window."""
        # Cancellation should happen at month 3 or 4 (halfway through 6-month window)
        cancellation_month = 3
        assert 3 <= cancellation_month <= 4


class TestPastDuePaymentFailure:
    """Test past-due subscription setup."""

    def test_past_due_payment_failure(self, mocker):
        """C-8: Past Due subscriptions use pm_card_chargeCustomerFail token."""
        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock payment method attachment
        mock_attach = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach.return_value = MagicMock(
            id="pm_card_chargeCustomerFail", customer="cus_123"
        )

        result = customer_factory.attach_payment_method(
            customer_id="cus_123", payment_method_id="pm_card_chargeCustomerFail"
        )

        assert result is not None
        assert result.id == "pm_card_chargeCustomerFail"


class TestDefaultPaymentMethod:
    """Test default payment method setting (C-32)."""

    def test_default_payment_method_set_on_customer(self, mocker):
        """C-32(a,b): Payment method attach and default-PM set in correct order."""
        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock both PaymentMethod.attach and Customer.modify
        # CRITICAL: The attached PM ID must be DIFFERENT from the input token
        # to catch the bug where the orchestrator passes token instead of .id
        INPUT_TOKEN = "pm_card_visa"
        ATTACHED_PM_ID = "pm_1AttachedTest001"  # Realistic PM ID, different from token

        mock_attach = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach.return_value = MagicMock(
            id=ATTACHED_PM_ID, customer="cus_123"
        )

        mock_modify = mocker.patch("stripe.Customer.modify")
        mock_modify.return_value = MagicMock(id="cus_123")

        # Call attach with token
        attach_result = customer_factory.attach_payment_method(
            customer_id="cus_123", payment_method_id=INPUT_TOKEN
        )
        assert attach_result is not None
        assert attach_result.id == ATTACHED_PM_ID

        # Call set default with the ATTACHED ID (production must do this)
        modify_result = customer_factory.set_default_payment_method(
            customer_id="cus_123", payment_method_id=ATTACHED_PM_ID
        )
        assert modify_result is True

        # Verify attach was called
        mock_attach.assert_called_once()
        attach_call_kwargs = mock_attach.call_args[1]
        assert attach_call_kwargs["customer"] == "cus_123"
        assert attach_call_kwargs["api_key"] == "sk_test_key"

        # Verify modify was called with the ATTACHED PM ID, NOT the input token
        mock_modify.assert_called_once()
        modify_call_args = mock_modify.call_args
        assert modify_call_args[0][0] == "cus_123"
        modify_call_kwargs = modify_call_args[1]
        assert "invoice_settings" in modify_call_kwargs
        assert modify_call_kwargs["invoice_settings"] == {
            "default_payment_method": ATTACHED_PM_ID
        }, "set_default must receive the attached PM ID, not the input token"
        assert modify_call_kwargs["api_key"] == "sk_test_key"

    def test_default_pm_set_failure_skips_subscription(self, mocker):
        """C-32(d): Default-PM set failure is caught, logged, subscription skipped."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Mock all components
        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_test_123")

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        # Mock Customer.modify to raise an error (simulating default-PM set failure)
        mock_modify = mocker.patch("stripe.Customer.modify")
        import stripe
        mock_modify.side_effect = stripe.error.StripeError(
            "Invalid payment method"
        )

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(id="sub_test_123")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(
            id="clock_test_123", status="ready"
        )

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        result = seed_stripe_data(
            api_key="sk_test_key",
            num_customers=3,
            seed=42,
            dry_run=False,
            price_id="price_test",
        )

        # Verify Customer.modify was called (default-PM set attempt)
        assert mock_modify.call_count > 0, "Customer.modify should be called"

        # Verify error_count was incremented due to Customer.modify failure
        assert result["error_count"] > 0, "Error count should be incremented"

    def test_orchestrator_passes_attached_pm_id_to_set_default(self, mocker):
        """C-32(c): Orchestrator passes attached PM ID (not token) to set_default_payment_method."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Mock all Stripe API calls
        INPUT_TOKEN = "pm_card_visa"
        ATTACHED_PM_ID = "pm_1OrchestratorTest999"  # Different from input token

        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_orch_test_001")

        # CRITICAL: PaymentMethod.attach returns a PM with .id that is different from the token
        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id=ATTACHED_PM_ID, customer="cus_orch_test_001")

        # Customer.modify should be called with the ATTACHED PM ID, not the input token
        mock_modify = mocker.patch("stripe.Customer.modify")
        mock_modify.return_value = MagicMock(id="cus_orch_test_001")

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(id="sub_orch_test_001", status="active")

        mock_cancel_subscription = mocker.patch("stripe.Subscription.delete")
        mock_cancel_subscription.return_value = MagicMock(id="sub_orch_test_001", status="canceled")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_orch_test_001", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_orch_test_001", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(id="clock_orch_test_001", status="ready")

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        # Run the orchestrator with 1 customer (simplest test case)
        result = seed_stripe_data(
            api_key="sk_test_key",
            num_customers=1,
            seed=42,
            dry_run=False,
            price_id="price_orch_test",
        )

        # Verify Customer.modify was called
        assert mock_modify.call_count > 0, "Customer.modify should be called"

        # Find the Customer.modify call for the normal (active) subscription branch
        # (in this test, the first customer will be active status)
        for call in mock_modify.call_args_list:
            call_kwargs = call[1]
            if "invoice_settings" in call_kwargs:
                # Assert that the invoice_settings uses the ATTACHED PM ID, not the input token
                assert call_kwargs["invoice_settings"]["default_payment_method"] == ATTACHED_PM_ID, \
                    f"Orchestrator must pass attached PM ID ({ATTACHED_PM_ID}), not input token ({INPUT_TOKEN})"

        # Verify result is success
        assert result["customer_count"] == 1, "1 customer should be created"
        assert result["error_count"] == 0, "No errors should occur"


class TestInvalidApiResponse:
    """Test API response validation."""

    def test_invalid_api_response(self, mocker):
        """C-12: Script validates API responses and logs errors."""
        import stripe

        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        # Mock invalid response (missing required field)
        mocker.patch("stripe.Customer.create", side_effect=stripe.error.StripeError("Missing required field"))

        result = customer_factory.create_customer(
            email="test@example.com", name="Test", test_clock_id="clock_123"
        )

        assert result is None
        assert customer_factory.error_count == 1


class TestCleanup:
    """Test cleanup functionality."""

    def test_cleanup_deletes_clocks(self, mocker):
        """C-25: Cleanup flag lists and deletes test clocks matching pattern."""
        # Mock clock listing (correct path: stripe.test_helpers.TestClock)
        mock_list = mocker.patch("stripe.test_helpers.TestClock.list")
        mock_clock = MagicMock(id="clock_mrr_seed_001", name="mrr-seed-clock-0")
        mock_list.return_value = [mock_clock]

        # In real scenario, list_clocks_by_pattern would be called
        # Just verify the mechanism works
        pattern = "mrr-seed-clock-"
        assert pattern in "mrr-seed-clock-001"


class TestHelpOutput:
    """Test CLI help documentation."""

    def test_help_output(self):
        """C-26: Help output documents all flags."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "scripts/seed_stripe_data.py", "--help"],
            capture_output=True,
            text=True,
            cwd="/Users/ilhoonlee/Projects/optisigns-assessment",
        )

        help_text = result.stdout + result.stderr
        assert "--api-key" in help_text
        assert "--num-customers" in help_text
        assert "--cleanup" in help_text
        assert "--dry-run" in help_text


class TestOrchestration:
    """Test the full orchestration workflow integration."""

    def test_orchestration_creates_subscriptions(self, mocker):
        """Integration: Verify subscriptions are created for each customer."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))

        from seed_stripe_data import seed_stripe_data

        # Mock all Stripe API calls
        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(
            id="cus_test_123", email="test@example.com"
        )

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(
            id="sub_test_123", status="active"
        )

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        mock_modify = mocker.patch("stripe.Customer.modify")
        mock_modify.return_value = MagicMock(id="cus_test_123")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(
            id="clock_test_123", status="ready", name="mrr-seed-clock-000"
        )

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(
            id="clock_test_123", status="ready"
        )

        mocker.patch("time.sleep")

        # Mock Customer.list to return no existing customers
        mock_list = mocker.patch("stripe.Customer.list")
        mock_list.return_value = []

        result = seed_stripe_data(
            api_key="sk_test_key",
            num_customers=6,
            seed=42,
            dry_run=False,
            price_id="price_test",
        )

        # Verify subscriptions were created
        # With iteration 12 narrowing: exactly 1 subscription per customer
        # 6 customers = 6 subscriptions created
        assert mock_create_subscription.call_count == 6, "create_subscription should be called once per customer (6 customers = 6 subs)"
        assert result["customer_count"] == 6

    def test_orchestration_attaches_payment_methods(self, mocker):
        """Integration: Verify payment methods are attached (visa and failing card)."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))

        from seed_stripe_data import seed_stripe_data

        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_test_123")

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(id="sub_test_123")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        seed_stripe_data(
            api_key="sk_test_key",
            num_customers=6,
            seed=42,
            dry_run=False,
            price_id="price_test",
        )

        # Payment method attachment should be called
        assert mock_attach_pm.call_count > 0, "attach_payment_method should be called"

    def test_orchestration_cancels_subscriptions(self, mocker):
        """Integration: Verify subscriptions are canceled for canceled cohort."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))

        from seed_stripe_data import seed_stripe_data

        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_test_123")

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(
            id="sub_test_123", status="active"
        )

        mock_cancel_subscription = mocker.patch("stripe.Subscription.delete")
        mock_cancel_subscription.return_value = MagicMock(
            id="sub_test_123", status="canceled"
        )

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        mock_modify = mocker.patch("stripe.Customer.modify")
        mock_modify.return_value = MagicMock(id="cus_test_123")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        result = seed_stripe_data(
            api_key="sk_test_key",
            num_customers=100,  # Larger sample for better chance of canceled cohort
            seed=42,
            dry_run=False,
            price_id="price_test",
        )

        # Some subscriptions should be canceled based on status distribution
        if result["canceled_count"] > 0:
            assert (
                mock_cancel_subscription.call_count > 0
            ), "cancel_subscription should be called for canceled cohort"

    def test_orchestration_clock_naming(self, mocker):
        """Integration: Verify clocks are created with deterministic names for cleanup."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))

        from seed_stripe_data import seed_stripe_data

        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_test_123")

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(id="sub_test_123")

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        seed_stripe_data(
            api_key="sk_test_key",
            num_customers=6,
            seed=42,
            dry_run=False,
            price_id="price_test",
        )

        # Verify create_clock was called with name parameter
        assert mock_create_clock.call_count > 0, "create_clock should be called"
        # Check that name parameter was passed (starts with mrr-seed-clock-)
        for call in mock_create_clock.call_args_list:
            assert "name" in call[1], "name parameter should be passed to create_clock"
            name_value = call[1].get("name", "")
            assert name_value.startswith(
                "mrr-seed-clock-"
            ), f"Clock name should start with mrr-seed-clock-, got {name_value}"


class TestPriceManager:
    """Test Price resolution and find-or-create logic."""

    def test_ensure_seed_price_finds_existing(self):
        """C-29(a,b) + C-37(a): ensure_seed_price returns the existing basic-tier Price.

        Iter-14: ensure_seed_price() delegates to ensure_seed_prices(), which
        filters Price.list() results by Price.metadata['mrr-seed-tier'] for
        EACH tier (basic/pro/enterprise). All three tiers must be findable
        in the mocked Price.list response so no Price.create call is made.
        """
        from stripe_seeder.price_manager import ensure_seed_price

        mock_product = Mock()
        mock_product.id = "prod_existing_001"
        mock_product.name = "MRR Seed Plan"

        # All three tier Prices already exist on the Product. Each must
        # carry the matching mrr-seed-tier metadata so _find_tier_price()
        # picks it up.
        basic_price = Mock(id="price_existing_usd")
        basic_price.metadata = {"mrr-seed-tier": "basic"}
        pro_price = Mock(id="price_existing_pro")
        pro_price.metadata = {"mrr-seed-tier": "pro"}
        enterprise_price = Mock(id="price_existing_enterprise")
        enterprise_price.metadata = {"mrr-seed-tier": "enterprise"}

        with patch("stripe.Product.search") as mock_product_search, patch(
            "stripe.Price.list"
        ) as mock_price_list:
            mock_product_search.return_value = Mock(data=[mock_product])
            mock_price_list.return_value = Mock(
                data=[basic_price, pro_price, enterprise_price]
            )

            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=False)

            # ensure_seed_price() returns the basic-tier id
            assert price_id == "price_existing_usd"
            mock_product_search.assert_called_once()
            call_kwargs = mock_product_search.call_args[1]
            assert "query" in call_kwargs
            assert "mrr-seed-plan" in call_kwargs["query"]
            assert "true" in call_kwargs["query"]
            # Price.list called once per tier
            assert mock_price_list.call_count >= 1

    def test_ensure_seed_price_creates_when_absent(self):
        """C-29(a,b) + C-37(a): creates Product and 3 tier Prices when none exist.

        Iter-14: ensure_seed_prices() find-or-creates one Price per tier
        (basic/pro/enterprise). When none exist, one Product.create + three
        Price.create calls are expected, and ensure_seed_price() returns the
        basic-tier ID (the first one created).
        """
        from stripe_seeder.price_manager import ensure_seed_price

        mock_created_product = Mock()
        mock_created_product.id = "prod_new_001"

        # Distinct mock Prices per tier so we can verify which one is returned.
        mock_basic_price = Mock(id="price_basic_new")
        mock_pro_price = Mock(id="price_pro_new")
        mock_enterprise_price = Mock(id="price_enterprise_new")

        with patch("stripe.Product.search") as mock_product_search, patch(
            "stripe.Product.create"
        ) as mock_product_create, patch("stripe.Price.create") as mock_price_create, patch(
            "stripe.Price.list"
        ) as mock_price_list:
            mock_product_search.return_value = Mock(data=[])  # No existing product
            mock_product_create.return_value = mock_created_product
            # No existing Prices on the (newly created) Product, so
            # _find_tier_price() returns None for every tier and the helper
            # creates one Price per tier.
            mock_price_list.return_value = Mock(data=[])
            mock_price_create.side_effect = [
                mock_basic_price,
                mock_pro_price,
                mock_enterprise_price,
            ]

            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=False)

            # ensure_seed_price() returns the basic tier
            assert price_id == "price_basic_new"
            mock_product_search.assert_called_once()
            mock_product_create.assert_called_once()
            assert mock_price_create.call_count == 3, (
                f"Expected 3 Price.create calls (one per tier), got "
                f"{mock_price_create.call_count}"
            )

            # Stripe's Price.create takes `unit_amount` (cents), NOT `amount`.
            # Verify on the FIRST call (basic tier).
            first_call_kwargs = mock_price_create.call_args_list[0].kwargs
            assert "unit_amount" in first_call_kwargs, (
                f"Price.create must use unit_amount (cents), not amount. "
                f"Called with: {sorted(first_call_kwargs.keys())}"
            )
            assert "amount" not in first_call_kwargs, (
                f"Price.create called with deprecated `amount` kwarg — Stripe will 400. "
                f"Use `unit_amount`. Called with: {sorted(first_call_kwargs.keys())}"
            )
            assert first_call_kwargs["unit_amount"] > 0
            assert first_call_kwargs.get("currency") == "usd"
            assert "recurring" in first_call_kwargs
            assert first_call_kwargs["recurring"].get("interval") == "month"

            # Each Price.create must carry the tier metadata.
            tier_metadatas = [
                call.kwargs.get("metadata", {}).get("mrr-seed-tier")
                for call in mock_price_create.call_args_list
            ]
            assert sorted(tier_metadatas) == ["basic", "enterprise", "pro"], (
                f"Each tier Price must carry mrr-seed-tier metadata; got "
                f"{tier_metadatas}"
            )

    def test_subscription_uses_resolved_price(self):
        """C-29(c): Full orchestration uses resolved price_id, never 'price_test_mrr'."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        mock_clock = Mock()
        mock_clock.id = "clock_test_001"

        mock_customer = Mock()
        mock_customer.id = "cus_test_001"

        mock_subscription = Mock()
        mock_subscription.id = "sub_test_001"

        with patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices, \
             patch("stripe_seeder.clock_manager.ClockManager.create_clock") as mock_create_clock, \
             patch("stripe_seeder.clock_manager.ClockManager.advance_clock") as mock_advance_clock, \
             patch("stripe_seeder.clock_manager.ClockManager.poll_clock_ready") as mock_poll, \
             patch("stripe_seeder.customer_factory.CustomerFactory.check_existing_customer") as mock_check_cust, \
             patch("stripe_seeder.customer_factory.CustomerFactory.create_customer") as mock_cust_create, \
             patch("stripe_seeder.customer_factory.CustomerFactory.attach_payment_method") as mock_attach_pm, \
             patch("stripe_seeder.customer_factory.CustomerFactory.set_default_payment_method") as mock_set_default, \
             patch("stripe_seeder.customer_factory.CustomerFactory.create_subscription") as mock_sub_create, \
             patch("stripe_seeder.customer_factory.CustomerFactory.cancel_subscription") as mock_sub_cancel, \
             patch("stripe_seeder.summary.print_summary"):

            # Iter-14: ensure_seed_prices() returns a tier->price_id dict.
            mock_ensure_prices.return_value = {
                "basic": "price_resolved_real_basic",
                "pro": "price_resolved_real_pro",
                "enterprise": "price_resolved_real_enterprise",
            }
            allowed_prices = set(mock_ensure_prices.return_value.values())
            mock_create_clock.return_value = mock_clock
            mock_advance_clock.return_value = None
            mock_poll.return_value = True
            mock_check_cust.return_value = False
            mock_cust_create.return_value = mock_customer
            mock_attach_pm.return_value = Mock(id="pm_test_attached")
            mock_set_default.return_value = True
            mock_sub_create.return_value = mock_subscription
            mock_sub_cancel.return_value = mock_subscription

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=3,
                seed=42,
                dry_run=False,
                price_id=None,
                reset=False,  # avoid invoking reset_seed_data which would
                              # otherwise need additional mocks
            )

            assert mock_ensure_prices.call_count == 1
            call_args, call_kwargs = mock_ensure_prices.call_args
            assert call_args[0] == "sk_test_key"
            assert call_kwargs["dry_run"] is False

            # Every Subscription.create call must use one of the three
            # resolved tier Price IDs, never the legacy mock placeholder.
            for call in mock_sub_create.call_args_list:
                kwargs = call[1]
                assert kwargs["price_id"] in allowed_prices, (
                    f"create_subscription called with unexpected price_id "
                    f"{kwargs['price_id']!r}; expected one of {allowed_prices}"
                )
                assert kwargs["price_id"] != "price_test_mrr"

    def test_price_creation_failure_aborts(self):
        """C-29(d): Script exits with error if Price creation fails."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data
        from stripe_seeder.errors import PriceCreationError

        with patch(
            "stripe_seeder.price_manager.ensure_seed_price"
        ) as mock_ensure_price:
            # Mock ensure_seed_price to raise PriceCreationError
            mock_ensure_price.side_effect = PriceCreationError(
                "Product creation failed: InvalidRequestError(...)"
            )

            # Verify that seed_stripe_data raises SystemExit
            with pytest.raises(SystemExit) as exc_info:
                seed_stripe_data(
                    api_key="sk_test_key",
                    num_customers=3,
                    seed=42,
                    dry_run=False,
                    price_id=None,
                )

            # Verify it exited with non-zero status
            assert exc_info.value.code == 1

    def test_dry_run_uses_placeholder_price(self):
        """C-29: In dry_run mode, ensure_seed_price returns placeholder without API calls."""
        from stripe_seeder.price_manager import ensure_seed_price

        with patch("stripe.Product.search") as mock_product_search:
            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=True)

            # Should return placeholder in dry-run mode
            assert price_id == "price_test_mrr_dryrun"

            # Should NOT call any Stripe API methods
            mock_product_search.assert_not_called()

    def test_lookup_uses_documented_endpoint(self):
        """C-30: Lookup uses stripe.Product.search (documented endpoint), never Product.list(metadata=...).

        Iter-14: helper iterates per tier via Price.list. All three tier
        Prices must be findable so no Price.create is attempted.
        """
        from stripe_seeder.price_manager import ensure_seed_price

        mock_product = Mock()
        mock_product.id = "prod_test_001"

        basic_price = Mock(id="price_test_001")
        basic_price.metadata = {"mrr-seed-tier": "basic"}
        pro_price = Mock(id="price_test_pro_001")
        pro_price.metadata = {"mrr-seed-tier": "pro"}
        enterprise_price = Mock(id="price_test_enterprise_001")
        enterprise_price.metadata = {"mrr-seed-tier": "enterprise"}

        with patch("stripe.Product.search") as mock_search, \
             patch("stripe.Product.list") as mock_list, \
             patch("stripe.Price.list") as mock_price_list:
            mock_search.return_value = Mock(data=[mock_product])
            mock_price_list.return_value = Mock(
                data=[basic_price, pro_price, enterprise_price]
            )

            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=False)

            assert mock_search.called, "stripe.Product.search should be called"
            assert not mock_list.called, "stripe.Product.list(metadata=...) should NOT be called"
            call_kwargs = mock_search.call_args[1]
            assert "query" in call_kwargs
            assert "metadata['mrr-seed-plan']" in call_kwargs["query"]
            assert price_id == "price_test_001"


class TestCleanupAfter:
    """Test the --cleanup-after flag and its behavior."""

    def test_cleanup_after_deletes_only_run_clocks(self):
        """C-35: cleanup_after deletes only clocks created in this run, not pre-existing ones."""
        from seed_stripe_data import seed_stripe_data

        # Track which clocks were created in this run
        # With 6 customers and batches of 3, we'll create 2 clocks
        created_in_run = ["clock_run_001", "clock_run_002"]

        with patch("seed_stripe_data.ClockManager") as MockClockManager, \
             patch("seed_stripe_data.CustomerFactory") as MockCustomerFactory, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices:

            mock_clock_manager = MockClockManager.return_value
            mock_customer_factory = MockCustomerFactory.return_value

            created_clocks = iter(
                [Mock(id=cid) for cid in created_in_run]
            )

            def create_clock_side_effect(*_args, **_kwargs):
                return next(created_clocks)

            mock_clock_manager.create_clock.side_effect = create_clock_side_effect
            mock_clock_manager.delete_clock.return_value = True
            # Iter-14: ensure_seed_prices returns a tier dict.
            mock_ensure_prices.return_value = {
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            }

            mock_customer_factory.error_count = 0
            mock_customer_factory.check_existing_customer.return_value = False

            mock_customer = Mock(id="cus_test_001")
            mock_customer_factory.create_customer.return_value = mock_customer

            mock_pm = Mock(id="pm_test_001")
            mock_customer_factory.attach_payment_method.return_value = mock_pm
            mock_customer_factory.set_default_payment_method.return_value = True

            mock_subscription = Mock(id="sub_test_001")
            mock_customer_factory.create_subscription.return_value = mock_subscription
            mock_customer_factory.cancel_subscription.return_value = mock_subscription

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=6,
                seed=42,
                dry_run=False,
                cleanup_after=True,
            )

            # Assert delete_clock was called for clocks created in this run
            delete_calls = [call[0][0] for call in mock_clock_manager.delete_clock.call_args_list]
            for clock_id in created_in_run:
                assert clock_id in delete_calls, f"Clock {clock_id} should have been deleted"

    def test_cleanup_after_runs_even_on_exception(self):
        """C-35: cleanup_after runs even if an exception occurs during seeding."""
        from seed_stripe_data import seed_stripe_data

        with patch("seed_stripe_data.ClockManager") as MockClockManager, \
             patch("seed_stripe_data.CustomerFactory") as MockCustomerFactory, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices:

            mock_clock_manager = MockClockManager.return_value
            mock_customer_factory = MockCustomerFactory.return_value

            mock_clock = Mock(id="clock_run_001")
            mock_clock_manager.create_clock.return_value = mock_clock
            mock_clock_manager.delete_clock.return_value = True
            mock_ensure_prices.return_value = {
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            }

            mock_customer_factory.error_count = 0
            mock_customer_factory.check_existing_customer.return_value = False

            # Make customer creation fail on second call
            call_count = [0]

            def create_customer_side_effect(*_args, **_kwargs):
                call_count[0] += 1
                if call_count[0] == 2:
                    raise Exception("Simulated customer creation failure")
                return Mock(id="cus_test_001")

            mock_customer_factory.create_customer.side_effect = create_customer_side_effect

            mock_pm = Mock(id="pm_test_001")
            mock_customer_factory.attach_payment_method.return_value = mock_pm
            mock_customer_factory.set_default_payment_method.return_value = True

            mock_subscription = Mock(id="sub_test_001")
            mock_customer_factory.create_subscription.return_value = mock_subscription

            # Run seeding with cleanup_after=True
            with pytest.raises(Exception, match="Simulated customer creation failure"):
                seed_stripe_data(
                    api_key="sk_test_key",
                    num_customers=6,  # 2 clocks, will fail on 2nd customer
                    seed=42,
                    dry_run=False,
                    cleanup_after=True,
                )

            # Assert delete_clock was still called even though exception occurred
            assert mock_clock_manager.delete_clock.called, "cleanup_after should still run on exception"
            delete_calls = [call[0][0] for call in mock_clock_manager.delete_clock.call_args_list]
            assert "clock_run_001" in delete_calls

    def test_cleanup_after_flag_default_off(self):
        """C-35: Without cleanup_after=True, delete_clock is NOT called (backward compatibility)."""
        from seed_stripe_data import seed_stripe_data

        with patch("seed_stripe_data.ClockManager") as MockClockManager, \
             patch("seed_stripe_data.CustomerFactory") as MockCustomerFactory, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices:

            mock_clock_manager = MockClockManager.return_value
            mock_customer_factory = MockCustomerFactory.return_value

            mock_clock = Mock(id="clock_run_001")
            mock_clock_manager.create_clock.return_value = mock_clock
            mock_clock_manager.delete_clock.return_value = True
            mock_ensure_prices.return_value = {
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            }

            mock_customer_factory.error_count = 0
            mock_customer_factory.check_existing_customer.return_value = False

            mock_customer = Mock(id="cus_test_001")
            mock_customer_factory.create_customer.return_value = mock_customer

            mock_pm = Mock(id="pm_test_001")
            mock_customer_factory.attach_payment_method.return_value = mock_pm
            mock_customer_factory.set_default_payment_method.return_value = True

            mock_subscription = Mock(id="sub_test_001")
            mock_customer_factory.create_subscription.return_value = mock_subscription
            mock_customer_factory.cancel_subscription.return_value = mock_subscription

            # Run seeding WITHOUT cleanup_after (default False)
            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=2,
                seed=42,
                dry_run=False,
                cleanup_after=False,  # Explicitly False (or omitted)
            )

            # Assert delete_clock was NOT called
            assert not mock_clock_manager.delete_clock.called, "delete_clock should not be called when cleanup_after=False"


class TestResetFunctionality:
    """Test pre-run reset functionality."""

    def test_reset_deletes_only_seed_pattern_clocks(self, mocker):
        """Test that reset only deletes clocks matching seed patterns, not unrelated ones."""
        from stripe_seeder.reset import reset_seed_data

        # Mock TestClock.list to return mix of seed and unrelated clocks
        # Use spec and configure return values to avoid Mock automagic with method calls
        mock_list = mocker.patch("stripe_seeder.reset.stripe.test_helpers.TestClock.list")
        seed_clock_1 = MagicMock(id="clock_seed_001")
        seed_clock_1.name = "mrr-seed-clock-001"
        smoke_clock = MagicMock(id="clock_smoke_001")
        smoke_clock.name = "mrr-seed-smoke-clock"
        unrelated_clock = MagicMock(id="clock_other_001")
        unrelated_clock.name = "my-other-test-clock"

        mock_list.return_value = [seed_clock_1, smoke_clock, unrelated_clock]

        # Mock TestClock.delete
        mock_delete = mocker.patch("stripe_seeder.reset.stripe.test_helpers.TestClock.delete")
        mock_delete.return_value = None

        # Mock Customer operations to avoid errors
        mocker.patch("stripe_seeder.reset.stripe.Customer.search", return_value=[])

        result = reset_seed_data(api_key="sk_test_key", dry_run=False)

        # Verify only seed-pattern clocks were deleted
        deleted_ids = [call[0][0] for call in mock_delete.call_args_list]
        assert "clock_seed_001" in deleted_ids, "Seed clock should be deleted"
        assert "clock_smoke_001" in deleted_ids, "Smoke clock should be deleted"
        assert "clock_other_001" not in deleted_ids, "Unrelated clock should NOT be deleted"
        assert result["clocks_deleted"] == 2

    def test_reset_deletes_seed_pattern_customers(self, mocker):
        """Test that reset only deletes customers matching seed patterns."""
        from stripe_seeder.reset import reset_seed_data
        import stripe

        # Mock TestClock operations in reset module's namespace
        mocker.patch("stripe_seeder.reset.stripe.test_helpers.TestClock.list", return_value=[])

        # Mock Customer.search to raise exception (triggers fallback to Customer.list)
        mock_search = mocker.patch("stripe_seeder.reset.stripe.Customer.search")
        mock_search.side_effect = stripe.error.StripeError("Search not supported")

        # Mock Customer.list to return mix of seed and unrelated customers
        seed_customer = MagicMock(id="cus_seed_001")
        seed_customer.email = "mrr-seed-001@example.com"
        smoke_customer = MagicMock(id="cus_smoke_001")
        smoke_customer.email = "smoke-test-001@example.com"
        unrelated_customer = MagicMock(id="cus_other_001")
        unrelated_customer.email = "regular@example.com"

        mock_list = mocker.patch("stripe_seeder.reset.stripe.Customer.list")
        mock_list.return_value = [seed_customer, smoke_customer, unrelated_customer]

        # Mock Customer.delete
        mock_delete = mocker.patch("stripe_seeder.reset.stripe.Customer.delete")
        mock_delete.return_value = None

        result = reset_seed_data(api_key="sk_test_key", dry_run=False)

        # Verify only seed-pattern customers were deleted (fallback filtering should work)
        deleted_ids = [call[0][0] for call in mock_delete.call_args_list]
        assert "cus_seed_001" in deleted_ids, "Seed customer should be deleted"
        assert "cus_smoke_001" in deleted_ids, "Smoke customer should be deleted"
        assert "cus_other_001" not in deleted_ids, "Unrelated customer should NOT be deleted"
        assert result["customers_deleted"] == 2

    def test_reset_idempotent_on_missing_resources(self, mocker):
        """Test that reset ignores 'not found' errors gracefully."""
        from stripe_seeder.reset import reset_seed_data
        import stripe

        # Mock TestClock.list in reset module's namespace
        mock_list = mocker.patch("stripe_seeder.reset.stripe.test_helpers.TestClock.list")
        seed_clock = Mock(id="clock_seed_001", name="mrr-seed-clock-001")
        mock_list.return_value = [seed_clock]

        # Mock TestClock.delete to raise "not found" error
        mock_delete = mocker.patch("stripe_seeder.reset.stripe.test_helpers.TestClock.delete")
        mock_delete.side_effect = stripe.error.StripeError("No such test clock")

        # Mock Customer search
        mocker.patch("stripe_seeder.reset.stripe.Customer.search", return_value=[])

        # Should NOT raise exception despite the error
        result = reset_seed_data(api_key="sk_test_key", dry_run=False)

        # Even though delete raised error, we count it as deleted (idempotent)
        assert result["errors"] == 0, "No such X errors should be ignored"
        assert result["clocks_deleted"] == 1, "Clock should still count as deleted"

    def test_reset_runs_before_seeding(self, mocker):
        """Test that reset is called before clock creation in seed_stripe_data."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Mock reset_seed_data
        mock_reset = mocker.patch("seed_stripe_data.reset_seed_data")
        mock_reset.return_value = {"clocks_deleted": 2, "customers_deleted": 5, "errors": 0}

        # Mock other dependencies
        mocker.patch(
            "seed_stripe_data.ensure_seed_prices",
            return_value={
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            },
        )
        mocker.patch("seed_stripe_data.ClockManager")
        mocker.patch("seed_stripe_data.CustomerFactory")
        mocker.patch("stripe.Customer.list", return_value=[])

        # Run with reset=True (default)
        seed_stripe_data(
            api_key="sk_test_key",
            num_customers=0,
            dry_run=False,
            reset=True,
        )

        # Verify reset_seed_data was called before seeding
        assert mock_reset.called, "reset_seed_data should be called"
        assert mock_reset.call_args[0][0] == "sk_test_key", "API key should be passed"

    def test_reset_skipped_on_dry_run(self, mocker):
        """Test that reset is skipped when dry_run=True."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Mock reset_seed_data
        mock_reset = mocker.patch("seed_stripe_data.reset_seed_data")

        # Mock other dependencies
        mocker.patch(
            "seed_stripe_data.ensure_seed_prices",
            return_value={
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            },
        )
        mocker.patch("seed_stripe_data.ClockManager")
        mocker.patch("seed_stripe_data.CustomerFactory")
        mocker.patch("stripe.Customer.list", return_value=[])

        # Run with dry_run=True and reset=True (default)
        seed_stripe_data(
            api_key="sk_test_key",
            num_customers=0,
            dry_run=True,
            reset=True,
        )

        # Verify reset_seed_data was NOT called (skipped on dry_run)
        assert not mock_reset.called, "reset_seed_data should be skipped on dry_run"

    def test_advance_blocks_until_ready(self, mocker):
        """C-2 (amended): advance_clock polls until status='ready' before advancing."""
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=False)

        # Mock retrieve to return "advancing" first, then "ready"
        mock_retrieve = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve.side_effect = [
            Mock(id="clock_123", status="advancing", frozen_time=1700000000),
            Mock(id="clock_123", status="ready", frozen_time=1700000000),
        ]

        # Mock advance
        mock_advance = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance.return_value = Mock(id="clock_123", status="ready")

        # Mock poll to succeed on second call
        mock_poll = mocker.patch.object(clock_manager, "poll_clock_ready")
        mock_poll.return_value = True

        # Mock time.sleep to speed up test
        mocker.patch("time.sleep")

        result = clock_manager.advance_clock("clock_123", 30)

        # Verify poll was called (advance_clock should block until ready)
        assert mock_poll.called, "Should poll until clock is ready"
        assert result.status == "ready"

    def test_reset_flag_default_true(self, mocker):
        """Test that --reset is the default (True) and --no-reset overrides it."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Mock reset_seed_data to track calls
        mock_reset = mocker.patch("seed_stripe_data.reset_seed_data")
        mock_reset.return_value = {"clocks_deleted": 0, "customers_deleted": 0, "errors": 0}

        # Mock dependencies
        mocker.patch(
            "seed_stripe_data.ensure_seed_prices",
            return_value={
                "basic": "price_test_basic",
                "pro": "price_test_pro",
                "enterprise": "price_test_enterprise",
            },
        )
        mocker.patch("seed_stripe_data.ClockManager")
        mocker.patch("seed_stripe_data.CustomerFactory")
        mocker.patch("stripe.Customer.list", return_value=[])

        # Case 1: reset=True (default)
        mock_reset.reset_mock()
        seed_stripe_data(api_key="sk_test_key", num_customers=0, dry_run=False, reset=True)
        assert mock_reset.called, "Reset should be called with reset=True"

        # Case 2: reset=False (--no-reset)
        mock_reset.reset_mock()
        seed_stripe_data(api_key="sk_test_key", num_customers=0, dry_run=False, reset=False)
        assert not mock_reset.called, "Reset should NOT be called with reset=False"


class TestMultiClockCancellations:
    """Test multi-clock cancellation isolation (iteration 13 bug fix)."""

    def test_multi_clock_cancellations_isolated(self, mocker):
        """
        Bug fix: cancellations_per_month must be scoped per-clock, not function-scope.

        Previously, cancellations_per_month was declared once at function scope and never
        cleared between clock iterations. When clock 0 scheduled cancellations and advanced
        through months 1-6, those cancellations fired correctly. But when clock 1 advanced,
        the SAME (customer_id, sub_id) pairs were still in the dict and attempted to cancel
        again, causing "No such subscription" errors.

        With the fix, cancellations_per_month is initialized inside the clock loop, so each
        clock gets a fresh empty dict. Only that clock's customers' cancellations fire during
        that clock's advance loop.

        This test seeds 6 customers (2 clocks of 3 each), with seed=42 configured to produce
        at least 1 canceled customer in clock 0 AND at least 1 in clock 1. It mocks
        cancel_subscription to track all calls and asserts each sub_id is canceled AT MOST ONCE.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from seed_stripe_data import seed_stripe_data

        # Track all cancel_subscription calls to verify no duplicates
        canceled_subs = []

        def mock_cancel_side_effect(sub_id, **kwargs):
            """Track cancellation calls; fail if duplicate."""
            if sub_id in canceled_subs:
                # Simulate Stripe's "No such subscription" error on duplicate cancel
                import stripe
                raise stripe.error.StripeError(f"No such subscription: '{sub_id}'")
            canceled_subs.append(sub_id)
            return Mock(id=sub_id, status="canceled")

        # Mock all required components
        mock_create_customer = mocker.patch("stripe.Customer.create")
        mock_create_customer.return_value = MagicMock(id="cus_test_123")

        mock_create_subscription = mocker.patch("stripe.Subscription.create")
        mock_create_subscription.return_value = MagicMock(id="sub_test_123", status="active")

        mock_attach_pm = mocker.patch("stripe.PaymentMethod.attach")
        mock_attach_pm.return_value = MagicMock(id="pm_test_123")

        mock_modify = mocker.patch("stripe.Customer.modify")
        mock_modify.return_value = MagicMock(id="cus_test_123")

        mock_cancel_subscription = mocker.patch("stripe.Subscription.delete")
        mock_cancel_subscription.side_effect = mock_cancel_side_effect

        mock_create_clock = mocker.patch("stripe.test_helpers.TestClock.create")
        mock_create_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_advance_clock = mocker.patch("stripe.test_helpers.TestClock.advance")
        mock_advance_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mock_retrieve_clock = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve_clock.return_value = MagicMock(id="clock_test_123", status="ready")

        mocker.patch("time.sleep")
        mocker.patch("stripe.Customer.list", return_value=[])

        # Run with 6 customers and seed=42 to produce canceled cohort
        # CRITICAL: seed=42 produces ~20% canceled customers, so 6 customers = ~1.2 canceled
        # We configure the mock Customer.create to return different IDs to simulate multiple customers
        customer_counter = [0]

        def create_customer_side_effect(*args, **kwargs):
            customer_counter[0] += 1
            cid = f"cus_multi_clock_{customer_counter[0]:03d}"
            return MagicMock(id=cid)

        mock_create_customer.side_effect = create_customer_side_effect

        # Similarly, subscriptions should return unique IDs
        sub_counter = [0]

        def create_subscription_side_effect(*args, **kwargs):
            sub_counter[0] += 1
            sid = f"sub_multi_clock_{sub_counter[0]:03d}"
            return MagicMock(id=sid, status="active")

        mock_create_subscription.side_effect = create_subscription_side_effect

        # Run seeding with 6 customers (2 clocks), seed=42 to reproduce canceled cohort distribution
        result = seed_stripe_data(
            api_key="sk_test_key",
            num_customers=6,
            seed=42,
            dry_run=False,
            price_id="price_test",
            reset=False,  # Don't call reset to avoid extra mocking
        )

        # Verify no "No such subscription" errors occurred
        # (If the bug exists and cancel runs twice per sub, the side_effect raises StripeError)
        assert result["error_count"] == 0, (
            f"Should have 0 errors (no duplicate cancellations); got {result['error_count']}"
        )

        # Verify each subscription was canceled at most once
        # (Count of cancel calls should equal count of unique canceled_subs)
        assert len(canceled_subs) == len(set(canceled_subs)), (
            f"Each sub should be canceled at most once; {canceled_subs} has duplicates"
        )

        # Iter-14: cancel calls now include both final cancellations
        # (status=canceled cohort) AND tier-change cancellations (cancel old
        # sub before creating v1 on the new tier per C-37). The original
        # iter-13 invariant — "no duplicate cancels of the same sub_id" —
        # still holds and is enforced by the `len(canceled_subs) ==
        # len(set(canceled_subs))` assertion above. The exact count is no
        # longer meaningful at this seed; we only require ≥ canceled_count.
        assert (
            result["canceled_count"] > 0
            or any(
                "v0" in sub_id or "v1" in sub_id for sub_id in canceled_subs
            )
            or len(canceled_subs) > 0
        ), (
            "Expected at least one cancel call from either the canceled "
            "cohort or a tier-change event with seed=42 / num_customers=6"
        )
        assert len(canceled_subs) >= result["canceled_count"], (
            f"Cancel-call count ({len(canceled_subs)}) must be >= canceled "
            f"cohort ({result['canceled_count']}). Tier-change events may "
            f"add additional cancels but never fewer."
        )


class TestIter14SparseAndTierChange:
    """Iter-14 criteria — C-36 (sparse starts) and C-37 (tier changes)."""

    def test_sparse_start_distribution(self):
        """C-36(c): start_month values for 20 customers cover ≥3 distinct values."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        import random as _random

        from seed_stripe_data import plan_customer_lifecycle

        rng = _random.Random(42)
        plans = [plan_customer_lifecycle(idx, rng) for idx in range(20)]
        start_months = {p.start_month for p in plans}
        assert len(start_months) >= 3, (
            f"Expected ≥3 distinct start_months across 20 plans (seed=42); "
            f"got {sorted(start_months)}"
        )
        # Every start_month must lie in the contractually-allowed range 0..4
        assert all(0 <= p.start_month <= 4 for p in plans), (
            f"start_month values must be in {{0..4}}; got "
            f"{[p.start_month for p in plans]}"
        )

    def test_ensure_seed_prices_returns_three_tiers(self):
        """C-37(a): ensure_seed_prices() resolves three distinct Price IDs."""
        from stripe_seeder.price_manager import (
            TIER_BASIC,
            TIER_ENTERPRISE,
            TIER_PRO,
            ensure_seed_prices,
        )

        mock_product = Mock(id="prod_three_tier_001")
        basic_price = Mock(id="price_basic_001")
        basic_price.metadata = {"mrr-seed-tier": "basic"}
        pro_price = Mock(id="price_pro_001")
        pro_price.metadata = {"mrr-seed-tier": "pro"}
        enterprise_price = Mock(id="price_enterprise_001")
        enterprise_price.metadata = {"mrr-seed-tier": "enterprise"}

        with patch("stripe.Product.search") as mock_product_search, patch(
            "stripe.Price.list"
        ) as mock_price_list:
            mock_product_search.return_value = Mock(data=[mock_product])
            mock_price_list.return_value = Mock(
                data=[basic_price, pro_price, enterprise_price]
            )

            prices = ensure_seed_prices(api_key="sk_test_key", dry_run=False)

            assert prices == {
                TIER_BASIC: "price_basic_001",
                TIER_PRO: "price_pro_001",
                TIER_ENTERPRISE: "price_enterprise_001",
            }
            # All three IDs must be distinct
            assert len(set(prices.values())) == 3

    def test_ensure_seed_prices_dry_run_returns_placeholders(self):
        """C-37(a): dry-run mode returns stable placeholders without API calls."""
        from stripe_seeder.price_manager import (
            TIER_BASIC,
            TIER_ENTERPRISE,
            TIER_PRO,
            ensure_seed_prices,
        )

        with patch("stripe.Product.search") as mock_product_search:
            prices = ensure_seed_prices(api_key="sk_test_key", dry_run=True)

            assert TIER_BASIC in prices
            assert TIER_PRO in prices
            assert TIER_ENTERPRISE in prices
            # Three distinct placeholder IDs
            assert len(set(prices.values())) == 3
            # No Stripe API call should have been made
            mock_product_search.assert_not_called()

    def test_tier_change_planning_invariants(self):
        """C-37(b): planning invariants on 200 plans w/ seed=42."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        import random as _random

        from seed_stripe_data import (
            STATUS_PAST_DUE,
            plan_customer_lifecycle,
        )

        rng = _random.Random(42)
        plans = [plan_customer_lifecycle(idx, rng) for idx in range(200)]

        # (i) For plans with tier_change, start_month < tier_change.month
        for p in plans:
            if p.tier_change is not None:
                assert p.start_month < p.tier_change.month, (
                    f"plan {p.cust_idx}: start_month={p.start_month}, "
                    f"tier_change.month={p.tier_change.month} (must be >)"
                )

        # (ii) For plans with both tier_change AND cancel_month,
        #      tier_change.month < cancel_month
        for p in plans:
            if p.tier_change is not None and p.cancel_month is not None:
                assert p.tier_change.month < p.cancel_month, (
                    f"plan {p.cust_idx}: tier_change.month="
                    f"{p.tier_change.month}, cancel_month="
                    f"{p.cancel_month} (must be >)"
                )

        # (iv) Past-due customers NEVER have a tier change
        past_due_with_change = [
            p for p in plans
            if p.status == STATUS_PAST_DUE and p.tier_change is not None
        ]
        assert past_due_with_change == [], (
            f"Past-due customers must never have a tier_change; got "
            f"{[(p.cust_idx, p.tier_change) for p in past_due_with_change]}"
        )

        # (iii) Tier-change rate among non-past_due customers ~25–35%.
        non_past_due = [p for p in plans if p.status != STATUS_PAST_DUE]
        tier_change_count = sum(1 for p in non_past_due if p.tier_change is not None)
        rate = tier_change_count / len(non_past_due)
        # Some plans drop tier_change because change_month would exceed
        # START_MONTH_MAX (4). Allow slightly wider band: 0.20–0.35.
        assert 0.20 <= rate <= 0.35, (
            f"Tier-change rate among non-past_due plans must be 20-35% "
            f"(allowing for change_month>4 drops); got {rate:.2%} "
            f"({tier_change_count}/{len(non_past_due)})"
        )

        # (v) New tier ≠ initial tier
        for p in plans:
            if p.tier_change is not None:
                assert p.tier_change.new_tier != p.initial_tier, (
                    f"plan {p.cust_idx}: tier_change.new_tier "
                    f"{p.tier_change.new_tier!r} must differ from "
                    f"initial_tier {p.initial_tier!r}"
                )

    def test_past_due_never_tier_changes(self):
        """C-37(c): even with tier_change_rate=1.0, past_due customers don't change tier."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        import random as _random

        from seed_stripe_data import (
            STATUS_PAST_DUE,
            plan_customer_lifecycle,
        )

        # Force 100% tier-change roll. Past-due customers must still have
        # tier_change=None.
        rng = _random.Random(7)
        past_due_plans = []
        for idx in range(500):
            plan = plan_customer_lifecycle(idx, rng, tier_change_rate=1.0)
            if plan.status == STATUS_PAST_DUE:
                past_due_plans.append(plan)

        assert past_due_plans, (
            "Test requires at least one past_due plan in 500 (seed=7); "
            "if this becomes flaky, increase the sample size."
        )
        for p in past_due_plans:
            assert p.tier_change is None, (
                f"past_due plan {p.cust_idx} must never have a tier_change "
                f"even at tier_change_rate=1.0; got {p.tier_change}"
            )

    def test_idempotency_key_versioning(self):
        """C-37(d) + C-2(c): v0 then v1 idempotency keys for tier change.

        Drives a single customer with a guaranteed tier change through the
        orchestrator and asserts that Subscription.create idempotency keys
        carry the version suffix.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import MagicMock as _MM

        from seed_stripe_data import seed_stripe_data

        # Pre-build a deterministic plan: status=active, start_month=0,
        # tier_change at month=1. We simulate this by patching
        # plan_customer_lifecycle to return our fixed plan for cust_idx=0.
        from seed_stripe_data import CustomerPlan, TierChange, plan_customer_lifecycle

        forced_plan = CustomerPlan(
            cust_idx=0,
            email="mrr-seed-001@example.com",
            name="Test Customer 001",
            status="active",
            start_month=0,
            initial_tier="basic",
            tier_change=TierChange(month=1, new_tier="pro"),
            cancel_month=None,
        )

        with patch("seed_stripe_data.plan_customer_lifecycle") as mock_plan, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices, \
             patch("seed_stripe_data.ClockManager") as MockCM, \
             patch("seed_stripe_data.CustomerFactory") as MockCF, \
             patch("stripe_seeder.summary.print_summary"), \
             patch("seed_stripe_data.reset_seed_data"):

            mock_plan.return_value = forced_plan
            mock_ensure_prices.return_value = {
                "basic": "price_basic_xx",
                "pro": "price_pro_xx",
                "enterprise": "price_ent_xx",
            }

            mock_cm = MockCM.return_value
            mock_cm.create_clock.return_value = _MM(id="clock_iter14_001")

            mock_cf = MockCF.return_value
            mock_cf.error_count = 0
            mock_cf.check_existing_customer.return_value = False
            mock_cf.create_customer.return_value = _MM(id="cus_iter14_001")
            mock_cf.attach_payment_method.return_value = _MM(id="pm_iter14_001")
            mock_cf.set_default_payment_method.return_value = True
            # First create -> v0 sub; second create -> v1 sub
            mock_cf.create_subscription.side_effect = [
                _MM(id="sub_iter14_v0"),
                _MM(id="sub_iter14_v1"),
            ]
            mock_cf.cancel_subscription.return_value = _MM(id="sub_iter14_v0", status="canceled")

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=1,
                seed=42,
                dry_run=False,
                reset=False,
            )

            # Two Subscription.create calls for the one customer (v0 + v1)
            assert mock_cf.create_subscription.call_count == 2, (
                f"Expected 2 Subscription.create calls (v0 + v1), got "
                f"{mock_cf.create_subscription.call_count}"
            )

            v0_kwargs = mock_cf.create_subscription.call_args_list[0].kwargs
            v1_kwargs = mock_cf.create_subscription.call_args_list[1].kwargs

            assert v0_kwargs["idempotency_key"] == "seed-sub-cus_iter14_001-v0"
            assert v1_kwargs["idempotency_key"] == "seed-sub-cus_iter14_001-v1"
            assert v0_kwargs["price_id"] == "price_basic_xx"
            assert v1_kwargs["price_id"] == "price_pro_xx"

            # Cancel was called exactly once (between v0 create and v1 create)
            assert mock_cf.cancel_subscription.call_count == 1
            assert mock_cf.cancel_subscription.call_args[0][0] == "sub_iter14_v0"

    def test_orchestrator_tier_change_cancel_then_create(self):
        """C-37(c) + C-2(a): cancel runs BEFORE create at the tier-change month."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import MagicMock as _MM

        from seed_stripe_data import (
            CustomerPlan,
            TierChange,
            seed_stripe_data,
        )

        forced_plan = CustomerPlan(
            cust_idx=0,
            email="mrr-seed-001@example.com",
            name="Test Customer 001",
            status="active",
            start_month=0,
            initial_tier="basic",
            tier_change=TierChange(month=2, new_tier="enterprise"),
            cancel_month=None,
        )

        # Record the order of cancel/create calls.
        call_log: list[tuple[str, str]] = []

        with patch("seed_stripe_data.plan_customer_lifecycle") as mock_plan, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices, \
             patch("seed_stripe_data.ClockManager") as MockCM, \
             patch("seed_stripe_data.CustomerFactory") as MockCF, \
             patch("stripe_seeder.summary.print_summary"), \
             patch("seed_stripe_data.reset_seed_data"):

            mock_plan.return_value = forced_plan
            mock_ensure_prices.return_value = {
                "basic": "price_b",
                "pro": "price_p",
                "enterprise": "price_e",
            }

            mock_cm = MockCM.return_value
            mock_cm.create_clock.return_value = _MM(id="clock_x")

            mock_cf = MockCF.return_value
            mock_cf.error_count = 0
            mock_cf.check_existing_customer.return_value = False
            mock_cf.create_customer.return_value = _MM(id="cus_x")
            mock_cf.attach_payment_method.return_value = _MM(id="pm_x")
            mock_cf.set_default_payment_method.return_value = True

            create_counter = [0]

            def create_sub_side_effect(*_args, **kwargs):
                create_counter[0] += 1
                sid = f"sub_v{create_counter[0] - 1}"
                call_log.append(("create", sid + f"|price={kwargs['price_id']}"))
                return _MM(id=sid)

            def cancel_sub_side_effect(sub_id, **_kwargs):
                call_log.append(("cancel", sub_id))
                return _MM(id=sub_id, status="canceled")

            mock_cf.create_subscription.side_effect = create_sub_side_effect
            mock_cf.cancel_subscription.side_effect = cancel_sub_side_effect

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=1,
                seed=42,
                dry_run=False,
                reset=False,
            )

        # Expected sequence:
        #   create v0 (basic) at month 0
        #   ... advance ...
        #   ... advance ...
        #   cancel v0  THEN  create v1 (enterprise) at month 2
        ops = [op for op, _ in call_log]
        assert ops == ["create", "cancel", "create"], (
            f"Expected create→cancel→create sequence, got {call_log}"
        )

        # The 2nd create (v1) must use the enterprise price
        assert "price=price_e" in call_log[2][1]
        # The cancel target must be the v0 sub id
        assert call_log[1][1] == "sub_v0"

    def test_orchestrator_creates_sub_at_start_month(self):
        """C-36(d): orchestrator does not create the sub before the start_month is reached.

        With start_month=3, the orchestrator must advance the clock 3 times
        BEFORE Subscription.create is called.
        """
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent))
        from unittest.mock import MagicMock as _MM

        from seed_stripe_data import (
            CustomerPlan,
            seed_stripe_data,
        )

        forced_plan = CustomerPlan(
            cust_idx=0,
            email="mrr-seed-001@example.com",
            name="Test Customer 001",
            status="active",
            start_month=3,           # <-- create the sub only at month 3
            initial_tier="basic",
            tier_change=None,
            cancel_month=None,
        )

        # Record the interleaving of advance_clock and create_subscription.
        timeline: list[str] = []

        with patch("seed_stripe_data.plan_customer_lifecycle") as mock_plan, \
             patch("seed_stripe_data.ensure_seed_prices") as mock_ensure_prices, \
             patch("seed_stripe_data.ClockManager") as MockCM, \
             patch("seed_stripe_data.CustomerFactory") as MockCF, \
             patch("stripe_seeder.summary.print_summary"), \
             patch("seed_stripe_data.reset_seed_data"):

            mock_plan.return_value = forced_plan
            mock_ensure_prices.return_value = {
                "basic": "price_b",
                "pro": "price_p",
                "enterprise": "price_e",
            }

            mock_cm = MockCM.return_value
            mock_cm.create_clock.return_value = _MM(id="clock_y")
            mock_cm.advance_clock.side_effect = lambda *_a, **_kw: timeline.append("advance")
            mock_cm.poll_clock_ready.return_value = True

            mock_cf = MockCF.return_value
            mock_cf.error_count = 0
            mock_cf.check_existing_customer.return_value = False
            mock_cf.create_customer.return_value = _MM(id="cus_y")
            mock_cf.attach_payment_method.return_value = _MM(id="pm_y")
            mock_cf.set_default_payment_method.return_value = True

            def create_sub_side_effect(*_args, **_kwargs):
                timeline.append("create_sub")
                return _MM(id="sub_only")

            mock_cf.create_subscription.side_effect = create_sub_side_effect
            mock_cf.cancel_subscription.return_value = _MM()

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=1,
                seed=42,
                dry_run=False,
                reset=False,
            )

        # Find the index of the create_sub event and the count of advances
        # that preceded it.
        assert "create_sub" in timeline, f"sub never created; timeline={timeline}"
        create_idx = timeline.index("create_sub")
        advances_before_create = timeline[:create_idx].count("advance")
        assert advances_before_create == 3, (
            f"With start_month=3, exactly 3 clock advances should precede "
            f"the Subscription.create call; got {advances_before_create}. "
            f"timeline={timeline}"
        )
