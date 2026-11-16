"""Adapters against recorded responses (tests/fixtures, captured from the live APIs on 2026-11-16)."""
import json
import unittest

from orphan_radar.adapters.autocomplete import parse_suggestions, relevant
from orphan_radar.adapters.base import ScanContext
from orphan_radar.adapters.firefox import FirefoxAdapter, addon_to_product, parse_ratings
from orphan_radar.adapters.github import GitHubAdapter, issue_evidence, repo_evidence, repo_to_product
from orphan_radar.adapters.hackernews import hit_to_evidence
from orphan_radar.adapters.openvsx import ext_evidence, ext_to_product
from orphan_radar.adapters.stackexchange import item_to_evidence
from orphan_radar.adapters.wordpress import WordPressAdapter, parse_feed, plugin_metrics, plugin_to_product
from orphan_radar.models import Evidence, Product
from orphan_radar.net import FixtureClient
from orphan_radar.pipeline import store

from .helpers import FIXTURES, TS, config, memdb


def load(name):
    return json.loads((FIXTURES / name).read_text())


class WordPressTests(unittest.TestCase):
    def test_product_and_metrics(self):
        raw = load("wordpress_plugin_information.json")
        p = plugin_to_product(raw)
        self.assertEqual(p.source_id, "wp-super-cache")
        self.assertEqual(p.user_count, 1_000_000)
        self.assertAlmostEqual(p.rating, 4.3)          # 86 / 20
        self.assertEqual(p.pricing_model, "free")      # fixture declares business_model: false
        self.assertEqual(plugin_to_product(dict(raw, business_model="commercial")).pricing_model, "freemium")
        ev = {e.metric_key: e for e in plugin_metrics(p, raw, "https://api.example/x", TS, "7.1.4", "https://core")}
        self.assertEqual(ev["user_count"].metric_value, 1_000_000)
        self.assertEqual(ev["tested_up_to"].metric_text, "7.1.4")
        self.assertEqual(ev["support_threads_recent"].metric_value, 5)
        self.assertEqual(ev["platform_current_version"].metric_text, "7.1.4")
        for e in ev.values():
            self.assertTrue(e.url and e.date_retrieved)

    def test_query_listing(self):
        data = load("wordpress_query_plugins.json")
        prods = [plugin_to_product(p) for p in data["plugins"]]
        self.assertTrue(all(p.url.startswith("https://wordpress.org/plugins/") for p in prods))

    def test_review_feed_parses_stars_and_drops_authors(self):
        p = Product(source="wordpress", source_id="wp-super-cache", name="WP Super Cache", url="u")
        xml = (FIXTURES / "wordpress_reviews_feed.xml").read_text()
        rows = parse_feed(xml, p, "reviews", TS)
        self.assertEqual(len(rows), 30)
        self.assertTrue(all(r.type == "review" and r.score in (1, 2, 3, 4, 5) for r in rows))
        blob = json.dumps([r.__dict__ for r in rows], default=str)
        self.assertNotIn("John Titor", blob)  # dc:creator in the feed: personal data must not be stored
        self.assertNotIn("villapesquera", blob)

    def test_support_feed_marks_unanswered(self):
        p = Product(source="wordpress", source_id="wp-super-cache", name="WP Super Cache", url="u")
        rows = parse_feed((FIXTURES / "wordpress_support_feed.xml").read_text(), p, "support", TS)
        self.assertEqual(len(rows), 30)
        for r in rows:
            self.assertEqual(r.type, "support_thread")
            self.assertEqual("unanswered" in r.tags, r.extra["replies"] == 0)

    def test_collect_end_to_end_with_fixtures(self):
        cfg = config(**{"scan.wordpress_pages": 1, "scan.wordpress_extra_queries": [], "scan.wordpress_feed_limit": 1})
        http = FixtureClient({"core/version-check": "wordpress_core_version.json", "query_plugins": "wordpress_query_plugins.json",
                              "/reviews/feed/": "wordpress_reviews_feed.xml", "/feed/": "wordpress_support_feed.xml"}, FIXTURES)
        conn = memdb()
        stats = {"products": 0, "evidence_new": 0, "evidence_refreshed": 0}
        store(conn, WordPressAdapter().collect(ScanContext(conn=conn, http=http, config=cfg)), stats)
        self.assertEqual(stats["products"], 3)
        self.assertGreater(stats["evidence_new"], 60)
        # rerunning is safe: nothing new, everything refreshed
        stats2 = {"products": 0, "evidence_new": 0, "evidence_refreshed": 0}
        store(conn, WordPressAdapter().collect(ScanContext(conn=conn, http=http, config=cfg)), stats2)
        self.assertEqual(stats2["evidence_new"], 0)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM evidence WHERE url IS NULL OR url='' OR date_retrieved IS NULL").fetchone()[0], 0)


