"""Scoring, signals, hard filters, matching and clustering on synthetic stored evidence."""
import unittest

from orphan_radar.cluster import classify, rule_clusters
from orphan_radar.detect import detect, wp_releases_behind
from orphan_radar.facts import EntityView
from orphan_radar.filters import hard_filters
from orphan_radar.matching import match_all
from orphan_radar.models import Evidence, Product, insert_evidence, upsert_product
from orphan_radar.pipeline import analyze, latest_scores
from orphan_radar.score import Component, score_entity

from .helpers import COMPLAINTS, TS, add_plugin, config, days_ago, memdb


def scored(conn, cfg=None):
    cfg = cfg or config()
    analyze(cfg, conn, scan_id=1, use_llm=False)
    return {r["name"]: r for r in latest_scores(conn, include_excluded=True)}


def comps(row):
    import json
    return {c["name"]: c for c in json.loads(row["components_json"])["components"]}


class ScoreTests(unittest.TestCase):
    def test_abandoned_beats_maintained(self):
        conn = memdb()
        add_plugin(conn, "old-gallery-pro", "Old Gallery Pro", complaints=COMPLAINTS)
        add_plugin(conn, "fresh-gallery", "Fresh Gallery Plus", updated_days=10, tested="7.1", opened=12, resolved=12, rating=4.8, complaints=[])
        rows = scored(conn)
        old, fresh = rows["Old Gallery Pro"], rows["Fresh Gallery Plus"]
        self.assertGreater(old["total"], fresh["total"])
        self.assertGreater(comps(old)["supply_failure"]["points"], comps(fresh)["supply_failure"]["points"])
        self.assertEqual(comps(fresh)["pain_specificity"]["points"], 0)

    def test_total_is_sum_of_components_and_bounded(self):
        conn = memdb()
        add_plugin(conn, complaints=COMPLAINTS)
        row = next(iter(scored(conn).values()))
        c = comps(row)
        self.assertAlmostEqual(row["total"], round(sum(x["points"] for x in c.values()), 1), places=1)
        self.assertLessEqual(row["total"], 100)
        for x in c.values():
            self.assertLessEqual(x["points"], x["max"])
            self.assertGreaterEqual(x["points"], 0)
            self.assertTrue(x["parts"], "every component explains itself")

    def test_weights_come_from_config(self):
        conn = memdb()
        add_plugin(conn, complaints=COMPLAINTS)
        cfg = config(**{"weights.demand": 50, "weights.supply_failure": 0})
        c = comps(next(iter(scored(conn, cfg).values())))
        self.assertEqual(c["demand"]["max"], 50)
        self.assertEqual(c["supply_failure"]["points"], 0)

    def test_weights_must_sum_to_100(self):
        import tempfile
        from pathlib import Path
        from orphan_radar.config import ROOT, load_config
        text = (ROOT / "config.toml").read_text().replace("demand = 20", "demand = 30", 1)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "c.toml"
            p.write_text(text)
            with self.assertRaises(ValueError):
                load_config(p)

    def test_signals(self):
        conn = memdb()
        add_plugin(conn, complaints=COMPLAINTS)
        match_all(conn)
        v = EntityView.load(conn, conn.execute("SELECT id FROM entities").fetchone()[0])
        s = detect(v)
        self.assertTrue(s["abandonment"].present)
        self.assertTrue(s["pain"].present)
        self.assertTrue(all(f.evidence_ids for sig in s.values() for r in sig.reasons for f in r.facts))

    def test_wp_release_arithmetic(self):
        self.assertEqual(wp_releases_behind("6.8", "7.1.4"), 3)
        self.assertEqual(wp_releases_behind("7.1", "7.1.4"), 0)
        self.assertEqual(wp_releases_behind("6.2", "6.4"), 2)
        self.assertIsNone(wp_releases_behind(None, "6.4"))

    def test_replacement_search_adds_demand_and_channel(self):
        conn = memdb()
        add_plugin(conn, complaints=COMPLAINTS)
        before = comps(next(iter(scored(conn).values())))
        eid = conn.execute("SELECT id FROM entities").fetchone()[0]
        insert_evidence(conn, Evidence(source="autocomplete", type="search_suggestion", url="https://suggestqueries.google.com/x",
                                       date_retrieved=TS, metric_key="suggestions_alternative", metric_value=3, text="Suggested searches: a; b; c",
                                       subject="Old Gallery Pro", extra={"entity_id": eid, "suggestions": ["old gallery pro alternative"]}))
        conn.commit()
        after = comps(next(iter(scored(conn).values())))
        self.assertGreater(after["demand"]["points"], before["demand"]["points"])
        self.assertGreater(after["channel"]["points"], before["channel"]["points"])

    def test_penalty_only_subtracts(self):
        c = Component("timing", 10)
        c.add("event", 7, 7)
        c.add("already switched", -3, 0)
        c.finish()
        self.assertAlmostEqual(c.points, round(4 / 7 * 10, 1))


