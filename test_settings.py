import unittest

from settings import (
    DEFAULT_AUTODJ_NAME,
    WEBHOOK_PREFIX,
    Settings,
    SettingsError,
    load_settings,
    parse_bool,
)

VALID = WEBHOOK_PREFIX + "123/secret-token-A"
VALID_STATUS = WEBHOOK_PREFIX + "456/secret-token-B"


class LoadSettingsTests(unittest.TestCase):
    def test_defaults_preserve_prod(self):
        s = load_settings({"NOW_PLAYING_WEBHOOK": VALID})
        self.assertIsInstance(s, Settings)
        self.assertEqual(s.station_server, "spiral.radio")
        self.assertEqual(s.station_shortcode, "radiospiral")
        self.assertEqual(s.station_name, "radiospiral")
        self.assertEqual(s.autodj_name, DEFAULT_AUTODJ_NAME)
        self.assertEqual(DEFAULT_AUTODJ_NAME, "Spud the Ambient Robot")
        self.assertFalse(s.status_board)
        self.assertEqual(s.webhook_url, VALID)
        self.assertEqual(s.webhook_timeout, 10.0)
        self.assertEqual(s.sse_read_timeout, 300.0)
        self.assertEqual(s.state_dir, ".")
        self.assertFalse(s.dry_run)

    def test_status_mode_requires_its_own_webhook(self):
        with self.assertRaises(SettingsError) as cm:
            load_settings({"STATUS_BOARD": "true", "NOW_PLAYING_WEBHOOK": VALID})
        self.assertIn("STATUS_BOARD_WEBHOOK", str(cm.exception))
        self.assertNotIn(VALID, str(cm.exception))
        self.assertNotIn("secret-token-A", str(cm.exception))

    def test_status_mode_uses_status_webhook(self):
        s = load_settings({
            "STATUS_BOARD": "true",
            "STATUS_BOARD_WEBHOOK": VALID_STATUS,
            "NOW_PLAYING_WEBHOOK": VALID,
        })
        self.assertTrue(s.status_board)
        self.assertEqual(s.webhook_url, VALID_STATUS)

    def test_invalid_webhooks_rejected(self):
        for label, env in [
            ("missing", {}),
            ("blank", {"NOW_PLAYING_WEBHOOK": "   "}),
            ("bad prefix", {"NOW_PLAYING_WEBHOOK": "http://example.com/secret-x"}),
        ]:
            with self.subTest(label):
                with self.assertRaises(SettingsError) as cm:
                    load_settings(env)
                self.assertIn("NOW_PLAYING_WEBHOOK", str(cm.exception))
                self.assertNotIn("secret-x", str(cm.exception))

    def test_dry_run_allows_missing_webhook(self):
        s = load_settings({"DRY_RUN": "1"})
        self.assertTrue(s.dry_run)

    def test_numeric_settings_validated(self):
        for value in ["abc", "0", "-5"]:
            with self.subTest(value):
                with self.assertRaises(SettingsError) as cm:
                    load_settings({"NOW_PLAYING_WEBHOOK": VALID, "WEBHOOK_TIMEOUT": value})
                self.assertIn("WEBHOOK_TIMEOUT", str(cm.exception))

    def test_sse_timeout_validated(self):
        with self.assertRaises(SettingsError) as cm:
            load_settings({"NOW_PLAYING_WEBHOOK": VALID, "SSE_READ_TIMEOUT": "nan"})
        self.assertIn("SSE_READ_TIMEOUT", str(cm.exception))

    def test_station_name_override(self):
        s = load_settings({
            "NOW_PLAYING_WEBHOOK": VALID,
            "STATION_SHORTCODE": "chill",
            "STATION_NAME": "Chill Out",
        })
        self.assertEqual(s.station_name, "Chill Out")
        s = load_settings({"NOW_PLAYING_WEBHOOK": VALID, "STATION_SHORTCODE": "chill"})
        self.assertEqual(s.station_name, "chill")


class ParseBoolTests(unittest.TestCase):
    def test_parse_bool(self):
        cases = [
            ("1", False, True), ("true", False, True), ("yes", False, True), ("on", False, True),
            ("0", True, False), ("false", True, False), ("no", True, False), ("off", True, False),
            (" TRUE ", False, True), ("off", True, False),
            (None, False, False), (None, True, True),
            ("", False, False), ("", True, True),
            ("maybe", False, False), ("maybe", True, True),
        ]
        for value, default, expected in cases:
            with self.subTest(value=value, default=default):
                self.assertEqual(parse_bool(value, default), expected)


if __name__ == "__main__":
    unittest.main()
