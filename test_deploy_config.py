import os
import re
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


APP_SERVICES = ["az-now-playing", "status-pulse", "status-inner", "status-outer"]


def compose_text():
    with open(os.path.join(HERE, "docker-compose.yml"), encoding="utf-8") as f:
        return f.read()


def service_block(name):
    """Text of one top-level service (2-space indent) under `services:`, comments removed."""
    text = compose_text()
    services = re.split(r"(?m)^services:[ \t]*$", text, maxsplit=1)[1]
    m = re.search(r"(?ms)^  %s:[ \t]*$(.*?)(?=^  \S|\Z)" % re.escape(name), services)
    assert m, f"service {name} not found in docker-compose.yml"
    lines = [re.sub(r"\s+#.*$", "", l) for l in m.group(1).splitlines()]
    return "\n".join(l for l in lines if l.strip() and not l.strip().startswith("#"))


def env_files(block):
    """Entries of an inline `env_file: [a, b]` or a block-style list."""
    m = re.search(r"(?m)^\s*env_file:\s*\[(.*?)\]", block)
    if m:
        return [e.strip().strip("\"'") for e in m.group(1).split(",") if e.strip()]
    m = re.search(r"(?ms)^(\s*)env_file:\s*$(.*?)(?=^\1\S|\Z)", block)
    assert m, "no env_file in block"
    return [l.strip()[1:].strip().strip("\"'") for l in m.group(2).splitlines()
            if l.strip().startswith("-")]


def norm(path):
    return path[2:] if path.startswith("./") else path


def state_volumes(block):
    return re.findall(r"""["']?(\./state/[\w.-]+):/state["']?""", block)


class ComposeStructureTests(unittest.TestCase):
    def test_status_services_load_only_their_own_station_env(self):
        for name in APP_SERVICES[1:]:
            with self.subTest(service=name):
                files = env_files(service_block(name))
                self.assertEqual(len(files), 1, files)
                self.assertRegex(files[0], r"^stations/[\w-]+\.env$")
                self.assertNotIn(".env", [norm(f) for f in files])
        own = [env_files(service_block(n))[0] for n in APP_SERVICES[1:]]
        self.assertEqual(len(set(own)), len(own), "station env files must be distinct")

    def test_main_service_loads_dotenv(self):
        self.assertIn(".env", [norm(f) for f in env_files(service_block("az-now-playing"))])

    def test_each_app_service_has_a_distinct_state_volume(self):
        seen = []
        for name in APP_SERVICES:
            with self.subTest(service=name):
                vols = state_volumes(service_block(name))
                self.assertEqual(len(vols), 1, vols)
                seen.append(vols[0])
        self.assertEqual(len(set(seen)), len(APP_SERVICES), seen)

    def test_app_services_are_managed_and_healthchecked(self):
        # Labels and healthcheck come from the YAML anchor; each service must merge it.
        text = compose_text()
        base = re.search(r"(?ms)^x-az-monitor-base:.*?(?=^\S)", text).group(0)
        self.assertRegex(base, r"az-monitor\.managed:\s*[\"']?true[\"']?")
        self.assertRegex(base, r"test:\s*\[.*healthcheck\.py.*\]")
        for name in APP_SERVICES:
            with self.subTest(service=name):
                block = service_block(name)
                inherits = re.search(r"<<:\s*\*az-monitor-(base|secondary)\b", block)
                direct = ("az-monitor.managed" in block and "healthcheck.py" in block)
                self.assertTrue(inherits or direct)
        sec = re.search(r"(?ms)^x-az-monitor-secondary:.*?(?=^\S)", text).group(0)
        self.assertIn("<<: *az-monitor-base", sec)

    def test_restarter_is_not_managed(self):
        block = service_block("restarter")
        self.assertNotIn("az-monitor.managed", block)
        self.assertNotRegex(block, r"<<:\s*\*az-monitor")


if __name__ == "__main__":
    unittest.main()
