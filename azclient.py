import json
import pprint
import sseclient
import urllib.parse

from datetime import datetime
from collections import namedtuple
from dataclasses import dataclass

@dataclass
class NowPlayingResponse:
    """The NowPlayingResponse encapsulates the  usually-desired
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

def with_urllib3(url, headers):
    """Get a streaming response for the given event feed using urllib3."""
    import urllib3
    http = urllib3.PoolManager()
    return http.request('GET', url, preload_content=False, headers=headers)

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

def build_sse_client(server, shortcode):
    """Constructs an SSE client for the given server and shortcode."""
    headers = {'Accept': 'text/event-stream'}
    response = with_urllib3(construct_sse_url(server, shortcode), headers)
    return sseclient.SSEClient(response)

def formatted_result(result):
    """
    formatted _result returns a string version of the
    captured data. Useful for logging or debugging.
    """
    on_album = ""
    if result.album != "":
        on_album = " on \"{result.album}\""
    return f"[{result.start}] \"{result.track}\", by {result.artist}{on_album} {result.elapsed}/{result.duration}\n" + f"DJ: {result.dj} {result.live}\n"

def extract_metadata(np):
    """
    This function takes a record from the SSE client and
    extracts the metadata from it into a NowPlayingResponse.
    """
    livestatus = np['live']
    now_playing = np['now_playing']
    song = now_playing['song']
    streamer = "Spud the Ambient Robot"
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
    return NowPlayingResponse(
                streamer, live, formatted_runtime, formatted_elapsed,
                start_datetime, artist, track, album, artwork_url)


 # Run the client, passing parsed messages to the callback
def run(client, callback):
    """
    Runs the client created by build_sse_client and
    makes a callback to the function of your choice
    each time a new event occurs.

    Example:
        client = build_sse_client("spiral.radio", "radiospiral")
        run(client, lambda result: print(formatted_result(result)))

    The callback receives a NowPlayingResponse object for every event
    returned by the SSE server; you must monitor these events and
    decide which ones to process.
    """
    for event in client.events():
        payload = json.loads(event.data)
        if 'connect' in payload:
            np = payload['connect']['subs']['station:radiospiral']['publications'][0]['data']['np']
            result = extract_metadata(np)
            callback(result)

        if 'channel' in payload:
            np = payload['pub']['data']['np']
            result = extract_metadata(np)
            if os.getenv["AZ_CLIENT_DEBUG"] != "":
                print(formatted_result(result))
            callback(result)
