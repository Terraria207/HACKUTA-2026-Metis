import asyncio
import hmac
import hashlib
import io
import json
import os
import math
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from metis.config import Config
from metis.store import Store, uid, now
from metis.base import seed, import_module, ISLANDS
from metis.graph import (
    Settings,
    graph,
    proof_closure,
    invalidate_dependents,
    visible_layers,
)
from metis.pipeline import Pipeline, STAGES
from metis.ingestion import fetch, arxiv_url, extract_text, content_hash, MAX_BYTES
from metis.providers import AtlasVectors, ProviderUnavailable, BudgetExceeded


class JourneyInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    islands: list[str] = Field(min_length=1, max_length=3)
    modules: list[str] = Field(default_factory=list)
    settings: Settings = Field(default_factory=Settings)


class PaperInput(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    kind: Literal["text", "url", "arxiv", "fixture", "corpus"] = "text"
    value: str = Field(default="", max_length=300000)
    home_group: str
    year: int | None = Field(default=None, ge=1500, le=2100)


class RunInput(BaseModel):
    paper_id: str
    budget_usd: float = Field(default=0, ge=0, allow_inf_nan=False)
    ingest_only: bool = False


class FeedbackInput(BaseModel):
    target_id: str
    target_type: Literal["edge", "concept"] = "edge"
    mark: Literal["interesting", "wrong"]
    comment: str = Field(default="", max_length=2000)


class RoleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal[
        "openai", "anthropic", "gemini", "voyage", "mistral", "xai", "nvidia"
    ]
    model: str = Field(min_length=1, max_length=100)
    key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,100}$")
    max_cost_usd: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    max_output_tokens: int = Field(default=4096, ge=128, le=16000)
    input_usd_per_million: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    output_usd_per_million: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    request_overhead_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def create_app(config=None, start_worker=True):
    config = (config or Config()).validate()
    store = Store(config)
    if config.mode == "fixture":
        seed(store)
    worker = Pipeline(store, config)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            worker.start()
        yield
        worker.close()

    app = FastAPI(title="Metis", version="1.0.0", lifespan=lifespan)
    app.state.store = store
    app.state.worker = worker

    @app.middleware("http")
    async def security(request, call_next):
        if request.url.path.startswith("/api/") and config.api_token:
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ")
            if not hmac.compare_digest(supplied, config.api_token):
                return Response("Unauthorized", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return Response("Cross-origin mutation forbidden", 403)
            if int(request.headers.get("content-length", "0")) > MAX_BYTES + 1000000:
                return Response("Request too large", 413)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return Response(
            json.dumps({"detail": str(exc)}), 400, media_type="application/json"
        )

    @app.exception_handler(BudgetExceeded)
    async def budget_error(request, exc):
        return Response(
            json.dumps({"detail": str(exc)}), 409, media_type="application/json"
        )

    @app.exception_handler(ProviderUnavailable)
    async def provider_error(request, exc):
        return Response(
            json.dumps({"detail": str(exc)}), 503, media_type="application/json"
        )

    def require(collection, ident, journey=None):
        d = store.get(collection, ident)
        if not d or (journey and d.get("journey_id") != journey):
            raise HTTPException(404, "Not found in this journey")
        return d

    def journey(ident):
        return require("journeys", ident)

    def visible(jid, collection, ident):
        j = journey(jid)
        d = require(collection, ident)
        if d.get("layer") not in visible_layers(j):
            raise HTTPException(404, "Not found in this journey")
        return d

    def report_data(jid, rid):
        require("runs", rid, jid)
        r = require("reports", rid, jid)
        r = dict(r)
        for key in ("ranked", "potentially_new", "rediscoveries", "unchecked"):
            r[key] = [
                e
                for ident in r[key]
                if (e := store.get("edges", ident))
                and not e.get("invalidated")
                and e.get("review_status") == "passed"
            ]
        return r

    @app.get("/api/status")
    def status():
        return {
            "mode": config.mode,
            "fixture": config.mode == "fixture",
            "storage": "MongoDB"
            if store.mongo is not None
            else "SQLite — local fixture only",
            "live_enabled": config.allow_live,
            "live_budget_usd": config.live_budget,
            "stages": STAGES,
            "lean_sandbox_configured": bool(config.lean_image and config.lean_project),
            "notice": "Fixture results are scripted demonstrations, not mathematical discoveries."
            if config.mode == "fixture"
            else "Live adapters fail closed. Literature search cannot establish novelty.",
        }

    @app.get("/api/modules")
    def modules():
        return store.all("modules", status="ready")

    @app.post("/api/modules/import", status_code=201)
    def module_import(bundle: dict):
        return import_module(store, bundle)

    @app.get("/api/journeys")
    def journeys():
        result = []
        for j in store.all("journeys"):
            result.append(
                dict(
                    j,
                    paper_count=len(store.all("papers", journey_id=j["id"])),
                    run_count=len(store.all("runs", journey_id=j["id"])),
                )
            )
        return sorted(result, key=lambda j: j["last_activity"], reverse=True)

    @app.post("/api/journeys", status_code=201)
    def new_journey(data: JourneyInput):
        if any(i not in ISLANDS for i in data.islands):
            raise ValueError("Unknown demo island")
        chosen = []
        if data.modules:
            for mid in data.modules:
                m = require("modules", mid)
                if m["status"] != "ready" or not set(m["islands"]).issubset(
                    data.islands
                ):
                    raise ValueError(
                        "Module is not ready or covers an unselected island"
                    )
                if config.mode == "live" and m.get("fixture"):
                    raise ValueError("Fixture modules cannot be used in live journeys")
                chosen.append(mid)
        else:
            for island in data.islands:
                ready = [
                    m
                    for m in store.all("modules", status="ready")
                    if m["islands"] == [island]
                    and (config.mode == "fixture" or not m.get("fixture"))
                ]
                if not ready:
                    raise ValueError(
                        "No ready module for "
                        + island
                        + "; import a reviewed version first"
                    )
                chosen.append(sorted(ready, key=lambda m: m["version"])[-1]["id"])
            chosen += [
                m["id"]
                for m in store.all("modules", status="ready")
                if len(m["islands"]) > 1
                and set(m["islands"]).issubset(data.islands)
                and (config.mode == "fixture" or not m.get("fixture"))
            ]
        for mid in chosen:
            if not set(require("modules", mid).get("requires", [])).issubset(chosen):
                raise ValueError(
                    "Bridge module prerequisites must match selected pinned versions"
                )
        for island in data.islands:
            if (
                sum(require("modules", mid)["islands"] == [island] for mid in chosen)
                > 1
            ):
                raise ValueError("Select only one version of each island module")
        if set(data.islands) != {
            i for mid in chosen for i in require("modules", mid)["islands"]
        }:
            raise ValueError("Modules must cover every selected island")
        j = {
            "id": uid("j_"),
            "name": data.name,
            "islands": data.islands,
            "modules": chosen,
            "settings": data.settings.model_dump(),
            "status": "ready",
            "created": now(),
            "last_activity": now(),
            "fixture": config.mode == "fixture",
        }
        store.put("journeys", j)
        return j

    @app.get("/api/journeys/{jid}")
    def get_journey(jid: str):
        return journey(jid)

    @app.put("/api/journeys/{jid}/settings")
    def update_settings(jid: str, settings: Settings):
        journey(jid)
        return store.patch("journeys", jid, settings=settings.model_dump())

    @app.get("/api/journeys/{jid}/papers")
    def papers(jid: str):
        journey(jid)
        return [
            {k: v for k, v in p.items() if k != "text"}
            for p in store.all("papers", journey_id=jid)
        ]

    def add_paper(jid, data, raw=None):
        j = journey(jid)
        group = visible(jid, "groups", data.home_group)
        if group["depth"] != 3:
            raise ValueError("Select a subtopic (depth 3) before importing")
        source = {"kind": data.kind}
        text = ""
        if raw is not None:
            text = extract_text(raw, "application/pdf")
            source["kind"] = "pdf"
            source["raw_sha256"] = hashlib.sha256(raw).hexdigest()
            source["size_bytes"] = len(raw)
        elif data.kind == "fixture":
            if config.mode != "fixture":
                raise ValueError("Fixture paper disabled in live mode")
            text = "Fixture paper: symmetry and spectral decompositions. This scripted sample exercises Metis without provider calls. It makes no real discovery."
        elif data.kind == "corpus":
            previous = require("papers", data.value)
            text = previous["text"]
            source = {
                "kind": "corpus",
                "paper_id": previous["id"],
                "original": previous["source"],
            }
        elif data.kind in ("url", "arxiv"):
            url = arxiv_url(data.value) if data.kind == "arxiv" else data.value
            raw, ctype, final = fetch(url)
            text = extract_text(raw, ctype)
            source.update(url=url, resolved_url=final)
        else:
            text = data.value.strip()
            if len(text) < 30:
                raise ValueError("Paper text must contain at least 30 characters")
        paper = {
            "id": uid("p_"),
            "journey_id": jid,
            "title": data.title,
            "text": text,
            "source": source,
            "content_hash": content_hash(text),
            "msc": group["msc"],
            "home_group": group["id"],
            "ancestors": group["ancestors"],
            "year": data.year,
            "concept_ids": [],
            "created": now(),
            "fixture": j["fixture"],
        }
        store.put("papers", paper)
        return {k: v for k, v in paper.items() if k != "text"}

    @app.get("/api/journeys/{jid}/papers/{pid}")
    def paper_details(jid: str, pid: str):
        journey(jid)
        return require("papers", pid, jid)

    @app.post("/api/journeys/{jid}/papers", status_code=201)
    def new_paper(jid: str, data: PaperInput):
        return add_paper(jid, data)

    @app.post("/api/journeys/{jid}/papers/pdf", status_code=201)
    async def upload(
        jid: str,
        title: str = Form(...),
        home_group: str = Form(...),
        file: UploadFile = File(...),
    ):
        raw = await file.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "PDF exceeds 12 MiB")
        if not raw.startswith(b"%PDF-"):
            raise ValueError("File is not a PDF")
        return await asyncio.to_thread(
            add_paper, jid, PaperInput(title=title, home_group=home_group), raw
        )

    @app.put("/api/journeys/{jid}/papers/{pid}/placement")
    def placement(jid: str, pid: str, data: dict):
        p = require("papers", pid, jid)
        gg = visible(jid, "groups", data["home_group"])
        if p.get("extracted"):
            raise ValueError(
                "Placement locked after extraction; import a new paper copy to reclassify"
            )
        if gg["depth"] != 3:
            raise ValueError("Choose subtopic")
        return store.patch(
            "papers", pid, home_group=gg["id"], msc=gg["msc"], ancestors=gg["ancestors"]
        )

    @app.post("/api/journeys/{jid}/papers/bulk", status_code=201)
    def bulk(jid: str, data: dict):
        ids = data.get("arxiv_ids", [])
        if len(ids) > 20:
            raise ValueError("Bulk import limited to 20 arXiv IDs")
        results = []
        for ident in ids:
            try:
                results.append(
                    {
                        "paper": add_paper(
                            jid,
                            PaperInput(
                                title="arXiv " + ident,
                                kind="arxiv",
                                value=ident,
                                home_group=data["home_group"],
                            ),
                        )
                    }
                )
            except (ValueError, OSError) as exc:
                results.append({"arxiv_id": ident, "error": str(exc)})
        return results

    @app.get("/api/journeys/{jid}/suggestions")
    def suggestions(jid: str):
        from metis.graph import tree_distance

        j = journey(jid)
        g = graph(store, j)
        nodes = {n["id"]: n for n in g["concepts"]}
        completed = [
            r for r in store.all("runs", journey_id=jid) if r["status"] == "complete"
        ]
        completed.sort(key=lambda r: r["created"], reverse=True)
        used = {r["paper_id"] for r in completed}
        latest = completed[0] if completed else None
        bridges = [
            e
            for e in g["edges"]
            if latest
            and e.get("run_id") == latest["id"]
            and e.get("review_status") == "passed"
            and not e.get("invalidated")
        ]
        anchors = [nodes[n] for e in bridges for n in e["premises"] + [e["conclusion"]]]
        papers = [p for p in store.all("papers", journey_id=jid) if p["id"] not in used]
        papers.sort(
            key=lambda p: min((tree_distance(p, n) for n in anchors), default=3)
        )
        return [
            {
                k: v
                for k, v in dict(
                    p,
                    suggestion_reason="Near the latest reviewed bridge groups"
                    if anchors
                    else "Unexplored corpus paper",
                ).items()
                if k != "text"
            }
            for p in papers[:10]
        ]

    @app.get("/api/journeys/{jid}/runs")
    def runs(jid: str):
        journey(jid)
        return sorted(
            store.all("runs", journey_id=jid), key=lambda r: r["created"], reverse=True
        )

    @app.post("/api/journeys/{jid}/runs", status_code=201)
    def new_run(jid: str, data: RunInput, request: Request):
        j = journey(jid)
        paper = require("papers", data.paper_id, jid)
        idem = request.headers.get("Idempotency-Key", uid())
        rid = "r_" + content_hash(jid + idem)[:32]
        old = store.get("runs", rid)
        if old:
            return old
        # One active run per journey; durable claim prevents duplicate starts from concurrent tabs.
        active = [
            r
            for r in store.all("runs", journey_id=jid)
            if r["status"] in ("queued", "running", "paused")
        ]
        if active:
            raise HTTPException(409, "Finish or cancel the active run first")
        if not store.insert("locks", {"id": "active:" + jid, "run_id": rid}):
            raise HTTPException(409, "An active run holds this journey lock")
        g = graph(store, j)
        run = {
            "id": rid,
            "journey_id": jid,
            "paper_id": paper["id"],
            "status": "queued",
            "checkpoint": 0,
            "attempt": 0,
            "ordinal": len(store.all("runs", journey_id=jid)),
            "budget_usd": data.budget_usd,
            "fixture": j["fixture"],
            "ingest_only": data.ingest_only,
            "created": now(),
            "before": {
                "nodes": [n["id"] for n in g["concepts"]],
                "edges": [e["id"] for e in g["edges"]],
            },
            "targets": [],
        }
        store.insert("snapshots", {"id": rid, "journey_id": jid, "graph": g})
        store.insert("runs", run)
        worker.enqueue(run)
        store.patch("journeys", jid, status="running")
        return run

    @app.get("/api/journeys/{jid}/runs/{rid}")
    def get_run(jid: str, rid: str):
        return require("runs", rid, jid)

    @app.post("/api/journeys/{jid}/runs/{rid}/{action}")
    def control(
        jid: str,
        rid: str,
        action: Literal["pause", "resume", "cancel", "retry"],
        data: dict | None = None,
    ):
        r = require("runs", rid, jid)
        if r["status"] in ("complete", "cancelled"):
            raise HTTPException(409, "Run is terminal")
        if action == "pause":
            if r["status"] not in ("running", "queued"):
                raise HTTPException(409, "Run cannot pause")
            r = store.transition_run(rid, ("running", "queued"), status="paused")
            if not r:
                raise HTTPException(409, "Run changed state")
            store.patch("journeys", jid, status="paused")
        elif action == "cancel":
            r = store.transition_run(
                rid, ("running", "queued", "paused", "failed"), status="cancelled"
            )
            if not r:
                raise HTTPException(409, "Run changed state")
            store.patch("journeys", jid, status="ready")
            store.delete("locks", "active:" + jid)
        else:
            if r["status"] not in ("paused", "failed"):
                raise HTTPException(409, "Only paused or failed runs can resume/retry")
            if r["checkpoint"] >= 7:
                r = store.transition_run(
                    rid, ("paused", "failed"), status="complete", error=None
                )
                if not r:
                    raise HTTPException(409, "Run changed state")
                store.delete("locks", "active:" + jid)
                store.patch("journeys", jid, status="ready")
                return r
            updates = {
                "status": "queued",
                "error": None,
                "attempt": r.get("attempt", 0) + (1 if action == "retry" else 0),
            }
            if data and "budget_usd" in data:
                if (
                    not math.isfinite(float(data["budget_usd"]))
                    or float(data["budget_usd"]) < 0
                ):
                    raise ValueError("Invalid budget")
                updates["budget_usd"] = float(data["budget_usd"])
            r = store.transition_run(rid, ("paused", "failed"), **updates)
            if not r:
                raise HTTPException(409, "Run changed state")
            worker.enqueue(r)
            store.patch("journeys", jid, status="running")
        store.event(jid, "run", {"id": rid, "status": r["status"]})
        return r

    @app.get("/api/journeys/{jid}/trace")
    def trace(
        jid: str,
        run_id: str | None = None,
        agent: str | None = None,
        step: int | None = None,
    ):
        journey(jid)
        items = store.all("trace", journey_id=jid)
        return sorted(
            [
                t
                for t in items
                if (not run_id or t["run_id"] == run_id)
                and (not agent or t["agent"] == agent)
                and (step is None or t["step"] == step)
            ],
            key=lambda t: t["time"],
        )

    @app.get("/api/journeys/{jid}/events")
    async def events(jid: str, request: Request, after: float = 0):
        journey(jid)

        async def stream():
            cursor = max(after, float(request.headers.get("last-event-id", "0")))
            seen = set()
            while not await request.is_disconnected():
                items = sorted(
                    [
                        e
                        for e in store.all("events", journey_id=jid)
                        if e["time"] >= cursor and e["id"] not in seen
                    ],
                    key=lambda e: (e["time"], e["id"]),
                )
                for e in items:
                    cursor = e["time"]
                    seen.add(e["id"])
                    yield (
                        "id: "
                        + str(cursor)
                        + "\nevent: update\ndata: "
                        + json.dumps(e)
                        + "\n\n"
                    )
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/journeys/{jid}/graph")
    def get_graph(
        jid: str,
        tier: str | None = None,
        existing: str | None = None,
        island: str | None = None,
        run_id: str | None = None,
        new_only: bool = False,
        before: bool = False,
        q: str | None = None,
        include_rejected: bool = False,
    ):
        j = journey(jid)
        g = graph(store, j)
        if run_id:
            r = require("runs", run_id, jid)
            if before and store.get("snapshots", run_id):
                g = store.get("snapshots", run_id)["graph"]
            elif before:
                g["concepts"] = [
                    n for n in g["concepts"] if n["id"] in r["before"]["nodes"]
                ]
                g["edges"] = [e for e in g["edges"] if e["id"] in r["before"]["edges"]]
            elif new_only:
                g["edges"] = [e for e in g["edges"] if e.get("run_id") == run_id]
        g["concepts"] = [
            n
            for n in g["concepts"]
            if (not island or n["island"] == island)
            and (not q or q.casefold() in (n["name"] + " " + n["statement"]).casefold())
        ]
        ids = {n["id"] for n in g["concepts"]}
        g["edges"] = [
            e
            for e in g["edges"]
            if (
                include_rejected
                or (e.get("review_status") != "rejected" and not e.get("invalidated"))
            )
            and all(n in ids for n in e["premises"] + [e["conclusion"]])
            and (not tier or e["tier"] == tier)
            and (not existing or e["existing"] == existing)
            and (not new_only or e.get("provenance", {}).get("kind") != "integration")
        ]
        return g

    @app.post("/api/journeys/{jid}/search/semantic")
    def semantic(jid: str, data: dict, request: Request):
        j = journey(jid)
        if config.mode == "fixture":
            return {
                "fixture": True,
                "notice": "Fixture lexical search only; no live vector search",
                "results": [
                    n
                    for n in graph(store, j)["concepts"]
                    if data.get("query", "").lower()
                    in (
                        n["name"] + " " + n["statement"] + " " + n["description"]
                    ).lower()
                ],
            }
        vector = data.get("vector")
        if data.get("query"):
            query = str(data["query"])
            if len(query) > 3000:
                raise ValueError("Semantic query limited to 3000 characters")
            cap = float(data.get("budget_usd", 0))
            if not math.isfinite(cap) or cap < 0:
                raise ValueError("Negative search budget")
            search_run = {
                "id": "search_"
                + content_hash(jid + request.headers.get("Idempotency-Key", uid())),
                "journey_id": jid,
                "budget_usd": cap,
            }
            vector = worker.providers.call(
                "embeddings",
                {"texts": [query], "input_type": "query"},
                search_run,
                "query",
            )["embeddings"][0]
        if (
            not isinstance(vector, list)
            or not 1 <= len(vector) <= 4096
            or not all(isinstance(x, (float, int)) and abs(x) < 1e10 for x in vector)
        ):
            raise ValueError(
                "Supply a finite query vector from the configured Voyage model"
            )
        return {
            "fixture": False,
            "results": AtlasVectors(store).search(
                "concepts", vector, visible_layers(j)
            ),
        }

    @app.get("/api/journeys/{jid}/details/{kind}/{ident}")
    def details(jid: str, kind: Literal["edge", "concept"], ident: str):
        collection = "edges" if kind == "edge" else "concepts"
        d = visible(jid, collection, ident)
        return {
            "item": d,
            "reviews": store.all("reviews", journey_id=jid, edge_id=ident)
            if kind == "edge"
            else [],
            "feedback": store.all("feedback", journey_id=jid, target_id=ident),
            "support": store.all("support", journey_id=jid, edge_id=ident)
            if kind == "edge"
            else [],
        }

    @app.post("/api/journeys/{jid}/proof")
    def proof(jid: str, data: dict):
        g = graph(store, journey(jid))
        return proof_closure(
            data.get("starts", []),
            {n["id"]: n for n in g["concepts"]},
            g["edges"],
            bool(data.get("allow_cited", True)),
        )

    @app.get("/api/journeys/{jid}/runs/{rid}/report")
    def get_report(jid: str, rid: str):
        return report_data(jid, rid)

    @app.get("/api/journeys/{jid}/runs/{rid}/export/{fmt}")
    def export(jid: str, rid: str, fmt: Literal["json", "md", "pdf"]):
        r = report_data(jid, rid)
        run = require("runs", rid, jid)
        payload = dict(
            report=r,
            run=run,
            trace=store.all("trace", journey_id=jid, run_id=rid),
            reviews=store.all("reviews", journey_id=jid, run_id=rid),
        )
        if fmt == "json":
            raw = json.dumps(payload, indent=2, ensure_ascii=False).encode()
            mime = "application/json"
        else:
            text = (
                "# Metis exploration report\n\n"
                + ("FIXTURE SIMULATION — NOT DISCOVERY\n\n" if r["fixture"] else "")
                + r["summary"]
                + "\n\n"
            )
            for key, title in [
                ("potentially_new", "Potentially new (recorded searches only)"),
                ("rediscoveries", "Rediscoveries"),
                ("unchecked", "Unchecked"),
            ]:
                text += "## " + title + "\n\n"
                for e in r[key]:
                    text += (
                        "- "
                        + e["argument"]
                        + " | "
                        + e["tier"]
                        + " | "
                        + e["existing"]
                        + " | score "
                        + str((e.get("bridge_score") or {}).get("value"))
                        + "\n  Evidence: "
                        + json.dumps(e["evidence"], ensure_ascii=False)
                        + "\n  Search: "
                        + json.dumps(e.get("literature", {}), ensure_ascii=False)
                        + "\n"
                    )
            if fmt == "md":
                raw = text.encode()
                mime = "text/markdown"
            else:
                from reportlab.pdfgen import canvas
                from reportlab.pdfbase import pdfmetrics
                from reportlab.pdfbase.ttfonts import TTFont
                import reportlab

                font_path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
                if "MetisVera" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("MetisVera", str(font_path)))
                from textwrap import wrap

                buf = io.BytesIO()
                c = canvas.Canvas(buf)
                c.setTitle("Metis exploration report")
                c.setFont("MetisVera", 9)
                y = 800
                for line in text.splitlines():
                    for part in wrap(line, 95) or [""]:
                        if y < 45:
                            c.showPage()
                            c.setFont("MetisVera", 9)
                            y = 800
                        c.drawString(35, y, part)
                        y -= 13
                c.save()
                raw = buf.getvalue()
                mime = "application/pdf"
        return Response(
            raw,
            media_type=mime,
            headers={
                "Content-Disposition": f'attachment; filename="metis-{rid}.{fmt}"'
            },
        )

    @app.post("/api/journeys/{jid}/feedback", status_code=201)
    def feedback(jid: str, data: FeedbackInput):
        j = journey(jid)
        d = visible(
            jid, "edges" if data.target_type == "edge" else "concepts", data.target_id
        )
        f = dict(data.model_dump(), id=uid("f_"), journey_id=jid, time=now())
        store.put("feedback", f)
        if data.mark == "wrong":
            # Base content remains immutable: store journey invalidation overlay.
            store.put(
                "memory",
                {
                    "id": jid + ":invalid:" + d["id"],
                    "journey_id": jid,
                    "kind": "invalidation",
                    "target_id": d["id"],
                    "feedback_id": f["id"],
                },
            )
            if data.target_type == "edge":
                invalidate_dependents(
                    store, j, d["id"], "User wrong feedback pending re-review"
                )
                item = {
                    "id": f["id"],
                    "journey_id": jid,
                    "edge_id": d["id"],
                    "status": "queued",
                    "feedback_id": f["id"],
                }
                store.put("rechecks", item)
                worker.enqueue_recheck(item)
            else:
                if d["layer"] == "journey:" + jid:
                    store.patch("concepts", d["id"], invalidated=True)
                for e in graph(store, j)["edges"]:
                    if d["id"] in e["premises"] + [e["conclusion"]]:
                        invalidate_dependents(
                            store, j, e["id"], "Wrong concept feedback"
                        )
        store.event(jid, "feedback", f)
        return f

    @app.post("/api/journeys/{jid}/rechecks/{fid}")
    def recheck(jid: str, fid: str):
        item = require("rechecks", fid, jid)
        worker.perform_recheck(item)
        return store.get("rechecks", fid)

    @app.get("/api/journeys/{jid}/rechecks")
    def rechecks(jid: str):
        journey(jid)
        return store.all("rechecks", journey_id=jid)

    @app.get("/api/discoveries")
    def discoveries():
        results = []
        for r in store.all("reports"):
            j = journey(r["journey_id"])
            for ident in r.get("potentially_new", []):
                e = store.get("edges", ident)
                if e and not e.get("invalidated"):
                    results.append(
                        {
                            "journey_id": j["id"],
                            "journey_name": j["name"],
                            "run_id": r["id"],
                            "edge": e,
                            "fixture": r["fixture"],
                        }
                    )
        return results

    @app.get("/api/settings")
    def settings():
        return {
            "roles": worker.providers.public(),
            "credentials": "Server environment only; keys are never returned",
            "live_enabled": config.allow_live,
            "global_budget_usd": config.live_budget,
            "lean_image": config.lean_image or None,
        }

    @app.put("/api/settings/providers")
    def update_providers(data: dict[str, RoleSpec]):
        if not config.provider_file:
            raise ValueError(
                "Set METIS_PROVIDERS_FILE to a writable server configuration path"
            )
        allowed = set(worker.providers.public()) | {"embeddings"}
        if not set(data).issubset(allowed):
            raise ValueError("Unknown role")
        roles = {r: s.model_dump() for r, s in data.items()}
        temp = config.provider_file + ".tmp"
        Path(temp).write_text(json.dumps(roles, indent=2))
        os.chmod(temp, 0o600)
        os.replace(temp, config.provider_file)
        worker.providers.roles = roles
        return worker.providers.public()

    @app.get("/api/costs")
    def costs(journey_id: str | None = None):
        if journey_id:
            journey(journey_id)
        calls = store.all("calls")
        if journey_id:
            calls = [c for c in calls if c["journey_id"] == journey_id]
        return {
            "accounting": "Conservative maximum-cost charges, not provider invoices. Ambiguous calls retain charge.",
            "calls": [
                {k: v for k, v in c.items() if k not in ("result",)} for c in calls
            ],
            "budgets": store.all("budgets"),
            "total_usd": sum(c["max_cost_usd"] for c in calls),
            "fixture": config.mode == "fixture",
        }

    web = Path(__file__).resolve().parent.parent / "web"
    app.mount("/static", StaticFiles(directory=web), name="static")

    @app.get("/")
    def index():
        return FileResponse(web / "index.html")

    return app
