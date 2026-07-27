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


# ---------------- Self buffer window: tightened to 3 days ----------------

async def test_self_buffer_within_3_days_allowed(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    sd = (server.now_detroit() - server.timedelta(days=3)).date().isoformat()
    r = await client.post("/api/pulse", json={**FULL_PULSE, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text


async def test_self_buffer_beyond_3_days_rejected(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    sd = (server.now_detroit() - server.timedelta(days=4)).date().isoformat()
    r = await client.post("/api/pulse", json={**FULL_PULSE, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 400


# ---------------- Upline proxy entry ----------------

async def test_mga_can_enter_for_downline_agent(client, seeded_db):
    # MGA_1 -> GA_1 -> SA_1 -> AG_1: AG_1 is in MGA_1's downline.
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "target_agent_id": "AG_1"}, headers=auth(token))
    assert r.status_code == 200, r.text
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert entry["is_proxy_entry"] is True
    assert entry["entered_by"] == "user_level_3_MGA_1"
    assert entry["entered_by_role"] == "level_3"
    assert entry["submitted_on_time"] is True  # bypasses the 9 PM gate


async def test_ga_cannot_enter_for_downline_agent(client, seeded_db):
    # GA is level_2 — entry starts at level_3, one tier above viewing.
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "target_agent_id": "AG_1"}, headers=auth(token))
    assert r.status_code == 403


async def test_mga_cannot_enter_for_agent_outside_downline(client, seeded_db):
    # AG_2 is under MGA_1's sibling branch (GA_2), not GA_1/SA_1 — still under
    # MGA_1 actually (MGA_1 -> GA_2 -> AG_2), so use RGA_1 vs a different MGA's
    # tree to prove the boundary: MGA_1 cannot enter for RGA_1 (upline, not down).
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "target_agent_id": "RGA_1"}, headers=auth(token))
    assert r.status_code == 403


async def test_rga_can_enter_for_anyone(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/pulse", json={**FULL_PULSE, "target_agent_id": "AG_2"}, headers=auth(token))
    assert r.status_code == 200, r.text


async def test_proxy_entry_uses_upline_7_day_buffer_not_3_day(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    sd = (server.now_detroit() - server.timedelta(days=5)).date().isoformat()
    r = await client.post("/api/pulse", json={**FULL_PULSE, "target_agent_id": "AG_1", "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text


async def test_self_entry_still_shows_entered_by_self(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/pulse", json=FULL_PULSE, headers=auth(token))
    assert r.status_code == 200
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert entry["is_proxy_entry"] is False
    assert entry["entered_by"] == "user_level_1_AG_1"


# ---------------- pulse/me/today and pulse/me/streak with target agent_id ----------------

async def test_mga_can_view_downline_today_totals(client, seeded_db):
    agent_tok = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await client.post("/api/pulse", json=FULL_PULSE, headers=auth(agent_tok))

    mga_tok = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/pulse/me/today?agent_id=AG_1", headers=auth(mga_tok))
    assert r.status_code == 200
    assert r.json()["totals"]["sales"] == FULL_PULSE["sales"]


async def test_ga_cannot_view_downline_today_totals_via_agent_id(client, seeded_db):
    ga_tok = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.get("/api/pulse/me/today?agent_id=AG_1", headers=auth(ga_tok))
    assert r.status_code == 403


async def test_mga_cannot_view_totals_outside_downline(client, seeded_db):
    mga_tok = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/pulse/me/today?agent_id=RGA_1", headers=auth(mga_tok))
    assert r.status_code == 403


async def test_mga_can_view_downline_streak(client, seeded_db):
    mga_tok = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/pulse/me/streak?agent_id=AG_1", headers=auth(mga_tok))
    assert r.status_code == 200
