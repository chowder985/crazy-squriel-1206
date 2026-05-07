"""Configuration and environment variable loading."""

import logging
import os
from typing import Optional

from .errors import InvalidAPIKeyError

logger = logging.getLogger(__name__)


def load_api_key(cli_key: Optional[str] = None) -> str:
    """
    Load Stripe API key from CLI argument or environment variable.

    Args:
        cli_key: Optional API key from CLI --api-key flag

    Returns:
        Validated Stripe API key (test mode)

    Raises:
        InvalidAPIKeyError: If key is missing or in live mode
    """
    # CLI flag takes precedence
    api_key = cli_key or os.environ.get("STRIPE_API_KEY")

    if not api_key:
        raise InvalidAPIKeyError(
            "STRIPE_API_KEY not set. Provide via --api-key flag or STRIPE_API_KEY environment variable."
        )

    # Validate: reject live keys
    if api_key.startswith("sk_live_"):
        raise InvalidAPIKeyError(
            "Live API key detected (sk_live_*). This script only works with test keys (sk_test_*). "
            "Get a test key from https://dashboard.stripe.com/apikeys"
        )

    if not api_key.startswith("sk_test_"):
        logger.warning(
            "API key does not start with 'sk_test_'. Ensure you are using a test key."
        )

    return api_key
