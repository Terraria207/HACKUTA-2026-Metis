"""System-build prompt: a self-contained specification for an AI that builds large systems.

It is assembled from the same evidence as the brief, through the same citing Writer, and must
pass the same audit before it is saved: every figure cites evidence, unknowns are stated as
unknown, and the builder is told what to verify before writing code.
"""
from __future__ import annotations

import re
import sqlite3

from .brief import (Writer, _phrase, alternative_threads, audit_brief, export_mentions, fmt, load_context, paying_mentions,
                    replacement_searches, safe_title, top_quotes, write_documents)
from .cluster import Cluster
from .db import dumps, loads, now_iso
from .facts import MARKETPLACES, EntityView
from .textutil import snippet

# Requirement templates per complaint cluster. No digits: the audit would flag them.
REQUIREMENTS: dict[str, tuple[str, str, str]] = {
    # key: (title, requirement, acceptance criterion)
    "compat": ("Works on today's platform",
               "Runs on the current platform release and on every release the platform still supports, including the current PHP or browser engine versions where relevant.",
               "An automated compatibility job installs the product on the current release and performs the core job with no errors, deprecation notices or console warnings."),
    "not_working": ("Does its core job reliably",
                    "The core job succeeds on the sites, pages or setups that users name in the complaints below.",
                    "A regression suite built from the quoted cases passes; each case is a fixture, not a manual check."),
    "paywall": ("Core features stay free",
                "Every feature users say moved behind a paywall or subscription is available in the free tier, with no upgrade gate, nag or trial timer.",
                "A review of the free build finds no locked feature, upgrade prompt or forced wait; paid features, if any, are separate and clearly labelled."),
    "data_loss": ("Never loses data or settings",
                  "No operation deletes or resets user data or settings without an explicit, confirmed action; settings survive upgrades and reinstalls; a backup is offered before any destructive change.",
                  "An upgrade test from the previous version keeps every setting; a destructive-action test shows the confirmation and the backup."),
    "crash": ("No crashes, fatal errors or broken pages",
              "Errors are caught and reported inside the product; nothing the product does can break the host page, site or editor.",
              "The quoted failures are reproduced as tests and fixed; an error boundary test proves a failing component cannot take the host down."),
    "performance": ("Lightweight",
                    "Adds a measured, bounded amount of page weight, CPU and memory; heavy work is lazy, cached or moved off the critical path.",
                    "A performance budget test fails the build when the measured cost exceeds the budget you set in the first milestone."),
    "ads_privacy": ("No ads, no tracking, transparent ownership",
                    "No advertising, no tracking, no telemetry without opt-in, no injected content; the source is public and the ownership is stated in the listing.",
                    "A network audit of a full session shows no third-party calls except those the user explicitly triggers."),
    "ui_regression": ("Keeps the workflow users relied on",
                      "The workflow or option that users say was removed or worsened exists in the first release; redesigns are opt-in.",
                      "Each quoted workflow is a passing acceptance test; a settings switch restores classic behaviour where the quotes describe one."),
    "sync_login": ("Never breaks sign-in or sync",
                   "The product does not interfere with sign-in or sync on the sites it touches, and works without creating an account.",
                   "Sign-in flows on the major identity providers pass with the product enabled; the product runs with no account."),
    "import_export": ("Open import and export",
                      "All user data can be exported to an open, documented format and imported back, in one step.",
                      "A round-trip test exports, wipes, imports and compares; the documented format is in the repository."),
    "support": ("Visible, answered support",
                "A public issue tracker, a stated response time, and a changelog that names fixed issues.",
                "The listing links the tracker; a release checklist requires the changelog entry."),
    "missing_feature": ("The specific features users asked for",
                        "Implement exactly the features requested in the quoted complaints, each as a small, documented option.",
                        "Each quoted request maps to a passing acceptance test and a line in the docs."),
}

