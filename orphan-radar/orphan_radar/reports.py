"""Weekly digest, CSV/markdown export and the outcome ledger."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import dumps, loads, now_iso
from .pipeline import latest_scores

COMPONENTS = ["demand", "supply_failure", "pain_specificity", "channel", "potential_profit", "ease_of_development", "timing"]


def _components(row) -> dict[str, float]:
    data = loads(row["components_json"], {})
    return {c["name"]: c["points"] for c in data.get("components", [])}


def _signals(row) -> list[str]:
    data = loads(row["components_json"], {})
    return [k for k, s in (data.get("signals") or {}).items() if s.get("present")]


def export_csv(conn: sqlite3.Connection, path: Path) -> int:
    rows = latest_scores(conn)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "entity_id", "name", "score", *COMPONENTS, "signals", "sources", "category", "state", "url", "scored_at"])
        for n, r in enumerate(rows, 1):
            comp = _components(r)
            w.writerow([n, r["id"], r["name"], r["total"], *[comp.get(c, 0) for c in COMPONENTS], " ".join(_signals(r)),
                        r["sources"], r["category"], r["state"], r["url"], r["computed_at"]])
    return len(rows)


def export_markdown(conn: sqlite3.Connection, out_dir: Path, top: int = 25) -> list[Path]:
    """Ranked table plus one file per brief."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = latest_scores(conn)
    written = []
    lines = ["# Orphan Radar: ranked opportunities", "", f"Exported {now_iso()}", "",
             "| # | Product | Score | Signals | Sources | Brief |", "|---|---|---|---|---|---|"]
    for n, r in enumerate(rows[:top], 1):
        has_brief = conn.execute("SELECT 1 FROM briefs WHERE entity_id=?", (r["id"],)).fetchone()
        has_prompt = conn.execute("SELECT 1 FROM build_prompts WHERE entity_id=?", (r["id"],)).fetchone()
        brief_link = (f"[brief](briefs/{r['id']}.md)" if has_brief else "") + (f" · [build prompt](build-prompts/{r['id']}.md)" if has_prompt else "")
        lines.append(f"| {n} | [{r['name']}]({r['url']}) | {r['total']} | {', '.join(_signals(r))} | {r['sources']} | {brief_link} |")
    excl = conn.execute("""SELECT e.id, e.name, group_concat(x.reason, ' / ') AS reasons FROM exclusions x JOIN entities e ON e.id=x.entity_id
                           WHERE x.rule != 'too_small' GROUP BY e.id ORDER BY e.name""").fetchall()
    lines += ["", "## Excluded by hard filters", "", "| Product | Reason |", "|---|---|"]
    lines += [f"| {r['name']} | {r['reasons']} |" for r in excl]
    small = conn.execute("SELECT COUNT(DISTINCT entity_id) FROM exclusions WHERE rule='too_small'").fetchone()[0]
    lines += ["", f"Plus {small} products below the minimum audience (not listed)."]
    p = out_dir / "opportunities.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    written.append(p)
    bdir = out_dir / "briefs"
    bdir.mkdir(exist_ok=True)
    for b in conn.execute("SELECT entity_id, markdown FROM briefs WHERE entity_id NOT IN (SELECT entity_id FROM exclusions)"):
        bp = bdir / f"{b['entity_id']}.md"
        bp.write_text(b["markdown"], encoding="utf-8")
        written.append(bp)
    pdir = out_dir / "build-prompts"
    pdir.mkdir(exist_ok=True)
    for b in conn.execute("SELECT entity_id, markdown FROM build_prompts WHERE entity_id NOT IN (SELECT entity_id FROM exclusions)"):
        pp = pdir / f"{b['entity_id']}.md"
        pp.write_text(b["markdown"], encoding="utf-8")
        written.append(pp)
    return written


