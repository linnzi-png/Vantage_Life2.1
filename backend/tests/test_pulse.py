"""Pulse submission: entry creation, sales-day assignment, buffered-flush limits."""
import server
from conftest import auth, make_session

FULL_PULSE = {
    "sets": 4, "sits": 3, "sales": 2, "ots_sits": 1, "ots_sales": 0,
    "n1": 1, "refs_obtained": 5, "ref_sits": 1, "ref_sales": 0,
    "pos_sits": 1, "pos_sales": 1, "vet_sits": 0, "vet_sales": 0,
    "gross_alp": 2500.0,
}


async def test_agent_can_submit_pulse(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/pulse", json=FULL_PULSE, headers=auth(token))
    assert r.status_code == 200, r.text

    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert entry is not None
    for k, v in FULL_PULSE.items():
        assert entry[k] == v, f"{k}: {entry[k]} != {v}"
    assert entry["sales_day"] == server.current_sales_day_str()
    assert entry["office"] == "MCM"


async def test_future_sales_day_rejected(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "sales_day": "2099-01-01"}, headers=auth(token))
    assert r.status_code == 400


async def test_stale_buffered_sales_day_rejected(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "sales_day": "2020-01-01"}, headers=auth(token))
    assert r.status_code == 400


async def test_malformed_sales_day_rejected(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "sales_day": "01/01/2026"}, headers=auth(token))
    assert r.status_code == 400
