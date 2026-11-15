"""Identical document semantics over durable MongoDB and explicitly local SQLite fixtures.
Worker leases and budget reservations are atomic. No change stream is used as a queue.
"""

from contextlib import contextmanager
import copy
import math
import json
import os
import sqlite3
import threading
import time
import uuid
from pymongo import MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError


def now():
    return time.time()


def uid(prefix=""):
    return prefix + uuid.uuid4().hex


class Store:
    def __init__(self, config):
        self.config = config
        self.lock = threading.RLock()
        self.mongo = None
        if config.mode == "live":
            self.mongo = MongoClient(
                config.mongo_uri, serverSelectionTimeoutMS=5000, maxPoolSize=10
            )[config.mongo_db]
            self.mongo.command("ping")
            for name in (
                "operations",
                "modules",
                "journeys",
                "groups",
                "concepts",
                "edges",
                "papers",
                "extractions",
                "runs",
                "jobs",
                "trace",
                "reviews",
                "feedback",
                "memory",
                "calls",
                "budgets",
                "discussion",
                "builds",
                "support",
                "events",
                "reports",
                "rechecks",
                "locks",
                "snapshots",
                "sources",
            ):
                self.mongo[name].create_index("id", unique=True)
            self.mongo.edges.create_index(
                [("layer", 1), ("duplicate_key", 1)], unique=True
            )
            self.mongo.jobs.create_index([("status", 1), ("lease_until", 1)])
            self.mongo.calls.create_index("call_key", unique=True)
            self.mongo.trace.create_index([("run_id", 1), ("time", 1)])
            self.mongo.discussion.create_index([("journey_id", 1), ("time", 1)])
            for name in ("groups", "concepts"):
                self.mongo[name].create_index("layer")
            self.mongo.extractions.create_index("cache_key", unique=True)
            # Live view polls only events newer than the client's cursor.
            self.mongo.events.create_index([("journey_id", 1), ("time", 1)])
        else:
            os.makedirs(os.path.dirname(config.sqlite_path) or ".", exist_ok=True)
            self.sql = sqlite3.connect(
                config.sqlite_path, check_same_thread=False, isolation_level=None
            )
            self.sql.execute("PRAGMA journal_mode=WAL")
            self.sql.execute(
                "CREATE TABLE IF NOT EXISTS docs (collection TEXT, id TEXT, body TEXT, PRIMARY KEY(collection,id))"
            )
            self.sql.execute(
                "CREATE INDEX IF NOT EXISTS docs_events_cursor ON docs(collection, json_extract(body,'$.journey_id'), json_extract(body,'$.time'))"
            )
            # A deployment can hold dozens of basis groups; reads must not scan all of them.
            for key in ("layer", "journey_id", "run_id", "edge_id"):
                self.sql.execute(
                    "CREATE INDEX IF NOT EXISTS docs_%s ON docs(collection, json_extract(body,'$.%s'))" % (key, key)
                )

    def get(self, collection, ident):
        if self.mongo is not None:
            d = self.mongo[collection].find_one({"id": ident}, {"_id": 0})
            return d
        with self.lock:
            row = self.sql.execute(
                "SELECT body FROM docs WHERE collection=? AND id=?", (collection, ident)
            ).fetchone()
            return json.loads(row[0]) if row else None

    def all(self, collection, **where):
        if self.mongo is not None:
            return list(self.mongo[collection].find(where, {"_id": 0}))
        # Plain string and integer filters go to SQLite (indexed for the common keys); anything
        # else is compared in Python. The Python check below keeps the semantics identical.
        sql, params = "SELECT body FROM docs WHERE collection=?", [collection]
        for key, value in where.items():
            if key.isidentifier() and type(value) in (str, int):
                sql += " AND json_extract(body,'$.%s')=?" % key
                params.append(value)
        with self.lock:
            docs = [json.loads(r[0]) for r in self.sql.execute(sql, params)]
        return [d for d in docs if all(d.get(k) == v for k, v in where.items())]

    def layered(self, collection, layers):
        """Documents of the given layers only (a journey's modules plus its own layer)."""
        layers = list(layers)
        if not layers:
            return []
        if self.mongo is not None:
            return list(self.mongo[collection].find({"layer": {"$in": layers}}, {"_id": 0}))
        with self.lock:
            rows = self.sql.execute(
                "SELECT body FROM docs WHERE collection=? AND json_extract(body,'$.layer') IN (%s)" % ",".join("?" * len(layers)),
                [collection] + layers,
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def count_layer(self, collection, layer):
        if self.mongo is not None:
            return self.mongo[collection].count_documents({"layer": layer})
        with self.lock:
            return self.sql.execute(
                "SELECT COUNT(*) FROM docs WHERE collection=? AND json_extract(body,'$.layer')=?", (collection, layer)
            ).fetchone()[0]

    def events_since(self, journey_id, since):
        """Events at or after a time cursor, in cursor order; never a full-collection scan."""
        if self.mongo is not None:
            return list(
                self.mongo.events.find(
                    {"journey_id": journey_id, "time": {"$gte": since}}, {"_id": 0}
                ).sort([("time", 1), ("id", 1)])
            )
        with self.lock:
            rows = self.sql.execute(
                "SELECT body FROM docs WHERE collection='events' AND json_extract(body,'$.journey_id')=? AND json_extract(body,'$.time')>=?",
                (journey_id, since),
            ).fetchall()
        return sorted((json.loads(r[0]) for r in rows), key=lambda e: (e["time"], e["id"]))

    def _check_published(self, collection, ident):
        if collection not in ("modules", "concepts", "groups", "edges"):
            return
        existing = self.get(collection, ident)
        if not existing:
            return
        module = existing if collection == "modules" else (
            self.get("modules", existing.get("layer", "")[7:])
            if existing.get("layer", "").startswith("module:") else None
        )
        if module and module.get("status") == "ready":
            raise ValueError("Published module versions are immutable; publish a new version")

    def put(self, collection, doc):
        doc = copy.deepcopy(doc)
        if "id" in doc:
            self._check_published(collection, doc["id"])
        if "id" not in doc:
            doc["id"] = uid()
        if self.mongo is not None:
            self.mongo[collection].replace_one({"id": doc["id"]}, doc, upsert=True)
        else:
            with self.lock:
                self.sql.execute(
                    "INSERT INTO docs VALUES(?,?,?) ON CONFLICT(collection,id) DO UPDATE SET body=excluded.body",
                    (collection, doc["id"], json.dumps(doc)),
                )
        return doc

    def insert(self, collection, doc):
        try:
            if self.mongo is not None:
                self.mongo[collection].insert_one(copy.deepcopy(doc))
            else:
                with self.lock:
                    self.sql.execute(
                        "INSERT INTO docs VALUES(?,?,?)",
                        (collection, doc["id"], json.dumps(doc)),
                    )
            return True
        except (DuplicateKeyError, sqlite3.IntegrityError):
            return False

    def patch(self, collection, ident, **updates):
        self._check_published(collection, ident)
        if self.mongo is not None:
            return self.mongo[collection].find_one_and_update(
                {"id": ident},
                {"$set": updates},
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
        with self.lock:
            d = self.get(collection, ident)
            if d is None:
                return None
            return self.put(collection, dict(d, **updates))

    def transition_run(self, ident, allowed, **updates):
        if self.mongo is not None:
            return self.mongo.runs.find_one_and_update(
                {"id": ident, "status": {"$in": list(allowed)}},
                {"$set": updates},
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
        with self.lock:
            current = self.get("runs", ident)
            if not current or current["status"] not in allowed:
                return None
            return self.patch("runs", ident, **updates)

    def release_run_lock(self, journey_id, run_id):
        ident = "active:" + journey_id
        if self.mongo is not None:
            self.mongo.locks.delete_one({"id": ident, "run_id": run_id})
        else:
            with self.lock:
                current = self.get("locks", ident)
                if current and current.get("run_id") == run_id:
                    self.delete("locks", ident)

    def advance_run(self, ident, checkpoint):
        next_step = checkpoint + 1
        if self.mongo is not None:
            return self.mongo.runs.find_one_and_update(
                {"id": ident, "checkpoint": checkpoint},
                [
                    {
                        "$set": {
                            "checkpoint": next_step,
                            "status": {
                                "$cond": [
                                    {"$in": ["$status", ["paused", "cancelled"]]},
                                    "$status",
                                    "complete" if next_step == 7 else "queued",
                                ]
                            },
                            "error": None,
                            "updated": now(),
                        }
                    }
                ],
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
        with self.lock:
            current = self.get("runs", ident)
            if not current or current["checkpoint"] != checkpoint:
                return None
            status = (
                current["status"]
                if current["status"] in ("paused", "cancelled")
                else "complete"
                if next_step == 7
                else "queued"
            )
            return self.patch(
                "runs",
                ident,
                checkpoint=next_step,
                status=status,
                error=None,
                updated=now(),
            )

    def delete(self, collection, ident):
        self._check_published(collection, ident)
        if self.mongo is not None:
            self.mongo[collection].delete_one({"id": ident})
        else:
            with self.lock:
                self.sql.execute(
                    "DELETE FROM docs WHERE collection=? AND id=?", (collection, ident)
                )

    def claim(self, owner, lease=120):
        t = now()
        if self.mongo is not None:
            return self.mongo.jobs.find_one_and_update(
                {
                    "$or": [
                        {"status": "queued", "available_at": {"$lte": t}},
                        {"status": "working", "lease_until": {"$lt": t}},
                    ]
                },
                {
                    "$set": {
                        "status": "working",
                        "owner": owner,
                        "lease_until": t + lease,
                    }
                },
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
                sort=[("available_at", 1)],
            )
        with self.lock:
            self.sql.execute("BEGIN IMMEDIATE")
            try:
                candidates = [
                    j
                    for j in self.all("jobs")
                    if (j["status"] == "queued" and j.get("available_at", 0) <= t)
                    or (j["status"] == "working" and j.get("lease_until", 0) < t)
                ]
                if not candidates:
                    self.sql.execute("COMMIT")
                    return None
                j = min(candidates, key=lambda j: j.get("available_at", 0))
                j.update(status="working", owner=owner, lease_until=t + lease)
                self.put("jobs", j)
                self.sql.execute("COMMIT")
                return j
            except Exception:
                self.sql.execute("ROLLBACK")
                raise

    def owned_patch(self, job, **updates):
        if self.mongo is not None:
            return self.mongo.jobs.find_one_and_update(
                {"id": job["id"], "owner": job["owner"], "status": "working"},
                {"$set": updates},
                return_document=ReturnDocument.AFTER,
                projection={"_id": 0},
            )
        with self.lock:
            current = self.get("jobs", job["id"])
            if current.get("owner") != job["owner"] or current["status"] != "working":
                return None
            return self.patch("jobs", job["id"], **updates)

    @contextmanager
    def transaction(self):
        # Separate Store connections have separate Python locks. SQLite's write
        # transaction supplies the cross-connection reservation boundary.
        with self.lock:
            nested = self.sql.in_transaction
            if not nested:
                self.sql.execute("BEGIN IMMEDIATE")
            try:
                yield
                if not nested:
                    self.sql.execute("COMMIT")
            except BaseException:
                if not nested:
                    self.sql.execute("ROLLBACK")
                raise

    def reserve(self, account, cap, amount):
        if not all(math.isfinite(v) for v in (cap, amount)) or amount <= 0:
            raise ValueError("A positive maximum call cost is required")
        self.insert("budgets", {"id": account, "spent": 0.0, "reserved": 0.0})
        if self.mongo is not None:
            result = self.mongo.budgets.find_one_and_update(
                {
                    "id": account,
                    "$expr": {"$lte": [{"$add": ["$spent", "$reserved", amount]}, cap]},
                },
                {"$inc": {"reserved": amount}},
                return_document=ReturnDocument.AFTER,
            )
            return result is not None
        with self.transaction():
            d = self.get("budgets", account)
            if d["spent"] + d["reserved"] + amount > cap + 1e-9:
                return False
            self.patch("budgets", account, reserved=d["reserved"] + amount)
            return True

    def settle(self, account, reserved, charged):
        if self.mongo is not None:
            self.mongo.budgets.update_one(
                {"id": account}, {"$inc": {"reserved": -reserved, "spent": charged}}
            )
        else:
            with self.transaction():
                d = self.get("budgets", account)
                self.patch(
                    "budgets",
                    account,
                    reserved=max(0, d["reserved"] - reserved),
                    spent=d["spent"] + charged,
                )

    def event(self, journey, kind, data):
        return self.put(
            "events",
            {
                "id": uid("ev_"),
                "journey_id": journey,
                "kind": kind,
                "data": data,
                "time": now(),
            },
        )
