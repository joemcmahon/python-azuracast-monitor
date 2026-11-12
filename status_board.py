"""Status board: one Discord message per station, edited in place on each track change."""
import logging
import os
import sqlite3
import time
from contextlib import closing
from typing import NamedTuple, Optional, Tuple

from discord_webhook import DiscordWebhook, DiscordEmbed
from tzlocal import get_localzone

from azclient import NowPlayingResponse

logger = logging.getLogger(__name__)


class StoredStatus(NamedTuple):
    message_id: str
    last_value: str
    updated_at: float


class StatusBoardStore:
    """SQLite-backed map of station -> (message id, last value). One connection per operation."""

    def __init__(self, path: str):
        self.path = path
        parent = os.path.dirname(os.path.abspath(path))
        os.makedirs(parent, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            with conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS status ("
                    "station TEXT PRIMARY KEY, message_id TEXT, "
                    "last_value TEXT, updated_at REAL)"
                )

    def get(self, station: str) -> Optional[StoredStatus]:
        with closing(sqlite3.connect(self.path)) as conn:
            row = conn.execute(
                "SELECT message_id, last_value, updated_at FROM status WHERE station = ?",
                (station,),
            ).fetchone()
        return StoredStatus(*row) if row else None

    def save(self, station: str, message_id: str, last_value: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO status (station, message_id, last_value, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(station) DO UPDATE SET message_id = excluded.message_id, "
                    "last_value = excluded.last_value, updated_at = excluded.updated_at",
                    (station, message_id, last_value, time.time()),
                )


def status_value(response: NowPlayingResponse) -> str:
    """The fields NowPlayingResponse.__eq__ compares; elapsed time is deliberately excluded."""
    return f"{response.dj}|{response.artist}|{response.track}|{response.album}"


def format_status(response: NowPlayingResponse, station_name: str) -> dict:
    local_tz = get_localzone()
    start = response.start.replace(tzinfo=local_tz)
    album_part = ""
    if response.album != "":
        album_part = f"from _{response.album}_ by "
    return {
        "title": f"{station_name} — {response.track}",
        "description": f"{album_part}{response.artist} ({response.duration})",
        "timestamp": start,
        "thumbnail_url": response.artURL,
    }


class StatusBoardSender:
    """Posts one message per station, then edits it on each track change."""

    def __init__(self, webhook_url, station_name, store, timeout=10.0,
                 webhook_factory=DiscordWebhook):
        self._url = webhook_url
        self.station_name = station_name
        self.store = store
        self.timeout = timeout
        self._factory = webhook_factory
        # Last (message_id, last_value) we successfully posted/edited. Used when
        # the store has no row or fails, so a broken disk cannot cause a flood
        # of new messages.
        self._memory: Optional[Tuple[str, str]] = None

    def _load(self) -> Optional[Tuple[str, str]]:
        try:
            stored = self.store.get(self.station_name)
        except Exception as e:
            logger.error("Status board store read failed for %s: %s",
                         self.station_name, type(e).__name__)
            return self._memory
        if stored is not None and stored.message_id:
            return (stored.message_id, stored.last_value)
        return self._memory

    def _remember(self, message_id: str, value: str) -> None:
        self._memory = (message_id, value)
        try:
            self.store.save(self.station_name, message_id, value)
        except Exception as e:
            logger.error("Status board store write failed for %s: %s",
                         self.station_name, type(e).__name__)

    def _build(self, response, message_id=None):
        kwargs = {"url": self._url, "timeout": self.timeout}
        if message_id is not None:
            kwargs["id"] = message_id
        webhook = self._factory(**kwargs)
        data = format_status(response, self.station_name)
        embed = DiscordEmbed(title=data["title"], description=data["description"])
        if data["timestamp"] != 0:
            embed.set_timestamp(data["timestamp"])
        embed.set_thumbnail(url=data["thumbnail_url"])
        webhook.add_embed(embed)
        return webhook

    def _post(self, response, value) -> None:
        webhook = self._build(response)
        result = webhook.execute()
        if result.status_code in (200, 204) and isinstance(webhook.id, str):
            self._remember(webhook.id, value)
            logger.info("Status board posted for %s", self.station_name)
        else:
            logger.error("Status board post failed for %s: HTTP %s",
                         self.station_name, result.status_code)

    def send(self, response: NowPlayingResponse) -> None:
        # Exception messages are never logged: requests errors can embed the URL.
        try:
            value = status_value(response)
            known = self._load()
            if known is not None and known[1] == value:
                logger.debug("Status board unchanged for %s", self.station_name)
                return
            if known is None:
                self._post(response, value)
                return
            message_id = known[0]
            result = self._build(response, message_id).edit()
            if result.status_code in (200, 204):
                self._remember(message_id, value)
                logger.info("Status board edited for %s", self.station_name)
            elif result.status_code == 404:
                logger.warning("Status board message for %s was deleted; reposting",
                               self.station_name)
                self._post(response, value)
            else:
                logger.error("Status board edit failed for %s: HTTP %s",
                             self.station_name, result.status_code)
        except Exception as e:
            logger.error("Status board update failed for %s: %s",
                         self.station_name, type(e).__name__)
