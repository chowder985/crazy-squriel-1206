"""Transform Stripe objects into BigQuery rows."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from .errors import TransformError

logger = logging.getLogger(__name__)


def _lookup(obj: Any, key: str, default: Any = None) -> Any:
    """Lookup ``key`` on ``obj`` using bracket access for dict-like Stripe
    objects and attribute access for everything else.

    Stripe SDK objects extend ``dict``, which makes ``obj.items``,
    ``obj.keys``, and other dict-method names shadow the underlying data.
    Bracket access avoids the shadowing for real Stripe objects. Unit-test
    fixtures use ``Mock``/``MagicMock`` (which don't extend dict), so the
    fallback to ``getattr`` keeps existing tests working without changing
    their mock construction.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_timestamp(timestamp_val: Optional[Any]) -> Optional[str]:
    """
    Parse Stripe timestamp to UTC TIMESTAMP string.

    Stripe timestamps are unix epoch integers. Convert to ISO 8601 format.
    On parsing failure, return None (row will be skipped by caller).

    Args:
        timestamp_val: Stripe timestamp (int or None)

    Returns:
        ISO 8601 timestamp string or None
    """
    if timestamp_val is None:
        return None

    try:
        if isinstance(timestamp_val, int):
            dt = datetime.utcfromtimestamp(timestamp_val)
            return dt.isoformat() + "Z"
        else:
            # Already a string, try to parse
            return str(timestamp_val)
    except (ValueError, OSError) as e:
        logger.error(f"Failed to parse timestamp {timestamp_val}: {e}")
        return None


def transform_customers(customers: list) -> Dict[str, list]:
    """
    Transform Stripe customer objects to BigQuery rows (C-38).

    Args:
        customers: List of Stripe Customer objects

    Returns:
        Dict with 'customers' key and list of row dicts
    """
    rows = []
    now_iso = datetime.utcnow().isoformat() + "Z"

    for customer in customers:
        try:
            created_at = _parse_timestamp(customer.created)
            if created_at is None:
                logger.error(f"Customer {customer.id}: malformed timestamp {customer.created}; skipping")
                continue

            row = {
                "stripe_customer_id": customer.id,
                "email": customer.email,
                "name": customer.name,
                "created_at": created_at,
                "default_currency": customer.default_source.get("currency") if customer.default_source else None,
                "livemode": customer.livemode,
                "test_clock_id": customer.metadata.get("test_clock_id") if customer.metadata else None,
                "metadata": json.dumps(customer.metadata) if customer.metadata else None,
                "synced_at": now_iso,
            }
            rows.append(row)
        except Exception as e:
            logger.error(f"Failed to transform customer {getattr(customer, 'id', '?')}: {e}")
            continue

    return {"customers": rows}


def transform_subscriptions(subscriptions: list) -> Dict[str, list]:
    """
    Transform Stripe subscription objects to BigQuery rows (C-39, C-42, C-46).

    Denormalizes current price details from items[0].price.
    Skips subscriptions with unknown status (not in expected enum).

    Args:
        subscriptions: List of Stripe Subscription objects

    Returns:
        Dict with 'subscriptions' key and list of row dicts
    """
    rows = []
    now_iso = datetime.utcnow().isoformat() + "Z"
    VALID_STATUSES = {"active", "past_due", "canceled", "trialing", "incomplete"}

    for subscription in subscriptions:
        try:
            # Validate status (C-49)
            if subscription.status not in VALID_STATUSES:
                logger.warning(f"Skipping subscription {subscription.id} with unexpected status: {subscription.status}")
                continue

            created_at = _parse_timestamp(subscription.created)
            if created_at is None:
                logger.error(f"Subscription {subscription.id}: malformed created timestamp; skipping")
                continue

            # Extract price from items[0] (C-42, C-46)
            price = None
            unit_amount_cents = None
            currency = None
            interval = None
            interval_count = None

            # Iter-4: ``subscription.items`` returns the inherited dict.items
            # method (Stripe Subscription extends dict). Use ``_lookup`` which
            # prefers bracket access on dict-like Stripe objects and falls
            # back to attribute access for unit-test Mock fixtures (which
            # don't extend dict).
            sub_items = _lookup(subscription, "items")
            sub_items_data = _lookup(sub_items, "data") if sub_items is not None else None
            if sub_items_data and len(sub_items_data) > 0:
                first_item = sub_items_data[0]
                price_obj = _lookup(first_item, "price")
                if price_obj:
                    price = _lookup(price_obj, "id")
                    unit_amount_cents = _lookup(price_obj, "unit_amount")
                    currency = _lookup(price_obj, "currency")
                    recurring = _lookup(price_obj, "recurring")
                    if recurring:
                        interval = _lookup(recurring, "interval")
                        interval_count = _lookup(recurring, "interval_count")

            billing_cycle_anchor = _parse_timestamp(subscription.billing_cycle_anchor)
            current_period_start = _parse_timestamp(subscription.current_period_start)
            current_period_end = _parse_timestamp(subscription.current_period_end)
            start_date = _parse_timestamp(subscription.start_date)
            canceled_at = _parse_timestamp(subscription.canceled_at)
            ended_at = _parse_timestamp(subscription.ended_at)

            row = {
                "stripe_subscription_id": subscription.id,
                "stripe_customer_id": subscription.customer,
                "status": subscription.status,
                "current_price_id": price,
                "unit_amount_cents": unit_amount_cents,
                "currency": currency,
                "interval": interval,
                "interval_count": interval_count,
                "billing_cycle_anchor": billing_cycle_anchor,
                "current_period_start": current_period_start,
                "current_period_end": current_period_end,
                "start_date": start_date,
                "canceled_at": canceled_at,
                "ended_at": ended_at,
                "created_at": created_at,
                "livemode": subscription.livemode,
                "idempotency_key": subscription.metadata.get("idempotency_key") if subscription.metadata else None,
                "metadata": json.dumps(subscription.metadata) if subscription.metadata else None,
                "synced_at": now_iso,
            }
            rows.append(row)
        except Exception as e:
            logger.error(f"Failed to transform subscription {getattr(subscription, 'id', '?')}: {e}")
            continue

    return {"subscriptions": rows}


def transform_invoices(invoices: list) -> Dict[str, list]:
    """
    Transform Stripe invoice objects to BigQuery rows (C-40, C-43).

    Collapses line items into total_cents / amount_paid_cents / amount_due_cents.

    Args:
        invoices: List of Stripe Invoice objects

    Returns:
        Dict with 'invoices' key and list of row dicts
    """
    rows = []
    now_iso = datetime.utcnow().isoformat() + "Z"

    for invoice in invoices:
        try:
            created_at = _parse_timestamp(invoice.created)
            if created_at is None:
                logger.error(f"Invoice {invoice.id}: malformed created timestamp; skipping")
                continue

            period_start = _parse_timestamp(invoice.period_start)
            period_end = _parse_timestamp(invoice.period_end)
            paid_at = _parse_timestamp(invoice.status_transitions.get("paid_at") if invoice.status_transitions else None)

            row = {
                "stripe_invoice_id": invoice.id,
                "stripe_customer_id": invoice.customer,
                "stripe_subscription_id": invoice.subscription,
                "period_start": period_start,
                "period_end": period_end,
                "status": invoice.status,
                "total_cents": invoice.total,
                "amount_paid_cents": invoice.amount_paid,
                "amount_due_cents": invoice.amount_due,
                "currency": invoice.currency,
                "paid_at": paid_at,
                "created_at": created_at,
                "livemode": invoice.livemode,
                "metadata": json.dumps(invoice.metadata) if invoice.metadata else None,
                "synced_at": now_iso,
            }
            rows.append(row)
        except Exception as e:
            logger.error(f"Failed to transform invoice {getattr(invoice, 'id', '?')}: {e}")
            continue

    return {"invoices": rows}
