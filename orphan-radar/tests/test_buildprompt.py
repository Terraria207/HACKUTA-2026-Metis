"""The system-build prompt: complete, grounded, and refused when it cannot be traced."""
import re
import unittest

from orphan_radar.brief import audit_brief
from orphan_radar.buildprompt import REQUIREMENTS, generate_build_prompt, write_build_prompts
from orphan_radar.cluster import load_clusters
from orphan_radar.pipeline import analyze, latest_scores

from .helpers import COMPLAINTS, add_plugin, config, memdb


class BuildPromptTests(unittest.TestCase):
    def setUp(self):
        self.conn = memdb()
        add_plugin(self.conn, complaints=COMPLAINTS)
        self.cfg = config()
        analyze(self.cfg, self.conn, scan_id=1, use_llm=False)
        self.eid = latest_scores(self.conn)[0]["id"]
        self.md = generate_build_prompt(self.conn, self.eid, self.cfg)

    def test_sections_in_order(self):
        heads = re.findall(r"^## (\d+)\. ", self.md, re.M)
        self.assertEqual(heads, [str(i) for i in range(1, 13)])
        for needle in ("Requirement A: Parity", "Acceptance:", "one-click import", "Milestone one", "Unknowns to resolve", "WordPress plugin in PHP"):
            self.assertIn(needle, self.md)

    def test_every_specific_cluster_becomes_a_requirement(self):
        specific = [c for c in load_clusters(self.conn, self.eid) if c.key != "other"]
        self.assertTrue(specific)
        for c in specific[:8]:
            self.assertIn(REQUIREMENTS[c.key][0], self.md, c.key)
        self.assertEqual(len(re.findall(r"^### Requirement [A-Z]:", self.md, re.M)), 1 + min(len(specific), 8))

    def test_passes_audit_and_is_stored(self):
        self.assertEqual(audit_brief(self.conn, self.md, ["Old Gallery Pro"]), [])
        row = self.conn.execute("SELECT markdown FROM build_prompts WHERE entity_id=?", (self.eid,)).fetchone()
        self.assertEqual(row["markdown"], self.md)

    def test_templates_contain_no_uncited_digits(self):
        # The templates themselves must be digit-free; anything numeric must come from evidence.
        from orphan_radar.buildprompt import PLATFORM, QUALITY
        for text in [t for v in REQUIREMENTS.values() for t in v] + [t for v in PLATFORM.values() for t in v] + QUALITY:
            self.assertFalse(re.search(r"\d", text), text)

    def test_unknowns_are_stated_not_estimated(self):
        self.assertIn("Export format of the incumbent: unknown", self.md)
        self.assertIn("Rivals' prices: unknown", self.md)

    def test_refuses_untraceable(self):
        self.conn.execute("UPDATE evidence SET date_retrieved='' WHERE entity_id=?", (self.eid,))
        with self.assertRaises(ValueError):
            generate_build_prompt(self.conn, self.eid, self.cfg)

    def test_write_all_above_threshold(self):
        done, failed = write_build_prompts(self.conn, config(**{"thresholds.brief_min_score": 0}))
        self.assertEqual((done, failed), ([self.eid], {}))


class SharedHelperTests(unittest.TestCase):
    def test_top_quotes_prefers_most_reacted_issues_then_recent(self):
        from orphan_radar.brief import top_quotes
        rows = [{"id": 1, "type": "issue", "score": 1, "text": "a", "date_posted": "2026-01-01"},
                {"id": 2, "type": "issue", "score": 10, "text": "b", "date_posted": "2025-01-01"},
                {"id": 3, "type": "review", "score": 1, "text": "c", "date_posted": "2026-06-01"},
                {"id": 4, "type": "review", "score": 2, "text": "d", "date_posted": "2026-05-01"}]
        self.assertEqual([r["id"] for r in top_quotes(rows)], [2, 1, 3])

    def test_write_documents_with_empty_list_writes_nothing(self):
        from orphan_radar.brief import write_documents, generate_brief
        conn = memdb()
        add_plugin(conn, complaints=COMPLAINTS)
        analyze(config(), conn, scan_id=1, use_llm=False)
        self.assertEqual(write_documents(conn, config(), [generate_brief], only=[]), ([], {}))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0], 0)

    def test_unknown_id_is_a_clean_error(self):
        from orphan_radar.brief import load_context
        with self.assertRaises(ValueError):
            load_context(memdb(), 999, config())
