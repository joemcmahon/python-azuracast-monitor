"""Tests for heartbeat.py"""
import os
import tempfile
import unittest

import heartbeat
from heartbeat import Heartbeat, check_heartbeat, heartbeat_path, main


class TestHeartbeat(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = self._tmp.name

    def test_heartbeat_path(self):
        self.assertEqual(heartbeat_path("/x/y"), os.path.join("/x/y", "heartbeat"))

    def test_touch_creates_file_and_directories(self):
        path = os.path.join(self.dir, "a", "b", "heartbeat")
        Heartbeat(path).touch()
        self.assertTrue(os.path.isfile(path))

    def test_touch_updates_mtime(self):
        path = os.path.join(self.dir, "heartbeat")
        hb = Heartbeat(path)
        hb.touch()
        os.utime(path, (1000, 1000))
        hb.touch()
        self.assertGreater(os.path.getmtime(path), 1000)

    def test_check_missing(self):
        self.assertFalse(check_heartbeat(os.path.join(self.dir, "nope"), 60))

    def test_check_fresh_and_stale(self):
        path = os.path.join(self.dir, "heartbeat")
        Heartbeat(path).touch()
        os.utime(path, (1000, 1000))
        self.assertTrue(check_heartbeat(path, 60, now=1030))
        self.assertFalse(check_heartbeat(path, 60, now=1061))

    def test_main_missing_fresh_stale(self):
        env = {"STATE_DIR": self.dir}
        self.assertEqual(main(env), 1)
        path = heartbeat_path(self.dir)
        Heartbeat(path).touch()
        self.assertEqual(main(env), 0)
        os.utime(path, (1000, 1000))
        self.assertEqual(main(env), 1)

    def test_main_max_age_from_env(self):
        path = heartbeat_path(self.dir)
        Heartbeat(path).touch()
        os.utime(path, (os.path.getmtime(path) - 100,) * 2)
        self.assertEqual(main({"STATE_DIR": self.dir, "HEARTBEAT_MAX_AGE": "10"}), 1)
        self.assertEqual(main({"STATE_DIR": self.dir, "HEARTBEAT_MAX_AGE": "500"}), 0)

    def test_default_max_age_is_900(self):
        path = heartbeat_path(self.dir)
        Heartbeat(path).touch()
        os.utime(path, (os.path.getmtime(path) - 800,) * 2)
        self.assertEqual(main({"STATE_DIR": self.dir}), 0)
        os.utime(path, (os.path.getmtime(path) - 200,) * 2)
        self.assertEqual(main({"STATE_DIR": self.dir}), 1)


if __name__ == "__main__":
    unittest.main()