class FirefoxTests(unittest.TestCase):
    def test_product(self):
        a = load("amo_search.json")["results"][0]
        p = addon_to_product(a)
        self.assertEqual(p.name, "uBlock Origin")  # localized dict -> en-US
        self.assertEqual(p.user_count, a["average_daily_users"])
        self.assertEqual(p.license, "GNU General Public License v3.0 only")

    def test_ratings_drop_reviewer_identity(self):
        p = Product(source="firefox", source_id="video-downloadhelper", name="Video DownloadHelper", url="u")
        rows = parse_ratings(load("amo_ratings.json"), p, "https://ratings", TS, 365)
        self.assertTrue(rows)
        reviews = [r for r in rows if r.type == "review"]
        self.assertTrue(all("/reviews/" in r.url for r in reviews))
        self.assertTrue(all(r.score == 1 for r in reviews))
        self.assertNotIn("Crinoid", json.dumps([r.__dict__ for r in rows], default=str))

    def test_collect_with_fixtures(self):
        cfg = config(**{"scan.firefox_pages": 1, "scan.firefox_reviews_limit": 1})
        http = FixtureClient({"/addons/search/": "amo_search.json", "/ratings/rating/": "amo_ratings.json"}, FIXTURES)
        conn = memdb()
        recs = list(FirefoxAdapter().collect(ScanContext(conn=conn, http=http, config=cfg)))
        self.assertEqual(sum(isinstance(r, Product) for r in recs), 2)
        self.assertTrue(any(isinstance(r, Evidence) and r.type == "review" for r in recs))


class GitHubTests(unittest.TestCase):
    def test_archived_repo(self):
        r = load("github_search_repositories.json")["items"][0]
        p = repo_to_product(r)
        self.assertEqual(p.source_id, "atom/atom")
        self.assertIsNone(p.user_count)  # stars are not users
        ev = repo_evidence(p, r, "https://api.github.com/search", TS)
        keys = {e.metric_key for e in ev if e.type == "metric"}
        self.assertIn("github_stars", keys)
        self.assertTrue(any(e.type == "event" and "event:sunset" in e.tags for e in ev))

    def test_issue(self):
        p = repo_to_product(load("github_search_repositories.json")["items"][0])
        item = load("github_search_issues.json")["items"][0]
        e = issue_evidence(p, item, TS)
        self.assertEqual(e.type, "issue")
        self.assertEqual(e.score, item["reactions"]["total_count"])
        self.assertNotIn(item["user"]["login"], json.dumps(e.__dict__, default=str))

    def test_collect_with_fixtures(self):
        cfg = config(**{"scan.github_issue_repos": 1})
        http = FixtureClient({"search/repositories": "github_search_repositories.json", "search/issues": "github_search_issues.json"}, FIXTURES)
        recs = list(GitHubAdapter().collect(ScanContext(conn=memdb(), http=http, config=cfg)))
        self.assertTrue(any(isinstance(r, Product) for r in recs))
        self.assertTrue(any(isinstance(r, Evidence) and r.type == "issue" for r in recs))


