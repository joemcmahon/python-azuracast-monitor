import json
import os
from dotenv import load_dotenv
from discord_webhook import DiscordWebhook, DiscordEmbed
from azclient import build_sse_client, run, NowPlayingResponse
from datetime import datetime
from tzlocal import get_localzone

# Load environment variables
load_dotenv()
NOW_PLAYING_WEBHOOK = os.getenv('NOW_PLAYING_WEBHOOK')

# State variables
startup = True
last_response = None

def send_webhook(embed_data):
    """Send data to the Discord webhook."""
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
    if response.status_code != 200:
        print(f"Failed to send webhook: {response.status_code} {response.text}")

def wrapper(startup, last_response):
    def sender(response: NowPlayingResponse):
        nonlocal startup, last_response
        if response == last_response:
            return

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

        startup = False
        last_response = response

    return sender

# Main function
if __name__ == "__main__":
    # Build the SSE client
    client = build_sse_client("spiral.radio", "radiospiral")

    # Create the sender function and start listening
    send_embed_with_image = wrapper(startup, last_response)
    run(client, send_embed_with_image)
