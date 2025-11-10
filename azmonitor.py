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
from logger_config import setup_logging, get_logger

# Load environment variables
load_dotenv()

# Setup logging
setup_logging()
logger = get_logger(__name__)

NOW_PLAYING_WEBHOOK = os.getenv('NOW_PLAYING_WEBHOOK')

# Configuration
STATION_SERVER = "spiral.radio"
STATION_SHORTCODE = "radiospiral"

def send_webhook(embed_data):
    """Send data to the Discord webhook."""
    try:
        webhook = DiscordWebhook(url=NOW_PLAYING_WEBHOOK)
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
        logger.error(f"Failed to send webhook: {e}", exc_info=True)

class DiscordSender:
    """Stateful sender that tracks last response to avoid duplicates"""

    def __init__(self):
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
        send_webhook(embed_data)

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


def validate_environment():
    """Validate required environment variables are set"""
    required_vars = {
        'NOW_PLAYING_WEBHOOK': NOW_PLAYING_WEBHOOK,
    }

    missing_vars = [name for name, value in required_vars.items() if not value]

    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        logger.error("Please check your .env file")
        sys.exit(1)

    # Validate webhook URL format
    if not NOW_PLAYING_WEBHOOK.startswith('https://discord.com/api/webhooks/'):
        logger.error("NOW_PLAYING_WEBHOOK does not appear to be a valid Discord webhook URL")
        sys.exit(1)

    logger.info("Environment validation passed")


# Main function
if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("Starting Azuracast Discord Monitor")

    # Validate environment
    validate_environment()

    logger.info(f"Connecting to {STATION_SERVER}/{STATION_SHORTCODE}")

    try:
        # Create the sender
        sender = DiscordSender()

        # Use resilient runner with automatic reconnection
        runner = ResilientRunner(
            server=STATION_SERVER,
            shortcode=STATION_SHORTCODE,
            callback=sender.send,
            max_retries=None  # Infinite retries
        )

        exit_code = runner.run(shutdown_check=lambda: shutdown_requested)
        sys.exit(exit_code)

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("Azuracast Discord Monitor stopped")