PLATFORM: dict[str, list[str]] = {
    "wordpress": [
        "Build a WordPress plugin in PHP that follows the WordPress.org plugin guidelines: GPL-compatible license, no tracking without consent, no remote code, uninstall cleanup, translation-ready strings, nonces and capability checks on every action.",
        "Target the current WordPress release and the oldest release WordPress still supports, and the PHP versions WordPress currently supports; run the official plugin check tool before every submission.",
        "Ship a readme.txt in WordPress.org format, a settings page under the admin menu, and WP-CLI commands for anything an administrator may want to script.",
        "Use the WordPress options and custom-table APIs; never write to core tables directly; add an uninstall hook that removes options only when the user asks.",
    ],
    "firefox": [
        "Build a WebExtension on the latest manifest version so the same code ships to Firefox and Chromium browsers; request the minimum permissions and explain each one in the listing.",
        "No remote code, no bundled minified third-party code without source; keep settings in extension storage and use browser sync storage where available.",
        "Submit to addons.mozilla.org with reproducible build instructions; keep the source repository public.",
        "Run the extension on the current release and the extended-support release of Firefox in CI.",
    ],
    "openvsx": [
        "Build a VS Code extension in TypeScript on the public extension API; publish to Open VSX and the Visual Studio Marketplace under the new name.",
        "Activate lazily on the relevant events only; keep the activation time measured and bounded.",
        "Ship tests with the extension test runner and run them on the current stable editor release.",
    ],
    "atlassian": [
        "Build an Atlassian Forge app for the same host product as the incumbent (hosted by Atlassian, so no servers to run); use the Marketplace listing requirements and security self-assessment as part of the definition of done.",
        "Store data in Forge storage, scoped per site; request the minimum scopes and list them in the listing.",
        "Provide an export of all app data per site from day one.",
    ],
    "github": [
        "Build a standalone tool with the same install path as the incumbent (package registry, binary release or container); if the incumbent is a library, keep its public API compatible so dependents can switch with a one-line change.",
        "Publish releases with signed artifacts and a changelog; keep CI green on the operating systems and runtimes the incumbent supported.",
    ],
}

QUALITY = [
    "Automated tests for every requirement above, for the import path, and for the core job; CI runs them on each push.",
    "Accessibility: keyboard operable, labelled controls, current WCAG level AA for any interface you ship.",
    "Internationalisation: all strings translatable; English first.",
    "Privacy: no personal data collection beyond what a feature needs; a plain-language privacy statement in the listing.",
    "Security: dependencies pinned and audited; no secrets in the repository; input validated at every boundary.",
    "Documentation: a README with install, settings and import steps; a CHANGELOG; a public issue tracker.",
    "Observability for yourself: a debug log users can switch on and attach to issues, with no automatic upload.",
]


def _req_lines(w: Writer, c: Cluster, ev: dict[int, dict], letter: str) -> list[str]:
    title, req, acc = REQUIREMENTS.get(c.key, ("A specific fix", c.fix if c.fix != "unknown" else "Address the quoted complaints.", "Each quoted complaint maps to a passing acceptance test."))
    out = [f"### Requirement {letter}: {title}", "",
           f"Problem users report: **{c.label}** ({w.cite(c.size, c.evidence_ids)} complaints" + (f"; {c.summary}" if c.summary else "") + ").", "",
           f"- Requirement: {req}", f"- Acceptance: {acc}", "- Evidence (verbatim):"]
    for e in top_quotes([ev[i] for i in c.evidence_ids if i in ev]):
        out.append(f"  - {w.quote(e, 240)}")
    out.append("")
    return out


