"""orphan-radar command line."""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import llm
from .adapters import ADAPTERS, SKIPPED_SOURCES
from .brief import audit_brief, generate_brief, write_briefs, write_documents
from .buildprompt import generate_build_prompt, write_build_prompts
from .config import ROOT, load_config
from .db import connect, loads, now_iso
from .pipeline import analyze, latest_scores, scan
from .reports import digest, export_csv, export_markdown, ledger_add, ledger_insights, ledger_update


def _table(rows: list[list], headers: list[str]) -> str:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    out = [line, "  ".join("-" * w for w in widths)]
    out += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)) for r in rows]
    return "\n".join(out)


def _top(conn, n: int) -> str:
    rows = []
    for i, r in enumerate(latest_scores(conn)[:n], 1):
        comp = {c["name"]: c["points"] for c in loads(r["components_json"], {}).get("components", [])}
        sig = [k[0].upper() for k, s in loads(r["components_json"], {}).get("signals", {}).items() if s["present"]]
        rows.append([i, r["id"], r["name"][:38], r["total"], comp.get("demand"), comp.get("supply_failure"), comp.get("pain_specificity"),
                     comp.get("channel"), comp.get("potential_profit"), comp.get("ease_of_development"), comp.get("timing"), "".join(sig) or "-", r["sources"], r["state"]])
    return _table(rows, ["#", "id", "product", "score", "dem", "sup", "pain", "chan", "profit", "ease", "time", "sig", "sources", "state"]) + \
        "\n(sig: A=abandonment D=displacement P=pain)"


def cmd_init(args, config):
    connect(config.db_path).close()
    env_file = ROOT / ".env"
    if not env_file.exists():
        shutil.copy(ROOT / ".env.example", env_file)
        print(f"created {env_file} from .env.example")
    print(f"database: {config.db_path}")


def cmd_sources(args, config):
    rows = []
    for a in ADAPTERS:
        ok, why = a().available()
        rows.append([a.name, a.title, "phase " + str(a.phase), "ready" if ok else "off: " + why])
    print(_table(rows, ["source", "title", "runs", "status"]))
    print("\nReviewed and skipped:")
    for k, v in SKIPPED_SOURCES.items():
        print(f"- {k}: {v}")
    ok, why = llm.available()
    print(f"\nLanguage model: {'on (' + why + ')' if ok else 'off: ' + why}")


def cmd_scan(args, config):
    conn = connect(config.db_path)
    stats = scan(config, sources=args.source or None, offline=args.offline, strict_robots=args.strict_robots,
                 use_llm=False if args.no_llm else None, conn=conn)
    print("\nScan finished.")
    for name, s in stats["ran"].items():
        print(f"  {name:14} products={s['products']:<5} new evidence={s['evidence_new']:<5} refreshed={s['evidence_refreshed']:<5} {s['seconds']}s")
    for name, why in stats["skipped"].items():
        print(f"  {name:14} skipped: {why}")
    for name, why in stats["failed"].items():
        print(f"  {name:14} FAILED: {why}")
    print(f"  entities scored={stats['entities_scored']} excluded={stats['entities_excluded']} "
          f"http requests={stats['http_requests']} cache hits={stats['cache_hits']} llm={'on' if stats['llm'] else 'off'}")
    if not args.no_briefs:
        done, failed = write_documents(conn, config, [generate_brief, generate_build_prompt])
        print(f"  briefs and build prompts written: {len(done)}" + (f", failed: {failed}" if failed else ""))
        out = config.data_dir / "digests" / f"digest-{now_iso()[:10]}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(digest(conn, float(config.threshold("brief_min_score", 45))), encoding="utf-8")
        print(f"  digest: {out}")
    print()
    print(_top(conn, 10))
    return 0 if stats["ran"] else 1


def cmd_analyze(args, config):
    conn = connect(config.db_path)
    r = analyze(config, conn, scan_id=None, use_llm=False if args.no_llm else None)
    print(r)
    print(_top(conn, 10))


def cmd_list(args, config):
    conn = connect(config.db_path)
    if args.excluded:
        rows = conn.execute("""SELECT e.id, e.name, x.rule, x.reason FROM exclusions x JOIN entities e ON e.id=x.entity_id
                               WHERE (? OR x.rule != 'too_small') ORDER BY e.name""", (args.all,)).fetchall()
        print(_table([[r["id"], r["name"][:40], r["rule"], r["reason"][:90]] for r in rows], ["id", "product", "rule", "reason"]))
        return
    print(_top(conn, args.top))


