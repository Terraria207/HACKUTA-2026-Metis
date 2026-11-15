"""Odyssey discussion (UI spec): each agent's trace output restyled as dialogue between the
Odyssey characters.

The narrator restyles wording only. Verdicts, tiers, existing tags, concept names and citations
are never taken from the narrator: they are read from the stored records and shown beside the
line, verbatim. A narrator line that mentions a status word the entry does not carry is discarded
for the template. Narration never fails, pauses or delays a run: any provider problem falls back
to a deterministic template, which is also all that fixture mode ever uses.
"""

import hashlib

from metis.store import now

# Pipeline step speakers (UI spec, "Who speaks for each step"). The decomposer has no character
# yet and no particular god portrays "the gods": both are open questions in the spec, so they
# speak under their role names.
SPEAKERS = {
    "decomposer": {"name": "The decomposer", "portrait": "decomposer"},
    "gods": {"name": "The gods", "portrait": "gods"},
    "Eurylochus": {"name": "Eurylochus", "portrait": "eurylochus"},
    "Elpenor": {"name": "Elpenor", "portrait": "elpenor"},
    "Polites": {"name": "Polites", "portrait": "polites"},
    "Perimedes": {"name": "Perimedes", "portrait": "perimedes"},
    "Penelope": {"name": "Penelope", "portrait": "penelope"},
    "Hephaestus": {"name": "Hephaestus", "portrait": "hephaestus"},
    "Tiresias": {"name": "Tiresias", "portrait": "tiresias"},
    "Odysseus": {"name": "Odysseus", "portrait": "odysseus"},
}
OPENERS = {
    "decomposer": ["I have laid the paper out, part by part.", "The paper is unrolled and sorted."],
    "Eurylochus": ["I looked from above, where the general results stand.", "From the high ground, this is what I saw."],
    "Elpenor": ["I built it up from the first stones.", "Starting from the plainest structures, I found this."],
    "Polites": ["I followed how the idea came down through the years.", "Tracing its lineage, I came upon this."],
    "Perimedes": ["I pushed at the edges, where things break.", "At the extremes, this is what held."],
    "Penelope": ["I have tested this thread at my loom.", "I pulled at the weave to see what holds."],
    "Hephaestus": ["I put it to the forge.", "The anvil does not flatter."],
    "Tiresias": ["I asked among those who came before.", "I searched what others have already seen."],
    "Odysseus": ["I have weighed what the crew brought back.", "Here is how the findings stand."],
    "gods": ["It is set in stone.", "The island takes shape."],
}
# Summaries folded into one exchange per comparison instead of one pop-up each.
FOLDED = {"Proposal recorded", "Malformed crew proposal rejected"}
STATUS_WORDS = [
    "verified", "cited", "intuitive", "existing", "not found", "unchecked", "passed", "rejected",
    "proven", "accepted", "potentially new", "novel", "new result", "machine-verified",
]


def facts_for(store, data):
    """Verbatim facts for the pop-up, read from stored records, never from a model."""
    facts = {}
    names = lambda ids: [
        (store.get("concepts", i) or {}).get("name") or i for i in ids
    ]
    edge = store.get("edges", data["edge_id"]) if data.get("edge_id") else None
    if edge:
        facts.update(
            edge_type=edge["type"],
            tier=edge["tier"],
            existing=edge.get("existing"),
            premises=names(edge["premises"]),
            conclusion=names([edge["conclusion"]])[0],
        )
        citations = [
            " — ".join(str(v[k]) for k in ("source", "location") if v.get(k))
            for v in edge.get("evidence", [])
            if isinstance(v, dict) and v.get("source")
        ]
        if citations:
            facts["citations"] = citations[:3]
    concept = store.get("concepts", data["concept_id"]) if data.get("concept_id") else None
    if concept:
        facts.update(concept=concept.get("name"), status=concept.get("status"))
    for key in ("reason", "perspective", "band"):
        if isinstance(data.get(key), str) and data[key]:
            facts[key] = data[key][:400]
    attempt = data.get("attempt")
    if isinstance(attempt, dict) and attempt.get("status"):
        facts["formal_status"] = attempt["status"]
    return facts


def target_for(data, facts):
    if data.get("edge_id") and "tier" in facts:
        return {"kind": "edge", "id": data["edge_id"]}
    if data.get("concept_id") and "concept" in facts:
        return {"kind": "concept", "id": data["concept_id"]}
    return None


