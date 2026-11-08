"""The secrets scan: what it stops on, what it warns about, what it leaves alone."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from omarchy_blueprint import scan_secrets


class TestScan(unittest.TestCase):
    def scan(self, text):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "f.conf").write_text(text)
            with redirect_stdout(io.StringIO()) as out:
                rc = scan_secrets.main([d])
            return rc, out.getvalue()

    def test_tokens_stop_the_commit(self):
        rc, out = self.scan('token = "ghp_' + "a" * 36 + '"\n')
        self.assertEqual(rc, 1)
        self.assertIn("ghp_…", out)
        self.assertNotIn("a" * 36, out)

    def test_password_values_warn_without_stopping(self):
        # These were never shown before: an empty pattern file hid every warning.
        rc, out = self.scan("password = hunter2hunter2\n")
        self.assertEqual(rc, 0)
        self.assertIn("look like credentials", out)

    def test_code_and_settings_stay_quiet(self):
        rc, out = self.scan('authUrl = parsed.authUrl\ntoken = "terminal"\n# password = example1234\n')
        self.assertEqual(rc, 0)
        self.assertIn("No secrets found", out)


if __name__ == "__main__":
    unittest.main()
