"""One-page opportunity brief.

Every figure is written through `cite()`, which appends a footnote pointing at the evidence
records it came from; footnotes resolve to an evidence index with URL and retrieval date.
`audit_brief()` re-reads the finished markdown and lists any number that is not cited.
A brief that fails the audit is never saved.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from . import llm
from .cluster import Cluster, load_clusters
from .db import dumps, loads, now_iso
from .detect import detect
from .facts import MARKETPLACES, EntityView, Fact
from .textutil import mentions_export, snippet

SOURCE_LABEL = {"wordpress": "WordPress.org", "firefox": "addons.mozilla.org", "github": "GitHub", "openvsx": "Open VSX",
                "hackernews": "Hacker News", "stackexchange": "Stack Exchange", "autocomplete": "Google autocomplete", "reddit": "Reddit",
                "atlassian": "Atlassian Marketplace"}
TYPE_LABEL = {"review": "review", "support_thread": "support thread", "issue": "issue", "discussion": "discussion",
              "question": "question", "search_suggestion": "search suggestions", "event": "notice", "metric": "listing"}
# Ordered: more specific names first ("lesser general public" before "general public").
OPEN_LICENSES = [
    (("agpl", "affero"), "Forking is permitted; a hosted fork must publish its source under the AGPL."),
    (("lgpl", "lesser general public", "library general public"), "Forking is permitted; changes to the library itself must stay under the LGPL."),
    (("gpl", "general public license"), "Forking is permitted; the fork and anything distributed with it must stay under the GPL."),
    (("mit",), "Forking is permitted; keep the copyright and license notice."),
    (("apache",), "Forking is permitted; keep the notices and state your changes."),
    (("bsd",), "Forking is permitted; keep the copyright notice."),
    (("mpl", "mozilla public"), "Forking is permitted; modified MPL files must stay under the MPL."),
    (("epl", "eclipse public"), "Forking is permitted; modified EPL code must stay under the EPL."),
    (("isc",), "Forking is permitted; keep the copyright notice."),
    (("unlicense", "cc0", "public domain"), "Forking is permitted without conditions."),
]


def fmt(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value >= 1000 else f"{value:.2f}".rstrip("0").rstrip(".")
    text = str(value)
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return text[:10]
    return text


@dataclass
class Writer:
    evidence: dict[int, dict]
    notes: list[list[int]] = field(default_factory=list)   # footnote n (1-based) -> evidence ids
    facts: list[dict] = field(default_factory=list)

    def ref(self, ids: list[int]) -> str:
        ids = sorted(set(ids))
        if not ids:
            raise ValueError("a citation needs at least one evidence id")
        if ids in self.notes:
            n = self.notes.index(ids) + 1
        else:
            self.notes.append(ids)
            n = len(self.notes)
        return f"[^{n}]"

    def cite(self, value, ids: list[int]) -> str:
        text = fmt(value).replace(" ", " ")  # one token, so the audit can see it is cited
        self.facts.append({"value": text, "evidence_ids": sorted(set(ids))})
        return f"{text}{self.ref(ids)}"

    def fact(self, f: Fact | None, suffix: str = "") -> str:
        if not f:
            return "unknown"
        return self.cite(f"{fmt(f.value)}{suffix}", f.evidence_ids)

    def link(self, e: dict, label: str | None = None) -> str:
        label = label or f"{SOURCE_LABEL.get(e['source'], e['source'])} {TYPE_LABEL.get(e['type'], e['type'])}"
        return f"[{label}]({e['url']}){self.ref([e['id']])}"

    def quote(self, e: dict, limit: int = 220) -> str:
        text = snippet(e["text"], limit).replace("“", '"').replace("”", '"')
        stars = f" ({e['score']}★)" if e["type"] == "review" and e["score"] else ""
        posted = f", {self.cite(e['date_posted'][:10], [e['id']])}" if e.get("date_posted") else ""
        return f"“{text}”{stars.replace(str(e['score']), self.cite(e['score'], [e['id']])) if stars else ''} — {self.link(e)}{posted}"

    def footnotes(self) -> str:
        lines = ["## Evidence", ""]
        for n, ids in enumerate(self.notes, 1):
            if len(ids) == 1:
                e = self.evidence[ids[0]]
                lines.append(f"[^{n}]: #{ids[0]} {_describe(e)}")
            else:
                lines.append(f"[^{n}]: derived from {len(ids)} evidence records: " + ", ".join(f"#{i}" for i in ids))
        lines += ["", "### Evidence index", ""]
        for i in sorted({i for ids in self.notes for i in ids}):
            lines.append(f"- #{i} {_describe(self.evidence[i])}")
        return "\n".join(lines)


def _describe(e: dict) -> str:
    what = e["metric_key"] if e["type"] == "metric" else TYPE_LABEL.get(e["type"], e["type"])
    return f"{SOURCE_LABEL.get(e['source'], e['source'])} {what}, <{e['url']}>, retrieved {e['date_retrieved'][:10]}"


# ---------------------------------------------------------------------------

FACT_PHRASES = {
    "last_updated": "last updated {}", "months_since_update": "{} months ago", "support_threads_recent": "{} support threads opened in the last two months",
    "support_threads_resolved": "{} resolved", "unresolved_share": "{} unresolved", "unanswered_threads": "{} recent threads with no reply",
    "tested_up_to": "tested up to WordPress {}", "platform_current_version": "current WordPress is {}", "releases_behind": "{} major releases behind",
    "archived": "repository {}", "event_date": "latest dated mention {}", "recent_complaints": "{} complaints in the last twelve months",
    "top_issue_reactions": "{} reactions on the most-reacted open issue", "rating": "lifetime rating {} stars",
    "rating_recent": "recent rating {} stars", "event_mentions": "in {} records",
}


def _phrase(w: Writer, f: Fact) -> str:
    if f.key.startswith("event_") and f.key not in ("event_date", "event_mentions"):
        return w.cite(f.value, f.evidence_ids) if any(ch.isdigit() for ch in str(f.value)) else f"{f.value}{w.ref(f.evidence_ids)}"
    tmpl = FACT_PHRASES.get(f.key, f.key.replace("_", " ") + " {}")
    return tmpl.format(w.cite(f.value, f.evidence_ids))


def _signal_section(w: Writer, v: EntityView, signals) -> list[str]:
    out = []
    names = {"abandonment": "Abandonment", "displacement": "Displacement event", "pain": "Pain density"}
    for kind in ("abandonment", "displacement", "pain"):
        s = signals[kind]
        if not s.reasons:
            out.append(f"- **{names[kind]}**: none found.")
            continue
        status = "present" if s.present else "weak"
        out.append(f"- **{names[kind]}** ({status}):")
        for r in s.reasons:
            out.append(f"  - {r.text}: " + "; ".join(_phrase(w, f) for f in r.facts))
    events = sorted([e for e in v.evidence if any(t.startswith("event:") for t in e["tag_list"]) and e["type"] != "metric"],
                    key=lambda e: e["date_posted"] or "", reverse=True)[:5]
    if events:
        out.append("")
        out.append("Dated sources for the events:")
        for e in events:
            out.append(f"- {w.quote(e, 160)}")
    return out


def _complaints_section(w: Writer, v: EntityView, clusters: list[Cluster]) -> list[str]:
    ev = {e["id"]: e for e in v.evidence}
    specific = [c for c in clusters if c.key != "other"]
    if not specific:
        other = next((c for c in clusters if c.key == "other"), None)
        if not other:
            return ["No recent complaints in the evidence. Top complaints: unknown."]
        return [f"Only unspecific complaints ({w.cite(other.size, other.evidence_ids)} records); no concrete problem can be named."]
    out = []
    for c in specific[:5]:
        out.append(f"**{c.label}** ({w.cite(c.size, c.evidence_ids)} complaints)" + (f": {c.summary}" if c.summary else ""))
        rows = sorted((ev[i] for i in c.evidence_ids if i in ev), key=lambda e: (-(e["score"] or 0) if e["type"] == "issue" else 0, -(len(e["text"] or "") < 400), e["date_posted"] or ""), reverse=False)
        for e in rows[:3]:
            out.append(f"> {w.quote(e)}")
            out.append(">")
        if out[-1] == ">":
            out.pop()
        out.append("")
    other = next((c for c in clusters if c.key == "other"), None)
    if other:
        out.append(f"Plus {w.cite(other.size, other.evidence_ids)} complaints too vague to cluster.")
    return out


def _export_section(w: Writer, v: EntityView) -> list[str]:
    rows = [e for e in v.evidence if e["text"] and e["type"] != "search_suggestion" and mentions_export(e["text"])]
    formats = {}
    for e in rows:
        for fmt_name in ("CSV", "JSON", "XML", "OPML", "SQL", "ZIP", "HTML"):
            if re.search(rf"\b{fmt_name}\b", e["text"], re.I):
                formats.setdefault(fmt_name, []).append(e["id"])
    out = []
    if formats:
        out.append("Formats named in the evidence: " + ", ".join(f"{k}{w.ref(ids)}" for k, ids in formats.items()) + ".")
    else:
        out.append("Export format: unknown. No evidence record states whether or how data can be exported.")
    if rows:
        out.append("")
        out.append("What users say about import, export or migration:")
        for e in rows[:3]:
            out.append(f"- {w.quote(e, 180)}")
    out += ["", "A one-click import would need (to verify before building, not established by the evidence):",
            "- where the incumbent stores its data and settings, and whether that store is readable without the incumbent installed;",
            "- the export format, if one exists, and a sample file;",
            "- a mapping from each incumbent setting to the replacement's setting, with defaults for anything unmapped."]
    return out


def _channel_section(w: Writer, v: EntityView) -> list[str]:
    out = []
    for p in v.products:
        if p["source"] in MARKETPLACES:
            ids = [e["id"] for e in v.metric_rows("description") + v.metric_rows("user_count") + v.metric_rows("github_stars") + v.metric_rows("downloads")
                   if e["product_id"] == p["id"]][:1]
            ref = w.ref(ids) if ids else ""
            out.append(f"- List it on **{MARKETPLACES[p['source']]}**, where the incumbent is: <{p['url']}>{ref}")
    sugg = [e for e in v.of_type("search_suggestion") if e["metric_value"]]
    if sugg:
        out.append("- Replacement searches to target (Google autocomplete):")
        for e in sugg:
            for s in (e["extra"].get("suggestions") or [])[:5]:
                s_txt = f"“{s}”" if any(ch.isdigit() for ch in s) else s
                out.append(f"  - `{s_txt}`{w.ref([e['id']])}")
    else:
        checked = v.of_type("search_suggestion")
        out.append("- Replacement searches: " + ("none found for the alternative / not working / pricing queries" + w.ref([e['id'] for e in checked]) if checked else "not checked (unknown)") + ".")
    asks = [e for e in v.evidence if "intent" in e["tag_list"] and e["type"] in ("discussion", "question", "review", "support_thread", "issue")]
    if asks:
        out.append("- Public threads where people asked for an alternative (links only):")
        for e in asks[:6]:
            title = snippet(e["extra"].get("title") or e["text"], 90)
            title = title.replace("[", "(").replace("]", ")")
            if any(ch.isdigit() for ch in title):
                title = f"“{title}”"
            out.append(f"  - [{title}]({e['url']}){w.ref([e['id']])}")
    else:
        out.append("- Public threads asking for an alternative: none found.")
    return out


def _price_section(w: Writer, v: EntityView) -> list[str]:
    out = []
    bm, rp = v.metric("business_model"), v.metric("requires_payment")
    if bm:
        meaning = "sells paid upgrades or services" if bm.value == "commercial" else "declares no commercial offering"
        out.append(f"- Incumbent: the listing's business model is '{bm.value}'{w.ref(bm.evidence_ids)}, i.e. it {meaning}. Exact prices: unknown.")
    elif rp:
        out.append(f"- Incumbent: the listing says some features require payment{w.ref(rp.evidence_ids)}. Exact prices: unknown.")
    else:
        out.append("- Incumbent price: unknown. No evidence record states a price.")
    paying = [e for e in v.evidence if "paying" in e["tag_list"] and e["type"] not in ("search_suggestion", "metric")]
    if paying:
        out.append("- What users say about paying:")
        for e in paying[:4]:
            out.append(f"  - {w.quote(e, 180)}")
    pr = v.metric("suggestions_pricing")
    if pr and pr.value:
        out.append(f"- People search for “{v.name} pricing”{w.ref(pr.evidence_ids)}.")
    out.append("- Rivals' prices: unknown. No evidence record prices a rival.")
    return out


def _license_section(w: Writer, v: EntityView) -> list[str]:
    lic = v.metric("license", prefer="primary")
    out = []
    if lic:
        key = str(lic.value).lower()
        verdict = next((txt for keys, txt in OPEN_LICENSES if any(re.search(rf"\b{re.escape(k)}\b", key) for k in keys)), None)
        lic_txt = f"“{lic.value}”" if any(ch.isdigit() for ch in str(lic.value)) else str(lic.value)
        out.append(f"- License: {lic_txt}{w.ref(lic.evidence_ids)}.")
        out.append(f"- Forking: {verdict or 'unknown; the license is not a recognised open-source license, so assume forking is not permitted without permission.'}")
    else:
        out.append("- License: unknown. Forking: unknown; assume it is not permitted until the license is confirmed.")
    out.append(f"- Use a new name and new branding. Do not use “{v.name}”, its logo or its screenshots in the product name, listing or ads; "
               "mention it only to say what you import from or replace, where the marketplace allows that.")
    return out


def _risks(w: Writer, v: EntityView, signals, clusters, score: dict) -> list[str]:
    out = []
    aud, proxy = v.audience()
    if proxy:
        out.append("The audience figure is a proxy (stars or downloads), not active users.")
    last = v.last_update()
    from .detect import months_since
    m = months_since(last.value) if last else None
    if m is not None and m < 3:
        out.append(f"The incumbent was updated recently ({w.fact(last)}): it may be recovering rather than abandoned.")
    present = [k for k, s in signals.items() if s.present]
    if len(present) < 2:
        out.append("Fewer than two of the three signals are present; the opportunity rests on one kind of evidence.")
    n_complaints = sum(c.size for c in clusters)
    if n_complaints < 5:
        out.append("Few recent complaints, so the problem list may be incomplete or unrepresentative.")
    srcs = {e["source"] for e in v.evidence}
    if len(srcs) == 1:
        out.append("All evidence comes from a single source.")
    if not v.metric("suggestions_alternative"):
        out.append("Replacement searches were not checked.")
    elif not v.metric("suggestions_alternative").value:
        out.append("Nobody's autocomplete suggests searching for an alternative yet.")
    from .filters import native_claims
    for e in native_claims(v)[:1]:
        out.append(f"A user says the platform already does this natively: {w.quote(e, 160)}. Check before building.")
    author = v.metric("author", prefer="primary")
    if author and re.search(r"wordpress\.org|wordpress contributors|wordpressdotorg|automattic|woothemes|woocommerce|mozilla", str(author.value), re.I):
        out.append(f"Maintained by the platform's own organisation (author: \u201c{author.value}\u201d{w.ref(author.evidence_ids)}): "
                   "it may be fixed or folded into the platform, and users may distrust a third-party replacement.")
    bm = v.metric("business_model")
    if bm and bm.value == "commercial":
        out.append("The incumbent has a commercial side and may still be funded to fix these problems.")
    out.append("Whether a maintained replacement already dominates is not established by this evidence: check the marketplace category before building.")
    return [f"- {r}" for r in out]


def _confidence(w: Writer, v: EntityView, signals, clusters) -> list[str]:
    rows = []
    aud, proxy = v.audience()
    rows.append(("Size of the stranded audience", "thin (proxy)" if proxy else ("well evidenced (official listing figure)" if aud else "unknown"),
                 w.ref(aud.evidence_ids) if aud else ""))
    ab = signals["abandonment"]
    rows.append(("Abandonment", "well evidenced (listing metrics)" if ab.present else ("thin" if ab.reasons else "unknown"), w.ref(ab.evidence_ids) if ab.evidence_ids else ""))
    d = signals["displacement"]
    strong = any(r.weight >= 0.6 for r in d.reasons)
    rows.append(("Displacement event", "well evidenced" if strong else ("thin (single reviewer claims)" if d.reasons else "none found"), w.ref(d.evidence_ids) if d.evidence_ids else ""))
    n = sum(c.size for c in clusters if c.key != "other")
    ids = [i for c in clusters if c.key != "other" for i in c.evidence_ids]
    rows.append(("Top complaints", "well evidenced" if n >= 8 else ("thin" if n >= 2 else "unknown"), w.ref(ids) if ids else ""))
    sugg = v.metric("suggestions_alternative")
    rows.append(("Replacement demand in search", "well evidenced" if sugg and sugg.value else ("checked, none found" if sugg else "unknown"), w.ref(sugg.evidence_ids) if sugg else ""))
    bm = v.metric("business_model") or v.metric("requires_payment")
    rows.append(("Price anchor", "thin (no prices, only that the incumbent charges)" if bm else "unknown", w.ref(bm.evidence_ids) if bm else ""))
    rows.append(("Switching wedge (export/import)", "unknown unless quoted above", ""))
    out = ["| Claim | Confidence | Evidence |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return out


def _smallest_replacement(w: Writer, v: EntityView, clusters: list[Cluster], signals) -> tuple[list[str], list[str]]:
    """Returns (markdown lines, plain feature list for the build prompt)."""
    desc = v.metric("description", prefer="primary")
    features, lines = [], []
    if desc:
        lines.append(f"Does the job the incumbent does today, as its listing describes it: “{snippet(str(desc.value), 200)}”{w.ref(desc.evidence_ids)}")
    top = [c for c in clusters if c.key != "other" and c.fix and c.fix != "unknown"][:3]
    for c in top:
        lines.append(f"- {c.fix} (fixes: {c.label.lower()}){w.ref(c.evidence_ids)}")
        features.append(f"{c.fix} (users of the incumbent complain: {c.label.lower()})")
    compat = [r for r in signals["abandonment"].reasons if r.text.startswith("WordPress releases behind")]
    if compat and not any(c.key == "compat" for c in top):
        lines.append(f"- Works on the current WordPress release{w.ref(compat[0].facts[-1].evidence_ids)}")
        features.append("Works on the current WordPress release")
    lines.append("- Imports the incumbent's settings and data (see the switching wedge)")
    features.append("A one-click import of the incumbent's settings and data")
    if not top:
        lines.insert(1 if desc else 0, "The evidence names no specific fixable problem, so the smallest replacement is: unknown beyond parity plus import.")
    lines.append("")
    lines.append("Nothing else. Anything not listed here is out of scope for the first release.")
    return lines, features


def build_prompt(v: EntityView, features: list[str], clusters: list[Cluster], w: Writer | None = None) -> str:
    p = v.primary or {}
    where = MARKETPLACES.get(p.get("source"), "the same place its users find tools today")
    desc = v.metric("description", prefer="primary")
    job = (f"\u201c{snippet(str(desc.value), 200)}\u201d" + (w.ref(desc.evidence_ids) if w else "")) if desc else "unknown; read the incumbent's public listing first"
    feats = "\n".join(f"- {f}" for f in features)
    text = f"""Build a replacement for an abandoned or failing product whose users are looking for an alternative.