def digest(conn: sqlite3.Connection, threshold: float, days: int = 7) -> str:
    """New opportunities and score changes over the last `days` days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    rows = latest_scores(conn)
    new, changed = [], []
    for r in rows:
        first = conn.execute("SELECT MIN(computed_at) AS t FROM scores WHERE entity_id=? AND scan_id IS NOT NULL", (r["id"],)).fetchone()["t"]
        before = conn.execute("""SELECT total FROM scores WHERE entity_id=? AND scan_id IS NOT NULL AND computed_at < ?
                                 ORDER BY id DESC LIMIT 1""", (r["id"], since)).fetchone()
        if r["total"] >= threshold and (first is None or first >= since) and before is None:
            new.append(r)
        elif before is not None and abs(r["total"] - before["total"]) >= 3:
            changed.append((r, before["total"]))
    lines = [f"# Orphan Radar weekly digest, {now_iso()[:10]}", "",
             f"Window: the last {days} days. Threshold for new opportunities: {threshold}.", ""]
    lines += ["## New opportunities", ""]
    if new:
        lines += ["| Product | Score | Signals | Sources |", "|---|---|---|---|"]
        lines += [f"| [{r['name']}]({r['url']}) | {r['total']} | {', '.join(_signals(r))} | {r['sources']} |" for r in new]
    else:
        lines.append("None above the threshold this week.")
    lines += ["", "## Score changes (3 points or more)", ""]
    if changed:
        lines += ["| Product | Before | Now | Change |", "|---|---|---|---|"]
        for r, b in sorted(changed, key=lambda x: -(x[0]["total"] - x[1])):
            lines.append(f"| [{r['name']}]({r['url']}) | {b} | {r['total']} | {r['total'] - b:+.1f} |")
    else:
        lines.append("No score moved by 3 points or more.")
    lines += ["", "## Current top ten", "", "| # | Product | Score | State |", "|---|---|---|---|"]
    lines += [f"| {n} | [{r['name']}]({r['url']}) | {r['total']} | {r['state']} |" for n, r in enumerate(rows[:10], 1)]
    return "\n".join(lines) + "\n"


# --- outcome ledger -------------------------------------------------------------

def ledger_add(conn: sqlite3.Connection, entity_id: int | None, name: str, url: str | None, launched_at: str | None, notes: str | None) -> int:
    snap = {}
    if entity_id:
        row = conn.execute("SELECT total, components_json FROM scores WHERE entity_id=? ORDER BY id DESC LIMIT 1", (entity_id,)).fetchone()
        if row:
            snap = {"total": row["total"], "components": _components(row), "signals": _signals(row)}
    cur = conn.execute("""INSERT INTO ledger (entity_id, launched_name, launched_url, launched_at, notes, snapshot_json, created_at)
                          VALUES (?,?,?,?,?,?,?)""", (entity_id, name, url, launched_at or now_iso()[:10], notes, dumps(snap), now_iso()))
    if entity_id:
        conn.execute("INSERT OR REPLACE INTO states (entity_id, state, note, updated_at) VALUES (?, 'building', ?, ?)",
                     (entity_id, f"launched as {name}", now_iso()))
    conn.commit()
    return cur.lastrowid


def ledger_update(conn: sqlite3.Connection, ledger_id: int, **fields) -> None:
    allowed = {"visitors_30d", "trials_30d", "paying_30d", "revenue_30d", "notes", "launched_url"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if sets:
        conn.execute(f"UPDATE ledger SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), ledger_id))
        conn.commit()


def ledger_insights(conn: sqlite3.Connection) -> dict:
    """Which signals and score components the winners (any paying customer or revenue at 30 days) had in common."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM ledger ORDER BY launched_at DESC")]
    for r in rows:
        r["snapshot"] = loads(r["snapshot_json"], {})
        r["winner"] = bool((r["paying_30d"] or 0) > 0 or (r["revenue_30d"] or 0) > 0)
        r["measured"] = any(r[k] is not None for k in ("visitors_30d", "trials_30d", "paying_30d", "revenue_30d"))
    measured = [r for r in rows if r["measured"]]
    winners = [r for r in measured if r["winner"]]
    losers = [r for r in measured if not r["winner"]]

    def avg(group, comp):
        vals = [g["snapshot"].get("components", {}).get(comp) for g in group if g["snapshot"].get("components")]
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def share(group, sig):
        snaps = [g for g in group if g["snapshot"]]
        return round(100 * sum(1 for g in snaps if sig in g["snapshot"].get("signals", [])) / len(snaps)) if snaps else None

    return {
        "rows": rows, "n_measured": len(measured), "n_winners": len(winners),
        "components": [{"name": c, "winners": avg(winners, c), "others": avg(losers, c)} for c in COMPONENTS],
        "signals": [{"name": s, "winners_pct": share(winners, s), "others_pct": share(losers, s)} for s in ("abandonment", "displacement", "pain")],
    }
