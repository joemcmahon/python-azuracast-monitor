"""Container healthcheck: exit 0 if the heartbeat file is fresh, else 1."""
import sys

import heartbeat

if __name__ == "__main__":
    sys.exit(heartbeat.main())
