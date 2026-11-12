import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

# Importing azmonitor runs setup_logging(), which would create azmonitor.log in
# the cwd and install console handlers. Stub it out for the import.
with mock.patch("logger_config.setup_logging"):
    import azmonitor

from azclient import NowPlayingResponse
from settings import load_settings
from status_board import StatusBoardSender

WEBHOOK = "https://discord.com/api/webhooks/123/SECRETTOKEN"


def make_response(track="Song"):
    return NowPlayingResponse(
        dj="Spud", live=False, duration="0:03:00", elapsed="0:00:10",
        start=datetime(2026, 1, 1, 12, 0, 0), artist="Artist", track=track,
        album="Album", artURL="https://example.com/art.png")


def settings_for(tmp, **extra):
    env = {"NOW_PLAYING_WEBHOOK": WEBHOOK, "STATE_DIR": tmp}
    env.update(extra)
    return load_settings(env)


class SenderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_sender_selects_class(self):
        dry = azmonitor.build_sender(settings_for(self.tmp, DRY_RUN="true"))
        self.assertIsInstance(dry, azmonitor.DryRunSender)
        board = azmonitor.build_sender(settings_for(
            self.tmp, STATUS_BOARD="true", STATUS_BOARD_WEBHOOK=WEBHOOK))
        self.assertIsInstance(board, StatusBoardSender)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "status_board.sqlite3")))
        plain = azmonitor.build_sender(settings_for(self.tmp))
        self.assertIsInstance(plain, azmonitor.DiscordSender)

    def test_build_sender_passes_webhook_timeout(self):
        board = azmonitor.build_sender(settings_for(
            self.tmp, STATUS_BOARD="true", STATUS_BOARD_WEBHOOK=WEBHOOK,
            WEBHOOK_TIMEOUT="7.5"))
        self.assertEqual(board.timeout, 7.5)
        plain = azmonitor.build_sender(settings_for(self.tmp, WEBHOOK_TIMEOUT="3.5"))
        with mock.patch.object(azmonitor, "DiscordWebhook") as wh:
            wh.return_value.execute.return_value.status_code = 200
            plain.send(make_response())
        wh.assert_called_once_with(url=WEBHOOK, timeout=3.5)

    def test_dry_run_in_status_board_mode_is_dry(self):
        s = azmonitor.build_sender(settings_for(
            self.tmp, STATUS_BOARD="true", DRY_RUN="1"))
        self.assertIsInstance(s, azmonitor.DryRunSender)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "status_board.sqlite3")))

    def test_dry_run_never_constructs_a_webhook(self):
        with mock.patch.object(azmonitor, "DiscordWebhook") as wh:
            azmonitor.DryRunSender("RadioSpiral").send(make_response())
        wh.assert_not_called()

    def test_discord_sender_passes_timeout(self):
        with mock.patch.object(azmonitor, "DiscordWebhook") as wh:
            wh.return_value.execute.return_value.status_code = 200
            azmonitor.DiscordSender(WEBHOOK, 4.5).send(make_response())
        wh.assert_called_once_with(url=WEBHOOK, timeout=4.5)

    def test_plain_mode_dedups(self):
        with mock.patch.object(azmonitor, "DiscordWebhook") as wh:
            wh.return_value.execute.return_value.status_code = 200
            sender = azmonitor.DiscordSender(WEBHOOK)
            sender.send(make_response())
            sender.send(make_response())
        self.assertEqual(wh.call_count, 1)

    def test_send_webhook_logs_exception_type_not_text(self):
        with mock.patch.object(azmonitor, "DiscordWebhook",
                               side_effect=RuntimeError(WEBHOOK)):
            with self.assertLogs(azmonitor.logger, level="ERROR") as cm:
                azmonitor.send_webhook(
                    {"title": "t", "description": "d", "timestamp": 0,
                     "thumbnail_url": "u"}, WEBHOOK)
        self.assertNotIn("SECRETTOKEN", "\n".join(cm.output))
        self.assertIn("RuntimeError", "\n".join(cm.output))


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        for target in (mock.patch.object(azmonitor, "load_dotenv"),
                       mock.patch.object(azmonitor.signal, "signal")):
            target.start()
            self.addCleanup(target.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_main_exits_1_without_connecting_on_bad_settings(self):
        env = {"STATUS_BOARD": "true", "NOW_PLAYING_WEBHOOK": WEBHOOK,
               "STATE_DIR": self.tmp}
        with mock.patch.object(azmonitor, "ResilientRunner") as runner, \
                self.assertLogs(azmonitor.logger, level="ERROR") as cm:
            self.assertEqual(azmonitor.main(env), 1)
        self.assertIn("STATUS_BOARD_WEBHOOK", "\n".join(cm.output))
        self.assertNotIn("SECRETTOKEN", "\n".join(cm.output))
        runner.assert_not_called()

    def test_main_wires_heartbeat_and_settings(self):
        env = {"NOW_PLAYING_WEBHOOK": WEBHOOK, "STATE_DIR": self.tmp,
               "STATION_SERVER": "example.org", "STATION_SHORTCODE": "ambient",
               "AUTODJ_NAME": "Robot", "SSE_READ_TIMEOUT": "42"}
        with mock.patch.object(azmonitor, "ResilientRunner") as runner:
            runner.return_value.run.return_value = 7
            self.assertEqual(azmonitor.main(env), 7)
        args, kwargs = runner.call_args
        self.assertEqual(args[:2], ("example.org", "ambient"))
        self.assertEqual(kwargs["read_timeout"], 42.0)
        self.assertEqual(kwargs["autodj_name"], "Robot")
        self.assertIsNone(kwargs["max_retries"])
        hb = os.path.join(self.tmp, "heartbeat")
        self.assertFalse(os.path.exists(hb))
        kwargs["on_event"]()
        self.assertTrue(os.path.exists(hb))
        os.remove(hb)
        kwargs["on_connect"]()
        self.assertTrue(os.path.exists(hb))

    def test_failure_building_sender_logs_traceback(self):
        env = {"NOW_PLAYING_WEBHOOK": WEBHOOK, "STATE_DIR": self.tmp}
        with mock.patch.object(azmonitor, "build_sender",
                               side_effect=PermissionError("/state nope")), \
                mock.patch.object(azmonitor, "ResilientRunner") as runner, \
                self.assertLogs(azmonitor.logger, level="ERROR") as cm:
            self.assertEqual(azmonitor.main(env), 1)
        runner.assert_not_called()
        self.assertTrue(any(r.exc_info for r in cm.records))
        self.assertIn("PermissionError", "\n".join(cm.output))

    def test_failure_from_runner_stays_type_only(self):
        env = {"NOW_PLAYING_WEBHOOK": WEBHOOK, "STATE_DIR": self.tmp}
        with mock.patch.object(azmonitor, "ResilientRunner") as runner, \
                self.assertLogs(azmonitor.logger, level="ERROR") as cm:
            runner.return_value.run.side_effect = RuntimeError(WEBHOOK)
            self.assertEqual(azmonitor.main(env), 1)
        self.assertFalse(any(r.exc_info for r in cm.records))
        self.assertIn("RuntimeError", "\n".join(cm.output))
        self.assertNotIn("SECRETTOKEN", "\n".join(cm.output))


if __name__ == "__main__":
    unittest.main()
