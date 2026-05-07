"""BigQuery table schema definitions."""

from typing import List

from google.cloud.bigquery import SchemaField


# Schema fields for customers table (C-38)
CUSTOMERS_SCHEMA: List[SchemaField] = [
    SchemaField("stripe_customer_id", "STRING", mode="REQUIRED", description="Stripe Customer ID (PK)"),
    SchemaField("email", "STRING", mode="NULLABLE", description="Customer email"),
    SchemaField("name", "STRING", mode="NULLABLE", description="Customer name"),
    SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="UTC creation time from Stripe"),
    SchemaField("default_currency", "STRING", mode="NULLABLE", description="Default currency"),
    SchemaField("livemode", "BOOLEAN", mode="REQUIRED", description="True if live mode, False if test mode"),
    SchemaField("test_clock_id", "STRING", mode="NULLABLE", description="Test clock ID (Sprint 1 seeding)"),
    SchemaField("metadata", "STRING", mode="NULLABLE", description="JSON-encoded metadata"),
    SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="When row was synced from Stripe"),
]

# Schema fields for subscriptions table (C-39)
SUBSCRIPTIONS_SCHEMA: List[SchemaField] = [
    SchemaField("stripe_subscription_id", "STRING", mode="REQUIRED", description="Stripe Subscription ID (PK)"),
    SchemaField("stripe_customer_id", "STRING", mode="REQUIRED", description="Stripe Customer ID (FK)"),
    SchemaField("status", "STRING", mode="REQUIRED", description="Subscription status (active, past_due, etc.)"),
    SchemaField("current_price_id", "STRING", mode="NULLABLE", description="Current Price ID"),
    SchemaField("unit_amount_cents", "INTEGER", mode="NULLABLE", description="Price in cents"),
    SchemaField("currency", "STRING", mode="NULLABLE", description="Currency code (e.g., 'usd')"),
    SchemaField("interval", "STRING", mode="NULLABLE", description="Billing interval (month, year)"),
    SchemaField("interval_count", "INTEGER", mode="NULLABLE", description="Interval multiplier"),
    SchemaField("billing_cycle_anchor", "TIMESTAMP", mode="NULLABLE", description="Billing cycle anchor (for MRR calc)"),
    SchemaField("current_period_start", "TIMESTAMP", mode="NULLABLE", description="Current period start (reference only)"),
    SchemaField("current_period_end", "TIMESTAMP", mode="NULLABLE", description="Current period end (reference only)"),
    SchemaField("start_date", "TIMESTAMP", mode="NULLABLE", description="Subscription start date"),
    SchemaField("canceled_at", "TIMESTAMP", mode="NULLABLE", description="Cancellation timestamp"),
    SchemaField("ended_at", "TIMESTAMP", mode="NULLABLE", description="End date if subscription ended"),
    SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="UTC creation time"),
    SchemaField("livemode", "BOOLEAN", mode="REQUIRED", description="True if live mode"),
    SchemaField("idempotency_key", "STRING", mode="NULLABLE", description="Idempotency key (v0/v1 for tier changes)"),
    SchemaField("metadata", "STRING", mode="NULLABLE", description="JSON-encoded metadata"),
    SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="When row was synced"),
]

# Schema fields for invoices table (C-40)
INVOICES_SCHEMA: List[SchemaField] = [
    SchemaField("stripe_invoice_id", "STRING", mode="REQUIRED", description="Stripe Invoice ID (PK)"),
    SchemaField("stripe_customer_id", "STRING", mode="REQUIRED", description="Stripe Customer ID (FK)"),
    SchemaField("stripe_subscription_id", "STRING", mode="NULLABLE", description="Stripe Subscription ID (FK, nullable)"),
    SchemaField("period_start", "TIMESTAMP", mode="NULLABLE", description="Period start"),
    SchemaField("period_end", "TIMESTAMP", mode="NULLABLE", description="Period end"),
    SchemaField("status", "STRING", mode="NULLABLE", description="Invoice status"),
    SchemaField("total_cents", "INTEGER", mode="NULLABLE", description="Total amount in cents"),
    SchemaField("amount_paid_cents", "INTEGER", mode="NULLABLE", description="Amount paid in cents"),
    SchemaField("amount_due_cents", "INTEGER", mode="NULLABLE", description="Amount due in cents"),
    SchemaField("currency", "STRING", mode="NULLABLE", description="Currency code"),
    SchemaField("paid_at", "TIMESTAMP", mode="NULLABLE", description="Payment timestamp"),
    SchemaField("created_at", "TIMESTAMP", mode="REQUIRED", description="UTC creation time"),
    SchemaField("livemode", "BOOLEAN", mode="REQUIRED", description="True if live mode"),
    SchemaField("metadata", "STRING", mode="NULLABLE", description="JSON-encoded metadata"),
    SchemaField("synced_at", "TIMESTAMP", mode="REQUIRED", description="When row was synced"),
]

# Schema for sync watermarks table (C-72)
WATERMARKS_SCHEMA: List[SchemaField] = [
    SchemaField("sync_key", "STRING", mode="REQUIRED", description="Sync phase key (e.g., 'customers', 'subscriptions')"),
    SchemaField("last_synced_at", "TIMESTAMP", mode="REQUIRED", description="Last successful sync timestamp"),
]

# Mapping of table names to schemas
TABLE_SCHEMAS = {
    "customers": CUSTOMERS_SCHEMA,
    "subscriptions": SUBSCRIPTIONS_SCHEMA,
    "invoices": INVOICES_SCHEMA,
    "_sync_watermarks": WATERMARKS_SCHEMA,
}