class DiscussionSourceTests(unittest.TestCase):
    def test_hn_hit(self):
        hit = load("hn_search.json")["hits"][0]
        e = hit_to_evidence(hit, TS)
        self.assertEqual(e.url, f"https://news.ycombinator.com/item?id={hit['objectID']}")
        self.assertIn("event:shutdown", e.tags)
        self.assertEqual(e.metric_value, hit["points"])
        self.assertNotIn(hit["author"], json.dumps(e.__dict__, default=str))

    def test_stackexchange_item(self):
        item = load("stackexchange_search.json")["items"][0]
        e = item_to_evidence(item, "stackoverflow", TS)
        self.assertEqual(e.metric_key, "view_count")
        self.assertEqual(e.metric_value, item["view_count"])
        self.assertEqual("unanswered" in e.tags, not item.get("accepted_answer_id"))

    def test_autocomplete(self):
        s = parse_suggestions((FIXTURES / "ddg_autocomplete.json").read_bytes())
        self.assertIn("notion alternatives", s)
        self.assertEqual(relevant(["notion alternatives", "obsidian vs logseq"], "notion"), ["notion alternatives"])
        self.assertEqual(parse_suggestions((FIXTURES / "google_suggest.json").read_bytes()), [])

    def test_openvsx(self):
        e = load("openvsx_search.json")["extensions"][0]
        p = ext_to_product(e)
        self.assertEqual(p.source_id, f"{e['namespace']}.{e['name']}")
        ev = ext_evidence(p, e, "https://open-vsx.org/api/-/search", TS)
        self.assertTrue(any(x.metric_key == "downloads" for x in ev))


if __name__ == "__main__":
    unittest.main()


class AtlassianTests(unittest.TestCase):
    def test_product_reviews_and_privacy(self):
        from orphan_radar.adapters.atlassian import AtlassianAdapter, addon_to_product, parse_reviews
        a = load("atlassian_addons.json")["_embedded"]["addons"][0]
        p = addon_to_product(a, paid=True)
        self.assertEqual(p.user_count, a["_embedded"]["distribution"]["totalInstalls"])
        self.assertTrue(p.url.startswith("https://marketplace.atlassian.com/apps/"))
        rows = parse_reviews(load("atlassian_reviews.json"), p, "https://r", TS, 365)
        self.assertTrue(any(r.type == "review" for r in rows))
        self.assertNotIn("/users/", json.dumps([r.__dict__ for r in rows], default=str))
        cfg = config(**{"scan.atlassian_pages": 1, "scan.atlassian_reviews_limit": 1})
        http = FixtureClient({"/reviews": "atlassian_reviews.json", "/rest/2/addons": "atlassian_addons.json"}, FIXTURES)
        recs = list(AtlassianAdapter().collect(ScanContext(conn=memdb(), http=http, config=cfg)))
        self.assertTrue(any(isinstance(r, Evidence) and r.metric_key == "requires_payment" for r in recs))


class AutocompleteResilienceTests(unittest.TestCase):
    def test_one_bad_query_does_not_stop_the_source_and_taglines_are_stripped(self):
        from orphan_radar.adapters.autocomplete import AutocompleteAdapter
        from orphan_radar.matching import match_all
        from orphan_radar.models import upsert_product
        from orphan_radar.net import FetchError

        conn = memdb()
        upsert_product(conn, Product(source="wordpress", source_id="a", name="Broken Thing – A Very Long Tagline", url="https://x/a", user_count=9000))
        upsert_product(conn, Product(source="wordpress", source_id="b", name="Working Widget", url="https://x/b", user_count=5000))
        match_all(conn)

        class Flaky(FixtureClient):
            def get(self, url, **kw):
                self.requested.append(url)
                if "broken+thing+alternative" in url:
                    raise FetchError("HTTP 400")
                return (FIXTURES / "google_suggest.json").read_bytes(), TS

        http = Flaky({}, FIXTURES)
        recs = list(AutocompleteAdapter().collect(ScanContext(conn=conn, http=http, config=config(**{"scan.autocomplete_top_products": 5}))))
        self.assertFalse(any("tagline" in u for u in http.requested))   # queries use the name, not the tagline
        self.assertEqual(len(recs), 5)                                   # 6 queries, 1 failed, the rest still ran
