"""
Resilient runner with retry logic and exponential backoff
"""
import time
import logging
from typing import Callable
from azclient import build_sse_client
from settings import DEFAULT_AUTODJ_NAME

logger = logging.getLogger(__name__)


class ResilientRunner:
    """
    Wraps the SSE client with automatic reconnection and exponential backoff
    """

    def __init__(self, server, shortcode, callback, max_retries=None,
                 autodj_name=DEFAULT_AUTODJ_NAME, read_timeout=300.0,
                 on_event=None, on_connect=None):
        """
        Args:
            server: Azuracast server domain
            shortcode: Station shortcode
            callback: Function to call with each NowPlayingResponse
            max_retries: Maximum number of retries (None = infinite)
            autodj_name: Name reported as the DJ when no live streamer is on
            read_timeout: SSE read timeout in seconds
            on_event: Optional no-argument hook called for every SSE event
            on_connect: Optional no-argument hook called after each
                successful (HTTP 200) connection
        """
        self.server = server
        self.shortcode = shortcode
        self.callback = callback
        self.max_retries = max_retries
        self.autodj_name = autodj_name
        self.read_timeout = read_timeout
        self.on_event = on_event
        self.on_connect = on_connect
        self.retry_count = 0

        # Backoff configuration
        self.initial_backoff = 1  # seconds
        self.max_backoff = 300  # 5 minutes
        self.backoff_multiplier = 2
        self.current_backoff = self.initial_backoff

    def _calculate_backoff(self):
        """Calculate the next backoff delay using exponential backoff with jitter"""
        import random

        # Exponential backoff
        backoff = min(self.current_backoff, self.max_backoff)

        # Add jitter (±20%)
        jitter = backoff * 0.2 * (2 * random.random() - 1)
        backoff_with_jitter = backoff + jitter

        # Update for next time
        self.current_backoff = min(self.current_backoff * self.backoff_multiplier, self.max_backoff)

        return max(1, backoff_with_jitter)  # Never less than 1 second

    def _reset_backoff(self):
        """Reset backoff to initial value after successful connection"""
        self.current_backoff = self.initial_backoff
        self.retry_count = 0

    def run(self, shutdown_check=None):
        """
        Run the client with automatic reconnection

        Args:
            shutdown_check: Optional callable that returns True if shutdown is requested

        Returns:
            Exit code (0 for graceful shutdown, 1 for max retries exceeded)
        """
        from azclient import run

        if shutdown_check is None:
            shutdown_check = lambda: False

        while True:
            # Check if shutdown was requested
            if shutdown_check():
                logger.info("Shutdown requested, exiting")
                return 0

            # Check retry limit
            if self.max_retries is not None and self.retry_count >= self.max_retries:
                logger.error(f"Max retries ({self.max_retries}) exceeded, giving up")
                return 1

            delivered = False

            def handle_event():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    # First event on this connection: it is healthy.
                    self._reset_backoff()
                if self.on_event is not None:
                    try:
                        self.on_event()
                    except Exception:
                        logger.exception("on_event hook failed; ignoring")

            try:
                logger.info(f"Connecting to {self.server}/{self.shortcode} (attempt {self.retry_count + 1})")

                # Build the client
                client = build_sse_client(self.server, self.shortcode,
                                          read_timeout=self.read_timeout)
                if self.on_connect is not None:
                    try:
                        self.on_connect()
                    except Exception:
                        logger.exception("on_connect hook failed; ignoring")

                # Run the client
                logger.info("Connection established, listening for events...")
                run(client, self.callback, self.shortcode,
                    autodj_name=self.autodj_name, on_event=handle_event)

                # If we get here, the connection closed normally
                logger.warning("SSE connection closed")
                if delivered:
                    continue

                # Closed without a single event: treat as a failed attempt
                # so we back off instead of reconnecting immediately.
                logger.warning("SSE connection closed without delivering any event")
                self.retry_count += 1

            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt")
                return 0

            except Exception as e:
                logger.error(f"Error during SSE connection: {e}", exc_info=True)
                self.retry_count += 1

            # Failed attempt: back off (shutdown-aware)
            if not shutdown_check():
                backoff = self._calculate_backoff()
                logger.info(f"Reconnecting in {backoff:.1f} seconds...")

                # Wait with periodic shutdown checks
                start_time = time.time()
                while time.time() - start_time < backoff:
                    if shutdown_check():
                        logger.info("Shutdown requested during backoff, exiting")
                        return 0
                    time.sleep(0.5)  # Check every 500ms
