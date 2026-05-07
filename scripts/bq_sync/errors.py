"""Custom exceptions for BigQuery ETL sync."""


class BQSyncError(Exception):
    """Base exception for all BigQuery sync errors."""

    pass


class BigQueryError(BQSyncError):
    """Raised when BigQuery operation fails."""

    pass


class InvalidDatasetNameError(BQSyncError):
    """Raised when dataset name is invalid or unsafe."""

    pass


class InvalidAPIKeyError(BQSyncError):
    """Raised when Stripe API key is invalid or in live mode."""

    pass


class ProductionSyncBlockedError(BQSyncError):
    """Raised when attempting to sync to a production dataset without override."""

    pass


class StripeAPIError(BQSyncError):
    """Raised when Stripe API returns an error."""

    pass


class TransformError(BQSyncError):
    """Raised when transforming Stripe objects to BigQuery rows fails."""

    pass