class FilterTests(unittest.TestCase):
    def test_children_and_small_audiences_are_excluded_with_reasons(self):
        conn = memdb()
        add_plugin(conn, "kids-quiz", "Kids Quiz Maker", description="Quizzes for kids in school classrooms.", complaints=COMPLAINTS)
        add_plugin(conn, "tiny-thing", "Tiny Thing Widget", users=400)
        add_plugin(conn, "normal-tool", "Normal Gallery Tool", complaints=COMPLAINTS)
        scored(conn)
        reasons = {r["name"]: r["reason"] for r in conn.execute("SELECT e.name, x.reason FROM exclusions x JOIN entities e ON e.id=x.entity_id")}
        self.assertIn("children", reasons["Kids Quiz Maker"])
        self.assertIn("400", reasons["Tiny Thing Widget"])
        self.assertNotIn("Normal Gallery Tool", reasons)
        ranked = [r["name"] for r in latest_scores(conn)]
        self.assertEqual(ranked, ["Normal Gallery Tool"])

    def test_min_users_is_configurable(self):
        conn = memdb()
        add_plugin(conn, "tiny-thing", "Tiny Thing Widget", users=400)
        match_all(conn)
        v = EntityView.load(conn, conn.execute("SELECT id FROM entities").fetchone()[0])
        self.assertTrue(any(r == "too_small" for r, _, _ in hard_filters(v, config())))
        self.assertFalse(any(r == "too_small" for r, _, _ in hard_filters(v, config(**{"thresholds.min_users": 100}))))

    def test_successor_named_by_maintainers(self):
        conn = memdb()
        add_plugin(conn, "legacy-forms", "Legacy Forms", description="Deprecated: this plugin is no longer maintained, use Better Forms instead.")
        scored(conn)
        rules = [r[0] for r in conn.execute("SELECT rule FROM exclusions")]
        self.assertIn("replacement_dominates", rules)


class MatchingTests(unittest.TestCase):
    def test_same_product_across_sources_merges_generic_single_words_do_not(self):
        conn = memdb()
        for src, sid, name in [("wordpress", "dark-reader", "Dark Reader"), ("firefox", "darkreader", "Dark Reader"),
                               ("wordpress", "gallery", "Gallery"), ("firefox", "gallery", "Gallery")]:
            upsert_product(conn, Product(source=src, source_id=sid, name=name, url=f"https://x/{src}/{sid}", user_count=5000))
        match_all(conn)
        groups = conn.execute("SELECT name, COUNT(*) FROM products GROUP BY entity_id ORDER BY name").fetchall()
        self.assertEqual([tuple(g) for g in groups], [("Dark Reader", 2), ("Gallery", 1), ("Gallery", 1)])

    def test_loose_evidence_attaches_only_on_a_clear_mention(self):
        conn = memdb()
        upsert_product(conn, Product(source="firefox", source_id="ub", name="uBlock Origin", url="https://x/ub", user_count=5000))
        for i, text in enumerate(["Is there an alternative to uBlock Origin after MV3?", "The best block origin story", "uBlock Origin vs Dark Reader"]):
            insert_evidence(conn, Evidence(source="hackernews", type="discussion", url=f"https://news.ycombinator.com/item?id={i}", date_retrieved=TS, text=text))
        match_all(conn)
        attached = [r[0] for r in conn.execute("SELECT text FROM evidence WHERE entity_id IS NOT NULL")]
        self.assertIn("Is there an alternative to uBlock Origin after MV3?", attached)
        self.assertNotIn("The best block origin story", attached)


class ClusterTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("Stopped working after the WordPress 6.5 update, fatal error"), "compat")
        self.assertEqual(classify("Now demanding a subscription or wait 2 hours"), "paywall")
        self.assertEqual(classify("Has stopped working on many websites"), "not_working")
        self.assertIsNone(classify("ok"))

    def test_rule_clusters_keep_links(self):
        rows = [{"id": i, "text": t} for i, (t, _) in enumerate(COMPLAINTS, 1)]
        clusters = rule_clusters(rows)
        self.assertEqual(sorted(i for c in clusters for i in c.evidence_ids), list(range(1, len(COMPLAINTS) + 1)))
        self.assertEqual(clusters[0].key, "compat")


if __name__ == "__main__":
    unittest.main()


class NativeFeatureTests(unittest.TestCase):
    def test_two_users_saying_the_platform_does_it_natively_exclude_one_does_not(self):
        conn = memdb()
        add_plugin(conn, "shot-a", "Shot Alpha", complaints=[("Removed it, full page capture can be done natively in Firefox now", 1)] + COMPLAINTS)
        add_plugin(conn, "shot-b", "Shot Beta", complaints=[("Useless, can be done natively in firefox", 1), ("You can do it in Firefox itself", 2)] + COMPLAINTS)
        add_plugin(conn, "shot-c", "Shot Gamma", complaints=[("This should be built into WordPress", 2)] + COMPLAINTS)
        scored(conn)
        excluded = {r[0] for r in conn.execute("SELECT e.name FROM exclusions x JOIN entities e ON e.id=x.entity_id WHERE x.rule='platform_native'")}
        self.assertEqual(excluded, {"Shot Beta"})

    def test_marketing_copy_is_not_a_native_announcement(self):
        conn = memdb()
        add_plugin(conn, "blocks-ai", "Blocks AI Builder", description="Build a full website with AI, then edit every block natively in Gutenberg.")
        add_plugin(conn, "old-tabs", "Old Tabs Thing", description="This feature is now built-in to WordPress, so this plugin is no longer needed.")
        scored(conn)
        excluded = {r[0] for r in conn.execute("SELECT e.name FROM exclusions x JOIN entities e ON e.id=x.entity_id WHERE x.rule='platform_native'")}
        self.assertEqual(excluded, {"Old Tabs Thing"})
