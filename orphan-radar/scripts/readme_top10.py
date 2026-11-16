"""Write the top ten opportunities and their full briefs into README.md (between the TOP10 markers)
and snapshot the export into report/. Run after a scan:  python3 scripts/readme_top10.py
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from orphan_radar.brief import audit_brief, generate_brief, write_documents  # noqa: E402
from orphan_radar.buildprompt import generate_build_prompt  # noqa: E402
from orphan_radar.config import load_config  # noqa: E402
from orphan_radar.db import connect, loads  # noqa: E402
from orphan_radar.pipeline import latest_scores  # noqa: E402
from orphan_radar.reports import digest, export_csv, export_markdown  # noqa: E402


def main() -> int:
    config = load_config()
    conn = connect(config.db_path)
    top = latest_scores(conn)[:10]
    done, failed = write_documents(conn, config, [generate_brief, generate_build_prompt], only=[r["id"] for r in top])
    if failed:
        print("document failures:", failed)
        return 1
    scans = conn.execute("SELECT * FROM scans WHERE status='done' ORDER BY id").fetchall()
    scan_lines = []
    for sc in scans:
        st = loads(sc["stats_json"], {})
        ran = ", ".join(f"{k} ({v['products']} products, {v['evidence_new']} new evidence)" if v["products"] else f"{k} ({v['evidence_new']} new evidence)"
                        for k, v in st.get("ran", {}).items())
        skipped = "; ".join(f"{k}: {v}" for k, v in st.get("skipped", {}).items())
        scan_lines.append(f"- Scan #{sc['id']}, {sc['started_at']} to {sc['finished_at']}: {ran}."
                          + (f" Skipped: {skipped}." if skipped else "") + (f" Failed: {', '.join(st['failed'])}." if st.get("failed") else ""))
    n_products = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    n_evidence = conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    n_entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    n_excluded = conn.execute("SELECT COUNT(DISTINCT entity_id) FROM exclusions").fetchone()[0]

    out = ["## Top ten from the latest real scan", "",
           "Live data collected on this machine with `./setup.sh` (full scan), followed by an incremental rerun of the autocomplete source "
           "after a bug fix. No language model was configured, so clusters are rule-based and briefs come from templates.", ""] + scan_lines + ["",
           f"The database holds {n_products:,} product listings, merged into {n_entities:,} products, and {n_evidence:,} evidence records. "
           f"{n_excluded:,} products were excluded by hard filters; the full list is in `report/opportunities.md` and on the dashboard's Excluded page.", "",
           "Every brief below passed the traceability audit (`orphan-radar verify`). Footnote numbers are prefixed per brief so they stay unique on this page. "
           "The same briefs are in `report/briefs/`, and the full system-build specification for each is in `report/build-prompts/`.", "",
           "| # | Product | Score | Signals | Sources | Top complaint cluster | Build prompt |", "|---|---|---|---|---|---|---|"]
    for n, r in enumerate(top, 1):
        sig = [k for k, s in loads(r["components_json"], {}).get("signals", {}).items() if s.get("present")]
        cl = conn.execute("SELECT label, size FROM clusters WHERE entity_id=? AND key!='other' ORDER BY size DESC LIMIT 1", (r["id"],)).fetchone()
        out.append(f"| {n} | [{r['name']}]({r['url']}) | {r['total']} | {', '.join(sig) or '-'} | {r['sources']} | "
                   f"{(cl['label'] + ' (' + str(cl['size']) + ')') if cl else '-'} | [spec](report/build-prompts/{r['id']}.md) |")
    out.append("")
    for n, r in enumerate(top, 1):
        md = conn.execute("SELECT markdown FROM briefs WHERE entity_id=?", (r["id"],)).fetchone()["markdown"]
        names = [x["name"] for x in conn.execute("SELECT name FROM products WHERE entity_id=?", (r["id"],))] + [r["name"]]
        assert not audit_brief(conn, md, names), r["name"]
        md = re.sub(r"\[\^(\d+)\]", lambda m: f"[^b{n}-{m.group(1)}]", md)
        md = re.sub(r"^(#{1,4}) ", lambda m: "#" * min(len(m.group(1)) + 2, 6) + " ", md, flags=re.M)
        out += [f"<details><summary><b>{n}. {r['name']}</b>, score {r['total']}</summary>", "", md.strip(), "", "</details>", ""]

    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    start, end = "<!-- TOP10:START -->", "<!-- TOP10:END -->"
    text = text[: text.index(start) + len(start)] + "\n" + "\n".join(out) + "\n" + text[text.index(end):]
    readme.write_text(text, encoding="utf-8")

    report = ROOT / "report"
    if report.exists():
        shutil.rmtree(report)
    export_markdown(conn, report, top=50)
    export_csv(conn, report / "opportunities.csv")
    (report / "digest.md").write_text(digest(conn, float(config.threshold("brief_min_score", 45))), encoding="utf-8")
    print(f"README updated with {len(top)} briefs; report/ written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
