"""MERGE/upsert logic for BigQuery tables.

Iter-4 rewrite (2026-05-07): switched from ``ArrayQueryParameter("rows",
"RECORD", row_dicts)`` to a staging-table pattern. The previous approach
crashed at runtime with ``AttributeError: 'dict' object has no attribute
'to_api_repr'`` because BigQuery's ``ArrayQueryParameter`` for STRUCT/RECORD
arrays requires each element to be a ``StructQueryParameter`` with typed
``ScalarQueryParameter`` children, not raw dicts. Mocked unit tests in
iter-1/iter-2/iter-3 accepted any ``query()`` kwargs so the failure didn't
surface until iter-4 live exercise.

The staging-table idiom is the standard BigQuery bulk-upsert pattern:
1. Read the target table's schema.
2. Create a per-call ephemeral staging table with the same schema (1-hour
   expiry as a safety net in case of crash before cleanup).
3. ``insert_rows_json(staging_table, rows)`` bulk-loads dicts (TIMESTAMP
   strings auto-parsed; JSON columns store as STRING).
4. ``MERGE INTO target USING staging ON pk WHEN MATCHED THEN UPDATE …
   WHEN NOT MATCHED THEN INSERT …`` resolves the upsert atomically.
5. ``delete_table(staging_table)`` cleans up.

Trade-off: the staging-table approach makes 4 BigQuery API calls per merge
(get_table, create_table, insert_rows_json, query, delete_table) instead of
1; for Sprint 2's batch size (~tens to thousands of rows per entity per
sync), the overhead is acceptable.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from google.cloud import bigquery

from .bq_client import BigQueryClient
from .errors import BigQueryError

logger = logging.getLogger(__name__)


def merge_rows(
    client: BigQueryClient,
    dataset_id: str,
    table_name: str,
    rows: List[Dict[str, Any]],
    pk_column: str,
) -> Dict[str, int]:
    """
    Execute MERGE/upsert for rows into a BigQuery table (C-50, C-54).

    Args:
        client: BigQueryClient instance.
        dataset_id: Dataset ID.
        table_name: Target table name.
        rows: List of row dicts to merge. Each dict must have keys matching
            the target table's schema; missing keys default to NULL.
        pk_column: Primary key column name (used in MERGE ON clause).

    Returns:
        Dict with 'inserted' and 'updated' counts. ``inserted`` here is the
        total number of rows processed (BigQuery doesn't surface a per-row
        matched-vs-not-matched split without a follow-up query); the field
        is preserved for caller compatibility but should be read as
        "processed".

    Raises:
        BigQueryError: If staging-table lifecycle, insert, or merge fails.
    """
    if not rows:
        return {"inserted": 0, "updated": 0}

    project = client.client.project
    target_full_id = f"{project}.{dataset_id}.{table_name}"
    staging_name = f"_staging_{table_name}_{uuid.uuid4().hex[:8]}"
    staging_full_id = f"{project}.{dataset_id}.{staging_name}"

    try:
        # 1. Read target schema (also confirms the target exists; if not, the
        #    caller forgot to ensure_tables_exist() and we want to fail loudly).
        target_table = client.client.get_table(target_full_id)
        columns = [field.name for field in target_table.schema]

        # 2. Create staging table with the same schema. 1-hour expiry is a
        #    safety net so a crash mid-merge doesn't leave permanent debris —
        #    BigQuery will drop the table automatically.
        staging_table = bigquery.Table(staging_full_id, schema=target_table.schema)
        staging_table.expires = datetime.now(timezone.utc) + timedelta(hours=1)
        client.client.create_table(staging_table, exists_ok=False)

        try:
            # 3. Bulk-load rows. insert_rows_json accepts plain dicts and
            #    parses ISO-8601 strings into TIMESTAMP automatically.
            errors = client.client.insert_rows_json(staging_table, rows)
            if errors:
                raise BigQueryError(
                    f"insert_rows_json into {staging_full_id} returned errors: {errors}"
                )

            # 4. MERGE staging → target.
            col_str = ", ".join(f"`{c}`" for c in columns)
            set_clauses = [
                f"`{c}` = S.`{c}`" for c in columns if c != pk_column
            ]
            set_str = (
                ", ".join(set_clauses)
                if set_clauses
                else f"`{pk_column}` = S.`{pk_column}`"
            )
            values_str = ", ".join(f"S.`{c}`" for c in columns)

            merge_sql = f"""
            MERGE INTO `{target_full_id}` T
            USING `{staging_full_id}` S
            ON T.`{pk_column}` = S.`{pk_column}`
            WHEN MATCHED THEN UPDATE SET {set_str}
            WHEN NOT MATCHED THEN INSERT ({col_str}) VALUES ({values_str})
            """
            query_job = client.client.query(merge_sql)
            query_job.result()

            logger.info(
                f"MERGE {table_name}: {len(rows)} rows processed via staging"
            )
            return {"inserted": len(rows), "updated": 0}
        finally:
            # 5. Drop the staging table. Don't fail the merge on cleanup error.
            try:
                client.client.delete_table(staging_full_id, not_found_ok=True)
            except Exception as cleanup_err:
                logger.warning(
                    f"Failed to drop staging table {staging_full_id}: {cleanup_err}"
                )
    except BigQueryError:
        raise
    except Exception as e:
        logger.error(f"MERGE failed for {table_name}: {type(e).__name__}: {e}")
        raise BigQueryError(f"MERGE operation failed: {e}") from e
