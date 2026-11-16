"""Local web dashboard: ranked table with filters, detail pages with evidence, state buttons,
briefs, exclusions, leads, sources and the outcome ledger. Standard library only; binds to
127.0.0.1 by default and accepts POSTs only from its own origin."""
from __future__ import annotations

import html
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..adapters import ADAPTERS, SKIPPED_SOURCES
from ..brief import generate_brief
from ..buildprompt import generate_build_prompt
from ..cluster import load_clusters
from ..db import connect, loads, now_iso
from ..pipeline import latest_scores
from ..reports import COMPONENTS, digest, ledger_add, ledger_insights, ledger_update
from .markdown import render

E = lambda x: html.escape("" if x is None else str(x))  # noqa: E731

CSS = """
:root{--surface:#fcfcfb;--panel:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#8a8984;--line:#e6e5e0;--meter:#2a78d6;--track:#e9f1fc;--accent:#1c5cab}
@media (prefers-color-scheme: dark){:root{--surface:#1a1a19;--panel:#222220;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;--line:#34332f;--meter:#3987e5;--track:#2b3340;--accent:#86b6ef}}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--surface);color:var(--ink)}
header{display:flex;gap:18px;align-items:center;padding:12px 24px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:2}
header b{font-size:15px}header a{color:var(--ink2);text-decoration:none}header a:hover{color:var(--ink)}
main{padding:20px 24px;max-width:1400px;margin:0 auto}a{color:var(--accent)}
table{border-collapse:collapse;width:100%;background:var(--panel)}th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{font-weight:600;color:var(--ink2);font-size:12px;text-transform:uppercase;letter-spacing:.03em;position:sticky;top:49px;background:var(--panel)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.meter{display:inline-block;width:64px;height:8px;border-radius:4px;background:var(--track);vertical-align:middle;margin-right:6px;overflow:hidden}
.meter i{display:block;height:100%;background:var(--meter);border-radius:0 4px 4px 0}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:end;margin-bottom:14px}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2)}
select{max-width:220px}input,select,textarea,button{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--panel);color:var(--ink)}
button{cursor:pointer}button.primary{background:var(--meter);color:#fff;border-color:transparent}
.pill{display:inline-block;padding:1px 7px;border-radius:9px;border:1px solid var(--line);font-size:12px;color:var(--ink2);margin-right:4px}
.muted{color:var(--muted)}.grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;margin-bottom:16px}
.card h3{margin:0 0 8px;font-size:14px}blockquote{margin:6px 0;padding:4px 12px;border-left:3px solid var(--line);color:var(--ink2)}
pre{white-space:pre-wrap;background:var(--surface);border:1px solid var(--line);padding:12px;border-radius:6px}
.brief{max-width:900px}.brief li.nested{margin-left:18px}.fn{font-size:12px;color:var(--ink2);margin:2px 0}
.states{margin:10px 0}.states form{display:inline-block;margin-right:4px}.hero{font-size:34px;font-weight:650}
"""


def meter(points: float, maximum: float, label: str = "") -> str:
    pct = 0 if not maximum else max(0, min(100, 100 * points / maximum))
    tip = E(f"{label}: {points} of {maximum}")
    return f'<span class="meter" title="{tip}" role="img" aria-label="{tip}"><i style="width:{pct:.0f}%"></i></span>'


def page(title: str, body: str) -> bytes:
    nav = ('<header><b>Orphan Radar</b><a href="/">Opportunities</a><a href="/excluded">Excluded</a><a href="/leads">Leads</a>'
           '<a href="/ledger">Ledger</a><a href="/digest">Digest</a><a href="/sources">Sources</a></header>')
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{E(title)} - Orphan Radar</title><style>{CSS}</style></head><body>{nav}<main>{body}</main></body></html>").encode()


