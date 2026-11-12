import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

SETTING_NAMES = [
    "STATION_SERVER", "STATION_SHORTCODE", "STATION_NAME", "AUTODJ_NAME",
    "STATUS_BOARD", "NOW_PLAYING_WEBHOOK", "STATUS_BOARD_WEBHOOK",
    "STATE_DIR", "WEBHOOK_TIMEOUT", "SSE_READ_TIMEOUT", "DRY_RUN",
]


def read_lines(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return f.read().splitlines()


class DeployConfigTests(unittest.TestCase):
    def test_dockerfile_does_not_copy_env(self):
        for line in read_lines("Dockerfile"):
            if line.strip().upper().startswith(("COPY", "ADD")):
                self.assertNotIn(".env", line)

    def test_dockerignore_excludes_secrets_and_state(self):
        path = os.path.join(HERE, ".dockerignore")
        self.assertTrue(os.path.exists(path), ".dockerignore is missing")
        entries = {l.strip() for l in read_lines(".dockerignore")}
        for needed in (".env", ".venv", ".git", "state/"):
            self.assertIn(needed, entries)

    def test_env_example_documents_all_settings(self):
        text = "\n".join(read_lines(".env.example"))
        for name in SETTING_NAMES:
            self.assertIn(name, text)

    def test_gitignore_covers_station_env_and_state(self):
        entries = {l.strip() for l in read_lines(".gitignore")}
        for needed in ("stations/*.env", "state/", "*.sqlite3"):
            self.assertIn(needed, entries)
        for line in entries:
            if line.startswith("#"):
                continue
            self.assertNotIn("example", line)
