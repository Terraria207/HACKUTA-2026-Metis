import hashlib
import json
import random
import threading
from typing import Literal
from pydantic import BaseModel, Field
from metis.store import uid, now
from metis.graph import (
    TIERS,
    graph,
    visible_layers,
    EdgeInput,
    duplicate_key,
    score,
    blind_edge,
    adjacency,
    tree_distance,
    invalidate_dependents,
)
from metis.providers import Providers, ProviderUnavailable, BudgetExceeded, AtlasVectors
from metis import formal, narrator

STAGES = [
    "Decompose & integrate",
    "Draw targets",
    "Crew exploration",
    "Independent proof review",
    "Formal proof attempts",
    "Literature search",
    "Ranking & memory",
]
PERSPECTIVES = ["top-down", "first-principles", "historical", "edge-cases"]


class Interrupted(RuntimeError):
    pass


CREW = ["Eurylochus", "Elpenor", "Polites", "Perimedes"]
EXISTING_RANK = {"Not found": 2, "Unchecked": 1, "Existing": 0}


def ranking_key(edge, support_count):
    """Odysseus ranks by tier, bridge score, literature status and independent agreement
    (overview, Odysseus: Responsibilities), in that order. Higher sorts first."""
    return (
        TIERS.get(edge.get("tier"), 0),
        (edge.get("bridge_score") or {}).get("value") or 0,
        EXISTING_RANK.get(edge.get("existing"), 0),
        support_count,
    )


class ExtractedConcept(BaseModel):
    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: Literal["axiom", "definition", "theorem", "conjecture", "construction", "lemma"]
    msc: str = Field(min_length=1)


class Extraction(BaseModel):
    concepts: list[dict] = Field(default_factory=list, max_length=100)
    edges: list[dict] = Field(default_factory=list, max_length=200)
    msc_codes: list[str] = Field(default_factory=list, max_length=10)


def extraction_edge_errors(extraction):
    """Validate concepts and local references before embeddings or integration."""
    keys = set()
    errors = []
    for index, raw in enumerate(extraction["concepts"]):
        try:
            concept = ExtractedConcept.model_validate(raw)
            if concept.key in keys:
                raise ValueError("Duplicate concept key")
            keys.add(concept.key)
        except (ValueError, TypeError) as exc:
            errors.append({"concept_index": index, "reason": str(exc)[:1000]})
    for index, raw in enumerate(extraction["edges"]):
        try:
            edge = EdgeInput.model_validate(raw)
            if any(k not in keys for k in edge.premises + [edge.conclusion]):
                raise ValueError("Unknown extracted concept key")
        except (ValueError, TypeError) as exc:
            errors.append({"edge_index": index, "reason": str(exc)[:1000]})
    return errors


