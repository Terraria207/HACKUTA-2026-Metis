"""Odysseus proposals are quarantined, independently checked and never self-ranked.
A pattern trigger alone never creates an accepted mathematical statement.
"""

from metis.graph import EdgeInput
from metis.store import now
from metis.pipeline import CREW


def consider(pipeline, run, patterns):
    if run["fixture"]:
        return []  # Never invent a discovery in deterministic mode.
    store = pipeline.store
    journey, g, nodes = pipeline.context(run)
    created = []
    for pattern in patterns:
        if (
            pattern.get("status")
            != "awaiting independent concept proposal and blind testing"
        ):
            continue
        key = pattern["id"]
        result = pipeline.call(
            "odysseus",
            {
                "task": "A recurring cross-paper pattern suggests a missing concept. Return candidate:null if insufficient. Otherwise candidate {name,statement,description,kind:definition|conjecture,home_group}. Do not claim truth or novelty. Existing home_group only, or proposed_group {name,description,parent,msc} under existing island or subfield.",
                "pattern": pattern,
                "groups": [
                    {
                        "id": gg["id"],
                        "name": gg["name"],
                        "depth": gg["depth"],
                        "msc": gg["msc"],
                    }
                    for gg in g["groups"]
                ],
                "supporting_edges": [
                    e
                    for e in g["edges"]
                    if e.get("run_id") in pattern["runs"]
                    and e["tier"] == "intuitive"
                    and e.get("review_status") == "passed"
                ],
            },
            run,
            "concept:" + key,
        )
        candidate = result.get("candidate")
        if not candidate:
            store.patch("memory", key, status="no candidate", checked=now())
            continue
        if candidate.get("kind") not in ("definition", "conjecture") or not all(
            candidate.get(k) for k in ("name", "statement", "description")
        ):
            raise ValueError("Malformed orchestrator concept")
        group = next(
            (gg for gg in g["groups"] if gg["id"] == candidate.get("home_group")), None
        )
        if not group:
            proposed = result.get("proposed_group", {})
            parent = next(
                (
                    gg
                    for gg in g["groups"]
                    if gg["id"] == proposed.get("parent") and gg["depth"] in (1, 2)
                ),
                None,
            )
            if not parent or not all(
                proposed.get(k) for k in ("name", "description", "msc")
            ):
                store.patch("memory", key, status="held: invalid home group")
                continue
            gid = run["id"] + ":group:" + key
            group = dict(
                proposed,
                id=gid,
                layer="journey:" + journey["id"],
                run_id=run["id"],
                depth=parent["depth"] + 1,
                ancestors=parent["ancestors"] + [gid],
                island=parent["island"],
                concept_count=0,
                source="Odysseus",
            )
            store.put("groups", group)
            g["groups"].append(group)
        ident = journey["id"] + ":odysseus:" + key
        node = dict(
            candidate,
            id=ident,
            layer="journey:" + journey["id"],
            run_id=run["id"],
            status="Proposed",
            home_group=group["id"],
            ancestors=group["ancestors"],
            island=group["island"],
            integrated=False,
            fixture=False,
            source={"agent": "Odysseus", "pattern_id": key},
            checks=[],
        )
        store.put("concepts", node)
        nodes[ident] = node
        checks = []
        verdict = pipeline.call(
            "penelope",
            {
                "task": "Apply the strictest bar to this proposed concept: well-defined, nontrivial, not renamed duplicate. Return well_defined,not_trivial,not_duplicate booleans and reason.",
                "candidate": {
                    "statement": node["statement"],
                    "description": node["description"],
                    "kind": node["kind"],
                },
                "existing_concepts": [
                    {"statement": n["statement"], "description": n["description"]}
                    for n in nodes.values()
                    if n["id"] != ident
                ],
            },
            run,
            "concept-review:" + key,
        )
        checks.append({"stage": "strict review", "result": verdict})
        passed = all(
            verdict.get(k) is True
            for k in ("well_defined", "not_trivial", "not_duplicate")
        )
        if passed:
            literature = pipeline.call(
                "tiresias",
                {
                    "task": "Search this concept itself. Return found:boolean,sources:[{url,location,excerpt}],failures:[string],summary. Negative searches cannot establish novelty.",
                    "concept": {
                        "statement": node["statement"],
                        "description": node["description"],
                    },
                },
                run,
                "concept-literature:" + key,
                grounded=True,
            )
            checks.append({"stage": "literature", "result": literature, "time": now()})
            complete = literature.get("_search_complete") and not literature.get(
                "failures"
            )
            urls = {
                c.get("web", {}).get("uri")
                for c in (literature.get("_grounding") or {}).get("groundingChunks", [])
            }
            sources = [
                s
                for s in literature.get("sources", [])
                if s.get("url") in urls and s.get("location") and s.get("excerpt")
            ]
            if complete and literature.get("found") is True and sources:
                store.patch(
                    "concepts",
                    ident,
                    status="Established",
                    source=dict(node["source"], literature=sources),
                    checks=checks,
                    rediscovery=True,
                )
                store.patch("memory", key, status="rediscovery", concept_id=ident)
                created.append(ident)
                continue
            if not complete or literature.get("found") is not False:
                passed = False
        accepted_edges = []
        if passed:
            # Each fresh context is blinded to author, trigger and other crew responses.
            input_node = {
                k: node[k] for k in ("id", "statement", "description", "kind")
            }
            support = set()
            for i, crew in enumerate(CREW):
                result = pipeline.call(
                    "crew" + str(i),
                    {
                        "task": (
                            "Try to break the candidate with boundary cases. Return counterexample_found:boolean,reason,proposals matching schema."
                            if i == 3
                            else "Connect this candidate to established concepts. Return counterexample_found:boolean,reason,proposals matching schema."
                        ),
                        "candidate": input_node,
                        "established": [
                            {
                                "id": n["id"],
                                "statement": n["statement"],
                                "description": n["description"],
                            }
                            for n in nodes.values()
                            if n["status"] != "Proposed"
                        ],
                        "edge_schema": EdgeInput.model_json_schema(),
                    },
                    run,
                    "concept-blind:" + key + ":" + str(i),
                )
                checks.append(
                    {"stage": "blind testing", "crew": crew, "result": result}
                )
                if result.get("counterexample_found") is not False:
                    passed = False
                    break
                for j, raw in enumerate(
                    result.get("proposals", [])[: journey["settings"]["p"]]
                ):
                    edge = EdgeInput.model_validate(raw).model_dump()
                    if ident not in edge["premises"] + [edge["conclusion"]] or not all(
                        n in nodes for n in edge["premises"] + [edge["conclusion"]]
                    ):
                        continue
                    e = pipeline.save_edge(
                        run,
                        edge,
                        crew,
                        {
                            "agent": crew,
                            "kind": "orchestrator_support",
                            "blind_test": True,
                        },
                        "concept-edge:" + key + str(i) + str(j),
                    )
                    ok, tier, review, independent = pipeline.review(
                        run, e, nodes, "concept-edge-review:" + key + str(i) + str(j)
                    )
                    store.patch(
                        "edges",
                        e["id"],
                        review_status="passed" if ok else "rejected",
                        tier=tier,
                        independent=independent,
                    )
                    if ok:
                        support.add(crew)
                        accepted_edges.append(e["id"])
            passed = passed and len(support) >= journey["settings"]["blind_support"]
        if (
            passed
            and node["kind"] == "definition"
            and journey["settings"].get("formalize_definitions")
        ):
            formalization = formalize_definition(pipeline, run, journey, node, key)
            checks.append({"stage": "definition type-check", "result": formalization})
            passed = formalization.get("type_checked") is True
        status = "Accepted" if passed else "Proposed"
        formal_attempt = None
        if passed and node["kind"] == "conjecture":
            # Overview, new-node check 4: an accepted conjecture may be attempted in Lean; only an
            # audited sandbox compilation with independent statement alignment makes it Proven.
            formal_attempt = prove_conjecture(pipeline, run, journey, node, key)
            checks.append({"stage": "formal proof attempt", "result": formal_attempt})
            if formal_attempt.get("machine_verified"):
                status = "Proven"
        store.patch(
            "concepts",
            ident,
            status=status,
            checks=checks,
            check_status="passed" if passed else "failed or incomplete",
            accepted_edges=accepted_edges,
            formal_attempt=formal_attempt,
        )
        store.patch(
            "memory",
            key,
            status="accepted concept" if passed else "quarantined concept",
            concept_id=ident,
        )
        pipeline.trace(
            run,
            6,
            "Odysseus",
            "Orchestrator conjecture machine-verified (Proven)"
            if status == "Proven"
            else "Orchestrator concept accepted"
            if passed
            else "Orchestrator concept remains quarantined",
            concept_id=ident,
            checks=checks,
        )
        created.append(ident)
    return created


