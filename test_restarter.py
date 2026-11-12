import os
import shutil
import socket
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "restarter.sh")

FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
if [ "$1" = "ps" ]; then
  case "$*" in
    *health=unhealthy*) for i in $FAKE_UNHEALTHY; do echo "$i"; done ;;
    *) for i in $FAKE_MANAGED; do echo "$i"; done ;;
  esac
fi
if [ "$1" = "inspect" ]; then
  [ -n "$FAKE_INSPECT" ] && echo "$FAKE_INSPECT"
  [ -n "$FAKE_INSPECT_FAIL" ] && exit 1
fi
exit 0
"""


@unittest.skipUnless(shutil.which("sh"), "sh not available")
class RestarterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "calls.log")
        self.state = os.path.join(self.tmp.name, "last")
        self.docker = os.path.join(self.tmp.name, "fake-docker")
        with open(self.docker, "w") as f:
            f.write(FAKE_DOCKER)
        os.chmod(self.docker, os.stat(self.docker).st_mode | stat.S_IXUSR)

    def run_pass(self, hm, day="2026-11-12", unhealthy="", managed="",
                 extra=None):
        env = dict(os.environ)
        env.pop("PROJECT", None)
        env.update({
            "DOCKER": self.docker, "RUN_ONCE": "1", "NOW_HM": hm,
            "NOW_DAY": day, "RESTARTER_STATE": self.state,
            "FAKE_LOG": self.log, "FAKE_UNHEALTHY": unhealthy,
            "FAKE_MANAGED": managed,
        })
        env.update(extra or {})
        result = subprocess.run(["sh", SCRIPT], env=env, capture_output=True,
                                text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return f.read().splitlines()

    def restarts(self):
        return [c for c in self.calls() if c.startswith("restart")]

    def reset_log(self):
        if os.path.exists(self.log):
            os.remove(self.log)

    def test_unhealthy_sweep_restarts_labelled_unhealthy_containers(self):
        self.run_pass("12:00", unhealthy="aaa bbb", managed="aaa bbb ccc")
        restarts = self.restarts()
        self.assertEqual(len(restarts), 2)
        self.assertTrue(any("aaa" in r for r in restarts))
        self.assertTrue(any("bbb" in r for r in restarts))
        self.assertFalse(any("ccc" in r for r in restarts))

    def test_daily_restart_once_per_day(self):
        managed = "m1 m2 m3"
        self.run_pass("05:00", managed=managed)
        self.assertEqual(len(self.restarts()), 3)
        self.assertTrue(os.path.exists(self.state))
        self.reset_log()
        self.run_pass("05:01", managed=managed)
        self.assertEqual(self.restarts(), [])
        self.reset_log()
        self.run_pass("05:00", day="2026-11-13", managed=managed)
        self.assertEqual(len(self.restarts()), 3)

    def test_before_restart_time_does_nothing_daily(self):
        self.run_pass("04:59", managed="m1 m2")
        self.assertEqual(self.restarts(), [])
        self.assertFalse(os.path.exists(self.state))

    def test_startup_after_restart_time_does_not_restart(self):
        managed = "m1 m2"
        self.run_pass("14:00", managed=managed)
        self.assertEqual(self.restarts(), [])
        self.assertTrue(os.path.exists(self.state))
        self.run_pass("05:00", day="2026-11-13", managed=managed)
        self.assertEqual(len(self.restarts()), 2)

    def test_ps_uses_the_managed_label(self):
        self.run_pass("12:00")
        ps_calls = [c for c in self.calls() if c.startswith("ps")]
        self.assertTrue(ps_calls)
        for call in ps_calls:
            self.assertIn("label=az-monitor.managed=true", call)

    def ps_calls(self):
        return [c for c in self.calls() if c.startswith("ps")]

    def test_ps_calls_are_scoped_to_the_compose_project(self):
        self.run_pass("05:00", managed="m1", extra={"PROJECT": "foo"})
        ps_calls = self.ps_calls()
        self.assertEqual(len(ps_calls), 2)
        for call in ps_calls:
            self.assertIn("label=com.docker.compose.project=foo", call)

    def test_project_discovered_via_inspect(self):
        self.run_pass("05:00", managed="m1", extra={"FAKE_INSPECT": "bar"})
        ps_calls = self.ps_calls()
        self.assertEqual(len(ps_calls), 2)
        for call in ps_calls:
            self.assertIn("label=com.docker.compose.project=bar", call)
        inspects = [c for c in self.calls() if c.startswith("inspect")]
        self.assertEqual(len(inspects), 1)
        self.assertIn(socket.gethostname(), inspects[0])

    def test_unknown_project_runs_unscoped_with_warning(self):
        result = self.run_pass("05:00", managed="m1",
                               extra={"FAKE_INSPECT_FAIL": "1"})
        ps_calls = self.ps_calls()
        self.assertEqual(len(ps_calls), 2)
        for call in ps_calls:
            self.assertNotIn("com.docker.compose.project", call)
        self.assertIn("WARNING", result.stdout + result.stderr)
        self.assertEqual(len(self.restarts()), 1)

    def test_empty_ps_does_not_call_restart(self):
        self.run_pass("05:00")
        self.assertEqual(self.restarts(), [])


if __name__ == "__main__":
    unittest.main()
