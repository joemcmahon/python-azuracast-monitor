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
Settings come from environment variables. In Docker they are loaded by compose
`env_file` (`.env` for the main station, `stations/<name>.env` for each status
board); the files are never copied into the image. See `.env.example`.

| Variable | Default | Meaning |
|---|---|---|
| `STATION_SERVER` | `spiral.radio` | AzuraCast host to watch |
| `STATION_SHORTCODE` | `radiospiral` | Station shortcode on that server |
| `STATION_NAME` | the shortcode | Display name |
| `AUTODJ_NAME` | `Spud the Ambient Robot` | Name AzuraCast reports for AutoDJ streamers |
| `STATUS_BOARD` | false | `1`/`true`/`yes`/`on`: run as a status board instead of posting now-playing messages |
| `NOW_PLAYING_WEBHOOK` | none | Discord webhook for the main now-playing channel (main container only) |
| `STATUS_BOARD_WEBHOOK` | none | Webhook for a station's status-board channel (status-board containers only; no fallback to the main one) |
| `STATE_DIR` | `.` | Directory for the heartbeat file and the status board's SQLite file |
| `WEBHOOK_TIMEOUT` | `10` | Seconds to wait on a Discord webhook call |
| `SSE_READ_TIMEOUT` | `300` | Seconds of SSE silence before reconnecting |
| `DRY_RUN` | false | Log what would be posted instead of posting |
| `HEARTBEAT_MAX_AGE` | `900` | Healthcheck: maximum heartbeat age in seconds. Keep it above `SSE_READ_TIMEOUT` + the reconnect backoff cap (300) + a margin: 300 + 300 + 300 = 900 |
| `RESTART_AT` | `05:00` | Restarter: daily restart time, `HH:MM` (container clock) |
| `RESTARTER_STATE` | `/tmp/restarter.last` | Restarter: file holding the last day the daily restart was done |
| `DOCKER` | `docker` | Restarter: docker command to call (a test hook) |

`BOT_TOKEN`, `AZ_CLIENT_DEBUG` and `LOG_LEVEL` are as in `.env.example`.

# Running it
Directly: install `requirements.txt`, create `.env` with `NOW_PLAYING_WEBHOOK`,
and run `python azmonitor.py`.

With Docker, keep `.env` on the host next to `docker-compose.yml`, then
`docker compose up -d --build`. That starts the main monitor
(`az-now-playing`) and the `restarter`. The restarter restarts every container
labelled `az-monitor.managed=true` once a day at `RESTART_AT` (Python's memory
use grows in the SSE monitor, so a daily restart is a cheap fix), and restarts
any such container whose healthcheck reports `unhealthy` (no data from
AzuraCast within `HEARTBEAT_MAX_AGE`). If the restarter is created after
today's restart time it records the day as done instead of restarting
everything.

# Multiple stations
Other stations get a status board: one container per station that keeps a
single Discord message up to date (edited in place, reposted if it was
deleted). State lives in a SQLite file under `./state/<name>`.

1. Copy each example and fill it in:
   `cp stations/pulse.env.example stations/pulse.env` (same for `inner`,
   `outer`). The real `stations/*.env` and `state/` are git-ignored.
2. Start them with the `secondary` profile:
   `docker compose --profile secondary up -d --build`
   (or `COMPOSE_PROFILES=secondary`). A plain `docker compose up` starts only
   the main monitor and the restarter.
3. `docker compose down` needs the same profile flag, or the secondary
   containers are left running.

Each status-board service loads only its own `stations/<name>.env`, never the
main `.env`, so it cannot post to the main channel.

The shortcodes, AutoDJ persona names and test-server host in
`stations/*.env.example` are placeholders: confirm them on the test server.

## Test stack
Run tests against a separate stack with its OWN webhooks (different `.env` and
`stations/*.env` pointing at test channels) and its own project name, e.g.
`docker compose -p az-test --profile secondary up -d --build`, from a checkout
whose env files hold only test webhooks, so a test run cannot post to a
production channel. Note the main service has a fixed `container_name`, so it
cannot run twice on one host; use `DRY_RUN=1` or another host for that.

# Migrating the existing production container
The old main container got its webhook only from the `.env` baked into the old
image. That image no longer contains `.env`, so:

1. Keep `.env` on the host next to `docker-compose.yml`; it must hold
   `NOW_PLAYING_WEBHOOK`. Compose loads it through `env_file` before the
   first rebuild.
2. Run `docker compose up -d --build --remove-orphans`. Compose recreates the
   same-named `restarter` service in place; do not stop it by hand.

# Not yet verified
Written without Docker available. Unverified until run on a real Docker host:
compose profiles, the label and health filters in the restarter against a real
daemon, `docker compose config`, and webhook edits (and 404 on a deleted
message) against Discord. The restarter's logic is tested with a fake
`docker` command (`test_restarter.py`).
