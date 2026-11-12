"""Tests for resilient_runner.py"""
import logging
import unittest
import unittest.mock
from unittest.mock import patch

import resilient_runner
from azclient import SSEConnectionError
from resilient_runner import ResilientRunner


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, n):
        self.sleeps.append(n)
        self.now += n


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        for p in (
            patch("resilient_runner.time", self.clock),
            patch("random.random", return_value=0.5),
            patch("resilient_runner.build_sse_client"),
            patch("azclient.run"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.build = resilient_runner.build_sse_client
        import azclient
        self.az_run = azclient.run

    def shutdown_after(self, n):
        calls = {"n": 0}

        def check():
            calls["n"] += 1
            return calls["n"] > n
        return check


class TestConnectHooks(RunnerTestCase):
    def test_on_connect_called_per_successful_connection(self):
        on_connect = unittest.mock.Mock()
        self.az_run.side_effect = lambda *a, **k: k["on_event"]()
        r = ResilientRunner("s", "c", print, on_connect=on_connect)
        r.run(self.shutdown_after(3))
        self.assertEqual(on_connect.call_count, 3)

    def test_failed_build_does_not_call_on_connect(self):
        on_connect = unittest.mock.Mock()
        for exc in (RuntimeError("x"), SSEConnectionError("HTTP 503")):
            self.build.side_effect = exc
            r = ResilientRunner("s", "c", print, on_connect=on_connect)
            r.run(self.shutdown_after(2))
        on_connect.assert_not_called()

    def test_on_connect_exception_ignored(self):
        def boom():
            raise ValueError("no")
        self.az_run.side_effect = lambda *a, **k: k["on_event"]()
        r = ResilientRunner("s", "c", print, on_connect=boom)
        self.assertEqual(r.run(self.shutdown_after(1)), 0)

    def test_forwarding(self):
        on_event = unittest.mock.Mock()
        cb = unittest.mock.Mock()
        r = ResilientRunner("srv", "code", cb, read_timeout=42.0,
                            autodj_name="Auto", on_event=on_event)
        self.az_run.side_effect = lambda *a, **k: k["on_event"]()
        r.run(self.shutdown_after(1))
        self.build.assert_called_with("srv", "code", read_timeout=42.0)
        args, kwargs = self.az_run.call_args
        self.assertEqual(args[1:3], (cb, "code"))
        self.assertEqual(kwargs["autodj_name"], "Auto")
        on_event.assert_called_once()


class TestBackoff(RunnerTestCase):
    def test_event_resets_backoff(self):
        outcomes = iter(["fail", "fail", "fail", "event_then_fail", "fail"])

        def fake_run(client, cb, code, **k):
            o = next(outcomes)
            if o == "event_then_fail":
                k["on_event"]()
            raise RuntimeError("boom")
        self.az_run.side_effect = fake_run
        runner = ResilientRunner("s", "c", print)
        waits = []
        orig = runner._calculate_backoff

        def spy():
            v = orig()
            waits.append(v)
            return v
        runner._calculate_backoff = spy
        runner.run(lambda: len(waits) >= 5)
        self.assertEqual(waits[:5], [1, 2, 4, 1, 2])

    def test_backoff_doubles_without_events(self):
        self.az_run.side_effect = RuntimeError("boom")
        runner = ResilientRunner("s", "c", print)
        waits = []
        orig = runner._calculate_backoff
        runner._calculate_backoff = lambda: waits.append(orig()) or waits[-1]
        runner.run(lambda: len(waits) >= 11)
        self.assertEqual(waits[:11], [1, 2, 4, 8, 16, 32, 64, 128, 256, 300, 300])

    def test_event_less_close_backs_off_instead_of_spinning(self):
        self.az_run.return_value = None
        runner = ResilientRunner("s", "c", print)
        waits = []
        orig = runner._calculate_backoff
        runner._calculate_backoff = lambda: waits.append(orig()) or waits[-1]
        attempts = {"n": 0}

        def check():
            return len(waits) >= 4
        self.build.side_effect = lambda *a, **k: attempts.__setitem__("n", attempts["n"] + 1)
        runner.run(check)
        self.assertEqual(waits, [1, 2, 4, 8])
        self.assertTrue(all(w > 0 for w in waits))
        self.assertGreater(sum(self.clock.sleeps), 0)
        self.assertLessEqual(attempts["n"], 5)

    def test_shutdown_during_backoff_exits(self):
        self.az_run.return_value = None
        runner = ResilientRunner("s", "c", print)
        state = {"calls": 0}

        def check():
            state["calls"] += 1
            return state["calls"] > 3
        self.assertEqual(runner.run(check), 0)


if __name__ == "__main__":
    unittest.main()
