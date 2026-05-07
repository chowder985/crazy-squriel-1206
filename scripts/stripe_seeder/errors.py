"""Custom exceptions for Stripe seeding script."""


class StripeSeederError(Exception):
    """Base exception for all seeding errors."""

    pass


class ClockTimeoutError(StripeSeederError):
    """Raised when a test clock fails to reach 'ready' status within timeout."""

    pass


class RateLimitExceededError(StripeSeederError):
    """Raised when rate limit retries are exhausted."""

    pass


class InvalidAPIKeyError(StripeSeederError):
    """Raised when API key is invalid or in live mode."""

    pass


class InvalidAPIResponseError(StripeSeederError):
    """Raised when Stripe API response is invalid or missing required fields."""

    pass


class PriceCreationError(StripeSeederError):
    """Raised when Price or Product creation fails."""

    pass
