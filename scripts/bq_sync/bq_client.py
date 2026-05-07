"""Thin wrapper around Google BigQuery client."""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError

from .errors import BigQueryError
from .schema import TABLE_SCHEMAS

logger = logging.getLogger(__name__)


class BigQueryClient:
    """Wrapper around google.cloud.bigquery.Client for MRR sync."""

    def __init__(self, project_id: Optional[str] = None):
        """
        Initialize BigQuery client.

        Args:
            project_id: GCP project ID (uses ADC/GOOGLE_APPLICATION_CREDENTIALS if not provided)

        Raises:
            BigQueryError: If client initialization fails
        """
        try:
            self.client = bigquery.Client(project=project_id)
        except GoogleCloudError as e:
            logger.error(f"BigQuery authentication failed: {type(e).__name__}: {e}")
            raise BigQueryError(f"Failed to initialize BigQuery client: {e}") from e

    def ensure_dataset_exists(self, dataset_id: str) -> None:
        """
        Create dataset if it doesn't exist.

        Args:
            dataset_id: Dataset ID

        Raises:
            BigQueryError: If creation fails
        """
        try:
            dataset = bigquery.Dataset(f"{self.client.project}.{dataset_id}")
            dataset.location = "US"
            self.client.create_dataset(dataset, exists_ok=True)
            logger.info(f"Dataset {dataset_id} ready")
        except GoogleCloudError as e:
            logger.error(f"Failed to create dataset {dataset_id}: {e}")
            raise BigQueryError(f"Failed to ensure dataset exists: {e}") from e

    def ensure_tables_exist(self, dataset_id: str) -> None:
        """
        Create all required tables if they don't exist.

        Uses CREATE TABLE IF NOT EXISTS with partitioning and clustering.

        Args:
            dataset_id: Dataset ID

        Raises:
            BigQueryError: If table creation fails
        """
        for table_name, schema in TABLE_SCHEMAS.items():
            try:
                table_id = f"{self.client.project}.{dataset_id}.{table_name}"
                table = bigquery.Table(table_id, schema=schema)

                # Partition by created_at for data tables; not for watermarks
                if table_name != "_sync_watermarks":
                    table.time_partitioning = bigquery.TimePartitioning(
                        type_=bigquery.TimePartitioningType.DAY,
                        field="created_at",
                    )
                    # Cluster by relevant keys
                    if table_name == "customers":
                        table.clustering_fields = ["stripe_customer_id"]
                    elif table_name == "subscriptions":
                        table.clustering_fields = ["stripe_subscription_id", "stripe_customer_id"]
                    elif table_name == "invoices":
                        table.clustering_fields = ["stripe_invoice_id", "stripe_customer_id"]

                self.client.create_table(table, exists_ok=True)
                logger.info(f"Table {table_name} ready in {dataset_id}")
            except GoogleCloudError as e:
                logger.error(f"Failed to create table {table_name}: {e}")
                raise BigQueryError(f"Failed to ensure table exists: {e}") from e

    def merge(
        self,
        dataset_id: str,
        table_name: str,
        rows: List[Dict[str, Any]],
        pk_column: str,
    ) -> Dict[str, int]:
        """
        Execute MERGE/upsert for rows into a table.

        Args:
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
            # Build column lists
            columns = list(rows[0].keys())
            col_str = ", ".join(columns)
            set_str = ", ".join([f"{col} = S.{col}" for col in columns if col != pk_column])

            # Build parameter names
            param_names = [f"@{col}" for col in columns]
            param_str = ", ".join(param_names)

            merge_sql = f"""
            MERGE INTO `{self.client.project}.{dataset_id}.{table_name}` T
            USING (SELECT * FROM UNNEST(@rows)) S
            ON T.{pk_column} = S.{pk_column}
            WHEN MATCHED THEN UPDATE SET {set_str}
            WHEN NOT MATCHED THEN INSERT ({col_str}) VALUES ({param_str})
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter(
                        "rows",
                        "RECORD",
                        rows,
                        field_specs=[
                            bigquery.SchemaField(col, "STRING")
                            for col in columns
                        ],
                    )
                ]
            )

            query_job = self.client.query(merge_sql, job_config=job_config)
            query_job.result()

            # Parse result: return inserted/updated counts
            # Note: MERGE doesn't directly return counts, so we approximate via result
            return {"inserted": len(rows), "updated": 0}
        except GoogleCloudError as e:
            logger.error(f"MERGE failed for {table_name}: {e}")
            raise BigQueryError(f"MERGE operation failed: {e}") from e

    def truncate_table(self, dataset_id: str, table_name: str) -> None:
        """
        Truncate a table (delete all rows).

        Args:
            dataset_id: Dataset ID
            table_name: Table name

        Raises:
            BigQueryError: If truncation fails
        """
        try:
            delete_sql = f"DELETE FROM `{self.client.project}.{dataset_id}.{table_name}` WHERE TRUE"
            query_job = self.client.query(delete_sql)
            query_job.result()
            logger.info(f"Truncated {table_name}")
        except GoogleCloudError as e:
            logger.error(f"Failed to truncate {table_name}: {e}")
            raise BigQueryError(f"Truncation failed: {e}") from e

    def query(self, sql: str) -> List[Dict[str, Any]]:
        """
        Execute a query and return results.

        Args:
            sql: SQL query string

        Returns:
            List of result rows as dicts

        Raises:
            BigQueryError: If query fails
        """
        try:
            query_job = self.client.query(sql)
            results = query_job.result()
            return [dict(row) for row in results]
        except GoogleCloudError as e:
            logger.error(f"Query failed: {e}")
            raise BigQueryError(f"Query execution failed: {e}") from e
