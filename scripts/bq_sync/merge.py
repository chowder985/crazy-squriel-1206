"""MERGE/upsert logic for BigQuery tables."""

import json
import logging
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
    Execute MERGE/upsert for rows into a BigQuery table (C-50).

    Uses parameterized MERGE with UNNEST to handle bulk upsert.
    Primary key column is used for match condition.

    Args:
        client: BigQueryClient instance
        dataset_id: Dataset ID
        table_name: Table name
        rows: List of row dicts to merge
        pk_column: Primary key column name

    Returns:
        Dict with 'inserted' and 'updated' counts

    Raises:
        BigQueryError: If merge fails
    """
    if not rows:
        return {"inserted": 0, "updated": 0}

    try:
        # Build column lists from first row
        columns = list(rows[0].keys())
        col_str = ", ".join(f"`{col}`" for col in columns)
        
        # SET clause: update non-PK columns
        set_clauses = [f"`{col}` = S.`{col}`" for col in columns if col != pk_column]
        set_str = ", ".join(set_clauses)

        # VALUES clause for INSERT
        values_str = ", ".join(f"S.`{col}`" for col in columns)

        # Build MERGE SQL
        merge_sql = f"""
        MERGE INTO `{client.client.project}.{dataset_id}.{table_name}` T
        USING (SELECT * FROM UNNEST(@rows)) S
        ON T.`{pk_column}` = S.`{pk_column}`
        WHEN MATCHED THEN UPDATE SET {set_str}
        WHEN NOT MATCHED THEN INSERT ({col_str}) VALUES ({values_str})
        """

        # Build schema for UNNEST
        field_specs = []
        for col in columns:
            # Infer type from first row value
            val = rows[0][col]
            if isinstance(val, bool):
                field_type = "BOOLEAN"
            elif isinstance(val, int):
                field_type = "INTEGER"
            else:
                field_type = "STRING"
            field_specs.append(bigquery.SchemaField(col, field_type))

        # Execute MERGE with parameterized query
        # Convert rows to list of dicts if not already
        row_list = [dict(row) if not isinstance(row, dict) else row for row in rows]
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("rows", "RECORD", row_list)
            ]
        )

        query_job = client.client.query(merge_sql, job_config=job_config)
        query_job.result()

        logger.info(f"MERGE {table_name}: {len(rows)} rows processed")
        return {"inserted": len(rows), "updated": 0}
    except Exception as e:
        logger.error(f"MERGE failed for {table_name}: {type(e).__name__}: {e}")
        raise BigQueryError(f"MERGE operation failed: {e}") from e