def lean_version(pipeline, journey):
    versions = {
        pipeline.store.get("modules", m).get("mathlib_version") for m in journey["modules"]
    }
    return next(iter(versions)) if len(versions) == 1 else None


def prove_conjecture(pipeline, run, journey, node, key):
    """Hephaestus attempts a Lean proof of an accepted conjecture node.

    Proven means machine verified only: the generated statement must pass independent
    alignment review, compile in the pinned sandbox and clear the axiom audit. A failed or
    unavailable attempt leaves the node Accepted; failure is never evidence against it.
    """
    from metis import formal

    if node.get("kind") != "conjecture":
        raise ValueError("Only conjectures can be proven; definitions stop at Accepted")
    version = lean_version(pipeline, journey)
    if (
        run["fixture"]
        or not pipeline.config.lean_image
        or not pipeline.config.lean_project
    ):
        return {
            "status": "unavailable",
            "machine_verified": False,
            "reason": "Controlled Lean sandbox required; no prover call made",
        }
    candidate = pipeline.call(
        "hephaestus",
        {
            "task": "Return statement and proof Lean expressions proving this exact conjecture with ALL hypotheses. No imports, commands, axioms, sorry, admit, or metaprogramming.",
            "conjecture": {k: node[k] for k in ("statement", "description")},
            "mathlib_version": version,
        },
        run,
        "conjecture-formal:" + key,
    )
    alignment = pipeline.call(
        "alignment",
        {
            "task": "Does the formal statement exactly match the conjecture, preserving every hypothesis and quantifier? Return matches:boolean,reason. Do not assume compilation.",
            "conjecture": {k: node[k] for k in ("statement", "description")},
            "statement": candidate["statement"],
        },
        run,
        "conjecture-alignment:" + key,
    )
    result = formal.verify(
        pipeline.config,
        candidate["statement"],
        candidate["proof"],
        version,
        alignment.get("matches") is True,
    )
    return dict(result, alignment_review=alignment, statement=candidate["statement"])