def cmd_show(args, config):
    conn = connect(config.db_path)
    e = conn.execute("SELECT * FROM entities WHERE id=?", (args.id,)).fetchone()
    if not e:
        print("no such entity"); return 1
    row = conn.execute("SELECT total, components_json FROM scores WHERE entity_id=? ORDER BY id DESC LIMIT 1", (args.id,)).fetchone()
    data = loads(row["components_json"], {}) if row else {}
    print(f"{e['name']}  score {data.get('total')}")
    for p in conn.execute("SELECT source, url, user_count, last_updated, rating FROM products WHERE entity_id=?", (args.id,)):
        print(f"  {p['source']:10} {p['url']}  users={p['user_count']} updated={(p['last_updated'] or '')[:10]} rating={p['rating']}")
    for c in data.get("components", []):
        print(f"\n  {c['name']}: {c['points']} / {c['max']}")
        for part in c["parts"]:
            print(f"    {part['got']:>6} / {part['max']:<4} {part['label'].replace('cfg:', '')}  evidence={part['evidence_ids'][:8]}")
    for x in conn.execute("SELECT rule, reason FROM exclusions WHERE entity_id=?", (args.id,)):
        print(f"\n  EXCLUDED ({x['rule']}): {x['reason']}")


def _need_id(args):
    if args.id is None and not args.all:
        raise SystemExit("give an opportunity id, or --all")


def cmd_brief(args, config):
    _need_id(args)
    conn = connect(config.db_path)
    if args.all:
        done, failed = write_briefs(conn, config)
        print(f"briefs written: {len(done)}; failed: {failed or 'none'}")
        return 1 if failed else 0
    md = generate_brief(conn, args.id, config)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"written {args.out}")
    else:
        print(md)


def cmd_buildprompt(args, config):
    _need_id(args)
    conn = connect(config.db_path)
    if args.all:
        done, failed = write_build_prompts(conn, config)
        print(f"build prompts written: {len(done)}; failed: {failed or 'none'}")
        return 1 if failed else 0
    md = generate_build_prompt(conn, args.id, config)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"written {args.out}")
    else:
        print(md)


def cmd_verify(args, config):
    conn = connect(config.db_path)
    bad = 0
    for b in conn.execute("SELECT b.entity_id, b.markdown, e.name FROM briefs b JOIN entities e ON e.id=b.entity_id"):
        names = [r["name"] for r in conn.execute("SELECT name FROM products WHERE entity_id=?", (b["entity_id"],))] + [b["name"]]
        problems = audit_brief(conn, b["markdown"], names)
        if problems:
            bad += 1
            print(f"#{b['entity_id']} {b['name']}: {problems[:3]}")
    for b in conn.execute("SELECT b.entity_id, b.markdown, e.name FROM build_prompts b JOIN entities e ON e.id=b.entity_id"):
        names = [r["name"] for r in conn.execute("SELECT name FROM products WHERE entity_id=?", (b["entity_id"],))] + [b["name"]]
        problems = audit_brief(conn, b["markdown"], names)
        if problems:
            bad += 1
            print(f"build prompt #{b['entity_id']} {b['name']}: {problems[:3]}")
    print("all briefs and build prompts trace every figure to evidence" if not bad else f"{bad} document(s) failed")
    return 1 if bad else 0


def cmd_export(args, config):
    conn = connect(config.db_path)
    out = Path(args.out or config.data_dir / "export")
    out.mkdir(parents=True, exist_ok=True)
    if args.format in ("csv", "both"):
        n = export_csv(conn, out / "opportunities.csv")
        print(f"csv: {out / 'opportunities.csv'} ({n} rows)")
    if args.format in ("md", "both"):
        files = export_markdown(conn, out)
        print(f"markdown: {len(files)} files in {out}")


def cmd_digest(args, config):
    conn = connect(config.db_path)
    text = digest(conn, float(config.threshold("brief_min_score", 45)), args.days)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8"); print(f"written {args.out}")
    else:
        print(text)


def cmd_state(args, config):
    conn = connect(config.db_path)
    conn.execute("INSERT OR REPLACE INTO states (entity_id, state, note, updated_at) VALUES (?,?,?,?)", (args.id, args.state, args.note, now_iso()))
    conn.commit(); print(f"#{args.id} -> {args.state}")


def cmd_exclude(args, config):
    conn = connect(config.db_path)
    conn.execute("INSERT OR REPLACE INTO exclusions (entity_id, rule, reason, evidence_id, computed_at) VALUES (?, 'manual', ?, NULL, ?)",
                 (args.id, args.reason, now_iso()))
    conn.commit(); print(f"#{args.id} excluded: {args.reason}")


