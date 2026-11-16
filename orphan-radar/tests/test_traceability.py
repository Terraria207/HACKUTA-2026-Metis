"""Grounding rule: every figure in a brief traces to an evidence record with a URL and a retrieval date.

These tests fail if a brief contains a number that is not cited, or cites evidence that is
missing, has no URL or has no retrieval date. They run on synthetic data and on a full
pipeline run over the recorded fixtures.
"""
import re
import unittest

from orphan_radar.brief import audit_brief, generate_brief, write_briefs
from orphan_radar.net import FixtureClient
from orphan_radar.pipeline import analyze, latest_scores, scan

from .helpers import COMPLAINTS, FIXTURES, add_plugin, config, memdb


def brief_for(conn, cfg=None):
    cfg = cfg or config()
    analyze(cfg, conn, scan_id=1, use_llm=False)
    eid = latest_scores(conn)[0]["id"]
    return eid, generate_brief(conn, eid, cfg)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        add_plugin(self.conn, complaints=COMPLAINTS)
        self.eid, self.md = brief_for(self.conn)
        self.names = ["Old Gallery Pro"]

    def test_generated_brief_passes(self):
        self.assertEqual(audit_brief(self.conn, self.md, self.names), [])

    def test_brief_has_all_twelve_sections_in_order(self):
        heads = re.findall(r"^## (\d+)\. ", self.md, re.M)
        self.assertEqual(heads, [str(i) for i in range(1, 13)])

    def test_every_citation_resolves_to_url_and_retrieval_date(self):
        refs = set(re.findall(r"\[\^(\d+)\]", self.md.split("\n## Evidence\n")[0]))
        defs = dict(re.findall(r"^\[\^(\d+)\]: (.*)$", self.md, re.M))
        self.assertTrue(refs)
        for r in refs:
            self.assertIn(r, defs)
            for eid in re.findall(r"#(\d+)", defs[r]):
                row = self.conn.execute("SELECT url, date_retrieved FROM evidence WHERE id=?", (int(eid),)).fetchone()
                self.assertTrue(row["url"].startswith("http"))
                self.assertRegex(row["date_retrieved"], r"^\d{4}-\d{2}-\d{2}")

    def test_uncited_figure_fails(self):
        tampered = self.md.replace("## 1. Summary\n", "## 1. Summary\n\nAbout 50,000 sites still run it.\n")
        problems = audit_brief(self.conn, tampered, self.names)
        self.assertTrue(any("50,000" in p for p in problems), problems)

    def test_invented_price_fails(self):
        tampered = self.md.replace("## 8. Price anchor\n", "## 8. Price anchor\n\nRivals charge $29/month.\n")
        self.assertTrue(audit_brief(self.conn, tampered, self.names))

    def test_citation_to_missing_evidence_fails(self):
        tampered = self.md.replace("### Evidence index", "[^999]: #987654 made up\n\n### Evidence index")
        self.assertTrue(any("missing evidence" in p for p in audit_brief(self.conn, tampered, self.names)))

    def test_evidence_without_retrieval_date_fails(self):
        first = int(re.search(r"^\[\^1\]: #(\d+)", self.md, re.M).group(1))
        self.conn.execute("UPDATE evidence SET date_retrieved='' WHERE id=?", (first,))
        self.assertTrue(any("retrieval date" in p for p in audit_brief(self.conn, self.md, self.names)))

    def test_generation_refuses_to_save_an_untraceable_brief(self):
        # Corrupt the evidence behind the brief; regenerating must raise instead of saving.
        self.conn.execute("UPDATE evidence SET date_retrieved='' WHERE entity_id=?", (self.eid,))
        with self.assertRaises(ValueError):
            generate_brief(self.conn, self.eid, config())

    def test_unknown_instead_of_estimates(self):
        self.assertIn("Rivals' prices: unknown", self.md)
        self.assertIn("Export format: unknown", self.md)


class FixturePipelineTests(unittest.TestCase):
    """Full scan over recorded fixtures (no network), then every brief must pass the audit."""

    def test_all_briefs_from_fixture_scan_are_traceable(self):
        cfg = config(**{"scan.wordpress_pages": 1, "scan.wordpress_extra_queries": [], "scan.wordpress_feed_limit": 3,
                        "scan.firefox_pages": 1, "scan.firefox_reviews_limit": 2, "scan.github_issue_repos": 1,
                        "scan.hn_queries": ["shutting down"], "scan.stackexchange_sites": {"stackoverflow": ["wordpress"]},
                        "scan.autocomplete_top_products": 2, "scan.atlassian_pages": 1, "scan.atlassian_reviews_limit": 1, "scan.vscode_pages": 1, "scan.vscode_min_installs": 0,
                        "thresholds.brief_min_score": 0})
        http = FixtureClient({
            "core/version-check": "wordpress_core_version.json", "query_plugins": "wordpress_query_plugins.json",
            "/reviews/feed/": "wordpress_reviews_feed.xml", "/feed/": "wordpress_support_feed.xml",
            "/addons/search/": "amo_search.json", "/ratings/rating/": "amo_ratings.json",
            "search/repositories": "github_search_repositories.json", "search/issues": "github_search_issues.json",
            "open-vsx.org": "openvsx_search.json", "hn.algolia.com": "hn_search.json",
            "api.stackexchange.com": "stackexchange_search.json", "/reviews": "atlassian_reviews.json", "/rest/2/addons": "atlassian_addons.json", "suggestqueries.google.com": "google_suggest.json",
        }, FIXTURES)
        conn = memdb()
        stats = scan(cfg, conn=conn, http=http, use_llm=False)
        self.assertFalse(stats["failed"], stats["failed"])
        self.assertGreaterEqual(len(stats["ran"]), 6)
        done, failed = write_briefs(conn, cfg)
        self.assertFalse(failed, failed)
        self.assertGreaterEqual(len(done), 3)
        for b in conn.execute("SELECT b.entity_id, b.markdown, e.name FROM briefs b JOIN entities e ON e.id=b.entity_id"):
            names = [r[0] for r in conn.execute("SELECT name FROM products WHERE entity_id=?", (b["entity_id"],))] + [b["name"]]
            self.assertEqual(audit_brief(conn, b["markdown"], names), [], b["name"])


if __name__ == "__main__":
    unittest.main()
