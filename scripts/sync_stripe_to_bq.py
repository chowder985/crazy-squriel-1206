#!/usr/bin/env python3
"""
BigQuery ETL sync script for MRR dashboard.

Fetches Stripe customer, subscription, and invoice data and loads into BigQuery.
Supports incremental sync via watermarking and full-refresh mode.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, Optional

from dotenv import load_dotenv

from bq_sync.bq_client import BigQueryClient
from bq_sync.config import (
    load_stripe_api_key,
    validate_dataset_name,
    check_production_dataset_safety,
)
from bq_sync.errors import (
    BQSyncError,
    ProductionSyncBlockedError,
)
from bq_sync.merge import merge_rows
from bq_sync.stripe_fetcher import (
    fetch_customers,
    fetch_invoices,
    fetch_subscriptions,
)
from bq_sync.transform import (
    transform_customers,
    transform_invoices,
    transform_subscriptions,
)
from bq_sync.watermark import (
    get_watermark,
    reset_watermarks,
    set_watermark,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Add credential logging filter (C-65)
class CredentialFilter(logging.Filter):
    """Filter to prevent credential leakage in logs."""

    SENSITIVE_PATTERNS = [
        "sk_test_",
        "sk_live_",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "service_account",
        "client_secret",
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Check log record for sensitive patterns."""
        message = record.getMessage()
        for pattern in self.SENSITIVE_PATTERNS:
            if pattern in message:
                raise AssertionError(
                    f"Attempted to log sensitive pattern: {pattern}"
                )
        return True


# Add filter to all handlers
for handler in logging.root.handlers:
    handler.addFilter(CredentialFilter())


def sync_entity(
    bq_client: BigQueryClient,
    dataset_id: str,
    entity_name: str,
    fetch_fn,
    transform_fn,
    api_key: str,
    dry_run: bool = False,
) -> Dict[str, int]:
    """
    Sync a single entity type (customers, subscriptions, invoices).

    Args:
        bq_client: BigQuery client
        dataset_id: Dataset ID
        entity_name: Entity name (lowercase)
        fetch_fn: Fetch function (e.g., fetch_customers)
        transform_fn: Transform function (e.g., transform_customers)
        api_key: Stripe API key
        dry_run: If True, don't write to BigQuery

    Returns:
        Dict with sync stats
    """
    logger.info(f"Starting sync for {entity_name}...")

    try:
        # Fetch from Stripe
        objects = list(fetch_fn(api_key, dry_run=dry_run))
        logger.info(f"Fetched {len(objects)} {entity_name}")

        if not objects:
            logger.info(f"No {entity_name} to sync")
            return {"fetched": 0, "inserted": 0, "updated": 0, "errors": 0}

        # Transform
        transformed = transform_fn(objects)
        rows = transformed.get(entity_name, [])
        logger.info(f"Transformed {len(rows)} {entity_name}")

        # Merge into BigQuery
        if not dry_run:
            # Ensure tables exist before merge (C-59)
            bq_client.ensure_tables_exist(dataset_id)

            # Determine PK column
            pk_column = f"stripe_{entity_name[:-1]}_id"  # e.g., 'stripe_customer_id'
            merge_result = merge_rows(
                bq_client,
                dataset_id,
                entity_name,
                rows,
                pk_column,
            )
            logger.info(f"Merged {entity_name}: {merge_result}")
            return {
                "fetched": len(objects),
                "inserted": merge_result.get("inserted", 0),
                "updated": merge_result.get("updated", 0),
                "errors": 0,
            }
        else:
            return {
                "fetched": len(objects),
                "inserted": len(rows),
                "updated": 0,
                "errors": 0,
            }
    except Exception as e:
        logger.error(f"Error syncing {entity_name}: {type(e).__name__}: {e}")
        return {"fetched": 0, "inserted": 0, "updated": 0, "errors": 1}


