"""Heartbeat file: proof that the monitor is receiving data from AzuraCast."""
import math
import os
import sys
import time

DEFAULT_MAX_AGE = 900.0


def heartbeat_path(state_dir):
    """Return the heartbeat file path inside state_dir."""
    return os.path.join(state_dir, "heartbeat")


class Heartbeat:
    def __init__(self, path):
        self.path = path

    def touch(self):
        """Create the file (and parent dirs) if needed and update its mtime."""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "a"):
            pass
        os.utime(self.path, None)


def check_heartbeat(path, max_age, now=None):
    """True if the file exists and was modified within max_age seconds."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return False
    if now is None:
        now = time.time()
    return (now - mtime) <= max_age


def _parse_max_age(raw):
    """Parse HEARTBEAT_MAX_AGE; blank/invalid/non-positive values use the default."""
    if raw is None:
        return DEFAULT_MAX_AGE
    try:
        value = float(raw)
        if math.isfinite(value) and value > 0:
            return value
    except ValueError:
        pass
    print(f"healthcheck: HEARTBEAT_MAX_AGE is invalid; using default "
          f"{int(DEFAULT_MAX_AGE)}", file=sys.stderr)
    return DEFAULT_MAX_AGE


def main(environ=os.environ):
    """Healthcheck entry point: 0 if healthy, 1 otherwise."""
    state_dir = environ.get("STATE_DIR", ".")
    max_age = _parse_max_age(environ.get("HEARTBEAT_MAX_AGE"))
    return 0 if check_heartbeat(heartbeat_path(state_dir), max_age) else 1
