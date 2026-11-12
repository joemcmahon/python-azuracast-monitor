import logging
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

import requests

from azclient import NowPlayingResponse
from status_board import StatusBoardSender, StatusBoardStore, format_status

URL = "https://discord.com/api/webhooks/123/SECRET-TOKEN-abc"


class FakeResponse:
    def __init__(self, status_code, body_id=None):
        self.status_code = status_code
        self.body_id = body_id
        self.text = ""


class FakeWebhook:
    """Records constructor kwargs and calls; results are scripted per class."""
    instances = []
    post_results = []
    edit_results = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.url = kwargs.get("url")
        self.id = kwargs.get("id")
        self.timeout = kwargs.get("timeout")
        self.embeds = []
        self.calls = []
        FakeWebhook.instances.append(self)

    def add_embed(self, embed):
        self.embeds.append(embed)

    def _next(self, queue):
        result = queue.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def execute(self):
        self.calls.append("execute")
        result = self._next(FakeWebhook.post_results)
        if result.body_id:
            self.id = result.body_id
        return result

    def edit(self):
        self.calls.append("edit")
        return self._next(FakeWebhook.edit_results)


def make_response(track="Song", artist="Artist", album="Album", elapsed="00:00:01",
                  start=None, dj="AutoDJ"):
    return NowPlayingResponse(
        dj=dj, live=False, duration="00:03:00", elapsed=elapsed,
        start=start or datetime(2026, 1, 1, 12, 0, 0), artist=artist,
        track=track, album=album, artURL="http://example.com/art.png")


class StatusBoardTests(unittest.TestCase):
    def setUp(self):
        null = logging.NullHandler()
        logging.getLogger("status_board").addHandler(null)
        self.addCleanup(logging.getLogger("status_board").removeHandler, null)
        FakeWebhook.instances = []
        FakeWebhook.post_results = []
        FakeWebhook.edit_results = []
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = os.path.join(self._tmp.name, "sub", "dir", "board.db")
        self.store = StatusBoardStore(self.db)
        self.sender = self.make_sender(self.store)

    def make_sender(self, store, timeout=10.0):
        return StatusBoardSender(URL, "Station X", store, timeout=timeout,
                                 webhook_factory=FakeWebhook)

    def posts(self):
        return [w for w in FakeWebhook.instances if "execute" in w.calls]

    def edits(self):
        return [w for w in FakeWebhook.instances if "edit" in w.calls]

    def test_first_send_posts_and_saves_id(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        self.sender.send(make_response())
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(len(self.edits()), 0)
        stored = self.store.get("Station X")
        self.assertEqual(stored.message_id, "msg1")
        self.assertEqual(stored.last_value, "AutoDJ|Artist|Song|Album")
        self.assertEqual(len(self.posts()[0].embeds), 1)

    def test_second_send_edits_same_message(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(200)]
        self.sender.send(make_response())
        self.sender.send(make_response(track="Other"))
        self.assertEqual(len(self.posts()), 1)
        edits = self.edits()
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].kwargs["id"], "msg1")
        self.assertEqual(self.store.get("Station X").last_value,
                         "AutoDJ|Artist|Other|Album")

    def test_same_track_is_not_resent(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        self.sender.send(make_response())
        self.sender.send(make_response())
        self.assertEqual(len(FakeWebhook.instances), 1)

    def test_elapsed_only_change_is_not_resent(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        self.sender.send(make_response())
        self.sender.send(make_response(elapsed="00:02:00",
                                       start=datetime(2026, 1, 1, 12, 5, 0)))
        self.assertEqual(len(FakeWebhook.instances), 1)

    def test_recreate_keeps_editing_same_message(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(200)]
        self.sender.send(make_response())
        store2 = StatusBoardStore(self.db)
        sender2 = self.make_sender(store2)
        sender2.send(make_response(track="Next"))
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.edits()[0].kwargs["id"], "msg1")

    def test_deleted_message_reposts(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1"), FakeResponse(200, "msg2")]
        FakeWebhook.edit_results = [FakeResponse(404), FakeResponse(200)]
        self.sender.send(make_response())
        self.sender.send(make_response(track="Two"))
        self.assertEqual(len(self.posts()), 2)
        stored = self.store.get("Station X")
        self.assertEqual(stored.message_id, "msg2")
        self.assertEqual(stored.last_value, "AutoDJ|Artist|Two|Album")
        self.sender.send(make_response(track="Three"))
        self.assertEqual(self.edits()[-1].kwargs["id"], "msg2")
        self.assertEqual(len(self.posts()), 2)

    def test_failures_keep_id_and_do_not_raise(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(500), requests.exceptions.Timeout("slow"),
                                    FakeResponse(204)]
        self.sender.send(make_response())
        self.sender.send(make_response(track="Two"))
        self.assertEqual(self.store.get("Station X").message_id, "msg1")
        self.assertEqual(self.store.get("Station X").last_value, "AutoDJ|Artist|Song|Album")
        self.sender.send(make_response(track="Two"))
        self.assertEqual(self.store.get("Station X").message_id, "msg1")
        self.assertEqual(self.store.get("Station X").last_value, "AutoDJ|Artist|Song|Album")
        self.sender.send(make_response(track="Three"))
        self.assertEqual(self.store.get("Station X").last_value, "AutoDJ|Artist|Three|Album")
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(len(self.edits()), 3)

    def test_failed_first_post_saves_nothing_and_retries(self):
        FakeWebhook.post_results = [FakeResponse(500), requests.exceptions.Timeout("x"),
                                    FakeResponse(200, "msg1")]
        self.sender.send(make_response())
        self.assertIsNone(self.store.get("Station X"))
        self.sender.send(make_response())
        self.assertIsNone(self.store.get("Station X"))
        self.sender.send(make_response())
        self.assertEqual(self.store.get("Station X").message_id, "msg1")
        self.assertEqual(len(self.posts()), 3)

    def test_timeout_is_passed_to_every_webhook(self):
        sender = self.make_sender(self.store, timeout=4.5)
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(200)]
        sender.send(make_response())
        sender.send(make_response(track="Two"))
        self.assertEqual(len(FakeWebhook.instances), 2)
        for w in FakeWebhook.instances:
            self.assertEqual(w.kwargs["timeout"], 4.5)
            self.assertEqual(w.kwargs["url"], URL)

    def test_title_starts_with_station_name(self):
        data = format_status(make_response(), "Station X")
        self.assertTrue(data["title"].startswith("Station X"))
        self.assertIn("Song", data["title"])
        self.assertEqual(data["thumbnail_url"], "http://example.com/art.png")
        self.assertIn("_Album_", data["description"])
        self.assertIn("Artist (00:03:00)", data["description"])
        self.assertIsNotNone(data["timestamp"].tzinfo)

    def test_logs_never_contain_the_webhook_url(self):
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(500), requests.exceptions.Timeout(f"to {URL}")]
        with self.assertLogs(level=logging.DEBUG) as cm:
            self.sender.send(make_response())
            self.sender.send(make_response(track="Two"))
            self.sender.send(make_response(track="Three"))
        output = "\n".join(cm.output)
        self.assertNotIn(URL, output)
        self.assertNotIn("SECRET-TOKEN", output)


