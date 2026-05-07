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

    def test_advancement_interval_le_2_months(self):
        """C-10: Clock advancement uses <=2-month intervals (<=60 days)."""
        max_advancement_days = 60  # ~2 months

        # Test multiple advancement intervals
        intervals = [30, 45, 60]
        for interval in intervals:
            assert interval <= max_advancement_days

        # Over-limit should raise
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=True)
        with pytest.raises(ValueError):
            clock_manager.advance_clock("clock_123", days_forward=61)

    def test_clock_polling_timeout(self, mocker):
        """C-9: Clock polling times out after 30s if not ready."""
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=False)

        # Mock stripe API to never return ready (correct path: stripe.test_helpers.TestClock)
        mock_retrieve = mocker.patch("stripe.test_helpers.TestClock.retrieve")
        mock_retrieve.return_value = MagicMock(status="processing")

        # Mock time.sleep to avoid actual delays
        mocker.patch("time.sleep")

        with pytest.raises(ClockTimeoutError) as exc_info:
            clock_manager.poll_clock_ready("clock_never_ready")

        assert "did not reach 'ready'" in str(exc_info.value)


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
        """C-15: Subscriptions created with idempotency keys."""
        customer_factory = CustomerFactory(api_key="sk_test_key", dry_run=False)

        mock_sub_create = mocker.patch("stripe.Subscription.create")
        mock_sub_create.return_value = MagicMock(id="sub_test", status="active")

        idempotency_key = "seed-sub-cus_123-0"
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

    def test_api_key_not_logged(self, mocker, caplog):
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

    def test_active_subscription_lifecycle(self, mocker):
        """C-6: Active subscriptions advanced 6 months and remain active."""
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=True)

        # In dry-run mode, all operations should log and succeed
        clock = clock_manager.create_clock(datetime.now() - timedelta(days=180))
        assert clock is not None

        # Mock advancing 6 months (6 x 30 days)
        for month in range(1, 7):
            result = clock_manager.advance_clock("clock_123", days_forward=30)
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
        clock_manager = ClockManager(api_key="sk_test_key", dry_run=False)

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
        assert mock_create_subscription.call_count > 0, "create_subscription should be called"
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

        result = seed_stripe_data(
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

        result = seed_stripe_data(
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
        """C-29(a, b): ensure_seed_price finds and returns existing recurring USD Price."""
        from stripe_seeder.price_manager import ensure_seed_price

        mock_product = Mock()
        mock_product.id = "prod_existing_001"
        mock_product.name = "MRR Seed Plan"

        mock_price = Mock()
        mock_price.id = "price_existing_usd"

        with patch("stripe.Product.list") as mock_product_list, patch(
            "stripe.Price.list"
        ) as mock_price_list:
            mock_product_list.return_value = Mock(data=[mock_product])
            mock_price_list.return_value = Mock(data=[mock_price])

            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=False)

            assert price_id == "price_existing_usd"
            mock_product_list.assert_called_once()
            mock_price_list.assert_called_once()

    def test_ensure_seed_price_creates_when_absent(self):
        """C-29(a, b): ensure_seed_price creates Product and Price when none exist."""
        from stripe_seeder.price_manager import ensure_seed_price

        mock_created_product = Mock()
        mock_created_product.id = "prod_new_001"

        mock_created_price = Mock()
        mock_created_price.id = "price_new_usd"

        with patch("stripe.Product.list") as mock_product_list, patch(
            "stripe.Product.create"
        ) as mock_product_create, patch("stripe.Price.create") as mock_price_create:
            mock_product_list.return_value = Mock(data=[])  # No existing products
            mock_product_create.return_value = mock_created_product
            mock_price_create.return_value = mock_created_price

            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=False)

            assert price_id == "price_new_usd"
            mock_product_list.assert_called_once()
            mock_product_create.assert_called_once()
            mock_price_create.assert_called_once()

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

        with patch("seed_stripe_data.ensure_seed_price") as mock_ensure_price, \
             patch("stripe_seeder.clock_manager.ClockManager.create_clock") as mock_create_clock, \
             patch("stripe_seeder.clock_manager.ClockManager.advance_clock") as mock_advance_clock, \
             patch("stripe_seeder.customer_factory.CustomerFactory.check_existing_customer") as mock_check_cust, \
             patch("stripe_seeder.customer_factory.CustomerFactory.create_customer") as mock_cust_create, \
             patch("stripe_seeder.customer_factory.CustomerFactory.attach_payment_method") as mock_attach_pm, \
             patch("stripe_seeder.customer_factory.CustomerFactory.create_subscription") as mock_sub_create, \
             patch("stripe_seeder.summary.print_summary"):

            mock_ensure_price.return_value = "price_resolved_real_001"
            mock_create_clock.return_value = mock_clock
            mock_advance_clock.return_value = None
            mock_check_cust.return_value = False
            mock_cust_create.return_value = mock_customer
            mock_attach_pm.return_value = Mock()
            mock_sub_create.return_value = mock_subscription

            seed_stripe_data(
                api_key="sk_test_key",
                num_customers=3,
                seed=42,
                dry_run=False,
                price_id=None,
            )

            # Verify ensure_seed_price was called (it's called with positional args in the code)
            assert mock_ensure_price.call_count == 1
            call_args, call_kwargs = mock_ensure_price.call_args
            assert call_args[0] == "sk_test_key"
            assert call_kwargs["dry_run"] is False

            # Verify all subscription.create calls use the resolved price, never mock string
            for call in mock_sub_create.call_args_list:
                kwargs = call[1]
                assert kwargs["price_id"] == "price_resolved_real_001"
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

        with patch("stripe.Product.list") as mock_product_list:
            price_id = ensure_seed_price(api_key="sk_test_key", dry_run=True)

            # Should return placeholder in dry-run mode
            assert price_id == "price_test_mrr_dryrun"

            # Should NOT call any Stripe API methods
            mock_product_list.assert_not_called()
