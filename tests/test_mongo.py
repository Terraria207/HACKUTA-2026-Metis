"""Opt-in actual MongoDB persistence checks. Uses an isolated temporary database.
No Atlas/provider calls; does not claim Atlas Vector Search or change-stream validation.
"""

import os
import uuid
import pytest
from concurrent.futures import ThreadPoolExecutor
from metis.config import Config
from metis.store import Store


@pytest.mark.mongo
@pytest.mark.skipif(
    not os.getenv("METIS_TEST_MONGODB_URI"),
    reason="METIS_TEST_MONGODB_URI not configured",
)
def test_real_mongo_atomicity_indexes_and_restart():
    db = "mt_" + uuid.uuid4().hex  # Atlas free-tier names must fit 38 bytes.
    config = Config(
        mode="live", mongo_uri=os.environ["METIS_TEST_MONGODB_URI"], mongo_db=db
    )
    store = Store(config)
    try:
        store.put("journeys", {"id": "j", "name": "durable"})
        assert Store(config).get("journeys", "j")["name"] == "durable"
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: store.reserve("cap", 1, 0.1), range(30)))
        assert sum(results) == 10
        store.insert("jobs", {"id": "job", "status": "queued", "available_at": 0})
        with ThreadPoolExecutor(max_workers=10) as pool:
            claims = list(pool.map(lambda n: store.claim(str(n)), range(10)))
        assert len([c for c in claims if c]) == 1
        e = {"id": "e1", "layer": "journey:j", "duplicate_key": "same"}
        assert store.insert("edges", e)
        assert not store.insert("edges", dict(e, id="e2"))
        assert store.insert("edges", dict(e, id="e3", layer="journey:other"))
    finally:
        store.mongo.client.drop_database(db)