class FailingStore:
    """Wraps a real store; selected operations raise like a broken disk would."""
    def __init__(self, inner, fail_get=False, fail_save=False):
        self.inner = inner
        self.fail_get = fail_get
        self.fail_save = fail_save

    def get(self, station):
        if self.fail_get:
            raise sqlite3.OperationalError(f"disk I/O error for {URL}")
        return self.inner.get(station)

    def save(self, station, message_id, last_value):
        if self.fail_save:
            raise sqlite3.OperationalError(f"readonly database for {URL}")
        return self.inner.save(station, message_id, last_value)


class StoreFailureTests(unittest.TestCase):
    def setUp(self):
        FakeWebhook.instances = []
        FakeWebhook.post_results = [FakeResponse(200, "msg1")]
        FakeWebhook.edit_results = [FakeResponse(200) for _ in range(10)]
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.inner = StatusBoardStore(os.path.join(self._tmp.name, "b.db"))

    def sender(self, **kw):
        return StatusBoardSender(URL, "Station X", FailingStore(self.inner, **kw),
                                 webhook_factory=FakeWebhook)

    def posts(self):
        return [w for w in FakeWebhook.instances if "execute" in w.calls]

    def edits(self):
        return [w for w in FakeWebhook.instances if "edit" in w.calls]

    def check_one_post_rest_edits(self, sender, n=5):
        for i in range(n):
            sender.send(make_response(track=f"T{i}"))
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(len(self.edits()), n - 1)
        for w in self.edits():
            self.assertEqual(w.kwargs["id"], "msg1")

    def test_save_failure_still_edits_one_message(self):
        with self.assertLogs("status_board", level=logging.DEBUG):
            self.check_one_post_rest_edits(self.sender(fail_save=True))

    def test_get_and_save_failure_still_edits_one_message(self):
        with self.assertLogs("status_board", level=logging.DEBUG):
            self.check_one_post_rest_edits(self.sender(fail_get=True, fail_save=True))

    def test_same_track_not_resent_when_store_broken(self):
        s = self.sender(fail_get=True, fail_save=True)
        with self.assertLogs("status_board", level=logging.DEBUG):
            s.send(make_response())
            s.send(make_response())
        self.assertEqual(len(FakeWebhook.instances), 1)

    def test_distinct_store_failure_logs_without_url(self):
        with self.assertLogs("status_board", level=logging.DEBUG) as cm:
            s = self.sender(fail_get=True, fail_save=True)
            s.send(make_response())
            s.send(make_response(track="Two"))
        out = "\n".join(cm.output)
        self.assertIn("store write failed", out)
        self.assertIn("store read failed", out)
        self.assertIn("OperationalError", out)
        self.assertNotIn(URL, out)
        self.assertNotIn("SECRET-TOKEN", out)
        self.assertNotIn("disk I/O", out)

    def test_healthy_store_logs_no_store_failure(self):
        with self.assertLogs("status_board", level=logging.DEBUG) as cm:
            s = self.sender()
            s.send(make_response())
            s.send(make_response(track="Two"))
        self.assertNotIn("store", "\n".join(cm.output).replace("Status board", ""))


if __name__ == "__main__":
    unittest.main()
