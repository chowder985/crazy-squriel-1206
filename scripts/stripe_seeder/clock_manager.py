"""Stripe Test Clock management."""

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

import stripe

from .errors import ClockTimeoutError

logger = logging.getLogger(__name__)

# Constants
POLLING_INTERVAL = 1  # seconds
POLLING_TIMEOUT = 30  # seconds
MAX_ADVANCEMENT_DAYS = 60  # ~2 months


class ClockManager:
    """Manages Stripe Test Clocks for simulating time passage."""

    def __init__(self, api_key: str, dry_run: bool = False):
        """
        Initialize ClockManager.

        Args:
            api_key: Stripe API key
            dry_run: If True, log operations without making API calls
        """
        self.api_key = api_key
        self.dry_run = dry_run
        self.clocks: List[stripe.testhelpers.testclock.TestClock] = []

    def create_clock(self, frozen_time: datetime, name: Optional[str] = None) -> stripe.test_helpers.TestClock:
        """
        Create a new test clock.

        Args:
            frozen_time: Initial frozen time for the clock
            name: Optional name for the clock (for cleanup pattern matching)

        Returns:
            Created TestClock object
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create test clock at {frozen_time.isoformat()}")
            # Return a mock-like object for dry-run
            return type(
                "MockClock",
                (),
                {
                    "id": "clock_dryrun_001",
                    "frozen_time": int(frozen_time.timestamp()),
                    "status": "ready",
                    "name": name,
                },
            )()

        clock = stripe.test_helpers.TestClock.create(
            frozen_time=int(frozen_time.timestamp()),
            name=name or f"mrr-seed-clock-{len(self.clocks):03d}",
            api_key=self.api_key,
        )
        logger.info(f"Created test clock {clock.id} at {frozen_time.isoformat()} with name {clock.name if hasattr(clock, 'name') else 'N/A'}")
        self.clocks.append(clock)
        return clock

    def advance_clock(
        self, clock_id: str, days_forward: int
    ) -> stripe.test_helpers.TestClock:
        """
        Advance a test clock by the specified number of days.

        Args:
            clock_id: ID of the test clock to advance
            days_forward: Number of days to advance (max 60 for ~2 months)

        Returns:
            Updated TestClock object

        Raises:
            ValueError: If advancement exceeds max allowed
        """
        if days_forward > MAX_ADVANCEMENT_DAYS:
            raise ValueError(
                f"Advancement of {days_forward} days exceeds maximum {MAX_ADVANCEMENT_DAYS} days"
            )

        if self.dry_run:
            logger.info(f"[DRY RUN] Would advance clock {clock_id} by {days_forward} days")
            return type(
                "MockClock",
                (),
                {"id": clock_id, "status": "ready"},
            )()

        clock = stripe.test_helpers.TestClock.advance(
            clock_id,
            frozen_time=int((datetime.now() + timedelta(days=days_forward)).timestamp()),
            api_key=self.api_key,
        )
        logger.info(f"Advanced clock {clock_id} by {days_forward} days")
        return clock

    def poll_clock_ready(self, clock_id: str) -> bool:
        """
        Poll a test clock until it reaches 'ready' status or timeout.

        Args:
            clock_id: ID of the test clock

        Returns:
            True if clock reached 'ready' status

        Raises:
            ClockTimeoutError: If clock does not reach ready within timeout
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would poll clock {clock_id} for ready status")
            return True

        start_time = time.time()
        while time.time() - start_time < POLLING_TIMEOUT:
            try:
                clock = stripe.test_helpers.TestClock.retrieve(
                    clock_id, api_key=self.api_key
                )
                if clock.status == "ready":
                    logger.info(f"Clock {clock_id} is ready")
                    return True
            except stripe.error.StripeError as e:
                logger.warning(f"Error polling clock {clock_id}: {e}")

            time.sleep(POLLING_INTERVAL)

        raise ClockTimeoutError(
            f"Clock {clock_id} did not reach 'ready' status within {POLLING_TIMEOUT} seconds"
        )

    def delete_clock(self, clock_id: str) -> bool:
        """
        Delete a test clock.

        Args:
            clock_id: ID of the test clock

        Returns:
            True if deletion succeeded
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would delete clock {clock_id}")
            return True

        try:
            stripe.test_helpers.TestClock.delete(
                clock_id, api_key=self.api_key
            )
            logger.info(f"Deleted clock {clock_id}")
            return True
        except stripe.error.StripeError as e:
            logger.error(f"Error deleting clock {clock_id}: {e}")
            return False

    def list_clocks_by_pattern(self, name_pattern: str) -> List[str]:
        """
        List all test clocks matching a name pattern.

        Args:
            name_pattern: Name pattern to match (e.g., 'mrr-seed-clock-')

        Returns:
            List of matching clock IDs
        """
        if self.dry_run:
            logger.info(f"[DRY RUN] Would list clocks matching pattern '{name_pattern}'")
            return []

        try:
            clocks = stripe.test_helpers.TestClock.list(
                api_key=self.api_key, limit=100
            )
            matching = []
            for clock in clocks:
                # Check if clock has metadata with the pattern or name contains pattern
                if hasattr(clock, "name") and clock.name and name_pattern in clock.name:
                    matching.append(clock.id)
            return matching
        except stripe.error.StripeError as e:
            logger.error(f"Error listing clocks: {e}")
            return []
