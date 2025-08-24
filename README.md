# python-azuracast-monitor
An SSE-driven Azuracast metadata monitor

# Why this app
Azuracast's Icecast server doesn't seem to provide the stream metadata we were
used to having with our old broadcast software; it definitely does not when
accessed via https. Fortunately Azuracast provides a number of high-frequency
metadata update APIs, including an SSE (server-sent events) one.

This allowed me to write an SSE client to extract data from the extremely
detailed JSON provided by the Azuracast SSE API and then call a callback for
each event received.

The associated monitor program takes these events, checks to see if the
metadata has changed, and sends a message to our discord with nicely-formatted
messages, including the album cover.

The monitor app uses webhooks, as they are very easy to use, but there's no
reason that you couldn't write a channel-based one.

# Configuration
Everything is configured via a `.env` file. The pertinent variables are

 - `BOT_TOKEN`: a Discord bot token, created during bot setup
 - `NOW_PLAYING_WEBHOOK`: the Discord wekbook needed to post to your desired channel
 - `AZ_CLIENT_DEBUG`: Set this to any non-null value to enable logging of the extracted metadata as it arrives.

# Running it
If you want to run the monitor directly, then you should install the reqired
modules via `requirements.txt`, set up your Discord bot, add the bot token and
webhook URL to `.env`, and then run `python azmonitor.py` to start the monitor.

If you prefer Docker, then a `docker build .` or a `docker-compose up` will work.
The `docker-compose` file restarts the monitor once every 24 hours, as Python's
memory management seems to leak in the SSE monitor, eventually causing it to
stop responding. A once-a-day restart is a cheap and simple way to fix this.
