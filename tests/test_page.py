"""bin/blueprint serving the page and saving decisions as they are made."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from omarchy_blueprint import page


class TestServe(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        (self.out / "inventory.json").write_text(json.dumps({"schema": 1, "generated": "T1", "items": [], "machine": {}}))
        self.server, self.url = page.make_server(self.out, "")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def post(self, path, body, kind="application/json"):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": kind})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_page_is_served_only_at_the_secret_path(self):
        html = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn('<script type="application/json" id="served">true</script>', html)
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))
        root = self.url.rsplit("/", 2)[0] + "/"
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(root, timeout=5)

    def test_each_choice_is_saved_and_done_stops_the_server(self):
        body = {"schema": 1, "inventory": "T1", "decisions": {"package:age": {"class": "skip", "by": "you"}}}
        self.assertEqual(self.post("decisions", body), 204)
        self.assertEqual(json.loads((self.out / "decisions.json").read_text()), body)
        self.assertEqual(self.post("decisions?done", body), 204)
        self.thread.join(5)
        self.assertFalse(self.thread.is_alive())
        self.assertTrue(self.server.done)

    def test_refuses_other_inspections_and_non_json(self):
        self.assertEqual(self.post("decisions", {"schema": 1, "inventory": "OLD", "decisions": {}}), 400)
        self.assertEqual(self.post("decisions", {"schema": 1, "inventory": "T1", "decisions": {}}, "text/plain"), 415)
        self.assertFalse((self.out / "decisions.json").exists())


if __name__ == "__main__":
    unittest.main()