def generate_build_prompt(conn: sqlite3.Connection, entity_id: int, config, ctx=None) -> str:
    v, signals, clusters, score = ctx or load_context(conn, entity_id, config)
    ev = {e["id"]: e for e in v.evidence}
    w = Writer(ev)
    p = v.primary or {}
    src = p.get("source")
    where = MARKETPLACES.get(src, src or "unknown")
    aud, proxy = v.audience()
    last = v.last_update()
    desc = v.metric("description", prefer="primary")
    specific = [c for c in clusters if c.key != "other"]
    unknowns: list[str] = []

    L: list[str] = [f"# Build specification: a replacement for {v.name}", "",
                    f"<!-- meta: generated {now_iso()}; entity id {entity_id}; Orphan Radar build prompt -->", "",
                    "You are an AI system that builds complete software products. Build the product specified below end to end: "
                    "repository, code, tests, documentation, import tool, listing assets and release checklist. Work through the "
                    "milestones in order and stop at each definition of done. Treat every quoted user complaint as a test case. "
                    "Where this document says *unknown*, research the answer before building on it, and record what you found.", ""]

    # 1 Mission
    L += ["## 1. Mission", "",
          f"Replace **{v.name}**, listed on {where}" + (f" (<{p.get('url')}>)" if p.get("url") else "") + ", for users who are stranded by it. "
          f"The incumbent has {w.fact(aud)} {'GitHub stars (an audience proxy)' if aud and aud.key == 'github_stars' else ('downloads (an audience proxy)' if proxy else 'users')}"
          + (f" and was last updated {w.fact(last)}" if last else "") + ". "
          + (f"In its own listing's words it exists to: “{snippet(str(desc.value), 240)}”{w.ref(desc.evidence_ids)}." if desc else "Its listing description is unknown."), "",
          "Signals found: " + (", ".join(k for k, s in signals.items() if s.present) or "none strong") + ". "
          "The goal is the smallest product that does the incumbent's job and removes the complaints below, shipped where its users already look.", ""]

    # 2 Who it is for and what went wrong
    L += ["## 2. Who it is for, and what went wrong", ""]
    for kind, name in (("abandonment", "Abandonment"), ("displacement", "Displacement"), ("pain", "Pain")):
        s = signals[kind]
        if s.reasons:
            L.append(f"- **{name}** ({'present' if s.present else 'weak'}): " + "; ".join(
                r.text + ": " + ", ".join(_phrase(w, f) for f in r.facts) for r in s.reasons))
        else:
            L.append(f"- **{name}**: none found.")
    events = sorted([e for e in v.evidence if any(t.startswith("event:") for t in e["tag_list"]) and e["type"] != "metric"], key=lambda e: e["date_posted"] or "", reverse=True)[:4]
    if events:
        L += ["", "What users and maintainers said about the events:"]
        L += [f"- {w.quote(e, 200)}" for e in events]
    L.append("")

    # 3 Product definition
    L += ["## 3. Product definition", "",
          "- Working name: choose a new name and new branding. Do not reuse the incumbent's name, logo, screenshots or wording; mention it only as the product you import from, where the marketplace allows that.",
          f"- Job to be done: " + (f"“{snippet(str(desc.value), 240)}”{w.ref(desc.evidence_ids)}" if desc else "unknown; read the incumbent's listing and documentation first and write it in one sentence."),
          f"- Platform and distribution: {where}" + (f", same category as the incumbent (<{p.get('url')}>)" if p.get("url") else "") + ".",
          "- Non-goals for the first release: anything not covered by a requirement below. Write them down explicitly in the README so scope cannot creep.", ""]

    # 4 Requirements
    L += ["## 4. Requirements and acceptance criteria", "",
          "Requirement A is parity with the incumbent's core job; the rest come from clustered user complaints, strongest first. Every acceptance criterion must become an automated test.", "",
          "### Requirement A: Parity with the incumbent's core job", "",
          f"- Requirement: do what the incumbent does today" + (f": “{snippet(str(desc.value), 200)}”{w.ref(desc.evidence_ids)}" if desc else " (unknown: study the listing and documentation and list the features)") + ".",
          "- Acceptance: a feature checklist derived from the incumbent's public listing and documentation is complete, with a test per feature.", ""]
    letters = "BCDEFGHIJK"
    for i, c in enumerate(specific[:8]):
        L += _req_lines(w, c, ev, letters[i])
    if not specific:
        L += ["No specific complaint clusters exist in the evidence, so requirements beyond parity are unknown. Collect complaints before building more than parity.", ""]
        unknowns.append("Which specific problems users have (no complaint clusters in the evidence).")
    other = next((c for c in clusters if c.key == "other"), None)
    if other:
        L += [f"There are also {w.cite(other.size, other.evidence_ids)} complaints too vague to cluster; read them once for context, do not derive requirements from them.", ""]

    # 5 Switching wedge
    L += ["## 5. Switching: import from the incumbent", ""]
    formats, rows = export_mentions(v)
    if formats:
        L.append("Formats named in the evidence: " + ", ".join(f"{k}{w.ref(ids)}" for k, ids in formats.items()) + ".")
    else:
        L.append("Export format of the incumbent: unknown.")
        unknowns.append("Where the incumbent stores data and settings, and whether it can export them.")
    for e in rows[:3]:
        L.append(f"- {w.quote(e, 200)}")
    L += ["", "Build a one-click import that:",
          "- reads the incumbent's data and settings from wherever it stores them (verify the location and format first and document it);",
          "- maps every incumbent setting to a setting of the new product, with sensible defaults for anything unmapped, and shows the user the mapping before applying it;",
          "- is idempotent and reversible: running it twice changes nothing, and an undo restores the previous state;",
          "- is covered by a fixture-based test using a real export or a real settings dump from the incumbent.", ""]

    # 6 Architecture
    L += ["## 6. Architecture and platform guidance", ""]
    L += [f"- {line}" for line in PLATFORM.get(src, ["Platform unknown: match how the incumbent is installed and distributed."])]
    plat = v.metric("platform_current_version", prefer="primary")
    tested = v.metric("tested_up_to", prefer="primary")
    if plat:
        L.append(f"- Current platform release at retrieval time: {w.fact(plat)}" + (f"; the incumbent is tested only up to {w.fact(tested)}" if tested else "") + ".")
    lic = v.metric("license", prefer="primary")
    if lic:
        L.append(f"- The incumbent's license is “{lic.value}”{w.ref(lic.evidence_ids)}. Read its code and data formats to learn the job; copy code only if that license permits it, and comply with it if you do.")
    else:
        L.append("- The incumbent's license is unknown: do not copy its code.")
        unknowns.append("The incumbent's license and whether forking is permitted.")
    L += ["- Keep the architecture as small as the requirements allow: one codebase, no server unless a requirement needs one, no account system unless a requirement needs one.", ""]

    # 7 Quality bar
    L += ["## 7. Quality bar", ""] + [f"- {q}" for q in QUALITY] + [""]

    # 8 Listing and launch
    L += ["## 8. Listing and launch", "",
          f"- Publish on **{where}** in the incumbent's category" + (f" (<{p.get('url')}>)" if p.get("url") else "") + ".",
          "- Listing copy: lead with the fixes in section four, in the users' own words; state the import in the second sentence; state the license, privacy stance and support channel."]
    sugg = replacement_searches(v)
    if sugg:
        L.append("- Searches people already make (use these phrases in the listing title or first paragraph):")
        for s_, eid in sugg[:12]:
            L.append(f"  - `\u201c{s_}\u201d`{w.ref([eid])}" if any(ch.isdigit() for ch in s_) else f"  - `{s_}`{w.ref([eid])}")
    else:
        L.append("- Replacement searches: " + ("none found" if v.of_type("search_suggestion") else "unknown (not checked)") + ".")
    asks = alternative_threads(v)
    if asks:
        L.append("- Public threads where people asked for an alternative (answer there with a link once the product is live; no automated posting):")
        for e in asks[:5]:
            L.append(f"  - [{safe_title(e['extra'].get('title') or e['text'])}]({e['url']}){w.ref([e['id']])}")
    L.append("")

    # 9 Pricing
    L += ["## 9. Pricing", ""]
    bm, rp = v.metric("business_model"), v.metric("requires_payment")
    if bm and bm.value == "commercial":
        L.append(f"- The incumbent's listing declares a commercial business model{w.ref(bm.evidence_ids)}: paid upgrades or services exist, so users of this category are used to paying. Exact prices: unknown.")
    elif rp:
        L.append(f"- The incumbent requires payment for some features{w.ref(rp.evidence_ids)}. Exact prices: unknown.")
    else:
        L.append("- Whether the incumbent charges: unknown from the evidence.")
    for e in paying_mentions(v)[:3]:
        L.append(f"- Users on paying: {w.quote(e, 180)}")
    L += ["- Rivals' prices: unknown. Before setting a price, list the three nearest maintained rivals and their prices in the README.",
          "- Default plan: free tier with every feature in section four; one paid tier for team, business or volume needs; one-time or yearly, no dark patterns, cancel in one click.", ""]

    # 10 Milestones
    L += ["## 10. Milestones and definition of done", "",
          "- Milestone one, parity: Requirement A passes; the product installs from the marketplace or package in a test environment.",
          "- Milestone two, the fixes: every requirement from the complaint clusters passes its acceptance test; quoted complaints are regression tests.",
          "- Milestone three, switching: the one-click import passes its round-trip and fixture tests; undo works.",
          "- Milestone four, release: listing assets, privacy statement, license file, changelog, issue tracker, and the quality bar in section seven are complete; a first release is published under the new name.",
          "- Done means: all tests green in CI, the listing live, the import documented, and a short launch note ready for the threads in section eight.", ""]

    # 11 Unknowns
    if not v.of_type("search_suggestion"):
        unknowns.append("Whether people search for an alternative (replacement searches were not checked).")
    if not v.metric("business_model") and not v.metric("requires_payment"):
        unknowns.append("What the incumbent and its rivals charge.")
    unknowns.append("Whether a maintained replacement already dominates the category (check the marketplace before building).")
    L += ["## 11. Unknowns to resolve before building", ""] + [f"- {u}" for u in unknowns] + [""]

    # 12 Effort and value signals
    comps = {c["name"]: c for c in score.get("components", [])}
    L += ["## 12. Effort and value signals from the research", ""]
    for key, label in (("ease_of_development", "Ease of development"), ("potential_profit", "Potential profit"), ("demand", "Proven demand")):
        c = comps.get(key)
        if c:
            ids = sorted({i for part in c["parts"] for i in part["evidence_ids"]})
            pts = w.cite(c["points"], ids) if ids and c["points"] else ("none" if not c["points"] else "unscored")
            L.append(f"- {label}: {pts} of cfg:{fmt(c['max'])} points. " + "; ".join(part["label"] for part in c["parts"] if part["got"]) + ".")
    L.append("")

    md = "\n".join(L) + "\n" + w.footnotes() + "\n"
    problems = audit_brief(conn, md, extra_names=[q["name"] for q in v.products] + [v.name])
    if problems:
        raise ValueError("build prompt failed the traceability audit: " + "; ".join(problems[:5]))
    conn.execute("INSERT OR REPLACE INTO build_prompts (entity_id, generated_at, markdown, facts_json) VALUES (?,?,?,?)",
                 (entity_id, now_iso(), md, dumps(w.facts)))
    conn.commit()
    return md


def write_build_prompts(conn: sqlite3.Connection, config, only: list[int] | None = None) -> tuple[list[int], dict[int, str]]:
    return write_documents(conn, config, [generate_build_prompt], only)