def template_line(agent, summary, key):
    options = OPENERS.get(agent) or [""]
    opener = options[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)]
    return (opener + " " + summary.rstrip(".") + ".").strip()


def faithful(line, summary, facts):
    """Reject a narrated line that introduces a status word its entry does not carry."""
    if not isinstance(line, str) or not 0 < len(line.strip()) <= 500:
        return False
    source = (summary + " " + " ".join(str(v) for v in facts.values())).lower()
    lowered = line.lower()
    return not any(word in lowered and word not in source for word in STATUS_WORDS)


def narrate(pipeline, run, agent, summary, facts, key):
    """Returns (line, source). The model is used only in live runs with a narrator role."""
    line = template_line(agent, summary, key)
    journey = pipeline.store.get("journeys", run["journey_id"]) or {}
    if (
        run.get("fixture")
        or not journey.get("settings", {}).get("narration", True)
        or "narrator" not in pipeline.providers.roles
    ):
        return line, "template"
    try:
        result = pipeline.providers.call(
            "narrator",
            {
                "task": "Restyle this pipeline log entry as one or two short lines of dialogue spoken by the named Odyssey character. Restyle wording only: do not add, remove or change any fact. Do not state a verdict, tier, literature status, concept name or citation that is not in facts; those are displayed beside your line, verbatim. Never claim novelty or proof. Return {line}.",
                "speaker": SPEAKERS.get(agent, {"name": agent})["name"],
                "summary": summary,
                "facts": facts,
            },
            run,
            "narrate:" + key,
        )
        if faithful(result.get("line"), summary, facts):
            return result["line"].strip(), "narrator"
    except Exception:
        pass  # Budget, credentials, network, schema: the template stands; the run is untouched.
    return line, "template"


def discuss(pipeline, run, entry):
    """One discussion line for one trace entry. Never raises."""
    try:
        agent = entry["agent"]
        if agent not in SPEAKERS or entry["summary"] in FOLDED:
            return None
        facts = facts_for(pipeline.store, entry["data"])
        line, source = narrate(pipeline, run, agent, entry["summary"], facts, entry["id"])
        return _save(pipeline, run, entry["step"], agent, line, source, entry["summary"], facts,
                     [entry["id"]], target_for(entry["data"], facts), "d_" + entry["id"])
    except Exception:
        return None


def discuss_fold(pipeline, run, target, trace_ids, edge_ids, rejected):
    """Several proposals arriving together become one short exchange (UI spec: folding)."""
    try:
        if not trace_ids:
            return None
        agent = target["crew"]
        summary = "%d proposal(s) recorded against the %s %s target%s" % (
            len(edge_ids), target["band"], target.get("kind", "group"),
            "; %d malformed proposal(s) rejected" % rejected if rejected else "",
        )
        facts = {"perspective": target["perspective"], "band": target["band"], "proposals": []}
        for eid in edge_ids[:10]:
            edge_facts = facts_for(pipeline.store, {"edge_id": eid})
            if edge_facts:
                facts["proposals"].append(
                    " + ".join(edge_facts["premises"]) + " → " + edge_facts["conclusion"]
                    + " (" + edge_facts["edge_type"] + ", " + edge_facts["tier"] + ")"
                )
        key = hashlib.sha256("".join(trace_ids).encode()).hexdigest()
        line, source = narrate(pipeline, run, agent, summary, facts, key)
        return _save(pipeline, run, 2, agent, line, source, summary, facts, trace_ids,
                     {"kind": "edge", "id": edge_ids[0]} if edge_ids else None, "d_" + key)
    except Exception:
        return None


def _save(pipeline, run, step, agent, line, source, summary, facts, trace_ids, target, ident):
    speaker = SPEAKERS[agent]
    doc = {
        "id": ident,
        "run_id": run["id"],
        "journey_id": run["journey_id"],
        "step": step,
        "agent": agent,
        "speaker": speaker["name"],
        "portrait": speaker["portrait"],
        "line": line,
        "source": source,
        "summary": summary,
        "facts": facts,
        "trace_ids": trace_ids,
        "target": target,
        "time": now(),
        "fixture": run.get("fixture", False),
    }
    if pipeline.store.insert("discussion", doc):
        pipeline.store.event(run["journey_id"], "discussion", {"id": ident, "run_id": run["id"]})
    return doc
