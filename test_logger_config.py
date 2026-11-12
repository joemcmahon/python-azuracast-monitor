import io
import logging
import os
import tempfile
import unittest

import logger_config


class UrllibLoggingCapTest(unittest.TestCase):
    def setUp(self):
        root = logging.getLogger()
        self._handlers = list(root.handlers)
        self._level = root.level
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        root = logging.getLogger()
        for h in list(root.handlers):
            if h not in self._handlers:
                h.close()
        root.handlers[:] = self._handlers
        root.setLevel(self._level)
        for name in ("urllib3", "requests"):
            logging.getLogger(name).setLevel(logging.NOTSET)
        self._tmp.cleanup()

    def test_http_libraries_capped_at_warning_even_in_debug(self):
        logger_config.setup_logging(
            "DEBUG", log_file=os.path.join(self._tmp.name, "t.log"))
        self.assertGreaterEqual(
            logging.getLogger("urllib3").getEffectiveLevel(), logging.WARNING)
        self.assertGreaterEqual(
            logging.getLogger("requests").getEffectiveLevel(), logging.WARNING)

        stream = io.StringIO()
        logging.getLogger().addHandler(logging.StreamHandler(stream))
        logging.getLogger("urllib3.connectionpool").debug("POST /api/webhooks/SECRET")
        self.assertNotIn("SECRET", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
