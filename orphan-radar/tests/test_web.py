"""Dashboard pages render and escape untrusted text; POSTs only from the same origin."""
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from orphan_radar.brief import write_briefs
from orphan_radar.models import Evidence, insert_evidence
from orphan_radar.pipeline import analyze
from orphan_radar.web.app import App, make_handler
from orphan_radar.web.markdown import render

from .helpers import COMPLAINTS, TS, add_plugin, config, memdb


class MarkdownTests(unittest.TestCase):
    def test_escapes_html(self):
        out = render("# T\n\nA <script>alert(1)</script> [x](javascript:alert(1)) [y](https://ok.example)")
        self.assertNotIn("<script>", out)
        self.assertNotIn('href="javascript', out)
        self.assertIn('href="https://ok.example"', out)


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = memdb()
        add_plugin(cls.conn, complaints=COMPLAINTS + [("<img src=x onerror=alert(1)> broke after update", 1)])
        insert_evidence(cls.conn, Evidence(source="hackernews", type="discussion", url="https://news.ycombinator.com/item?id=1",
                                           date_retrieved=TS, date_posted=TS, text="Acme Notes is shutting down", tags=["event:shutdown"]))
        cls.cfg = config()
        analyze(cls.cfg, cls.conn, scan_id=1, use_llm=False)
        write_briefs(cls.conn, cls.cfg, only=[1])
        cls.app = App(cls.cfg)
        cls.app.conn = lambda: cls.conn  # share the in-memory database

    def test_pages_render(self):
        self.assertIn(b"Old Gallery Pro", self.app.index({}))
        self.assertIn(b"Old Gallery Pro", self.app.index({"signal": ["pain"]}))
        detail = self.app.detail(1)
        self.assertIn(b"Score breakdown", detail)
        self.assertNotIn(b"<img src=x", detail)          # review text is escaped
        self.assertIn(b"&lt;img src=x", detail)
        self.assertIn(b"Smallest replacement", self.app.brief(1))
        self.assertIn(b"No build prompt yet", self.app.buildprompt(1))
        self.assertEqual(self.app.post("/o/1/buildprompt", {}), "/o/1/buildprompt")
        self.assertIn(b"Build specification", self.app.buildprompt(1))
        self.assertIn(b"Open the build prompt", self.app.detail(1))
        self.assertIn(b"Acme Notes is shutting down", self.app.leads())
        for page in (self.app.excluded(), self.app.sources(), self.app.ledger(), self.app.digest_page()):
            self.assertIn(b"Orphan Radar", page)

    def test_state_and_ledger_actions(self):
        self.assertEqual(self.app.post("/o/1/state", {"state": ["watching"]}), "/o/1")
        self.assertEqual(self.conn.execute("SELECT state FROM states WHERE entity_id=1").fetchone()[0], "watching")
        self.app.post("/ledger", {"name": ["GalleryNext"], "entity": ["1"]})
        lid = self.conn.execute("SELECT id FROM ledger").fetchone()[0]
        self.app.post(f"/ledger/{lid}", {"paying_30d": ["2"], "revenue_30d": ["58"]})
        self.assertIn(b"winner", self.app.ledger())

    def test_cross_origin_post_refused(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/o/1/state"
            req = urllib.request.Request(url, data=b"state=dismissed", headers={"Origin": "http://evil.example"}, method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req, timeout=5)
            self.assertEqual(ctx.exception.code, 403)
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