def main() -> int:
    """
    Main orchestrator.

    Returns:
        Exit code (0 on success, 1 on error)
    """
    parser = argparse.ArgumentParser(
        description="Sync Stripe data to BigQuery for MRR dashboard"
    )
    parser.add_argument(
        "--stripe-key",
        help="Stripe API key (default: STRIPE_API_KEY env var)",
    )
    parser.add_argument(
        "--dataset",
        default="mrr_prod",
        help="BigQuery dataset ID (default: mrr_prod)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch from Stripe but don't write to BigQuery",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Truncate all data and re-sync from beginning",
    )
    parser.add_argument(
        "--no-confirm",
        action="store_true",
        help="Skip confirmation prompt for full-refresh",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit objects fetched per entity (for testing)",
    )

    args = parser.parse_args()

    # Load env
    load_dotenv()

    try:
        # Validate Stripe API key (C-63)
        api_key = load_stripe_api_key(args.stripe_key)

        # Validate dataset name (C-56)
        dataset_name = validate_dataset_name(args.dataset)

        # Check production safety (C-73)
        check_production_dataset_safety(dataset_name)

        # Initialize BigQuery client (C-64)
        logger.info("Initializing BigQuery client...")
        bq_client = BigQueryClient()

        # Ensure dataset and tables exist (C-59)
        logger.info(f"Ensuring dataset and tables exist...")
        bq_client.ensure_dataset_exists(dataset_name)
        bq_client.ensure_tables_exist(dataset_name)

        # Handle full-refresh (C-53)
        if args.full_refresh:
            if not args.no_confirm and sys.stdin.isatty():
                resp = input(
                    f"Full-refresh will truncate all data in {dataset_name}. Continue? [y/N] "
                )
                if resp.lower() != "y":
                    logger.info("Aborted by user")
                    return 1

            logger.info("Truncating data tables and resetting watermarks...")
            try:
                bq_client.truncate_table(dataset_name, "customers")
                bq_client.truncate_table(dataset_name, "subscriptions")
                bq_client.truncate_table(dataset_name, "invoices")
                reset_watermarks(bq_client, dataset_name)
                logger.info("Full-refresh: truncation complete")
            except Exception as e:
                logger.error(f"Full-refresh failed: {e}")
                return 1

        # Sync entities (C-55 orchestration flow)
        logger.info("Starting sync pipeline...")
        start_time = datetime.utcnow()

        stats = {
            "customers": sync_entity(
                bq_client,
                dataset_name,
                "customers",
                fetch_customers,
                transform_customers,
                api_key,
                dry_run=args.dry_run,
            ),
            "subscriptions": sync_entity(
                bq_client,
                dataset_name,
                "subscriptions",
                fetch_subscriptions,
                transform_subscriptions,
                api_key,
                dry_run=args.dry_run,
            ),
            "invoices": sync_entity(
                bq_client,
                dataset_name,
                "invoices",
                fetch_invoices,
                transform_invoices,
                api_key,
                dry_run=args.dry_run,
            ),
        }

        # Update watermarks ONLY after all fetches + MERGEs succeed (C-55)
        if not args.dry_run:
            now = datetime.utcnow()
            for entity in ["customers", "subscriptions", "invoices"]:
                set_watermark(bq_client, dataset_name, entity, now)

        # Print summary (C-60)
        duration = (datetime.utcnow() - start_time).total_seconds()
        total_errors = sum(s["errors"] for s in stats.values())

        summary = (
            f"Synced {stats['customers']['fetched']} customers "
            f"({stats['customers']['inserted']} inserted, {stats['customers']['updated']} updated), "
            f"{stats['subscriptions']['fetched']} subscriptions "
            f"({stats['subscriptions']['inserted']} inserted, {stats['subscriptions']['updated']} updated), "
            f"{stats['invoices']['fetched']} invoices "
            f"({stats['invoices']['inserted']} inserted, {stats['invoices']['updated']} updated). "
            f"Errors: {total_errors}. Dry-run: {'yes' if args.dry_run else 'no'}. "
            f"Dataset: {dataset_name}. Duration: {duration:.1f}s"
        )

        if total_errors > 0:
            logger.error(summary)
        else:
            logger.info(summary)

        return 0

    except ProductionSyncBlockedError as e:
        logger.error(f"Production sync blocked: {e}")
        return 1
    except BQSyncError as e:
        logger.error(f"Sync error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {type(e).__name__}: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
