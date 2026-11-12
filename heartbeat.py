"""Heartbeat file: proof that the monitor is receiving data from AzuraCast."""
import os
import time


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


def main(environ=os.environ):
    """Healthcheck entry point: 0 if healthy, 1 otherwise."""
    state_dir = environ.get("STATE_DIR", ".")
    max_age = float(environ.get("HEARTBEAT_MAX_AGE", 900))
    return 0 if check_heartbeat(heartbeat_path(state_dir), max_age) else 1