def attempt_accepted_conjectures(pipeline, run, limit):
    """Stage 4 follow-up: within the remaining per-run proof budget, Hephaestus can attempt
    accepted conjectures from earlier runs that are not yet Proven."""
    if limit <= 0 or run["fixture"]:
        return []
    store = pipeline.store
    journey = store.get("journeys", run["journey_id"])
    attempted = []
    for node in store.all("concepts", layer="journey:" + journey["id"]):
        if len(attempted) >= limit:
            break
        if (
            node.get("status") != "Accepted"
            or node.get("kind") != "conjecture"
            or node.get("invalidated")
            or (node.get("formal_attempt") or {}).get("status") in ("verified", "failed")
        ):
            continue
        attempt = prove_conjecture(pipeline, run, journey, node, node["id"] + ":" + run["id"])
        attempted.append(node["id"])
        store.patch(
            "concepts",
            node["id"],
            formal_attempt=attempt,
            status="Proven" if attempt.get("machine_verified") else "Accepted",
        )
        pipeline.trace(
            run, 4, "Hephaestus",
            "Conjecture proof attempt " + attempt["status"],
            concept_id=node["id"], attempt=attempt,
        )
    return attempted


def formalize_definition(pipeline, run, journey, node, key):
    from metis import formal

    version = lean_version(pipeline, journey)
    if (
        run["fixture"]
        or not pipeline.config.lean_image
        or not pipeline.config.lean_project
    ):
        return {
            "status": "unavailable",
            "type_checked": False,
            "machine_verified": False,
            "reason": "Controlled Lean sandbox required; no formalization call made",
        }
    candidate = pipeline.call(
        "hephaestus",
        {
            "task": "Formalize this definition as Lean type_expression and value expressions. Preserve all parameters and conditions. No imports, commands, placeholders or extra axioms.",
            "definition": {k: node[k] for k in ("statement", "description")},
            "mathlib_version": version,
        },
        run,
        "definition-formal:" + key,
    )
    alignment = pipeline.call(
        "alignment",
        {
            "task": "Does this Lean definition preserve exactly the supplied definition, all parameters and conditions? Return matches:boolean,reason. Type checking alone does not imply alignment.",
            "definition": {k: node[k] for k in ("statement", "description")},
            "type_expression": candidate["type_expression"],
            "value": candidate["value"],
        },
        run,
        "definition-alignment:" + key,
    )
    result = formal.verify_definition(
        pipeline.config,
        candidate["type_expression"],
        candidate["value"],
        version,
        alignment.get("matches") is True,
    )
    return dict(
        result,
        alignment_review=alignment,
        type_expression=candidate["type_expression"],
        value=candidate["value"],
    )