class Pipeline:
    def __init__(self, store, config):
        self.store, self.config = store, config
        self.providers = Providers(store, config)
        self.owner = uid("worker_")
        self.stop = threading.Event()
        self.thread = None

    def recover(self):
        for lock in self.store.all("locks"):
            if not self.store.get("runs", lock["run_id"]):
                self.store.delete("locks", lock["id"])
        for item in self.store.all("rechecks", status="queued"):
            self.enqueue_recheck(item)
        for run in self.store.all("runs"):
            if run["status"] in ("complete", "cancelled") or run["checkpoint"] >= 7:
                self.store.release_run_lock(run["journey_id"], run["id"])
                if run["checkpoint"] >= 7 and run["status"] != "cancelled":
                    self.store.patch("runs", run["id"], status="complete")
            elif run["status"] in ("queued", "running"):
                self.store.insert(
                    "locks", {"id": "active:" + run["journey_id"], "run_id": run["id"]}
                )
                self.enqueue(run)

    def start(self):
        self.recover()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)

    def trace(self, run, stage, agent, summary, **data):
        ident = hashlib.sha256(
            (
                run["id"]
                + str(stage)
                + agent
                + summary
                + json.dumps(data, sort_keys=True, default=str)
            ).encode()
        ).hexdigest()
        entry = {
            "id": ident,
            "run_id": run["id"],
            "journey_id": run["journey_id"],
            "step": stage,
            "agent": agent,
            "summary": summary,
            "data": data,
            "time": now(),
            "fixture": run["fixture"],
        }
        if self.store.insert("trace", entry):
            self.store.event(run["journey_id"], "trace", entry)
            narrator.discuss(self, run, entry)
        return ident

    def enqueue(self, run):
        jid = (
            run["id"] + ":" + str(run["checkpoint"]) + ":" + str(run.get("attempt", 0))
        )
        old = self.store.get("jobs", jid)
        if old:
            if old["status"] in ("paused", "failed", "done"):
                self.store.patch("jobs", jid, status="queued", available_at=now())
            return
        self.store.insert(
            "jobs",
            {
                "id": jid,
                "run_id": run["id"],
                "journey_id": run["journey_id"],
                "status": "queued",
                "stage": run["checkpoint"],
                "attempt": 0,
                "available_at": now(),
                "lease_until": 0,
            },
        )

    def loop(self):
        while not self.stop.is_set():
            job = self.store.claim(self.owner)
            if job:
                self.work(job)
            else:
                self.stop.wait(0.3)

    def enqueue_recheck(self, item):
        self.store.insert(
            "jobs",
            {
                "id": "recheck:" + item["id"] + ":" + str(item.get("attempt", 0)),
                "kind": "recheck",
                "recheck_id": item["id"],
                "status": "queued",
                "attempt": 0,
                "available_at": now(),
                "lease_until": 0,
            },
        )

    def perform_recheck(self, item):
        if item["status"] == "complete":
            return
        journey = self.store.get("journeys", item["journey_id"])
        e = self.store.get("edges", item["edge_id"])
        original = self.store.get("runs", e.get("run_id")) if e.get("run_id") else None
        # Feedback is a separate budgeted operation, including for terminal runs.
        run = {
            "id": "feedback:" + item["id"],
            "paper_id": (original or {}).get("paper_id"),
            "journey_id": journey["id"],
            "fixture": journey["fixture"],
            "budget_usd": item.get("budget_usd", 0),
            "attempt": item.get("attempt", 0),
        }
        nodes = {n["id"]: n for n in graph(self.store, journey)["concepts"]}
        passed, tier, result, independent = self.review(
            run, e, nodes, "feedback:" + item["id"]
        )
        if e["layer"] == "journey:" + journey["id"]:
            history = e.get("tier_history", []) + [
                {
                    "tier": tier,
                    "time": now(),
                    "reason": "Wrong-feedback independent re-review",
                    "review_id": item["id"],
                }
            ]
            self.store.patch(
                "edges",
                e["id"],
                review_status="passed" if passed else "rejected",
                invalidated=not passed,
                tier=tier,
                tier_history=history,
            )
        self.store.patch(
            "rechecks",
            item["id"],
            status="complete",
            passed=passed,
            result=result,
            independent=independent,
        )
        if passed:
            if e["layer"].startswith("module:"):
                self.store.put(
                    "memory",
                    {
                        "id": journey["id"] + ":review-override:" + e["id"],
                        "journey_id": journey["id"],
                        "kind": "edge_review_override",
                        "target_id": e["id"],
                        "tier": tier,
                        "existing": "Existing" if tier == "cited" else "Unchecked",
                        "review_id": item["id"],
                    },
                )
            self.store.delete("memory", journey["id"] + ":invalid:" + e["id"])
        self.store.event(
            journey["id"], "recheck", {"feedback_id": item["id"], "passed": passed}
        )

    def work(self, job):
        if job.get("kind") == "recheck":
            try:
                self.perform_recheck(self.store.get("rechecks", job["recheck_id"]))
                self.store.owned_patch(job, status="done")
            except Exception as exc:
                self.store.patch(
                    "rechecks",
                    job["recheck_id"],
                    status="failed",
                    error=type(exc).__name__ + ": " + str(exc)[:300],
                )
                self.store.owned_patch(job, status="failed")
            return
        run = self.store.get("runs", job["run_id"])
        if not run or run["status"] in ("paused", "cancelled", "complete"):
            self.store.owned_patch(
                job, status="paused" if run and run["status"] == "paused" else "done"
            )
            return
        if job["stage"] != run["checkpoint"]:
            self.store.owned_patch(job, status="done")
            return
        run["_job_attempt"] = job.get("attempt", 0)
        run["_job"] = job
        # Renew lease while network/Lean calls run. Worker ownership fences completion.
        done = threading.Event()

        def heartbeat():
            while not done.wait(20):
                if not self.store.owned_patch(job, lease_until=now() + 120):
                    return

        hb = threading.Thread(target=heartbeat, daemon=True)
        hb.start()
        try:
            if not self.store.transition_run(
                run["id"], ("queued", "running"), status="running"
            ):
                raise Interrupted("Run stopped before stage start")
            self.store.patch(
                "journeys", run["journey_id"], status="running", last_activity=now()
            )
            self.trace(
                run,
                run["checkpoint"],
                "system",
                "Stage started: " + STAGES[run["checkpoint"]],
            )
            if not run.get("ingest_only") or run["checkpoint"] in (0, 3, 6):
                getattr(self, "stage" + str(run["checkpoint"]))(run)
            if not self.store.owned_patch(job, lease_until=now() + 120):
                return
            current = self.store.advance_run(run["id"], run["checkpoint"])
            if not current:
                return
            checkpoint = current["checkpoint"]
            status = current["status"]
            self.store.owned_patch(job, status="done")
            self.trace(run, run["checkpoint"], "system", "Stage checkpoint saved")
            if checkpoint == 7 and status == "complete":
                self.store.release_run_lock(run["journey_id"], run["id"])
                self.store.patch(
                    "journeys", run["journey_id"], status="ready", last_activity=now()
                )
                self.store.event(run["journey_id"], "complete", {"run_id": run["id"]})
            elif status == "queued":
                self.enqueue(current)
        except Interrupted:
            current = self.store.get("runs", run["id"])
            self.store.owned_patch(
                job, status="paused" if current["status"] == "paused" else "done"
            )
        except BudgetExceeded as exc:
            self.store.owned_patch(job, status="paused")
            transitioned = self.store.transition_run(
                run["id"],
                ("running", "queued", "paused"),
                status="paused",
                error=str(exc),
                pause_reason="budget",
            )
            if transitioned:
                self.store.patch("journeys", run["journey_id"], status="paused")
            self.trace(run, run["checkpoint"], "system", str(exc))
        except Exception as exc:
            attempts = job.get("attempt", 0) + 1
            # Credentials/configuration are actionable errors; network/schema failures retry boundedly.
            retry = attempts < 3 and not isinstance(
                exc, (ProviderUnavailable, ValueError, KeyError)
            )
            self.store.owned_patch(
                job,
                status="queued" if retry else "failed",
                attempt=attempts,
                available_at=now() + 2**attempts,
                error=type(exc).__name__ + ": " + str(exc)[:300],
            )
            self.store.transition_run(
                run["id"],
                ("running", "queued"),
                status="queued" if retry else "failed",
                error=type(exc).__name__ + ": " + str(exc)[:300],
            )
            if not retry:
                self.store.patch("journeys", run["journey_id"], status="ready")
            self.trace(
                run,
                run["checkpoint"],
                "system",
                "Stage failed; "
                + ("automatic retry scheduled" if retry else "manual Retry available"),
                error=type(exc).__name__ + ": " + str(exc)[:300],
            )
        finally:
            done.set()
            hb.join(timeout=1)

    def ensure_active(self, run):
        current = self.store.get("runs", run["id"])
        if current and current.get("deadline_at") and now() >= current["deadline_at"]:
            self.store.transition_run(run["id"], ("queued", "running"),
                                      status="paused", pause_reason="acceptance_deadline")
            self.store.patch("journeys", current["journey_id"], status="paused")
            raise Interrupted("Acceptance deadline reached")
        if current and current["status"] in ("paused", "cancelled"):
            raise Interrupted("Run stopped")
        job = run.get("_job")
        if job:
            owned = self.store.get("jobs", job["id"])
            if (
                not owned
                or owned.get("owner") != job["owner"]
                or owned.get("status") != "working"
                or owned.get("lease_until", 0) < now()
            ):
                raise Interrupted("Worker lease lost")

    def context(self, run):
        self.ensure_active(run)
        j = self.store.get("journeys", run["journey_id"])
        g = graph(self.store, j)
        return j, g, {n["id"]: n for n in g["concepts"]}

    def call(self, role, payload, run, key, grounded=False):
        self.ensure_active(run)
        # Completed work survives manual retries without another paid request.
        call_key = key + ":attempt0"
        retry = str(run.get("attempt", 0)) + ":" + str(run.get("_job_attempt", 0))
        old = self.store.get(
            "calls", hashlib.sha256((run["id"] + ":" + call_key).encode()).hexdigest()
        )
        if old and old["status"] != "complete" and retry != "0:0":
            call_key += ":retry" + retry
        # A previous retry may itself have completed before a later crash.
        for attempt in range(run.get("attempt", 0) + 1):
            for job_attempt in range(4):
                candidate = (
                    key + ":attempt0:retry" + str(attempt) + ":" + str(job_attempt)
                )
                record = self.store.get(
                    "calls",
                    hashlib.sha256((run["id"] + ":" + candidate).encode()).hexdigest(),
                )
                if record and record["status"] == "complete":
                    call_key = candidate
                    break
        result = self.providers.call(role, payload, run, call_key, grounded)
        self.ensure_active(run)
        return result

    def stage0(self, run):
        journey, g, nodes = self.context(run)
        paper = self.store.get("papers", run["paper_id"])
        layer = "journey:" + journey["id"]
        schema = "extraction-v5"
        spec = self.providers.roles.get("decomposer", {})
        cache_key = hashlib.sha256(
            (
                paper["content_hash"]
                + schema
                + json.dumps(spec, sort_keys=True)
                + str(run["fixture"])
            ).encode()
        ).hexdigest()
        cached = self.store.get("extractions", cache_key)
        if cached:
            extraction = cached["extraction"]
        elif run["fixture"]:
            extraction = {
                "msc_codes": [paper["msc"]],
                "concepts": [
                    {
                        "key": "a",
                        "name": "Fixture: symmetric operator",
                        "statement": "Fixture example of a real symmetric operator on a finite dimensional inner product space.",
                        "description": "Symmetric operator in finite dimensions",
                        "kind": "definition",
                        "msc": paper["msc"],
                    },
                    {
                        "key": "b",
                        "name": "Fixture: spectral decomposition",
                        "statement": "Fixture example of orthogonal spectral decomposition for a real symmetric operator.",
                        "description": "Orthogonal decomposition into real eigenspaces",
                        "kind": "theorem",
                        "msc": paper["msc"],
                    },
                ],
                "edges": [
                    {
                        "premises": ["a"],
                        "conclusion": "b",
                        "type": "related",
                        "directed": True,
                        "tier": "intuitive",
                        "argument": "Illustrative association only; no discovery or proof claimed.",
                        "evidence": [],
                    }
                ],
            }
        else:
            extraction = self.call(
                "decomposer",
                {
                    "task": "Extract mathematical concepts and relationships with full hypotheses. Do not invent citations. Return concepts [{key,name,statement,description,kind,msc}], edges [{premises:[key],conclusion:key,type,directed,tier,argument,evidence:[{source,location,excerpt}]}], msc_codes. For integration include standard referenced concepts and their supporting citations, at most "
                    + str(journey["settings"]["integration_depth"])
                    + " levels. Independently of integration depth, extract relationships WITHIN the paper, including definitions and dependencies used by its results. Preserve all quantifiers, domain restrictions and conditional assumptions in each statement (including hypothetical divergence); a statement must be understandable without the paper. Extract the definitions needed to understand each result. Use dependency or defined_from for descriptive relationships; do not turn them into implications. An association is not a theorem. For excerpts from the input paper use source=input-paper, an exact location and a verbatim quote, not a paraphrase or ellipsis. Tier must be the string cited or intuitive, never a number or verified. No review or verification claims. Allowed types: implies,equivalent,defined_from,dependency,generalizes,special_case,related. Do not invent edges to satisfy a count; an empty list is allowed when unsupported.",
                    "evidence_rules": "Copy excerpts character-for-character from paper_text, allowing only whitespace normalization. Do not translate PDF formula text to LaTeX inside excerpts. Prefer intact prose excerpts around the cited definition/proof step. Separate multi-part theorems into individual claims so a dependency can identify the specific result it supports.",
                    "output_budget": "Keep the complete JSON response concise, within 6500 tokens. Prioritize the paper's principal definitions, results and explicit internal dependencies. Avoid duplicating long statements in descriptions or arguments. Return valid, complete JSON.",
                    "paper_text": paper["text"],
                    "contract": Extraction.model_json_schema(),
                    "edge_schema": EdgeInput.model_json_schema(),
                    "concept_schema": ExtractedConcept.model_json_schema(),
                },
                run,
                "extract",
            )
        extraction = Extraction.model_validate(extraction).model_dump()
        if not cached and not run["fixture"]:
            errors = extraction_edge_errors(extraction)
            if errors or not extraction["edges"]:
                self.trace(run, 0, "decomposer", "Extraction relationship repair requested",
                           errors=errors, empty=not extraction["edges"])
                extraction = Extraction.model_validate(self.call(
                    "decomposer",
                    {
                        "task": "Repair the complete extraction using the original paper. Correct schema errors and unknown references; preserve valid concepts and relationships. Check for omitted relationships WITHIN the paper, including defined_from and dependency relations. Preserve all hypotheses and quantifiers in standalone statements. Use only source-supported relationships and exact verbatim evidence with source=input-paper and location. Tier must be cited or intuitive, never numeric or verified. Return the complete extraction. Do not invent relationships: empty edges is valid if none are supported.",
                        "paper_text": paper["text"], "extraction": extraction,
                        "errors": errors, "contract": Extraction.model_json_schema(),
                        "edge_schema": EdgeInput.model_json_schema(),
                        "concept_schema": ExtractedConcept.model_json_schema(),
                    }, run, "extract:repair",
                )).model_dump()
                remaining = extraction_edge_errors(extraction)
                if remaining:
                    raise ValueError("Extraction relationships invalid after one repair attempt")
            if not extraction["edges"]:
                self.trace(run, 0, "decomposer", "No within-paper relationships extracted after coverage check")
        if not cached:
            self.store.insert(
                "extractions",
                {
                    "id": cache_key,
                    "cache_key": cache_key,
                    "extraction": extraction,
                    "schema": schema,
                    "fixture": run["fixture"],
                    "time": now(),
                },
            )
        mapping = {}
        embeddings = None
        if not run["fixture"] and extraction["concepts"]:
            result = self.call(
                "embeddings",
                {"texts": [c["description"] for c in extraction["concepts"]]},
                run,
                "extract-vectors",
            )
            embeddings = result["embeddings"]
            if len(embeddings) != len(extraction["concepts"]):
                raise ValueError("Embedding count mismatch")
        for i, c in enumerate(extraction["concepts"]):
            if not all(
                c.get(k) for k in ("key", "name", "statement", "description", "kind")
            ):
                raise ValueError("Incomplete extracted concept")
            if c["kind"] not in (
                "axiom",
                "definition",
                "theorem",
                "conjecture",
                "construction",
                "lemma",
            ):
                raise ValueError("Invalid concept kind")
            matches = [
                n
                for n in nodes.values()
                if n["statement"].strip().casefold()
                == c["statement"].strip().casefold()
            ]
            if not matches and not run["fixture"]:
                candidates = self.near_duplicates(
                    journey, nodes, c["description"], embeddings[i]
                )
                if candidates:
                    verdict = self.call(
                        "penelope",
                        {
                            "task": "Is the extracted concept mathematically identical, with identical hypotheses, to a candidate? Return match_id or null.",
                            "concept": c,
                            "candidates": [
                                {"id": n["id"], "statement": n["statement"]}
                                for n in candidates
                            ],
                        },
                        run,
                        "match:" + c["key"],
                    )
                    matches = [
                        n for n in candidates if n["id"] == verdict.get("match_id")
                    ]
            if matches:
                mapping[c["key"]] = matches[0]["id"]
                continue
            groups = [
                gg
                for gg in g["groups"]
                if gg["depth"] == 3 and c.get("msc", paper["msc"]).startswith(gg["msc"])
            ]
            if not groups:
                groups = [gg for gg in g["groups"] if gg["id"] == paper["home_group"]]
            if not groups:
                raise ValueError(
                    "Paper home group unavailable in pinned journey modules"
                )
            group = groups[0]
            ident = run["id"] + ":concept:" + c["key"]
            mapping[c["key"]] = ident
            doc = {
                "id": ident,
                "layer": layer,
                "run_id": run["id"],
                "name": c["name"],
                "statement": c["statement"],
                "description": c["description"],
                "kind": c["kind"],
                "status": "Established",
                "home_group": group["id"],
                "ancestors": group["ancestors"],
                "island": group["island"],
                "source": {
                    "paper_id": paper["id"],
                    "agent": "decomposer",
                    "extraction": cache_key,
                },
                "integrated": False,
                "fixture": run["fixture"],
                "embedding": [0.82, 0.54, 0.1 + i * 0.08]
                if run["fixture"]
                else embeddings[i],
            }
            self.store.put("concepts", doc)
            nodes[ident] = doc
        for i, raw in enumerate(extraction["edges"]):
            try:
                e = dict(
                    raw,
                    premises=[mapping[x] for x in raw["premises"]],
                    conclusion=mapping[raw["conclusion"]],
                )
                if e["conclusion"] in e["premises"]:
                    continue
                e = EdgeInput.model_validate(e).model_dump()
            except (ValueError, KeyError, TypeError):
                self.trace(run, 0, "decomposer", "Malformed extracted edge rejected",
                           edge_index=i, reason="Invalid edge fields or unknown concept reference")
                continue
            self.save_edge(
                run,
                e,
                "decomposer",
                {"kind": "integration", "paper_id": paper["id"]},
                "extract:" + str(i),
            )
        integration = self.integrate(run, journey, g, nodes, paper, mapping)
        self.store.patch(
            "papers",
            paper["id"],
            concept_ids=list(dict.fromkeys(mapping.values())),
            integration_ids=integration,
            extraction_id=cache_key,
            extracted=True,
        )
        # Integration is reviewed before target draws/crew exploration. Global cache does not cache this review.
        self.stage3(dict(run, _review_step=0))
        self.trace(
            run,
            0,
            "decomposer",
            "Cached extraction reused; journey matching and review remain local"
            if cached
            else "Extraction cached; journey matching completed",
            concept_ids=list(mapping.values()),
            cache_key=cache_key,
        )

    def near_duplicates(self, journey, nodes, description, vector, limit=5):
        """Concept-index candidates for the duplicate check: in-database automated embedding
        when enabled, otherwise the stored vector from the budgeted embeddings call."""
        vectors = AtlasVectors(self.store)
        hits = (
            vectors.search_text("concepts", description, visible_layers(journey), limit)
            if vectors.auto_embed
            else vectors.search("concepts", vector, visible_layers(journey), limit)
        )
        return [nodes[h["id"]] for h in hits if h["id"] in nodes]

    def connected_to(self, layer, ident, anchors):
        """Structural check used by the integration loop: does any saved relation in this journey
        link the node to a pre-existing node? Review and tier are applied later by stage 3."""
        for e in self.store.all("edges", layer=layer):
            ends = e["premises"] + [e["conclusion"]]
            if ident in ends and any(n in anchors and n != ident for n in ends):
                return True
        return False

    def integrate(self, run, journey, g, nodes, paper, mapping):
        """Enforced integration loop (overview, pipeline step 1).

        Each genuinely new concept must be connected to the graph that existed before this paper.
        Level by level, the decomposer states what each still-unconnected concept rests on or leads
        to. Links attach to existing nodes wherever matching finds them; a standard concept the graph
        lacks becomes an Established integration node with the paper's reference as its source and is
        linked onward the same way. The loop stops when every chain reaches an existing node or after
        integration_depth levels; whatever is still unconnected stays flagged unintegrated by stage 3.
        Fixture mode records that the loop was skipped; it never fabricates links.
        """
        depth = journey["settings"]["integration_depth"]
        layer = "journey:" + journey["id"]
        anchors = set(run["before"]["nodes"])
        frontier = [i for i in dict.fromkeys(mapping.values()) if i not in anchors]
        created = []
        if run["fixture"] or not frontier or depth == 0:
            self.trace(
                run, 0, "decomposer", "Integration loop skipped",
                reason="fixture mode never invents links" if run["fixture"]
                else "no new concepts" if not frontier else "integration_depth is 0",
            )
            return created
        for level in range(depth):
            unconnected = [i for i in frontier if not self.connected_to(layer, i, anchors)]
            if not unconnected:
                break
            result = self.call(
                "decomposer",
                {
                    "task": "These concepts from the input paper are not yet linked to any pre-existing concept. For each, state what it rests on and what it leads to using the paper: for a definition, the standard concepts it is defined from (one defined_from hyperedge into it); for a theorem, the known results it uses (dependency) and any known result it generalizes, specializes or implies. Reuse existing_concepts by id wherever one matches exactly. Where a link needs a standard concept the graph lacks, add it to nodes as an integration node with the paper's own reference (source, location, verbatim excerpt) and link it with the same rules. Every node you add must appear in at least one edge. Tier must be cited (with the paper reference as evidence) or intuitive; never verified. Return nodes [{key,name,statement,description,kind,msc,source:{reference,location,excerpt}}] and edges matching edge_schema whose endpoints are existing ids or node keys. Do not invent relationships; empty lists are allowed.",
                    "level": level,
                    "unconnected_concepts": [nodes[i] for i in unconnected],
                    "existing_concepts": [
                        {"id": n["id"], "name": n.get("name"), "statement": n["statement"]}
                        for n in nodes.values() if n["id"] in anchors
                    ][:400],
                    "paper_text": paper["text"],
                    "edge_schema": EdgeInput.model_json_schema(),
                    "concept_schema": ExtractedConcept.model_json_schema(),
                },
                run,
                "integrate:" + str(level),
            )
            raw_nodes = list(result.get("nodes", []))[:40]
            raw_edges = list(result.get("edges", []))[:80]
            used = {k for e in raw_edges for k in list(e.get("premises", [])) + [e.get("conclusion")]}
            texts, pending = [], []
            for c in raw_nodes:
                try:
                    concept = ExtractedConcept.model_validate(c).model_dump()
                except (ValueError, TypeError):
                    self.trace(run, 0, "decomposer", "Malformed integration node rejected", level=level)
                    continue
                if concept["key"] not in used:
                    self.trace(run, 0, "decomposer", "Standalone integration node dropped", level=level, key=concept["key"])
                    continue
                concept["source"] = c.get("source") if isinstance(c.get("source"), dict) else {}
                pending.append(concept)
                texts.append(concept["description"])
            vectors = (
                self.call("embeddings", {"texts": texts}, run, "integrate-vectors:" + str(level))["embeddings"]
                if texts else []
            )
            if len(vectors) != len(pending):
                raise ValueError("Integration embedding count mismatch")
            level_ids = []
            for concept, vector in zip(pending, vectors):
                matches = [
                    n for n in nodes.values()
                    if n["statement"].strip().casefold() == concept["statement"].strip().casefold()
                ]
                if not matches:
                    candidates = self.near_duplicates(journey, nodes, concept["description"], vector)
                    if candidates:
                        verdict = self.call(
                            "penelope",
                            {
                                "task": "Is the integration concept mathematically identical, with identical hypotheses, to a candidate? Return match_id or null.",
                                "concept": concept,
                                "candidates": [{"id": n["id"], "statement": n["statement"]} for n in candidates],
                            },
                            run,
                            "integrate-match:" + str(level) + ":" + concept["key"],
                        )
                        matches = [n for n in candidates if n["id"] == verdict.get("match_id")]
                if matches:
                    mapping["integration:" + str(level) + ":" + concept["key"]] = matches[0]["id"]
                    continue
                groups = [
                    gg for gg in g["groups"]
                    if gg["depth"] == 3 and concept["msc"].startswith(gg["msc"])
                ] or [gg for gg in g["groups"] if gg["id"] == paper["home_group"]]
                if not groups:
                    raise ValueError("Paper home group unavailable in pinned journey modules")
                ident = run["id"] + ":integration:" + str(level) + ":" + concept["key"]
                doc = {
                    "id": ident,
                    "layer": layer,
                    "run_id": run["id"],
                    "name": concept["name"],
                    "statement": concept["statement"],
                    "description": concept["description"],
                    "kind": concept["kind"],
                    "status": "Established",
                    "home_group": groups[0]["id"],
                    "ancestors": groups[0]["ancestors"],
                    "island": groups[0]["island"],
                    "source": {
                        "paper_id": paper["id"],
                        "agent": "decomposer",
                        "kind": "integration",
                        "level": level,
                        "reference": concept["source"],
                    },
                    "integrated": False,
                    "fixture": False,
                    "embedding": vector,
                }
                self.store.put("concepts", doc)
                nodes[ident] = doc
                mapping["integration:" + str(level) + ":" + concept["key"]] = ident
                created.append(ident)
                level_ids.append(ident)
            keys = {c["key"]: mapping["integration:" + str(level) + ":" + c["key"]] for c in pending}
            resolve = lambda x: keys.get(x, x)
            for j, raw in enumerate(raw_edges):
                try:
                    e = dict(raw, premises=[resolve(x) for x in raw["premises"]], conclusion=resolve(raw["conclusion"]))
                    if e["conclusion"] in e["premises"]:
                        continue
                    e = EdgeInput.model_validate(e).model_dump()
                    if e["tier"] == "verified" or not all(n in nodes for n in e["premises"] + [e["conclusion"]]):
                        raise ValueError("Integration edge claims verification or references an unknown node")
                except (ValueError, KeyError, TypeError):
                    self.trace(run, 0, "decomposer", "Malformed integration edge rejected", level=level, edge_index=j)
                    continue
                self.save_edge(
                    run, e, "decomposer",
                    {"kind": "integration", "paper_id": paper["id"], "level": level},
                    "integrate:" + str(level) + ":" + str(j),
                )
            self.trace(
                run, 0, "decomposer", "Integration level completed",
                level=level, unconnected=unconnected, integration_nodes=level_ids, edges=len(raw_edges),
            )
            frontier = level_ids
        remaining = [i for i in frontier if not self.connected_to(layer, i, anchors)]
        if remaining:
            self.trace(
                run, 0, "decomposer", "Integration depth limit reached; chains still open",
                depth=depth, unconnected=remaining,
            )
        return created

    def stage1(self, run):
        journey, g, nodes = self.context(run)
        paper = self.store.get("papers", run["paper_id"])
        rng = random.Random(run["id"])
        targets = []
        used = set()
        ref = {"ancestors": paper["ancestors"]}
        groups = [
            gg
            for gg in g["groups"]
            if any(
                n["home_group"] == gg["id"] and n["status"] != "Proposed"
                for n in nodes.values()
            )
        ]
        papers = [
            p
            for p in self.store.all("papers", journey_id=journey["id"])
            if p.get("concept_ids") and p["id"] != paper["id"]
        ]
        ordinal = run["ordinal"]
        for i, crew in enumerate(CREW):
            perspective = PERSPECTIVES[(i + ordinal) % 4]
            for band in ("short", "medium", "far"):

                def band_of(anc):
                    d = tree_distance(ref, {"ancestors": anc})
                    return "short" if d <= 1 else "medium" if d == 2 else "far"

                gp = [
                    ("group", gg) for gg in groups if band_of(gg["ancestors"]) == band
                ]
                pp = [("paper", p) for p in papers if band_of(p["ancestors"]) == band]
                chosen = gp if rng.random() < journey["settings"]["group_ratio"] else pp
                if not chosen:
                    chosen = pp or gp
                fresh = [x for x in chosen if x[1]["id"] not in used]
                fresh = fresh or [x for x in gp + pp if x[1]["id"] not in used]
                chosen = fresh or chosen
                if not chosen:
                    targets.append(
                        {
                            "crew": crew,
                            "crew_index": i,
                            "perspective": perspective,
                            "band": band,
                            "unavailable": True,
                        }
                    )
                    continue
                kind, target = rng.choice(chosen)
                used.add(target["id"])
                ids = (
                    target.get("concept_ids", [])
                    if kind == "paper"
                    else [
                        n["id"]
                        for n in nodes.values()
                        if n["home_group"] == target["id"] and n["status"] != "Proposed"
                    ]
                )
                from metis.graph import cosine

                input_nodes = [nodes[n] for n in paper["concept_ids"] if n in nodes]
                ids.sort(
                    key=lambda n: max(
                        (
                            cosine(nodes[n].get("embedding"), a.get("embedding")) or 0
                            for a in input_nodes
                        ),
                        default=0,
                    ),
                    reverse=True,
                )
                targets.append(
                    {
                        "crew": crew,
                        "crew_index": i,
                        "perspective": perspective,
                        "band": band,
                        "kind": kind,
                        "target_id": target["id"],
                        "concept_ids": ids[: journey["settings"]["k"]],
                    }
                )
        self.store.patch("runs", run["id"], targets=targets)
        self.trace(
            run,
            1,
            "system",
            "Independent targets drawn; empty bands explicitly recorded",
            targets=targets,
        )

    def save_edge(self, run, e, agent, provenance, key):
        self.ensure_active(run)
        layer = "journey:" + run["journey_id"]
        duplicate = duplicate_key(e)
        # Stable layer/type/endpoints identity makes retries and support overlays idempotent.
        ident = hashlib.sha256((layer + duplicate).encode()).hexdigest()
        existing = self.store.get("edges", ident)
        support_id = hashlib.sha256((run["id"] + key + duplicate).encode()).hexdigest()
        self.store.insert(
            "support",
            {
                "id": support_id,
                "journey_id": run["journey_id"],
                "run_id": run["id"],
                "edge_id": ident,
                "agent": agent,
                "provenance": provenance,
                "evidence": e["evidence"],
                "argument": e["argument"],
            },
        )
        if existing:
            evidence = list(existing.get("evidence", []))
            seen = {json.dumps(v, sort_keys=True) for v in evidence}
            for v in e["evidence"]:
                if json.dumps(v, sort_keys=True) not in seen:
                    evidence.append(v)
                    seen.add(json.dumps(v, sort_keys=True))
            # A stronger claim is re-reviewed; it never upgrades the accepted tier by itself.
            return self.store.patch("edges", ident, evidence=evidence)

        journey = self.store.get("journeys", run["journey_id"])
        base = next(
            (
                b
                for b in graph(self.store, journey)["edges"]
                if b["layer"].startswith("module:") and b["duplicate_key"] == duplicate
            ),
            None,
        )
        doc = dict(
            e,
            id=ident,
            base_edge_id=base["id"] if base else None,
            layer=layer,
            run_id=run["id"],
            duplicate_key=duplicate,
            provenance=dict(provenance, agent=agent),
            review_status="pending",
            existing="Unchecked",
            support_count=1,
            tier_history=[],
            fixture=run["fixture"],
            created=now(),
            invalidated=False,
        )
        self.store.insert("edges", doc)
        return doc

    def stage2(self, run):
        journey, g, nodes = self.context(run)
        paper = self.store.get("papers", run["paper_id"])
        current = self.store.get("runs", run["id"])
        for i, target in enumerate(current["targets"]):
            if target.get("unavailable"):
                continue
            if run["fixture"]:
                src = paper["concept_ids"][0]
                dest = next((n for n in target["concept_ids"] if n != src), None)
                proposals = (
                    []
                    if not dest
                    else [
                        {
                            "premises": [src],
                            "conclusion": dest,
                            "type": "related",
                            "directed": True,
                            "tier": "intuitive",
                            "argument": "Fixture association: compare symmetry and spectral structures. This is scripted, not model discovery.",
                            "evidence": [],
                        }
                    ]
                )
            else:
                result = self.call(
                    "crew" + str(target["crew_index"]),
                    {
                        "task": "Propose at most "
                        + str(journey["settings"]["p"])
                        + " nontrivial mathematical connections. Preserve every hypothesis. Return proposals matching edge_schema and optional new_nodes [{key,name,statement,description,kind,home_group,source}]. A new node must be used by a proposal; existing groups only. References to new nodes use key. No standalone nodes.",
                        "perspective": target["perspective"],
                        "input_paper": {
                            k: paper.get(k) for k in ("title", "year", "source", "msc")
                        },
                        "target_paper": self.store.get(
                            "papers", target.get("target_id")
                        )
                        if target["kind"] == "paper"
                        else None,
                        "input_paper_text": paper["text"],
                        "input_concepts": [nodes[n] for n in paper["concept_ids"]],
                        "target_concepts": [nodes[n] for n in target["concept_ids"]],
                        "groups": [
                            {"id": gg["id"], "description": gg["description"]}
                            for gg in g["groups"]
                        ],
                        "edge_schema": EdgeInput.model_json_schema(),
                    },
                    run,
                    "crew:" + str(i),
                )
                proposals = result.get("proposals", [])[: journey["settings"]["p"]]
                for c in result.get("new_nodes", [])[:10]:
                    if not any(
                        c["key"] in e["premises"] + [e["conclusion"]] for e in proposals
                    ):
                        continue
                    group = next(
                        (gg for gg in g["groups"] if gg["id"] == c["home_group"]), None
                    )
                    if not group:
                        self.trace(
                            run,
                            2,
                            target["crew"],
                            "New node held for Odysseus: no existing home group",
                            candidate=c,
                        )
                        continue
                    ident = run["id"] + ":crew:" + str(i) + ":" + c["key"]
                    doc = dict(
                        c,
                        id=ident,
                        layer="journey:" + journey["id"],
                        run_id=run["id"],
                        status="Proposed",
                        ancestors=group["ancestors"],
                        island=group["island"],
                        integrated=False,
                        source={"agent": target["crew"], "reference": c.get("source")},
                        fixture=False,
                    )
                    self.store.put("concepts", doc)
                    nodes[ident] = doc
                    for e in proposals:
                        e["premises"] = [
                            ident if p == c["key"] else p for p in e["premises"]
                        ]
                        if e["conclusion"] == c["key"]:
                            e["conclusion"] = ident
            folded, folded_edges, malformed = [], [], 0
            for j, raw in enumerate(proposals):
                try:
                    e = EdgeInput.model_validate(raw).model_dump()
                    if not all(n in nodes for n in e["premises"] + [e["conclusion"]]):
                        raise ValueError("Crew proposal references an unavailable node")
                except (ValueError, KeyError, TypeError):
                    folded.append(self.trace(run, 2, target["crew"], "Malformed crew proposal rejected",
                                             proposal_index=j, target_index=i,
                                             reason="Invalid edge fields or unavailable node"))
                    malformed += 1
                    continue
                saved = self.save_edge(
                    run, e, target["crew"], target, "crew:" + str(i) + ":" + str(j)
                )
                folded_edges.append(saved["id"])
                folded.append(self.trace(
                    run,
                    2,
                    target["crew"],
                    "Proposal recorded",
                    edge_id=saved["id"],
                    argument=e["argument"],
                    perspective=target["perspective"],
                    band=target["band"],
                ))
            # One crew mate's proposals for one comparison arrive together: one exchange, not N pop-ups.
            narrator.discuss_fold(self, run, target, folded, folded_edges, malformed)

    def citation_context(self, run, e):
        from metis.ingestion import fetch, extract_text, content_hash

        checked = []
        paper = self.store.get("papers", run.get("paper_id", ""))
        for evidence in e["evidence"][:3]:
            source = evidence.get("source")
            excerpt = evidence.get("excerpt", "")
            item = {
                "source": source,
                "location": evidence.get("location"),
                "excerpt": excerpt,
                "retrieval_status": "unavailable",
            }
            if (
                not isinstance(source, str)
                or not isinstance(excerpt, str)
                or len(excerpt) < 30
                or not item["location"]
            ):
                checked.append(item)
                continue
            try:
                original = (paper or {}).get("source", {})
                if paper and source in (
                    "input-paper",
                    paper["id"],
                    original.get("url"),
                    original.get("resolved_url"),
                ):
                    text = paper["text"]
                    item["retrieval_status"] = "input paper"
                elif source.startswith(("http://", "https://")):
                    cache_id = content_hash(run["id"] + source)
                    cached = self.store.get("sources", cache_id)
                    if cached:
                        text = cached["text"]
                    else:
                        raw, ctype, final = fetch(source)
                        text = extract_text(raw, ctype)
                        self.store.put(
                            "sources",
                            {
                                "id": cache_id,
                                "journey_id": run["journey_id"],
                                "run_id": run["id"],
                                "url": source,
                                "final_url": final,
                                "text": text,
                                "content_hash": content_hash(text),
                                "time": now(),
                            },
                        )
                    item["retrieval_status"] = "retrieved"
                else:
                    checked.append(item)
                    continue
                normalized = " ".join(text.split())
                quote = " ".join(excerpt.split())
                index = normalized.find(quote)
                item["excerpt_found"] = index >= 0
                if index >= 0:
                    item["source_context"] = normalized[
                        max(0, index - 700) : index + len(quote) + 700
                    ]
            except Exception as exc:
                item["retrieval_status"] = "failed"
                item["error"] = type(exc).__name__
            checked.append(item)
        return checked

    def review(self, run, e, nodes, key):
        blinded = blind_edge(e, nodes)
        citation_checks = (
            []
            if run["fixture"] or e["tier"] == "intuitive"
            else self.citation_context(run, e)
        )
        blinded["source_validation"] = citation_checks
        relation_semantics = (
            "This is a descriptive relation, not a logical implication. For dependency, "
            "check whether the source documents use of the premise in defining or proving "
            "the conclusion (possibly only a specified part). Do not require that the premise "
            "alone proves the entire conclusion. For defined_from, check the stated definition. "
            "Check every listed dependency is actually used and accurately scoped. A passed "
            "descriptive edge must never be interpreted as a proof step."
            if e["type"] in ("dependency", "defined_from", "related", "generalizes", "special_case")
            else "This is a logical relation: require every stated hypothesis and the complete conclusion."
        )
        if run["fixture"]:
            independent = {
                "hypotheses_match": True,
                "premises_necessary": True,
                "counterexample_found": False,
                "reason": "Simulated independent check; not mathematical validation.",
            }
            result = {
                "verdict": "pass",
                "reason": "Fixture-only review; illustrative relation accepted for UI testing.",
                "citation_valid": False,
                "well_defined": True,
                "not_duplicate": True,
                "not_trivial": True,
            }
        else:
            independent = self.call(
                "hypothesis",
                {
                    "task": "Independently test hypotheses, direction, necessity of EVERY premise and edge cases. Return hypotheses_match:boolean, premises_necessary:boolean,counterexample_found:boolean,reason:string. Do not rely on other reviews.",
                    "edge": blinded,
                    "relation_semantics": relation_semantics,
                },
                run,
                key + ":independent",
            )
            result = self.call(
                "penelope",
                {
                    "task": "Review well-formedness, nontriviality, duplicate/new-node definitions, logical correctness and evidence. For equivalence verify both directions. Return verdict (pass/reject),reason,citation_valid,well_defined,not_duplicate,not_trivial booleans. citation_valid true ONLY if the source excerpt at exact location states identical hypotheses/result. Never confirm machine verification.",
                    "edge": blinded,
                    "relation_semantics": relation_semantics,
                    "new_nodes": [
                        {
                            "statement": nodes[n]["statement"],
                            "description": nodes[n]["description"],
                            "kind": nodes[n]["kind"],
                        }
                        for n in e["premises"] + [e["conclusion"]]
                        if nodes[n]["status"] == "Proposed"
                    ],
                },
                run,
                key + ":penelope",
            )
        required = ("hypotheses_match", "premises_necessary", "counterexample_found")
        if not all(isinstance(independent.get(k), bool) for k in required):
            raise ValueError("Independent checker returned incomplete booleans")
        passed = (
            result.get("verdict") == "pass"
            and result.get("well_defined") is True
            and result.get("not_duplicate") is True
            and result.get("not_trivial") is True
            and independent["hypotheses_match"]
            and independent["premises_necessary"]
            and not independent["counterexample_found"]
        )
        tier = (
            "cited"
            if e["tier"] in ("verified", "cited")
            and result.get("citation_valid") is True
            and any(v.get("excerpt_found") for v in citation_checks)
            else "intuitive"
        )
        rid = run["id"] + ":" + key
        self.store.put(
            "reviews",
            {
                "id": rid,
                "journey_id": run["journey_id"],
                "run_id": run["id"],
                "edge_id": e["id"],
                "verdict": "pass" if passed else "reject",
                "reason": result.get("reason", ""),
                "independent": independent,
                "citation_checks": citation_checks,
                "final_tier": tier,
                "model_perspective": e.get("provenance"),
                "time": now(),
                "fixture": run["fixture"],
            },
        )
        return passed, tier, result, independent

    def stage3(self, run):
        journey, g, nodes = self.context(run)
        support = self.store.all("support", run_id=run["id"])
        edge_ids = {s["edge_id"] for s in support}
        for e in self.store.all("edges", layer="journey:" + journey["id"]):
            if e["id"] not in edge_ids:
                continue
            # Review in each journey/run context, including duplicate support; never import cached review.
            saved = self.store.get("reviews", run["id"] + ":review:" + e["id"])
            if saved:
                # Replay graph writes if the worker died after saving the review.
                passed, tier = saved["verdict"] == "pass", saved["final_tier"]
                result, independent = saved, saved["independent"]
            else:
                passed, tier, result, independent = self.review(
                    run, e, nodes, "review:" + e["id"]
                )
            if (
                passed
                and e["tier"] == "verified"
                and e.get("formal_attempt", {}).get("machine_verified")
            ):
                tier = "verified"
            review_id = run["id"] + ":review:" + e["id"]
            history = [
                h for h in e.get("tier_history", []) if h.get("review_id") != review_id
            ] + [
                {
                    "tier": tier,
                    "reason": result.get("reason"),
                    "time": now(),
                    "review_id": run["id"] + ":review:" + e["id"],
                }
            ]
            self.store.patch(
                "edges",
                e["id"],
                review_status="passed" if passed else "rejected",
                tier=tier,
                tier_history=history,
                existing="Existing" if tier == "cited" else "Unchecked",
                independent=independent,
            )
            if not passed:
                invalidate_dependents(
                    self.store,
                    journey,
                    e["id"],
                    "Independent or Penelope review rejected",
                )
                self.trace(
                    run,
                    run.get("_review_step", 3),
                    "Penelope",
                    "Proposal rejected; structured invalidation retained",
                    edge_id=e["id"],
                    reason=result.get("reason"),
                    invalidation=independent,
                )
            else:
                for n in e["premises"] + [e["conclusion"]]:
                    if (
                        nodes[n]["status"] == "Proposed"
                        and nodes[n].get("source", {}).get("agent") in CREW
                    ):
                        self.store.patch("concepts", n, status="Established")
                self.trace(
                    run,
                    run.get("_review_step", 3),
                    "Penelope",
                    "Proposal passed"
                    + (" with downgrade" if tier != e["tier"] else ""),
                    edge_id=e["id"],
                    reason=result.get("reason"),
                    independent=independent,
                )
        journey, g, nodes = self.context(run)
        adj = adjacency(nodes, g["edges"])
        anchors = {
            n["id"]
            for n in g["concepts"]
            if n["id"] in run["before"]["nodes"]
            and n.get("integrated")
            and n["status"] != "Proposed"
            and not n.get("invalidated")
        }
        for n in g["concepts"]:
            if n["layer"] != "journey:" + journey["id"]:
                continue
            seen = {n["id"]}
            todo = [n["id"]]
            while todo:
                current = todo.pop()
                for neighbor in adj.get(current, ()):
                    if neighbor not in seen:
                        seen.add(neighbor)
                        todo.append(neighbor)
            integrated = bool((seen - {n["id"]}) & anchors)
            self.store.patch("concepts", n["id"], integrated=integrated)
            nodes[n["id"]]["integrated"] = integrated
        for e in self.store.all("edges", layer="journey:" + journey["id"]):
            if e["id"] in edge_ids and e.get("review_status") == "passed":
                self.store.patch(
                    "edges",
                    e["id"],
                    bridge_score=score(
                        e, nodes, g["edges"], journey["settings"], anchors
                    ),
                )

    def run_edges(self, run):
        ids = {s["edge_id"] for s in self.store.all("support", run_id=run["id"])}
        return [
            e
            for e in self.store.all("edges", layer="journey:" + run["journey_id"])
            if e["id"] in ids
            and e.get("review_status") == "passed"
            and not e.get("invalidated")
        ]

    def stage4(self, run):
        journey, g, nodes = self.context(run)
        edges = sorted(
            self.run_edges(run),
            key=lambda e: (e.get("bridge_score") or {}).get("value") or 0,
            reverse=True,
        )
        versions = {
            self.store.get("modules", m).get("mathlib_version")
            for m in journey["modules"]
        }
        version = next(iter(versions)) if len(versions) == 1 else None
        attempted_edges = 0
        for e in [
            e
            for e in edges
            if e["tier"] == "intuitive" and e["type"] in ("implies", "equivalent")
        ][: journey["settings"]["proof_attempts"]]:
            attempted_edges += 1
            if run["fixture"]:
                attempt = {
                    "status": "unavailable",
                    "machine_verified": False,
                    "reason": "Fixture mode never executes or claims a Lean proof",
                }
            elif not self.config.lean_image or not self.config.lean_project:
                attempt = {
                    "status": "unavailable",
                    "machine_verified": False,
                    "reason": "Controlled Lean sandbox not configured; no prover call made",
                }
            else:
                candidate = self.call(
                    "hephaestus",
                    {
                        "task": "Return statement and proof Lean expressions for this exact edge with ALL hypotheses. No imports, commands, axioms, sorry, admit, or metaprogramming.",
                        "edge": blind_edge(e, nodes),
                        "mathlib_version": version,
                    },
                    run,
                    "formal:" + e["id"],
                )
                aligned = self.call(
                    "alignment",
                    {
                        "task": "Does the formal statement exactly match the mathematical edge, preserving every hypothesis and direction? Return matches:boolean,reason. Do not assume compilation.",
                        "edge": blind_edge(e, nodes),
                        "statement": candidate["statement"],
                    },
                    run,
                    "alignment:" + e["id"],
                )
                attempt = formal.verify(
                    self.config,
                    candidate["statement"],
                    candidate["proof"],
                    version,
                    aligned.get("matches") is True,
                )
                attempt["alignment_review"] = aligned
                attempt["statement"] = candidate["statement"]
            self.ensure_active(run)
            self.store.patch("edges", e["id"], formal_attempt=attempt)
            if attempt["machine_verified"] and not run["fixture"]:
                self.store.patch(
                    "edges",
                    e["id"],
                    tier="verified",
                    tier_history=e["tier_history"]
                    + [
                        {
                            "tier": "verified",
                            "time": now(),
                            "reason": "Sandbox compilation, axiom policy and independent alignment passed",
                        }
                    ],
                )
            self.trace(
                run,
                4,
                "Hephaestus",
                "Formal verification " + attempt["status"],
                edge_id=e["id"],
                attempt=attempt,
            )
        from metis.concepts import attempt_accepted_conjectures

        conjectures = attempt_accepted_conjectures(
            self, run, journey["settings"]["proof_attempts"] - attempted_edges
        )
        self.trace(
            run,
            4,
            "Hephaestus",
            "Formal stage complete; no compilation is inferred from literature or graph traversal",
            sandbox_configured=bool(
                self.config.lean_image and self.config.lean_project
            ),
            edge_attempts=attempted_edges,
            conjecture_attempts=conjectures,
        )

    def stage5(self, run):
        journey, g, nodes = self.context(run)
        for e in self.run_edges(run):
            if e["tier"] == "cited":
                continue
            if run["fixture"]:
                search = {
                    "status": "simulated",
                    "queries": ["fixture association example"],
                    "sources": [],
                    "failures": [],
                    "time": now(),
                    "conclusion": "Unchecked — fixture does not search the literature",
                }
                existing = "Unchecked"
            else:
                result = self.call(
                    "tiresias",
                    {
                        "task": "Search for prior statements of this exact connection. Return found:boolean,queries:[string],sources:[{url,title,location,excerpt}],failures:[string],summary:string. Negative search means potentially new only, never novel. Cite exact hypotheses.",
                        "edge": blind_edge(e, nodes),
                    },
                    run,
                    "literature:" + e["id"],
                    grounded=True,
                )
                complete = result.get("_search_complete") and not result.get("failures")
                grounding = result.get("_grounding") or {}
                grounded_urls = {
                    c.get("web", {}).get("uri")
                    for c in grounding.get("groundingChunks", [])
                }
                sources = [
                    s
                    for s in result.get("sources", [])
                    if s.get("url") in grounded_urls
                    and s.get("location")
                    and s.get("excerpt")
                ]
                existing = (
                    "Existing"
                    if complete and result.get("found") is True and sources
                    else "Not found"
                    if complete and result.get("found") is False
                    else "Unchecked"
                )
                search = {
                    "status": "complete" if complete else "incomplete",
                    "queries": grounding.get(
                        "webSearchQueries", result.get("queries", [])
                    ),
                    "sources": sources,
                    "failures": result.get("failures", []),
                    "summary": result.get("summary"),
                    "grounding": grounding,
                    "time": now(),
                }
                # A literature hit alone cannot promote a mathematical claim. Re-review exact source.
                if existing == "Existing":
                    reviewed = dict(
                        e,
                        tier="cited",
                        evidence=e["evidence"]
                        + [
                            {
                                "source": s["url"],
                                "location": s["location"],
                                "excerpt": s["excerpt"],
                            }
                            for s in sources
                        ],
                    )
                    passed, tier, verdict, independent = self.review(
                        run, reviewed, nodes, "citation:" + e["id"]
                    )
                    if passed and tier == "cited":
                        self.store.patch(
                            "edges",
                            e["id"],
                            tier="verified" if e["tier"] == "verified" else "cited",
                            evidence=reviewed["evidence"],
                            tier_history=e["tier_history"]
                            + [
                                {
                                    "tier": "verified"
                                    if e["tier"] == "verified"
                                    else "cited",
                                    "time": now(),
                                    "reason": "Grounded source independently reviewed",
                                }
                            ],
                        )
                    else:
                        existing = "Unchecked"
                    if not passed:
                        invalidate_dependents(
                            self.store,
                            journey,
                            e["id"],
                            "Literature evidence revealed conflict",
                        )
            self.store.patch("edges", e["id"], existing=existing, literature=search)
            self.trace(
                run,
                5,
                "Tiresias",
                "Literature status: " + existing,
                edge_id=e["id"],
                search=search,
            )

    def stage6(self, run):
        journey, g, nodes = self.context(run)
        edges = self.run_edges(run)
        findings = [
            e
            for e in edges
            if e.get("provenance", {}).get("kind") != "integration"
            and not any(
                nodes[n]["status"] == "Proposed"
                or nodes[n].get("source", {}).get("agent") == "Odysseus"
                for n in e["premises"] + [e["conclusion"]]
            )
        ]
        ranked = sorted(
            findings,
            key=lambda e: ranking_key(e, len(self.store.all("support", edge_id=e["id"]))),
            reverse=True,
        )
        summary = (
            "Fixture simulation: these scripted associations are not discoveries."
            if run["fixture"]
            else "Potentially new means no prior statement found in the recorded searches. Machine verification and literature support are separate."
        )
        if not run["fixture"] and not ranked:
            summary = "No accepted exploration findings in this run. Empty or rejected proposals are not discoveries."
        if not run["fixture"] and not run.get("ingest_only") and ranked:
            result = self.call(
                "odysseus",
                {
                    "task": "Summarize reviewed findings in concise public prose. Do not claim novelty or machine verification beyond recorded fields. Return summary. Rejected claims are invalidation signals only. Do not rank your own proposed nodes.",
                    "findings": ranked,
                    "invalidation_signals": [
                        {
                            "edge_id": e["id"],
                            "invalidated": e.get("invalidated"),
                            "independent": e.get("independent"),
                        }
                        for e in g["edges"]
                        if e.get("invalidated")
                    ],
                },
                run,
                "ranking",
            )
            summary = str(result.get("summary", summary))
        report = {
            "id": run["id"],
            "journey_id": journey["id"],
            "fixture": run["fixture"],
            "summary": summary,
            "potentially_new": [
                e["id"] for e in ranked if e["existing"] == "Not found"
            ],
            "rediscoveries": [e["id"] for e in ranked if e["existing"] == "Existing"],
            "unchecked": [e["id"] for e in ranked if e["existing"] == "Unchecked"],
            "proposed_concepts": [
                n["id"]
                for n in g["concepts"]
                if n.get("source", {}).get("agent") == "Odysseus"
            ],
            "new_groups": [
                gg["id"] for gg in g["groups"] if gg.get("run_id") == run["id"]
            ],
            "ranked": [e["id"] for e in ranked],
            "time": now(),
        }
        self.store.put("reports", report)
        for e in edges:
            supports = self.store.all("support", edge_id=e["id"])
            self.store.patch("edges", e["id"], support_count=len(supports))
        # Immutable base support overlays, never mutation of module documents.
        for e in edges:
            base = next(
                (
                    b
                    for b in g["edges"]
                    if b["layer"].startswith("module:")
                    and b["duplicate_key"] == e["duplicate_key"]
                ),
                None,
            )
            if base:
                self.store.put(
                    "memory",
                    {
                        "id": journey["id"] + ":base:" + base["id"],
                        "journey_id": journey["id"],
                        "kind": "base_support",
                        "edge_id": base["id"],
                        "support_edge": e["id"],
                        "count": len(self.store.all("support", edge_id=e["id"])),
                    },
                )
        # Shared reliability stores aggregate counts only, not journey content.
        pairs = {}
        for r in self.store.all("reviews"):
            p = r.get("model_perspective") or {}
            key = (p.get("agent", "unknown"), p.get("perspective", "none"))
            pairs.setdefault(key, [0, 0])
            pairs[key][0] += 1
            pairs[key][1] += r["verdict"] == "pass"
        for pair, counts in pairs.items():
            self.store.put(
                "memory",
                {
                    "id": "reliability:" + ":".join(pair),
                    "kind": "reliability",
                    "pair": list(pair),
                    "total": counts[0],
                    "passed": counts[1],
                },
            )
        # Record recurring cross-paper bridges, without inventing an unreviewed concept.
        patterns = {}
        for e in g["edges"]:
            if (
                e.get("review_status") != "passed"
                or e["tier"] != "intuitive"
                or e.get("invalidated")
                or any(
                    nodes[n]["status"] == "Proposed" or nodes[n].get("invalidated")
                    for n in e["premises"] + [e["conclusion"]]
                )
            ):
                continue
            for p in e["premises"]:
                pair = tuple(
                    sorted({nodes[p]["island"], nodes[e["conclusion"]]["island"]})
                )
                if len(pair) == 2:
                    patterns.setdefault(pair, set()).add(e.get("run_id"))
        for pair, runs in patterns.items():
            if len(runs) >= journey["settings"]["new_node_threshold"]:
                self.store.insert(
                    "memory",
                    {
                        "id": journey["id"] + ":pattern:" + ":".join(pair),
                        "journey_id": journey["id"],
                        "kind": "proposed_node_trigger",
                        "islands": list(pair),
                        "runs": sorted(r for r in runs if r),
                        "status": "awaiting independent concept proposal and blind testing",
                    },
                )
        from metis.concepts import consider

        proposed = (
            []
            if run.get("ingest_only")
            else consider(
                self,
                run,
                [
                    m
                    for m in self.store.all("memory", journey_id=journey["id"])
                    if m.get("kind") == "proposed_node_trigger"
                ],
            )
        )
        if proposed:
            report["proposed_concepts"] = list(
                dict.fromkeys(report["proposed_concepts"] + proposed)
            )
            report["new_groups"] = [
                gg["id"]
                for gg in graph(self.store, journey)["groups"]
                if gg.get("run_id") == run["id"]
            ]
            self.store.put("reports", report)
        self.trace(
            run,
            6,
            "Odysseus",
            "Ranked report saved",
            report_id=run["id"],
            report_summary=summary,
        )
