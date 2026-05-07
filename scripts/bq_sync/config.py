"""Configuration and environment variable loading for BigQuery sync."""

import logging
import os
import re
from typing import Optional

from .errors import InvalidAPIKeyError, InvalidDatasetNameError, ProductionSyncBlockedError

logger = logging.getLogger(__name__)


def load_stripe_api_key(cli_key: Optional[str] = None) -> str:
    """
    Load Stripe API key from CLI argument or environment variable.

    Args:
        cli_key: Optional API key from CLI --stripe-key flag

    Returns:
        Validated Stripe API key (test mode)

    Raises:
        InvalidAPIKeyError: If key is missing or in live mode
    """
    api_key = cli_key or os.environ.get("STRIPE_API_KEY")

    if not api_key:
        raise InvalidAPIKeyError(
            "STRIPE_API_KEY not set. Provide via --stripe-key flag or STRIPE_API_KEY environment variable."
        )

    # Reject live keys (C-63)
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


def validate_dataset_name(dataset_name: str) -> str:
    """
    Validate BigQuery dataset name.

    Dataset name must:
    - Match regex: ^[a-z0-9_]{1,1024}$
    - Not start with underscore (reserved for internal tables)

    Args:
        dataset_name: Dataset name to validate

    Returns:
        Validated dataset name

    Raises:
        InvalidDatasetNameError: If name is invalid (C-56)
    """
    if not dataset_name:
        raise InvalidDatasetNameError("Dataset name cannot be empty")

    if len(dataset_name) > 1024:
        raise InvalidDatasetNameError(
            f"Dataset name exceeds 1024 characters: {len(dataset_name)}"
        )

    if dataset_name.startswith("_"):
        raise InvalidDatasetNameError(
            "Dataset name cannot start with underscore (reserved for internal tables)"
        )

    # Regex: ^[a-z0-9_]{1,1024}$
    if not re.match(r"^[a-z0-9_]{1,1024}$", dataset_name):
        raise InvalidDatasetNameError(
            f"Dataset name must contain only lowercase letters, numbers, and underscores: {dataset_name}"
        )

    return dataset_name


def check_production_dataset_safety(dataset_name: str) -> None:
    """
    Check if dataset name indicates production and require explicit override.

    If dataset name contains 'prod' or 'live' (case-insensitive) and the
    ALLOW_PRODUCTION_SYNC environment variable is not set to 'true', raises
    ProductionSyncBlockedError (C-73).

    Args:
        dataset_name: Dataset name to check

    Raises:
        ProductionSyncBlockedError: If production dataset detected without override
    """
    # Case-insensitive check for 'prod' or 'live'
    if "prod" in dataset_name.lower() or "live" in dataset_name.lower():
        allow_prod = os.environ.get("ALLOW_PRODUCTION_SYNC", "").lower() == "true"
        if not allow_prod:
            logger.error(
                "Production dataset name rejected without ALLOW_PRODUCTION_SYNC=true"
            )
            raise ProductionSyncBlockedError(
                f"Dataset '{dataset_name}' appears to be a production dataset. "
                "Set ALLOW_PRODUCTION_SYNC=true to proceed."
            )
