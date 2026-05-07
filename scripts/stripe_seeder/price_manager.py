"""Price management for Stripe seeding script.

Handles find-or-create of recurring Stripe Prices used by seed customers.

Iteration 14 (Sprint 1, C-37) introduces three monthly tiers — basic ($50),
pro ($100), enterprise ($250) — all attached to the single ``mrr-seed-plan``
Product. Tier identity is encoded in **Price** metadata (key
``mrr-seed-tier``), not Product metadata, so all three Prices share one
Product.
"""

import logging
from typing import Dict, List, Optional

import stripe

from .errors import PriceCreationError

logger = logging.getLogger(__name__)

# Seed product / price configuration
SEED_PRODUCT_NAME = "MRR Seed Plan"
SEED_PRODUCT_METADATA_KEY = "mrr-seed-plan"
SEED_PRODUCT_METADATA_VALUE = "true"
SEED_PRICE_CURRENCY = "usd"
SEED_PRICE_AMOUNT_CENTS = 5000  # $50.00 — kept for backward-compat references
SEED_PRICE_INTERVAL = "month"

# Tier configuration (C-37). Order matters only for deterministic dict iteration.
TIER_BASIC = "basic"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"
SEED_TIER_ORDER: List[str] = [TIER_BASIC, TIER_PRO, TIER_ENTERPRISE]
SEED_TIER_AMOUNTS_CENTS: Dict[str, int] = {
    TIER_BASIC: 5000,         # $50.00 / month
    TIER_PRO: 10000,          # $100.00 / month
    TIER_ENTERPRISE: 25000,   # $250.00 / month
}
SEED_TIER_METADATA_KEY = "mrr-seed-tier"

# Dry-run placeholder Price IDs (stable per tier for reproducibility).
_DRY_RUN_PRICE_IDS: Dict[str, str] = {
    TIER_BASIC: "price_test_mrr_dryrun",  # historical placeholder — keeps
                                          # legacy ensure_seed_price() return
                                          # value identical in dry-run mode.
    TIER_PRO: "price_test_mrr_pro_dryrun",
    TIER_ENTERPRISE: "price_test_mrr_enterprise_dryrun",
}


def _find_or_create_seed_product(api_key: str) -> stripe.Product:
    """Find the ``mrr-seed-plan`` Product or create it; live mode only.

    Raises:
        PriceCreationError: if Stripe returns an error during create.
    """
    query = (
        f"metadata['{SEED_PRODUCT_METADATA_KEY}']:"
        f"'{SEED_PRODUCT_METADATA_VALUE}' AND active:'true'"
    )
    result = stripe.Product.search(query=query, limit=10, api_key=api_key)
    products = result.data
    if products:
        product = products[0]
        logger.debug(f"Found existing seed Product: {product.id} ({product.name})")
        return product

    try:
        product = stripe.Product.create(
            name=SEED_PRODUCT_NAME,
            metadata={SEED_PRODUCT_METADATA_KEY: SEED_PRODUCT_METADATA_VALUE},
            api_key=api_key,
        )
        logger.info(f"Created seed Product: {product.id}")
        return product
    except stripe.error.StripeError as e:
        logger.error(
            f"Failed to create seed Product: {e}. "
            f"name={SEED_PRODUCT_NAME}, "
            f"metadata={SEED_PRODUCT_METADATA_KEY}={SEED_PRODUCT_METADATA_VALUE}"
        )
        raise PriceCreationError(f"Product creation failed: {e}") from e


def _find_tier_price(
    api_key: str, product_id: str, tier: str
) -> Optional[stripe.Price]:
    """Return the existing Price for ``tier`` on the seed Product, or None.

    Filters Prices by metadata key ``mrr-seed-tier``. Among recurring USD
    monthly Prices on the product, returns the first whose metadata matches.
    """
    prices = stripe.Price.list(
        product=product_id,
        type="recurring",
        currency=SEED_PRICE_CURRENCY,
        active=True,
        limit=100,
        api_key=api_key,
    )
    for price in prices.data:
        meta = getattr(price, "metadata", None) or {}
        if meta.get(SEED_TIER_METADATA_KEY) == tier:
            return price
    return None


