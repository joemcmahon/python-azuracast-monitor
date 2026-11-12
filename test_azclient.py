"""
Test suite for azclient.py

Run with: python -m pytest test_azclient.py -v
or: python test_azclient.py
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import json

from azclient import (
    NowPlayingResponse,
    convert,
    construct_sse_url,
    extract_metadata,
    fallback_metadata,
    formatted_result,
    run,
)


class TestNowPlayingResponse(unittest.TestCase):
    """Test NowPlayingResponse dataclass"""

    def test_equality_same_metadata(self):
        """Test that two responses with same metadata are equal"""
        resp1 = NowPlayingResponse(
            dj="DJ Test",
            live="[LIVE]",
            duration="00:03:45",
            elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist Name",
            track="Track Title",
            album="Album Name",
            artURL="http://example.com/art.jpg"
        )
        resp2 = NowPlayingResponse(
            dj="DJ Test",
            live="[LIVE]",
            duration="00:03:45",
            elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist Name",
            track="Track Title",
            album="Album Name",
            artURL="http://example.com/art.jpg"
        )
        self.assertEqual(resp1, resp2)

    def test_equality_different_metadata(self):
        """Test that responses with different metadata are not equal"""
        resp1 = NowPlayingResponse(
            dj="DJ Test", live="", duration="00:03:45", elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist 1", track="Track 1", album="Album 1", artURL=""
        )
        resp2 = NowPlayingResponse(
            dj="DJ Test", live="", duration="00:03:45", elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist 2", track="Track 1", album="Album 1", artURL=""
        )
        self.assertNotEqual(resp1, resp2)

    def test_equality_ignores_timing_fields(self):
        """Test that equality ignores duration, elapsed, start, live, artURL"""
        resp1 = NowPlayingResponse(
            dj="DJ Test", live="", duration="00:03:45", elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist", track="Track", album="Album", artURL="url1"
        )
        resp2 = NowPlayingResponse(
            dj="DJ Test", live="[LIVE]", duration="00:05:00", elapsed="00:02:30",
            start=datetime(2025, 1, 1, 13, 0, 0),
            artist="Artist", track="Track", album="Album", artURL="url2"
        )
        self.assertEqual(resp1, resp2)


class TestConvert(unittest.TestCase):
    """Test time conversion function"""

    def test_convert_zero_seconds(self):
        self.assertEqual(convert(0), "00:00:00")

    def test_convert_seconds_only(self):
        self.assertEqual(convert(45), "00:00:45")

    def test_convert_minutes_and_seconds(self):
        self.assertEqual(convert(125), "00:02:05")

    def test_convert_hours_minutes_seconds(self):
        self.assertEqual(convert(3665), "01:01:05")

    def test_convert_large_value(self):
        self.assertEqual(convert(7265), "02:01:05")


class TestConstructSSEUrl(unittest.TestCase):
    """Test SSE URL construction"""

    def test_construct_sse_url(self):
        """Test that SSE URL is correctly formatted"""
        url = construct_sse_url("spiral.radio", "radiospiral")
        self.assertIn("https://spiral.radio", url)
        self.assertIn("/api/live/nowplaying/sse", url)
        self.assertIn("cf_connect=", url)
        self.assertIn("radiospiral", url)

    def test_construct_sse_url_different_station(self):
        """Test with different server and shortcode"""
        url = construct_sse_url("test.server.com", "teststation")
        self.assertIn("https://test.server.com", url)
        self.assertIn("teststation", url)


class TestExtractMetadata(unittest.TestCase):
    """Test metadata extraction from SSE events"""

    def setUp(self):
        """Create sample SSE data"""
        self.sample_data = {
            "live": {
                "is_live": False,
                "streamer_name": ""
            },
            "now_playing": {
                "duration": 225,
                "elapsed": 80,
                "played_at": 1704110400,
                "song": {
                    "artist": "Test Artist",
                    "title": "Test Track",
                    "album": "Test Album",
                    "art": "https://example.com/art.jpg"
                }
            }
        }

    def test_extract_metadata_basic(self):
        """Test basic metadata extraction"""
        result = extract_metadata(self.sample_data)
        self.assertIsInstance(result, NowPlayingResponse)
        self.assertEqual(result.artist, "Test Artist")
        self.assertEqual(result.track, "Test Track")
        self.assertEqual(result.album, "Test Album")
        self.assertEqual(result.artURL, "https://example.com/art.jpg")

    def test_extract_metadata_live_stream(self):
        """Test extraction when stream is live"""
        self.sample_data["live"]["is_live"] = True
        self.sample_data["live"]["streamer_name"] = "Live DJ"
        result = extract_metadata(self.sample_data)
        self.assertEqual(result.dj, "Live DJ")
        self.assertEqual(result.live, "[LIVE]")

    def test_extract_metadata_cypress_rosewood_quirk(self):
        """Test the Cypress Rosewood metadata swap"""
        self.sample_data["live"]["is_live"] = True
        self.sample_data["live"]["streamer_name"] = "Cypress Rosewood"
        self.sample_data["now_playing"]["song"]["artist"] = "Track Name"
        self.sample_data["now_playing"]["song"]["title"] = "Artist Name"
        self.sample_data["now_playing"]["song"]["album"] = ""

        result = extract_metadata(self.sample_data)
        self.assertEqual(result.artist, "Artist Name")
        self.assertEqual(result.track, "Track Name")

    def test_extract_metadata_track_with_dash_separator(self):
        """Test parsing track - album from title"""
        self.sample_data["now_playing"]["song"]["title"] = "Track Name - Album Name"
        self.sample_data["now_playing"]["song"]["album"] = ""

        result = extract_metadata(self.sample_data)
        self.assertEqual(result.track, "Track Name")
        self.assertEqual(result.album, "Album Name")

    def test_extract_metadata_empty_album(self):
        """Test handling of empty album field"""
        self.sample_data["now_playing"]["song"]["album"] = ""
        result = extract_metadata(self.sample_data)
        self.assertEqual(result.album, "")


class TestFormattedResult(unittest.TestCase):
    """Test formatted result output"""

    def test_formatted_result_with_album(self):
        """Test formatting with album information"""
        resp = NowPlayingResponse(
            dj="Test DJ", live="", duration="00:03:45", elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist", track="Track", album="Album", artURL=""
        )
        result = formatted_result(resp)
        self.assertIn("Track", result)
        self.assertIn("Artist", result)
        self.assertIn("Album", result)

    def test_formatted_result_without_album(self):
        """Test formatting without album information"""
        resp = NowPlayingResponse(
            dj="Test DJ", live="", duration="00:03:45", elapsed="00:01:20",
            start=datetime(2025, 1, 1, 12, 0, 0),
            artist="Artist", track="Track", album="", artURL=""
        )
        result = formatted_result(resp)
        self.assertIn("Track", result)
        self.assertIn("Artist", result)
        self.assertNotIn('on ""', result)


class TestTitleSplitAndAutoDJ(unittest.TestCase):
    def setUp(self):
        self.np = {
            "live": {"is_live": False, "streamer_name": ""},
            "now_playing": {
                "duration": 225, "elapsed": 80, "played_at": 1704110400,
                "song": {"artist": "A", "title": "Track", "album": "",
                         "art": ""},
            },
        }

    def test_three_part_title_with_empty_album(self):
        self.np["now_playing"]["song"]["title"] = "Artist - Track - Remix"
        result = extract_metadata(self.np)
        self.assertEqual(result.track, "Artist - Track")
        self.assertEqual(result.album, "Remix")

    def test_two_part_title_unchanged(self):
        self.np["now_playing"]["song"]["title"] = "Track - Album"
        result = extract_metadata(self.np)
        self.assertEqual(result.track, "Track")
        self.assertEqual(result.album, "Album")

    def test_autodj_name_is_configurable(self):
        self.assertEqual(extract_metadata(self.np).dj, "Spud the Ambient Robot")
        self.assertEqual(
            extract_metadata(self.np, autodj_name="Robot X").dj, "Robot X")


class TestFallbackMetadata(unittest.TestCase):
    def test_fallback_metadata_uses_raw_fields(self):
        np = {"now_playing": {"song": {"title": "T - X", "artist": "Art"}}}
        r = fallback_metadata(np, autodj_name="Bot")
        self.assertEqual(r.track, "T - X")
        self.assertEqual(r.artist, "Art")
        self.assertEqual(r.album, "")
        self.assertEqual(r.artURL, "")
        self.assertEqual(r.duration, "00:00:00")
        self.assertEqual(r.dj, "Bot")
        self.assertIsInstance(r.start, datetime)

    def test_fallback_metadata_none_without_title_or_artist(self):
        self.assertIsNone(fallback_metadata({"now_playing": {"song": {}}}))
        self.assertIsNone(fallback_metadata({}))
        self.assertIsNone(fallback_metadata("nope"))
        self.assertIsNone(fallback_metadata(None))


class _Ev:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self, datas):
        self._datas = datas

    def events(self):
        return (_Ev(d) for d in self._datas)


class TestRunResilience(unittest.TestCase):
    def test_run_survives_bad_events(self):
        good_np = {
            "live": {"is_live": False, "streamer_name": ""},
            "now_playing": {
                "duration": 10, "elapsed": 1, "played_at": 1704110400,
                "song": {"artist": "GA", "title": "GT", "album": "GAl",
                         "art": ""},
            },
        }
        bad_np = {"now_playing": {"song": {"title": "RawT", "artist": "RawA"}}}
        datas = [
            "not json",
            json.dumps({}),
            json.dumps({"connect": {}}),
            json.dumps({"channel": "station:x",
                        "pub": {"data": {"np": bad_np}}}),
            json.dumps({"channel": "station:x",
                        "pub": {"data": {"np": good_np}}}),
        ]
        got = []
        with patch.dict("os.environ", {"AZ_CLIENT_DEBUG": ""}):
            with self.assertLogs("azclient", level="DEBUG"):
                run(_FakeClient(datas), got.append, "x")
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0].track, "RawT")
        self.assertEqual(got[0].artist, "RawA")
        self.assertEqual(got[1].track, "GT")

    def test_callback_exceptions_propagate(self):
        np = {"live": {"is_live": False, "streamer_name": ""},
              "now_playing": {"duration": 1, "elapsed": 0, "played_at": 1,
                              "song": {"artist": "a", "title": "t",
                                       "album": "b", "art": ""}}}
        data = json.dumps({"channel": "c", "pub": {"data": {"np": np}}})

        def cb(_):
            raise RuntimeError("boom")
        with patch.dict("os.environ", {"AZ_CLIENT_DEBUG": ""}):
            with self.assertRaises(RuntimeError):
                run(_FakeClient([data]), cb, "x")


if __name__ == '__main__':
    unittest.main()
