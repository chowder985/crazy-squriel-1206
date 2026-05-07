"""Price management for Stripe seeding script.

Handles find-or-create of recurring Stripe Prices used by seed customers.
"""

import logging

import stripe

from .errors import PriceCreationError

logger = logging.getLogger(__name__)

# Seed price configuration
SEED_PRODUCT_NAME = "MRR Seed Plan"
SEED_PRODUCT_METADATA_KEY = "mrr-seed-plan"
SEED_PRODUCT_METADATA_VALUE = "true"
SEED_PRICE_CURRENCY = "usd"
SEED_PRICE_AMOUNT_CENTS = 5000  # $50.00
SEED_PRICE_INTERVAL = "month"


def ensure_seed_price(api_key: str, dry_run: bool = False) -> str:
    """
    Find or create the recurring USD/month Price used by the seed run.

    In dry_run mode, returns a stable placeholder without making API calls.
    In live mode:
        1. Search existing Products for one with metadata key
           `mrr-seed-plan = "true"`.
        2. If found, return its first recurring USD Price ID.
        3. If not found, create a new Product + Price and return the Price ID.
        4. On any StripeError during creation, log the error with parameters
           and raise PriceCreationError.

    Args:
        api_key: Stripe API key
        dry_run: If True, return placeholder without API calls

    Returns:
        Stripe Price ID (real in live mode, placeholder in dry_run)

    Raises:
        PriceCreationError: If Price lookup or creation fails
    """
    if dry_run:
        placeholder = "price_test_mrr_dryrun"
        logger.info(f"Resolved seed Price: {placeholder} (dry-run placeholder)")
        return placeholder

    stripe.api_key = api_key

    try:
        # Search for existing Product with metadata
        logger.debug(
            f"Searching for existing Product with metadata {SEED_PRODUCT_METADATA_KEY}={SEED_PRODUCT_METADATA_VALUE}"
        )
        products = stripe.Product.list(
            metadata={SEED_PRODUCT_METADATA_KEY: SEED_PRODUCT_METADATA_VALUE},
            active=True,
            limit=100,
        )

        # Check if any product found
        if products.data:
            product = products.data[0]
            logger.debug(f"Found existing Product: {product.id} ({product.name})")

            # Search for recurring USD Price on this product
            prices = stripe.Price.list(
                product=product.id,
                type="recurring",
                currency=SEED_PRICE_CURRENCY,
                limit=100,
            )

            if prices.data:
                price = prices.data[0]
                logger.info(f"Resolved seed Price: {price.id} (existing)")
                return price.id

            # No recurring price found on existing product; will create below
            logger.debug(f"No recurring price found on product {product.id}, creating new...")
        else:
            logger.debug("No existing Product found with mrr-seed-plan metadata, creating new...")

        # Create new Product if we didn't find one
        if not products.data:
            try:
                product = stripe.Product.create(
                    name=SEED_PRODUCT_NAME,
                    metadata={SEED_PRODUCT_METADATA_KEY: SEED_PRODUCT_METADATA_VALUE},
                )
                logger.info(f"Created new Product: {product.id}")
            except stripe.error.StripeError as e:
                logger.error(
                    f"Failed to create Product: {e.user_message}. "
                    f"Parameters: name={SEED_PRODUCT_NAME}, "
                    f"metadata={SEED_PRODUCT_METADATA_KEY}={SEED_PRODUCT_METADATA_VALUE}"
                )
                raise PriceCreationError(f"Product creation failed: {e}") from e
        else:
            # Use the product we found earlier
            product = products.data[0]

        # Create recurring Price
        try:
            price = stripe.Price.create(
                product=product.id,
                currency=SEED_PRICE_CURRENCY,
                amount=SEED_PRICE_AMOUNT_CENTS,
                recurring={
                    "interval": SEED_PRICE_INTERVAL,
                    "interval_count": 1,
                },
            )
            logger.info(f"Resolved seed Price: {price.id} (newly created)")
            return price.id
        except stripe.error.StripeError as e:
            logger.error(
                f"Failed to create Price: {e.user_message}. "
                f"Parameters: product={product.id}, currency={SEED_PRICE_CURRENCY}, "
                f"amount={SEED_PRICE_AMOUNT_CENTS} cents, interval={SEED_PRICE_INTERVAL}"
            )
            raise PriceCreationError(f"Price creation failed: {e}") from e

    except PriceCreationError:
        # Re-raise PriceCreationError as-is
        raise
    except Exception as e:
        # Catch any other error and wrap it
        logger.error(f"Unexpected error resolving seed Price: {e}")
        raise PriceCreationError(f"Unexpected error: {e}") from e