def _create_tier_price(
    api_key: str, product_id: str, tier: str
) -> stripe.Price:
    """Create a recurring USD/month Price for ``tier`` on the seed Product."""
    amount_cents = SEED_TIER_AMOUNTS_CENTS[tier]
    try:
        price = stripe.Price.create(
            product=product_id,
            currency=SEED_PRICE_CURRENCY,
            unit_amount=amount_cents,
            recurring={
                "interval": SEED_PRICE_INTERVAL,
                "interval_count": 1,
            },
            metadata={SEED_TIER_METADATA_KEY: tier},
            api_key=api_key,
        )
        logger.info(
            f"Created seed Price for tier '{tier}': {price.id} "
            f"(unit_amount={amount_cents} cents)"
        )
        return price
    except stripe.error.StripeError as e:
        logger.error(
            f"Failed to create seed Price for tier '{tier}': {e}. "
            f"Parameters: product={product_id}, currency={SEED_PRICE_CURRENCY}, "
            f"unit_amount={amount_cents}, interval={SEED_PRICE_INTERVAL}, "
            f"metadata={SEED_TIER_METADATA_KEY}={tier}"
        )
        raise PriceCreationError(f"Price creation failed for tier '{tier}': {e}") from e


def ensure_seed_prices(api_key: str, dry_run: bool = False) -> Dict[str, str]:
    """Return ``{tier: price_id}`` for all three tiers (basic, pro, enterprise).

    Find-or-create per tier, identifying tier by Price metadata
    (``mrr-seed-tier``). All three Prices belong to the single seed Product
    (find-or-created via the legacy `mrr-seed-plan` metadata key).

    In dry-run mode, returns stable placeholder IDs without making API calls.

    Args:
        api_key: Stripe API key.
        dry_run: If True, skip API calls and return placeholders.

    Returns:
        ``{"basic": "price_...", "pro": "price_...", "enterprise": "price_..."}``.

    Raises:
        PriceCreationError: If Product or any tier Price creation fails.
    """
    if dry_run:
        logger.info(
            f"Resolved seed Prices (dry-run): {_DRY_RUN_PRICE_IDS}"
        )
        return dict(_DRY_RUN_PRICE_IDS)

    stripe.api_key = api_key
    try:
        product = _find_or_create_seed_product(api_key)
    except PriceCreationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error resolving seed Product: {e}")
        raise PriceCreationError(f"Unexpected error: {e}") from e

    resolved: Dict[str, str] = {}
    for tier in SEED_TIER_ORDER:
        try:
            existing = _find_tier_price(api_key, product.id, tier)
        except stripe.error.StripeError as e:
            logger.error(f"Error listing Prices for tier '{tier}': {e}")
            raise PriceCreationError(f"Price lookup failed for tier '{tier}': {e}") from e

        if existing is not None:
            logger.info(f"Resolved seed Price for tier '{tier}': {existing.id} (existing)")
            resolved[tier] = existing.id
            continue

        created = _create_tier_price(api_key, product.id, tier)
        resolved[tier] = created.id

    logger.info(
        f"Resolved seed Prices: basic={resolved[TIER_BASIC]}, "
        f"pro={resolved[TIER_PRO]}, enterprise={resolved[TIER_ENTERPRISE]}"
    )
    return resolved


def ensure_seed_price(api_key: str, dry_run: bool = False) -> str:
    """Return the basic-tier seed Price ID (legacy single-tier helper).

    Retained for backward compatibility with the C-31 live smoke test
    (`test_smoke_ensure_seed_price_idempotent`) and any external caller that
    only needs a single Price ID. Internally delegates to
    :func:`ensure_seed_prices` and returns the basic tier entry.

    In dry_run mode, returns the historical placeholder ``price_test_mrr_dryrun``.

    Args:
        api_key: Stripe API key.
        dry_run: If True, return placeholder without API calls.

    Returns:
        Stripe Price ID for the basic ($50/month) tier.

    Raises:
        PriceCreationError: If Price lookup or creation fails.
    """
    prices = ensure_seed_prices(api_key, dry_run=dry_run)
    return prices[TIER_BASIC]
