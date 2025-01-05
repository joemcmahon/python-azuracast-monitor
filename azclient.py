import json
import pprint
import sseclient
import urllib.parse
from datetime import datetime
from collections import namedtuple

def convert(seconds):
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


# Note: If you're having trouble connecting to your Azuracast server,
# or you're not seeing any output, uncomment the following two lines,
# run the script, and then use `curl -N` with the printed URL to
# verify that you can connect to the SSE now-playing API on your server.

# print(construct_sse_url("your.server", "your_stations_shortcode"))
# exit

# set up the client
def build_sse_client(server, shortcode):
    headers = {'Accept': 'text/event-stream'}
    response = with_urllib3(construct_sse_url(server, shortcode), headers)
    return sseclient.SSEClient(response)

NowPlayingResponse = namedtuple('NowPlaying', ['dj', 'live', 'duration', 'elapsed',
                                               'start', 'artist', 'track', 'album', 'artURL'])

def formatted_result(result):
    on_album = ""
    if result.album != "":
        on_album = " on \"{result.album}\""
    return f"[{result.start}] \"{result.track}\", by {result.artist}{on_album} {result.elapsed}/{result.duration}\n" + f"DJ: {result.dj} {result.live}\n"

def extract_metadata(np):
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
    formatted_date = datetime.fromtimestamp(started_datestamp)
    formatted_runtime = convert(duration_secs)
    formatted_elapsed = convert(elapsed)
    return NowPlayingResponse(
                streamer, live, formatted_runtime, formatted_elapsed,
                formatted_date, artist, track, album, artwork_url)


 # Run the client, passing parsed messages to the callback
def run(client, callback):
    for event in client.events():
        payload = json.loads(event.data)
        if 'connect' in payload:
            np = payload['connect']['subs']['station:radiospiral']['publications'][0]['data']['np']
            result = extract_metadata(np)
            callback(result)

        if 'channel' in payload:
            np = payload['pub']['data']['np']
            result = extract_metadata(np)
            print(formatted_result(result))
            callback(result)
# Usage:
# client = build_sse_client("spiral.radio", "radiospiral")
# run(client, lambda result: print(formatted_result(result)))
#
# Your callback should use the 'result' object to do whatever it is you need.
