"""Customer and subscription creation logic."""

import logging
import random
from typing import List, Optional, Tuple

import stripe

from .errors import InvalidAPIResponseError, RateLimitExceededError

logger = logging.getLogger(__name__)

# Rate limit constants
MAX_RETRIES = 5
BACKOFF_MULTIPLIER = [1, 2, 4, 8, 16]  # exponential backoff in seconds


class CustomerFactory:
    """Factory for creating customers and subscriptions with rate-limit handling."""

    def __init__(self, api_key: str, dry_run: bool = False):
        """
        Initialize CustomerFactory.

        Args:
            api_key: Stripe API key
            dry_run: If True, log operations without making API calls
        """
        self.api_key = api_key
        self.dry_run = dry_run
        self.error_count = 0

    def check_existing_customer(self, email: str, test_clock_id: Optional[str] = None) -> bool:
        """
        Check if a customer with the given email already exists.

        Args:
            email: Customer email to check
            test_clock_id: Optional test clock ID to filter by

        Returns:
            True if customer exists, False otherwise
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would check for existing customer {email}")
            return False

        try:
            customers = stripe.Customer.list(email=email, api_key=self.api_key, limit=1)
            if len(customers) > 0:
                logger.info(f"Customer {email} already exists, skipping creation")
                return True
            return False
        except stripe.error.StripeError as e:
            logger.warning(f"Error checking for existing customer {email}: {e}")
            return False

    def create_customer(
        self, email: str, name: str, test_clock_id: str
    ) -> Optional[stripe.Customer]:
        """
        Create a new customer with rate-limit handling.

        Args:
            email: Customer email
            name: Customer name
            test_clock_id: Test clock ID for this customer

        Returns:
            Created Customer object or None if creation failed after retries
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create customer {email}")
            return type(
                "MockCustomer",
                (),
                {"id": "cus_dryrun_001", "email": email, "name": name},
            )()

        for attempt in range(MAX_RETRIES + 1):
            try:
                customer = stripe.Customer.create(
                    email=email,
                    name=name,
                    test_clock=test_clock_id,
                    api_key=self.api_key,
                )
                logger.info(f"Created customer {customer.id} ({email})")
                return customer
            except stripe.error.RateLimitError as e:
                if attempt < MAX_RETRIES:
                    wait_time = BACKOFF_MULTIPLIER[attempt]
                    logger.warning(
                        f"Rate limited creating customer {email}, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES + 1})"
                    )
                    import time

                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to create customer {email} after {MAX_RETRIES + 1} attempts"
                    )
                    self.error_count += 1
                    return None
            except stripe.error.StripeError as e:
                logger.error(f"Error creating customer {email}: {e}")
                self.error_count += 1
                return None

        return None

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        test_clock_id: str,
        idempotency_key: Optional[str] = None,
    ) -> Optional[stripe.Subscription]:
        """
        Create a subscription with rate-limit handling.

        Args:
            customer_id: ID of the customer
            price_id: Price ID for the subscription
            test_clock_id: Test clock ID
            idempotency_key: Optional idempotency key

        Returns:
            Created Subscription object or None if creation failed
        """
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would create subscription for customer {customer_id} "
                f"with price {price_id}"
            )
            return type(
                "MockSubscription",
                (),
                {
                    "id": "sub_dryrun_001",
                    "customer": customer_id,
                    "items": type("Items", (), {"data": []}),
                    "status": "active",
                },
            )()

        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs = {
                    "customer": customer_id,
                    "items": [{"price": price_id}],
                    "api_key": self.api_key,
                }
                if idempotency_key:
                    kwargs["idempotency_key"] = idempotency_key

                subscription = stripe.Subscription.create(**kwargs)
                logger.info(
                    f"Created subscription {subscription.id} for customer {customer_id}"
                )
                return subscription
            except stripe.error.RateLimitError as e:
                if attempt < MAX_RETRIES:
                    wait_time = BACKOFF_MULTIPLIER[attempt]
                    logger.warning(
                        f"Rate limited creating subscription for {customer_id}, "
                        f"retrying in {wait_time}s (attempt {attempt + 1}/{MAX_RETRIES + 1})"
                    )
                    import time

                    time.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to create subscription for {customer_id} "
                        f"after {MAX_RETRIES + 1} attempts"
                    )
                    self.error_count += 1
                    return None
            except stripe.error.StripeError as e:
                logger.error(f"Error creating subscription for {customer_id}: {e}")
                self.error_count += 1
                return None

        return None

    def cancel_subscription(self, subscription_id: str) -> Optional[stripe.Subscription]:
        """
        Cancel a subscription.

        Args:
            subscription_id: ID of subscription to cancel

        Returns:
            Canceled Subscription object or None if cancellation failed
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel subscription {subscription_id}")
            return type(
                "MockSubscription",
                (),
                {"id": subscription_id, "status": "canceled"},
            )()

        try:
            subscription = stripe.Subscription.delete(
                subscription_id, api_key=self.api_key
            )
            logger.info(f"Canceled subscription {subscription_id}")
            return subscription
        except stripe.error.StripeError as e:
            logger.error(f"Error canceling subscription {subscription_id}: {e}")
            self.error_count += 1
            return None

    def attach_payment_method(
        self, customer_id: str, payment_method_id: str
    ) -> Optional[stripe.PaymentMethod]:
        """
        Attach a payment method to a customer.

        Args:
            customer_id: Customer ID
            payment_method_id: Payment method ID

        Returns:
            Attached PaymentMethod or None
        """
        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would attach payment method {payment_method_id} "
                f"to customer {customer_id}"
            )
            return type(
                "MockPaymentMethod",
                (),
                {"id": payment_method_id, "customer": customer_id},
            )()

        try:
            pm = stripe.PaymentMethod.attach(
                payment_method_id,
                customer=customer_id,
                api_key=self.api_key,
            )
            logger.info(
                f"Attached payment method {payment_method_id} to customer {customer_id}"
            )
            return pm
        except stripe.error.StripeError as e:
            logger.error(
                f"Error attaching payment method {payment_method_id} "
                f"to customer {customer_id}: {e}"
            )
            self.error_count += 1
            return None