Incumbent (for reference only; do not use its name or branding): {v.name}, listed on {where}.
What it does, in its own listing's words: {job}

Build the smallest product that fixes what its users complain about, and nothing else:
{feats}

Distribution: publish it on {where}, in the same category as the incumbent, under a new name and new branding.
Write the listing so it answers the searches and threads where people ask for an alternative; describe the
fixes above in plain words.

Pricing: start free on the marketplace, and keep one clearly separated paid tier for advanced or business needs;
set the price only after checking what the incumbent and its rivals charge (not known yet).

Constraints:
- New name, logo, wording and screenshots; never imply affiliation with the incumbent.
- Do not copy the incumbent's code unless its license permits it, and follow that license if you do.
- No data collection beyond what the features need; no ads, no tracking.
- Ship with tests for the import path and for each fix listed above.
"""
    return text


# ---------------------------------------------------------------------------

def generate_brief(conn: sqlite3.Connection, entity_id: int, config, use_llm: bool | None = None) -> str:
    th = config.section("thresholds")
    v = EntityView.load(conn, entity_id, int(th.get("recent_window_days", 365)))
    signals = detect(v, float(th.get("stale_months", 18)), float(th.get("event_fresh_days", 180)))
    clusters = load_clusters(conn, entity_id)
    row = conn.execute("SELECT total, components_json FROM scores WHERE entity_id=? ORDER BY id DESC LIMIT 1", (entity_id,)).fetchone()
    score = loads(row["components_json"], {}) if row else {}
    evidence = {e["id"]: e for e in v.evidence}
    w = Writer(evidence)
    p = v.primary or {}
    aud, proxy = v.audience()
    last = v.last_update()
    present = [k for k, s in signals.items() if s.present]
    top = next((c for c in clusters if c.key != "other"), None)

    # 1. Summary
    aud_txt = f"{w.fact(aud)} {'GitHub stars' if aud and aud.key == 'github_stars' else ('downloads' if proxy else 'users')}" if aud else "an unknown number of users"
    summary = (f"{v.name} on {MARKETPLACES.get(p.get('source'), p.get('source', 'unknown'))} has {aud_txt}, was last updated {w.fact(last)}, "
               f"and shows {', '.join(present) if present else 'no strong signal'}"
               + (f"; its users' most common fixable complaint is “{top.label.lower()}”{w.ref(top.evidence_ids)}." if top else "."))

    lines = [f"# {v.name}", "",
             f"<!-- meta: generated {now_iso()}; entity id {entity_id}; Orphan Radar brief -->", "",
             f"Score **{w.cite(score.get('total', 0), _score_ids(score) or list(evidence)[:1])}** of cfg:100 \u00b7 signals: {', '.join(present) or 'none'}",
             "", "## 1. Summary", "", summary, ""]
    lines += ["## 2. What happened", ""] + _signal_section(w, v, signals) + [""]
    lines += ["## 3. Stranded users", ""]
    listed = False
    for prod in v.products:
        for key, label in (("user_count", "installations (sites)" if prod["source"] == "atlassian" else "users"), ("github_stars", "GitHub stars (proxy)"), ("downloads", "downloads (proxy)")):
            f = v.metric_for_product(key, prod["id"])
            if f:
                e = evidence[f.evidence_ids[0]]
                lines.append(f"- {w.cite(f.value, f.evidence_ids)} {label} on {MARKETPLACES.get(prod['source'], prod['source'])} (<{prod['url']}>), "
                             f"read from {SOURCE_LABEL.get(e['source'], e['source'])} on {w.cite(e['date_retrieved'][:10], [e['id']])}")
                listed = True
    if not listed:
        lines.append("- Count: unknown.")
    lines += ["", "## 4. Top complaints", ""] + _complaints_section(w, v, clusters) + [""]
    sr_lines, features = _smallest_replacement(w, v, clusters, signals)
    lines += ["## 5. Smallest replacement", ""] + sr_lines + [""]
    lines += ["## 6. Switching wedge", ""] + _export_section(w, v) + [""]
    lines += ["## 7. Launch channel", ""] + _channel_section(w, v) + [""]
    lines += ["## 8. Price anchor", ""] + _price_section(w, v) + [""]
    lines += ["## 9. License and naming", ""] + _license_section(w, v) + [""]
    lines += ["## 10. Risks and reasons to skip", ""] + _risks(w, v, signals, clusters, score) + [""]
    lines += ["## 11. Confidence", ""] + _confidence(w, v, signals, clusters) + [""]
    lines += ["## 12. Build prompt", "", "```text", build_prompt(v, features, clusters, w).rstrip(), "```", ""]
    lines += ["## Score breakdown", ""] + _score_table(w, score) + [""]
    md = "\n".join(lines) + "\n" + w.footnotes() + "\n"

    problems = audit_brief(conn, md, extra_names=[q["name"] for q in v.products] + [v.name])
    if problems:
        raise ValueError("brief failed the traceability audit: " + "; ".join(problems[:5]))
    conn.execute("INSERT OR REPLACE INTO briefs (entity_id, generated_at, score, method, markdown, facts_json) VALUES (?,?,?,?,?,?)",
                 (entity_id, now_iso(), score.get("total"), "template" + ("+llm-clusters" if any(c.method == "llm" for c in clusters) else ""),
                  md, dumps(w.facts)))
    conn.commit()
    return md


def _score_ids(score: dict) -> list[int]:
    return sorted({i for c in score.get("components", []) for p in c["parts"] for i in p["evidence_ids"]})


def _score_table(w: Writer, score: dict) -> list[str]:
    """Points are cited to the evidence that earned them; maxima are weights from config.toml (cfg:)."""
    out = ["| Component | Points | Max (cfg) | What counted |", "|---|---|---|---|"]
    for c in score.get("components", []):
        ids = sorted({i for p in c["parts"] for i in p["evidence_ids"]})
        parts = "; ".join(p["label"].replace("<product>", "\u2039product\u203a") for p in c["parts"] if p["got"])
        pts = w.cite(c["points"], ids) if ids and c["points"] else ("none" if not c["points"] else "unscored")
        out.append(f"| {c['name'].replace('_', ' ')} | {pts} | cfg:{fmt(c['max'])} | {parts or 'nothing'} |")
    return out


# --- audit -------------------------------------------------------------------

_CITED = re.compile(r"[^\s\[\]]*?\d[^\s\[\]]*?((?:\[\^\d+\])+)")
_FOOTREF = re.compile(r"\[\^(\d+)\]")


def audit_brief(conn: sqlite3.Connection, md: str, extra_names: list[str] | None = None) -> list[str]:
    """Problems that break the grounding rule: uncited numbers, or footnotes whose evidence
    record is missing, has no URL, or has no retrieval date."""
    problems = []
    body, _, notes = md.partition("\n## Evidence\n")
    if not notes:
        problems.append("missing evidence section")
    # footnote definitions
    defs = {}
    for m in re.finditer(r"^\[\^(\d+)\]: (.*)$", notes, re.M):
        ids = [int(x) for x in re.findall(r"#(\d+)", m.group(2))]
        defs[m.group(1)] = ids
        for i in ids:
            row = conn.execute("SELECT url, date_retrieved FROM evidence WHERE id=?", (i,)).fetchone()
            if not row:
                problems.append(f"footnote {m.group(1)} cites missing evidence #{i}")
            elif not row["url"] or not row["date_retrieved"]:
                problems.append(f"evidence #{i} lacks a URL or retrieval date")
    for ref in set(_FOOTREF.findall(body)):
        if ref not in defs:
            problems.append(f"footnote [^{ref}] is not defined")
    # numbers in the body
    text = re.sub(r"```text\n.*?```", lambda m: m.group(0) if re.search(r"\d", m.group(0)) else "", body, flags=re.S)
    for name in sorted(set(extra_names or []), key=len, reverse=True):
        if name:
            text = text.replace(name, " ")
    lines = []
    for line in text.splitlines():
        if line.startswith("<!-- meta:"):
            continue                                              # generation metadata, not a claim
        line = re.sub(r"cfg:\d+(?:\.\d+)?", " ", line)           # weights/thresholds from config.toml
        if re.match(r"^#{1,6} \d+\. ", line):
            line = re.sub(r"^(#{1,6}) \d+\. ", r"\1 ", line)
        if _FOOTREF.search(line):
            line = re.sub(r"“.*?”", " ", line)        # verbatim quotes on cited lines
        line = re.sub(r"\]\([^)]*\)", "]", line)                 # link targets
        line = re.sub(r"<https?://[^>]+>", " ", line)            # bare URLs
        line = _CITED.sub(" ", line)                              # cited figures
        line = _FOOTREF.sub(" ", line)
        lines.append(line)
    for n, line in enumerate(lines, 1):
        for m in re.finditer(r"\d[\d,.:%/-]*", line):
            problems.append(f"uncited number '{m.group(0)}' in line {n}: {line.strip()[:120]}")
    return problems


def write_briefs(conn: sqlite3.Connection, config, only: list[int] | None = None) -> tuple[list[int], dict[int, str]]:
    """Generate briefs for every non-excluded entity at or above brief_min_score (or the given ids)."""
    from .pipeline import latest_scores
    threshold = float(config.threshold("brief_min_score", 45))
    ids = only if only else [r["id"] for r in latest_scores(conn) if r["total"] >= threshold]
    done, failed = [], {}
    for eid in ids:
        try:
            generate_brief(conn, eid, config)
            done.append(eid)
        except Exception as exc:  # noqa: BLE001 - report and continue with the others
            failed[eid] = str(exc)
    return done, failed
