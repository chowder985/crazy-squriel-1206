"""Manage sync watermarks for incremental sync."""

import logging
from datetime import datetime
from typing import Optional

from .bq_client import BigQueryClient
from .errors import BigQueryError

logger = logging.getLogger(__name__)


def get_watermark(client: BigQueryClient, dataset_id: str, sync_key: str) -> Optional[datetime]:
    """
    Get last sync timestamp for a sync_key from _sync_watermarks table.

    Args:
        client: BigQuery client
        dataset_id: Dataset ID
        sync_key: Sync phase key (e.g., 'customers', 'subscriptions')

    Returns:
        Last synced datetime (UTC) or None if not found

    Raises:
        BigQueryError: On query failure
    """
    try:
        sql = f"""
        SELECT last_synced_at
        FROM `{client.client.project}.{dataset_id}._sync_watermarks`
        WHERE sync_key = @sync_key
        LIMIT 1
        """
        results = client.query(sql)
        if results:
            return results[0]["last_synced_at"]
        return None
    except BigQueryError:
        raise
    except Exception as e:
        logger.error(f"Failed to get watermark for {sync_key}: {e}")
        raise BigQueryError(f"Watermark query failed: {e}") from e


def set_watermark(client: BigQueryClient, dataset_id: str, sync_key: str, timestamp: datetime) -> None:
    """
    Set or update watermark for a sync_key in _sync_watermarks table.

    Uses MERGE to insert or update the row.

    Args:
        client: BigQuery client
        dataset_id: Dataset ID
        sync_key: Sync phase key
        timestamp: New watermark timestamp

    Raises:
        BigQueryError: On query failure
    """
    try:
        timestamp_str = timestamp.isoformat() + "Z"
        sql = f"""
        MERGE INTO `{client.client.project}.{dataset_id}._sync_watermarks` T
        USING (SELECT @sync_key as sync_key, @timestamp as last_synced_at) S
        ON T.sync_key = S.sync_key
        WHEN MATCHED THEN UPDATE SET last_synced_at = S.last_synced_at
        WHEN NOT MATCHED THEN INSERT (sync_key, last_synced_at) VALUES (S.sync_key, S.last_synced_at)
        """

        job_config = {
            "query_parameters": [
                {"parameterType": {"type": "STRING"}, "parameterValue": {"value": sync_key}},
                {"parameterType": {"type": "TIMESTAMP"}, "parameterValue": {"value": timestamp_str}},
            ]
        }

        client.client.query(sql, job_config=job_config).result()
        logger.info(f"Updated watermark for {sync_key}: {timestamp_str}")
    except Exception as e:
        logger.error(f"Failed to set watermark for {sync_key}: {e}")
        raise BigQueryError(f"Watermark update failed: {e}") from e


def reset_watermarks(client: BigQueryClient, dataset_id: str) -> None:
    """
    Reset all watermarks (truncate _sync_watermarks table).

    Used by --full-refresh to restart sync from beginning.

    Args:
        client: BigQuery client
        dataset_id: Dataset ID

    Raises:
        BigQueryError: On truncation failure
    """
    try:
        client.truncate_table(dataset_id, "_sync_watermarks")
        logger.info("Reset all sync watermarks")
    except BigQueryError:
        raise
    except Exception as e:
        logger.error(f"Failed to reset watermarks: {e}")
        raise BigQueryError(f"Watermark reset failed: {e}") from e