def cmd_ledger(args, config):
    conn = connect(config.db_path)
    if args.ledger_cmd == "add":
        lid = ledger_add(conn, args.entity, args.name, args.url, args.launched, args.notes)
        print(f"ledger entry {lid}")
    elif args.ledger_cmd == "update":
        ledger_update(conn, args.ledger_id, visitors_30d=args.visitors, trials_30d=args.trials, paying_30d=args.paying,
                      revenue_30d=args.revenue, notes=args.notes)
        print("updated")
    else:
        ins = ledger_insights(conn)
        print(_table([[r["id"], r["entity_id"], r["launched_name"], r["launched_at"], r["visitors_30d"], r["trials_30d"], r["paying_30d"],
                       r["revenue_30d"], "yes" if r["winner"] else ""] for r in ins["rows"]],
                     ["id", "entity", "launched", "date", "visitors", "trials", "paying", "revenue", "winner"]))
        print(f"\nmeasured: {ins['n_measured']}, winners: {ins['n_winners']}")
        print(_table([[c["name"], c["winners"], c["others"]] for c in ins["components"]], ["component (avg points)", "winners", "others"]))
        print(_table([[s["name"], s["winners_pct"], s["others_pct"]] for s in ins["signals"]], ["signal (% present)", "winners", "others"]))


def cmd_serve(args, config):
    from .web.app import serve
    serve(config, args.host, args.port)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="orphan-radar", description="Find software whose users are stranded and looking for a replacement.")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create the database and .env").set_defaults(fn=cmd_init)
    sub.add_parser("sources", help="list adapters, their status and skipped sources").set_defaults(fn=cmd_sources)
    s = sub.add_parser("scan", help="collect from all (or some) sources, then detect, score and brief")
    s.add_argument("--source", action="append", help="run only this source (repeatable)")
    s.add_argument("--offline", action="store_true", help="use cached responses only")
    s.add_argument("--strict-robots", action="store_true", help="apply robots.txt to documented APIs too (skips api.wordpress.org)")
    s.add_argument("--no-llm", action="store_true", help="never call the language model")
    s.add_argument("--no-briefs", action="store_true")
    s.set_defaults(fn=cmd_scan)
    s = sub.add_parser("analyze", help="recompute signals and scores from stored evidence (no network)")
    s.add_argument("--no-llm", action="store_true"); s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("list", help="ranked opportunities")
    s.add_argument("--top", type=int, default=20); s.add_argument("--excluded", action="store_true"); s.add_argument("--all", action="store_true")
    s.set_defaults(fn=cmd_list)
    s = sub.add_parser("show", help="score breakdown for one opportunity"); s.add_argument("id", type=int); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("brief", help="generate a brief")
    s.add_argument("id", type=int, nargs="?"); s.add_argument("--all", action="store_true"); s.add_argument("--out")
    s.set_defaults(fn=cmd_brief)
    s = sub.add_parser("buildprompt", help="generate the full system-build specification for an AI builder")
    s.add_argument("id", type=int, nargs="?"); s.add_argument("--all", action="store_true"); s.add_argument("--out")
    s.set_defaults(fn=cmd_buildprompt)
    sub.add_parser("verify", help="audit every stored brief and build prompt: each figure must cite evidence").set_defaults(fn=cmd_verify)
    s = sub.add_parser("export", help="export markdown and/or CSV")
    s.add_argument("--format", choices=["md", "csv", "both"], default="both"); s.add_argument("--out"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("digest", help="weekly digest of new opportunities and score changes")
    s.add_argument("--days", type=int, default=7); s.add_argument("--out"); s.set_defaults(fn=cmd_digest)
    s = sub.add_parser("state", help="mark an opportunity")
    s.add_argument("id", type=int); s.add_argument("state", choices=["new", "watching", "building", "dismissed"]); s.add_argument("--note")
    s.set_defaults(fn=cmd_state)
    s = sub.add_parser("exclude", help="exclude an opportunity by hand"); s.add_argument("id", type=int); s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_exclude)
    s = sub.add_parser("ledger", help="record launches and 30-day results")
    ls = s.add_subparsers(dest="ledger_cmd")
    a = ls.add_parser("add"); a.add_argument("--entity", type=int); a.add_argument("--name", required=True); a.add_argument("--url")
    a.add_argument("--launched", help="YYYY-MM-DD"); a.add_argument("--notes")
    u = ls.add_parser("update"); u.add_argument("ledger_id", type=int)
    for f in ("visitors", "trials", "paying"):
        u.add_argument(f"--{f}", type=int)
    u.add_argument("--revenue", type=float); u.add_argument("--notes")
    ls.add_parser("list")
    s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("serve", help="local web dashboard")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8765); s.set_defaults(fn=cmd_serve)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "scan" and not args.verbose:
        logging.getLogger("orphan_radar").setLevel(logging.INFO)
    config = load_config(args.config)
    return args.fn(args, config) or 0


if __name__ == "__main__":
    sys.exit(main())