class App:
    def __init__(self, config):
        self.config = config

    def conn(self):
        return connect(self.config.db_path)

    # -- pages ---------------------------------------------------------------
    def index(self, q: dict) -> bytes:
        conn = self.conn()
        rows = latest_scores(conn)
        src, cat, sig, state, text = (q.get(k, [""])[0] for k in ("source", "category", "signal", "state", "q"))
        min_score = float(q.get("min", ["0"])[0] or 0)
        all_sources = sorted({s for r in rows for s in (r["sources"] or "").split(",") if s})
        all_cats = sorted({r["category"] for r in rows if r["category"]})
        out = []
        for r in rows:
            data = loads(r["components_json"], {})
            sigs = [k for k, s in data.get("signals", {}).items() if s.get("present")]
            if src and src not in (r["sources"] or ""): continue
            if cat and cat != r["category"]: continue
            if sig and sig not in sigs: continue
            if state and state != r["state"]: continue
            if state != "dismissed" and r["state"] == "dismissed" and not state: continue
            if r["total"] < min_score: continue
            if text and text.lower() not in r["name"].lower(): continue
            out.append((r, data, sigs))
        opt = lambda vals, cur: "".join(f'<option value="{E(v)}"{" selected" if v == cur else ""}>{E(v) or "any"}</option>' for v in [""] + vals)
        filters = (f'<form class="filters" method="get"><label>Search<input name="q" value="{E(text)}"></label>'
                   f'<label>Source<select name="source">{opt(all_sources, src)}</select></label>'
                   f'<label>Category<select name="category">{opt(all_cats, cat)}</select></label>'
                   f'<label>Signal<select name="signal">{opt(["abandonment", "displacement", "pain"], sig)}</select></label>'
                   f'<label>State<select name="state">{opt(["new", "watching", "building", "dismissed"], state)}</select></label>'
                   f'<label>Min score<input name="min" type="number" step="1" value="{E(q.get("min", [""])[0])}" style="width:80px"></label>'
                   f'<button class="primary">Filter</button> <a href="/">reset</a></form>')
        total_matches = len(out)
        show_all = q.get("all", [""])[0] == "1"
        if not show_all:
            out = out[:150]
        more = "" if show_all or total_matches <= 150 else f'<p><a href="?{E(urllib.parse.urlencode({**{k: v[0] for k, v in q.items()}, "all": "1"}))}">Show all {total_matches}</a></p>'
        head = "".join(f'<th class="num">{E(c.replace("_", " "))}</th>' for c in COMPONENTS)
        body = []
        for n, (r, data, sigs) in enumerate(out, 1):
            comps = {c["name"]: c for c in data.get("components", [])}
            cells = "".join(f'<td class="num">{meter(comps[c]["points"], comps[c]["max"], c)}{comps[c]["points"]}</td>' if c in comps else "<td></td>" for c in COMPONENTS)
            body.append(f'<tr><td class="num">{n}</td><td><a href="/o/{r["id"]}">{E(r["name"])}</a><div class="muted">{E(r["category"])}</div></td>'
                        f'<td class="num"><b>{r["total"]}</b></td>{cells}<td>{"".join(f"<span class=pill>{E(s)}</span>" for s in sigs)}</td>'
                        f'<td>{E((r["sources"] or "").replace(",", ", "))}</td><td>{E(r["state"])}</td></tr>')
        table = (f'<table><thead><tr><th class="num">#</th><th>Product</th><th class="num">Score</th>{head}<th>Signals</th><th>Sources</th><th>State</th></tr></thead>'
                 f'<tbody>{"".join(body) or "<tr><td colspan=12>No opportunities match. Run <code>orphan-radar scan</code>.</td></tr>"}</tbody></table>')
        return page("Opportunities", f"<h2>Opportunities <span class=muted>({total_matches})</span></h2>{filters}{table}{more}")

    def detail(self, eid: int) -> bytes:
        conn = self.conn()
        e = conn.execute("SELECT * FROM entities WHERE id=?", (eid,)).fetchone()
        if not e:
            return page("Not found", "<p>No such opportunity.</p>")
        sc = conn.execute("SELECT total, components_json, computed_at FROM scores WHERE entity_id=? ORDER BY id DESC LIMIT 1", (eid,)).fetchone()
        data = loads(sc["components_json"], {}) if sc else {}
        st = conn.execute("SELECT state, note FROM states WHERE entity_id=?", (eid,)).fetchone()
        cur_state = st["state"] if st else "new"
        prods = conn.execute("SELECT * FROM products WHERE entity_id=?", (eid,)).fetchall()
        evidence = {r["id"]: r for r in conn.execute("SELECT * FROM evidence WHERE entity_id=? ORDER BY date_posted DESC", (eid,))}
        excl = conn.execute("SELECT rule, reason FROM exclusions WHERE entity_id=?", (eid,)).fetchall()
        has_brief = conn.execute("SELECT generated_at FROM briefs WHERE entity_id=?", (eid,)).fetchone()
        has_prompt = conn.execute("SELECT generated_at FROM build_prompts WHERE entity_id=?", (eid,)).fetchone()

        buttons = "".join(f'<form method="post" action="/o/{eid}/state"><input type="hidden" name="state" value="{s}">'
                          f'<button{" class=primary" if s == cur_state else ""}>{s}</button></form> ' for s in ("watching", "building", "dismissed", "new"))
        top = (f'<h2>{E(e["name"])}</h2><div class="hero">{data.get("total", "–")}<span class="muted" style="font-size:16px"> / 100</span></div>'
               f'<div class="states">State: <b>{E(cur_state)}</b> &nbsp; {buttons}</div>'
               + "".join(f'<p><span class="pill">excluded</span> {E(x["rule"])}: {E(x["reason"])}</p>' for x in excl)
               + f'<p>{"<a href=/o/%d/brief>Read the brief</a> (%s)" % (eid, E(has_brief["generated_at"][:16])) if has_brief else "No brief yet."} '
               f'</p><form method="post" action="/o/{eid}/brief" style="display:inline"><button>{"Regenerate" if has_brief else "Generate"} brief</button></form> '
               f'<form method="post" action="/o/{eid}/buildprompt" style="display:inline"><button>{"Regenerate" if has_prompt else "Generate"} build prompt</button></form>'
               + (f' <a href="/o/{eid}/buildprompt">Open the build prompt</a> ({E(has_prompt["generated_at"][:16])})' if has_prompt else ""))
        plist = "".join(f'<tr><td>{E(p["source"])}</td><td><a href="{E(p["url"])}" target=_blank rel=noopener>{E(p["name"])}</a></td><td class=num>{E(p["user_count"])}</td>'
                        f'<td>{E((p["last_updated"] or "")[:10])}</td><td class=num>{E(p["rating"])}</td><td class=num>{E(p["rating_count"])}</td><td>{E(p["license"])}</td></tr>' for p in prods)
        products = f'<div class=card><h3>Listings</h3><table><tr><th>Source</th><th>Listing</th><th class=num>Users</th><th>Updated</th><th class=num>Rating</th><th class=num>Ratings</th><th>License</th></tr>{plist}</table></div>'

        comp_html = []
        for c in data.get("components", []):
            parts = "".join(f'<tr><td>{E(p["label"].replace("cfg:", ""))}</td><td class=num>{p["got"]:.1f} / {p["max"]}</td><td>{" ".join(f"<a href=#ev{i}>#{i}</a>" for i in p["evidence_ids"][:6])}{" …" if len(p["evidence_ids"]) > 6 else ""}</td></tr>' for p in c["parts"])
            comp_html.append(f'<tr><th colspan=3 style="position:static">{meter(c["points"], c["max"], c["name"])}{E(c["name"].replace("_", " "))}: {c["points"]} of {c["max"]}</th></tr>{parts}')
        breakdown = f'<div class=card><h3>Score breakdown</h3><table>{"".join(comp_html)}</table></div>'

        sigs = []
        for r in conn.execute("SELECT kind, strength, reasons_json FROM signals WHERE entity_id=?", (eid,)):
            reasons = "".join(f'<li>{E(x["text"])}: ' + "; ".join(f'{E(f["key"])} = {E(f["value"])} ' + " ".join(f"<a href=#ev{i}>#{i}</a>" for i in f["evidence_ids"][:4]) for f in x["facts"]) + "</li>" for x in loads(r["reasons_json"], []))
            sigs.append(f'<p>{meter(r["strength"], 1, r["kind"])}<b>{E(r["kind"])}</b> {r["strength"]:.2f}</p><ul>{reasons}</ul>')
        signals = f'<div class=card><h3>Signals</h3>{"".join(sigs)}</div>'

        cl_html = []
        for c in load_clusters(conn, eid):
            quotes = "".join(f'<blockquote>{E((evidence[i]["text"] or "")[:260])} <a href="{E(evidence[i]["url"])}" target=_blank rel=noopener>source</a></blockquote>' for i in c.evidence_ids[:3] if i in evidence)
            cl_html.append(f'<h4>{E(c.label)} <span class=muted>({c.size}, {E(c.method)})</span></h4><p class=muted>Fix: {E(c.fix)}</p>{quotes}')
        clusters = f'<div class=card><h3>Complaint clusters</h3>{"".join(cl_html) or "<p class=muted>No recent complaints.</p>"}</div>'

        ev_rows = "".join(
            f'<tr id="ev{r["id"]}"><td class=num>#{r["id"]}</td><td>{E(r["source"])}</td><td>{E(r["type"])}{(" · " + E(r["metric_key"])) if r["metric_key"] else ""}</td>'
            f'<td>{E(r["metric_value"] if r["metric_value"] is not None else (r["metric_text"] or ""))[:40]}</td><td>{E((r["text"] or "")[:200])}</td>'
            f'<td>{"".join(f"<span class=pill>{E(t)}</span>" for t in loads(r["tags"], []))}</td><td>{E((r["date_posted"] or "")[:10])}</td>'
            f'<td>{E(r["date_retrieved"][:10])}</td><td><a href="{E(r["url"])}" target=_blank rel=noopener>link</a></td></tr>' for r in evidence.values())
        ev = (f'<div class=card><h3>Evidence ({len(evidence)})</h3><table><tr><th>#</th><th>Source</th><th>Type</th><th>Value</th><th>Text</th><th>Tags</th>'
              f'<th>Posted</th><th>Retrieved</th><th>URL</th></tr>{ev_rows}</table></div>')
        return page(e["name"], top + products + f'<div class=grid><div>{breakdown}</div><div>{signals}{clusters}</div></div>' + ev)

    def brief(self, eid: int) -> bytes:
        conn = self.conn()
        b = conn.execute("SELECT markdown FROM briefs WHERE entity_id=?", (eid,)).fetchone()
        if not b:
            return page("Brief", f'<p>No brief yet. <a href="/o/{eid}">Back</a></p>')
        return page("Brief", f'<p><a href="/o/{eid}">← evidence and score</a></p><div class="brief">{render(b["markdown"])}</div>')

    def buildprompt(self, eid: int) -> bytes:
        conn = self.conn()
        b = conn.execute("SELECT markdown FROM build_prompts WHERE entity_id=?", (eid,)).fetchone()
        if not b:
            return page("Build prompt", f'<p>No build prompt yet. <a href="/o/{eid}">Back</a></p>')
        return page("Build prompt", f'<p><a href="/o/{eid}">← evidence and score</a> · <a href="/o/{eid}/brief">brief</a></p>'
                    f'<p class=muted>Copy the raw text below into an AI system builder. The rendered version follows.</p>'
                    f'<textarea readonly rows="12" style="width:100%;max-width:900px;font-family:ui-monospace,monospace;font-size:12px">{E(b["markdown"])}</textarea>'
                    f'<div class="brief">{render(b["markdown"])}</div>')

    def excluded(self) -> bytes:
        conn = self.conn()
        rows = conn.execute("""SELECT e.id, e.name, x.rule, x.reason FROM exclusions x JOIN entities e ON e.id=x.entity_id
                               ORDER BY x.rule='too_small', x.rule, e.name""").fetchall()
        body = "".join(f'<tr><td><a href="/o/{r["id"]}">{E(r["name"])}</a></td><td>{E(r["rule"])}</td><td>{E(r["reason"])}</td></tr>' for r in rows)
        return page("Excluded", f'<h2>Excluded by hard filters <span class=muted>({len(rows)})</span></h2><table><tr><th>Product</th><th>Rule</th><th>Reason</th></tr>{body}</table>')

    def leads(self) -> bytes:
        conn = self.conn()
        rows = conn.execute("""SELECT * FROM evidence WHERE entity_id IS NULL AND tags LIKE '%event:%' AND type IN ('discussion','question')
                               ORDER BY date_posted DESC LIMIT 300""").fetchall()
        body = "".join(f'<tr><td>{E((r["date_posted"] or "")[:10])}</td><td>{E(r["source"])}</td><td><a href="{E(r["url"])}" target=_blank rel=noopener>{E((r["text"] or "")[:160])}</a></td>'
                       f'<td class=num>{E(r["score"])}</td><td>{"".join(f"<span class=pill>{E(t)}</span>" for t in loads(r["tags"], []) if t.startswith("event:"))}</td></tr>' for r in rows)
        return page("Leads", "<h2>Leads</h2><p class=muted>Displacement events that name no product Orphan Radar tracks yet. They are not scored: "
                    "there is no verifiable user count. Use them to decide which source to add next.</p>"
                    f"<table><tr><th>Posted</th><th>Source</th><th>Discussion</th><th class=num>Points</th><th>Events</th></tr>{body}</table>")

    def sources(self) -> bytes:
        conn = self.conn()
        rows = "".join(f'<tr><td>{E(a.name)}</td><td>{E(a.title)}</td><td>{"ready" if a().available()[0] else E(a().available()[1])}</td>'
                       f'<td><a href="{E(a.docs_url)}">docs</a> · <a href="{E(a.terms_url)}">terms</a></td></tr>' for a in ADAPTERS)
        skipped = "".join(f"<li><b>{E(k)}</b>: {E(v)}</li>" for k, v in SKIPPED_SOURCES.items())
        scans = "".join(f'<tr><td>{r["id"]}</td><td>{E(r["started_at"])}</td><td>{E(r["status"])}</td><td><pre>{E(json.dumps({k: v for k, v in loads(r["stats_json"], {}).items() if k in ("ran", "skipped", "failed")}, indent=1))}</pre></td></tr>'
                        for r in conn.execute("SELECT * FROM scans ORDER BY id DESC LIMIT 10"))
        return page("Sources", f"<h2>Sources</h2><table><tr><th>Name</th><th>Title</th><th>Status</th><th>Read before writing</th></tr>{rows}</table>"
                    f"<h3>Reviewed and skipped</h3><ul>{skipped}</ul><h3>Recent scans</h3><table><tr><th>#</th><th>Started</th><th>Status</th><th>Stats</th></tr>{scans}</table>")

    def ledger(self) -> bytes:
        conn = self.conn()
        ins = ledger_insights(conn)
        num = lambda name, v: f'<input name="{name}" type="number" step="any" value="{E(v)}" style="width:90px">'
        rows = "".join(
            f'<tr><form method="post" action="/ledger/{r["id"]}"><td>{E(r["launched_name"])}<div class=muted>{E(r["launched_at"])}</div></td>'
            f'<td>{("<a href=/o/%d>#%d</a>" % (r["entity_id"], r["entity_id"])) if r["entity_id"] else ""}</td>'
            f'<td>{num("visitors_30d", r["visitors_30d"])}</td><td>{num("trials_30d", r["trials_30d"])}</td><td>{num("paying_30d", r["paying_30d"])}</td>'
            f'<td>{num("revenue_30d", r["revenue_30d"])}</td><td><input name="notes" value="{E(r["notes"])}"></td><td>{"winner" if r["winner"] else ""}</td>'
            f'<td><button>Save</button></td></form></tr>' for r in ins["rows"])
        add = ('<form class="filters" method="post" action="/ledger"><label>Launched as<input name="name" required></label><label>URL<input name="url"></label>'
               '<label>Opportunity id<input name="entity" type="number" style="width:110px"></label><label>Launch date<input name="launched" type="date"></label>'
               '<label>Notes<input name="notes"></label><button class="primary">Add launch</button></form>')
        comp = "".join(f'<tr><td>{E(c["name"].replace("_", " "))}</td><td class=num>{E(c["winners"])}</td><td class=num>{E(c["others"])}</td></tr>' for c in ins["components"])
        sig = "".join(f'<tr><td>{E(s["name"])}</td><td class=num>{E(s["winners_pct"])}</td><td class=num>{E(s["others_pct"])}</td></tr>' for s in ins["signals"])
        return page("Ledger", f"<h2>Outcome ledger</h2>{add}<table><tr><th>Launch</th><th>From</th><th>Visitors (30d)</th><th>Trials</th><th>Paying</th><th>Revenue</th><th>Notes</th><th></th><th></th></tr>{rows}</table>"
                    f"<h3>What the winners had in common</h3><p class=muted>Winner = at least one paying customer or any revenue at 30 days. "
                    f"Measured launches: {ins['n_measured']}, winners: {ins['n_winners']}. Scores are the snapshot taken when the launch was recorded. "
                    f"Adjust the weights in config.toml by hand.</p><div class=grid><table><tr><th>Component (avg points)</th><th class=num>Winners</th><th class=num>Others</th></tr>{comp}</table>"
                    f"<table><tr><th>Signal present (%)</th><th class=num>Winners</th><th class=num>Others</th></tr>{sig}</table></div>")

    def digest_page(self) -> bytes:
        return page("Digest", f'<div class="brief">{render(digest(self.conn(), float(self.config.threshold("brief_min_score", 45))))}</div>')

    # -- actions ---------------------------------------------------------------
    def post(self, path: str, form: dict) -> str:
        conn = self.conn()
        f = lambda k: (form.get(k, [""])[0] or "").strip()  # noqa: E731
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "o" and parts[2] == "state" and f("state") in ("new", "watching", "building", "dismissed"):
            conn.execute("INSERT OR REPLACE INTO states (entity_id, state, note, updated_at) VALUES (?,?,?,?)", (int(parts[1]), f("state"), None, now_iso()))
            conn.commit(); return f"/o/{int(parts[1])}"
        if len(parts) == 3 and parts[0] == "o" and parts[2] == "brief":
            generate_brief(conn, int(parts[1]), self.config); return f"/o/{int(parts[1])}/brief"
        if len(parts) == 3 and parts[0] == "o" and parts[2] == "buildprompt":
            generate_build_prompt(conn, int(parts[1]), self.config); return f"/o/{int(parts[1])}/buildprompt"
        if parts == ["ledger"] and f("name"):
            ledger_add(conn, int(f("entity")) if f("entity").isdigit() else None, f("name"), f("url") or None, f("launched") or None, f("notes") or None)
            return "/ledger"
        if len(parts) == 2 and parts[0] == "ledger":
            num = lambda k, t: t(f(k)) if f(k) else None  # noqa: E731
            ledger_update(conn, int(parts[1]), visitors_30d=num("visitors_30d", int), trials_30d=num("trials_30d", int),
                          paying_30d=num("paying_30d", int), revenue_30d=num("revenue_30d", float), notes=f("notes") or None)
            return "/ledger"
        return "/"


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, body: bytes, status=200, ctype="text/html; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            q = urllib.parse.parse_qs(u.query)
            parts = u.path.strip("/").split("/")
            try:
                if u.path == "/":
                    body = app.index(q)
                elif parts[0] == "o" and len(parts) >= 2 and parts[1].isdigit():
                    sub = parts[2] if len(parts) == 3 else ""
                    body = app.brief(int(parts[1])) if sub == "brief" else app.buildprompt(int(parts[1])) if sub == "buildprompt" else app.detail(int(parts[1]))
                elif u.path == "/excluded":
                    body = app.excluded()
                elif u.path == "/leads":
                    body = app.leads()
                elif u.path == "/sources":
                    body = app.sources()
                elif u.path == "/ledger":
                    body = app.ledger()
                elif u.path == "/digest":
                    body = app.digest_page()
                else:
                    return self._send(page("Not found", "<p>Not found.</p>"), 404)
                self._send(body)
            except Exception as exc:  # noqa: BLE001
                self._send(page("Error", f"<pre>{E(repr(exc))}</pre>"), 500)

        def do_POST(self):
            origin = self.headers.get("Origin") or self.headers.get("Referer") or ""
            host = self.headers.get("Host", "")
            if origin and urllib.parse.urlsplit(origin).netloc != host:
                return self._send(b"cross-origin request refused", 403, "text/plain")
            length = min(int(self.headers.get("Content-Length") or 0), 100_000)
            form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            try:
                target = app.post(urllib.parse.urlsplit(self.path).path, form)
            except Exception as exc:  # noqa: BLE001
                return self._send(page("Error", f"<pre>{E(repr(exc))}</pre>"), 500)
            self.send_response(303)
            self.send_header("Location", target)
            self.end_headers()

    return Handler


def serve(config, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(App(config)))
    print(f"Orphan Radar dashboard on http://{host}:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
