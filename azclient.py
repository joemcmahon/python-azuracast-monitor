import json
import pprint
import sseclient
import urllib.parse
import os
import time
import logging
from typing import Callable, Optional

from datetime import datetime
from collections import namedtuple
from dataclasses import dataclass

from settings import DEFAULT_AUTODJ_NAME

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class NowPlayingResponse:
    """The NowPlayingResponse encapsulates the usually-desired
       data from the SSE response. The SSE now-playing data
       contains much more than the data captured here; if you
       want things like the play history, etc., they are
       available; expanding this object and extract_metadata
       will be necessary to capture them.
    """
    dj: str
    live: bool
    duration: str
    elapsed: str
    start: datetime
    artist: str
    track: str
    album: str
    artURL: str

    def __eq__(self, other) -> bool:
        if not isinstance(other, NowPlayingResponse):
            return False
        if other is None:
            return False
        return (self.dj == other.dj and
               self.artist == other.artist and
               self.track == other.track and
               self.album == other.album)

def convert(seconds):
    """Convert a duration in seconds to HH::M::SS"""
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{hours:02}:{minutes:02}:{seconds:02}"

class SSEConnectionError(Exception):
    """Raised when the SSE endpoint answers with a non-200 HTTP status."""


def with_urllib3(url, headers, timeout=30, read_timeout=300):
    """Get a streaming response for the given event feed using urllib3.

    Args:
        url: The SSE endpoint URL
        headers: HTTP headers for the request
        timeout: Connection timeout in seconds (default: 30)
        read_timeout: Read timeout in seconds (default: 300)

    Returns:
        urllib3 HTTPResponse object

    Raises:
        SSEConnectionError: On any HTTP status other than 200
        urllib3.exceptions.HTTPError: On HTTP errors
        urllib3.exceptions.TimeoutError: On timeout
    """
    import urllib3
    http = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=timeout, read=read_timeout),
        retries=False  # We'll handle retries at a higher level
    )
    response = http.request('GET', url, preload_content=False, headers=headers)
    if response.status != 200:
        status = response.status
        try:
            response.release_conn()
        except Exception:
            pass
        raise SSEConnectionError(f"SSE endpoint returned HTTP {status}")
    return response

def construct_sse_url(server, shortcode):
    """Builds out an Azuracast SSE URL.

       - server: the domain name of your Azuracast server
       - shortcode: the station's "shortcode" name, found in the station
                    profile on your Azuracast server
    """
    subs = {
        "subs": {
            f"station:{shortcode}": {"recover": True}
        }
     }
    json_subs = json.dumps(subs, separators=(',', ':'))
    json_subs = json_subs.replace("True", "true").replace("False", "false")
    encoded_query = urllib.parse.quote(json_subs)

    baseURL = f"https://{server}"
    return f"{baseURL}/api/live/nowplaying/sse?cf_connect={encoded_query}"

def build_sse_client(server, shortcode, read_timeout=300):
    """Constructs an SSE client for the given server and shortcode."""
    headers = {'Accept': 'text/event-stream'}
    response = with_urllib3(construct_sse_url(server, shortcode), headers,
                           read_timeout=read_timeout)
    return sseclient.SSEClient(response)

def formatted_result(result):
    """
    formatted _result returns a string version of the
    captured data. Useful for logging or debugging.
    """
    on_album = ""
    if result.album != "":
        on_album = f" on \"{result.album}\""
    return f"[{result.start}] \"{result.track}\", by {result.artist}{on_album} {result.elapsed}/{result.duration}\n" + f"DJ: {result.dj} {result.live}\n"

def extract_metadata(np, autodj_name=DEFAULT_AUTODJ_NAME):
    """
    This function takes a record from the SSE client and
    extracts the metadata from it into a NowPlayingResponse.
    """
    livestatus = np['live']

    now_playing = np['now_playing']
    song = now_playing['song']
    streamer = autodj_name
    live = ""
    if livestatus['is_live']:
        streamer = livestatus['streamer_name']
        live = '[LIVE]'
    duration_secs = now_playing['duration']
    elapsed = now_playing['elapsed']
    started_datestamp = now_playing['played_at']
    artist = song['artist']
    track = song['title']
    album = song['album']
    artwork_url = song['art']
    start_datetime = datetime.fromtimestamp(started_datestamp)
    formatted_runtime = convert(duration_secs)
    formatted_elapsed = convert(elapsed)
    # Work around streamer quirks
    if streamer == "Cypress Rosewood":
        # Tony's metadata has the track name in 'artist'
        # and the artist name in 'track'; 'album' is unset.
        save = artist
        artist = track
        track = save
    else:
        if album == "":
            parts = track.split(' - ')
            if len(parts) == 2:
                track = parts[0]
                album = parts[1]
            if len(parts) > 2:
                album = parts[-1]
                track = ' - '.join(parts[:-1])

    return NowPlayingResponse(
                streamer, live, formatted_runtime, formatted_elapsed,
                start_datetime, artist, track, album, artwork_url)


