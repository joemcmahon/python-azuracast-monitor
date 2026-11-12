import json
import os
import sys
import signal
from dotenv import load_dotenv
from discord_webhook import DiscordWebhook, DiscordEmbed
from azclient import build_sse_client, run, NowPlayingResponse
from resilient_runner import ResilientRunner
from datetime import datetime
from tzlocal import get_localzone
from settings import Settings, SettingsError, load_settings
from heartbeat import Heartbeat, heartbeat_path
from status_board import StatusBoardStore, StatusBoardSender
from logger_config import setup_logging, get_logger

# Setup logging
setup_logging()
logger = get_logger(__name__)


def send_webhook(embed_data, webhook_url, timeout=10.0):
    """Send data to the Discord webhook."""
    try:
        webhook = DiscordWebhook(url=webhook_url, timeout=timeout)
        embed = DiscordEmbed(
            title=embed_data['title'],
            description=embed_data['description'],
        )
        if embed_data['timestamp'] != 0:
            embed.set_timestamp(embed_data['timestamp'])
        embed.set_thumbnail(url=embed_data['thumbnail_url'])
        webhook.add_embed(embed)
        response = webhook.execute()
        if response.status_code == 200:
            logger.info(f"Successfully sent: {embed_data['title']}")
        else:
            logger.error(f"Webhook failed: {response.status_code} {response.text}")
    except Exception as e:
        # Type only: requests error text can embed the webhook URL.
        logger.error(f"Failed to send webhook: {type(e).__name__}")


class DiscordSender:
    """Stateful sender that tracks last response to avoid duplicates"""

    def __init__(self, webhook_url, timeout=10.0):
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.startup = True
        self.last_response = None

    def send(self, response: NowPlayingResponse):
        """Send a NowPlayingResponse to Discord webhook if it's changed"""
        if response == self.last_response:
            logger.debug("Skipping duplicate response")
            return

        logger.info(f"New track: {response.track} by {response.artist}")

        # Prepare the embed data
        local_tz = get_localzone()
        start = response.start.replace(tzinfo=local_tz)
        album_part = ""
        if response.album != "":
            album_part = f"from _{response.album}_ by "
        embed_data = {
            "title": f"{response.track}",
            "description": f"{album_part}{response.artist} ({response.duration})",
            "timestamp": start,
            "thumbnail_url": response.artURL,
        }

        # Send to webhook
        send_webhook(embed_data, self.webhook_url, self.timeout)

        self.startup = False
        self.last_response = response

# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    global shutdown_requested
    signal_name = signal.Signals(signum).name
    logger.info(f"Received {signal_name}, initiating graceful shutdown...")
    shutdown_requested = True


class DryRunSender:
    """Logs what would be posted; never touches Discord or the status-board store."""

    def __init__(self, station_name):
        self.station_name = station_name

    def send(self, response: NowPlayingResponse):
        logger.info(f"[dry run] {self.station_name}: would post "
                    f"{response.track} by {response.artist}")


def build_sender(settings: Settings):
    """Choose the sender for the configured mode."""
    if settings.dry_run:
        return DryRunSender(settings.station_name)
    if settings.status_board:
        store = StatusBoardStore(os.path.join(settings.state_dir, "status_board.sqlite3"))
        return StatusBoardSender(settings.webhook_url, settings.station_name,
                                 store, settings.webhook_timeout)
    return DiscordSender(settings.webhook_url, settings.webhook_timeout)


def main(environ=os.environ) -> int:
    load_dotenv()
    try:
        settings = load_settings(environ)
    except SettingsError as e:
        logger.error(f"Invalid configuration: {e}")
        return 1

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting Azuracast Discord Monitor")
    logger.info(f"Connecting to {settings.station_server}/{settings.station_shortcode}")

    try:
        sender = build_sender(settings)
        hb = Heartbeat(heartbeat_path(settings.state_dir))
        runner = ResilientRunner(
            settings.station_server,
            settings.station_shortcode,
            sender.send,
            max_retries=None,  # Infinite retries
            autodj_name=settings.autodj_name,
            read_timeout=settings.sse_read_timeout,
            on_event=hb.touch,
            on_connect=hb.touch,
        )
        return runner.run(shutdown_check=lambda: shutdown_requested)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {type(e).__name__}", exc_info=False)
        return 1
    finally:
        logger.info("Azuracast Discord Monitor stopped")


if __name__ == "__main__":
    sys.exit(main())