def fallback_metadata(np, autodj_name=DEFAULT_AUTODJ_NAME):
    """Build a minimal NowPlayingResponse from the raw song title/artist.

    Used when extract_metadata fails. Returns None when np is not a dict or
    has neither a title nor an artist.
    """
    if not isinstance(np, dict):
        return None
    now_playing = np.get('now_playing')
    if not isinstance(now_playing, dict):
        return None
    song = now_playing.get('song')
    if not isinstance(song, dict):
        return None
    title = song.get('title') or ""
    artist = song.get('artist') or ""
    if not title and not artist:
        return None
    return NowPlayingResponse(
        autodj_name, "", "00:00:00", "00:00:00", datetime.now(),
        artist, title, song.get('album') or "", song.get('art') or "")


def _np_from_payload(payload, station_key):
    """Return (np, is_channel) for an SSE payload, or (None, False) to skip."""
    if not isinstance(payload, dict):
        return None, False
    if 'connect' in payload:
        try:
            return (payload['connect']['subs'][station_key]['publications']
                    [0]['data']['np'], False)
        except (KeyError, IndexError, TypeError):
            return None, False
    if 'channel' in payload:
        try:
            return payload['pub']['data']['np'], True
        except (KeyError, TypeError):
            return None, False
    return None, False


def _has_subscription(payload, station_key):
    """True if a connect payload's subs include station_key."""
    try:
        return station_key in payload['connect']['subs']
    except (KeyError, TypeError):
        return False


def run(client, callback, shortcode, autodj_name=DEFAULT_AUTODJ_NAME,
        on_event=None):
    """
    Runs the client created by build_sse_client and
    makes a callback to the function of your choice
    each time a new event occurs.

    Args:
        client: SSE client created by build_sse_client
        callback: Function to call with each NowPlayingResponse
        shortcode: Station shortcode (must match the one used in build_sse_client)
        autodj_name: Name reported as the DJ when no live streamer is on
        on_event: Optional no-argument function called first for every received
            event, before parsing. Exceptions it raises are logged and ignored.

    Example:
        client = build_sse_client("spiral.radio", "radiospiral")
        run(client, lambda result: print(formatted_result(result)), "radiospiral")

    The callback receives a NowPlayingResponse object for every event
    returned by the SSE server; you must monitor these events and
    decide which ones to process. A malformed event is logged and skipped
    (or replaced by a raw-field fallback) so one bad event cannot end the
    loop; exceptions raised by the callback still propagate.
    """
    station_key = f"station:{shortcode}"
    warned_missing_subscription = False
    for event in client.events():
        if on_event is not None:
            try:
                on_event()
            except Exception:
                logger.exception("on_event hook failed; ignoring")
        try:
            payload = json.loads(event.data)
        except (ValueError, TypeError):
            logger.debug("Skipping SSE event with invalid JSON")
            continue
        if (not warned_missing_subscription and isinstance(payload, dict)
                and 'connect' in payload
                and not _has_subscription(payload, station_key)):
            warned_missing_subscription = True
            logger.warning("connect payload has no subscription for %s; "
                           "check STATION_SHORTCODE", station_key)
        np, is_channel = _np_from_payload(payload, station_key)
        if np is None:
            logger.debug("Skipping SSE event without usable now-playing data")
            continue
        try:
            result = extract_metadata(np, autodj_name)
        except Exception:
            logger.exception("extract_metadata failed; trying fallback")
            result = fallback_metadata(np, autodj_name)
            if result is None:
                logger.debug("No fallback metadata available; skipping event")
                continue
        if is_channel and os.getenv("AZ_CLIENT_DEBUG") != "":
            print(formatted_result(result))
        callback(result)
