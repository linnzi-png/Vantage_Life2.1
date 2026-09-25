"""Licensed states (owner, 2026-09-24): the list of states an agent may sell
in. A NEW list field, separate from the single resident `state` used by the
WAR-parity export — nothing here may touch `state` or /admin/set-state.

Two write paths, audit-logged the same way set-tenure is:
  * POST /api/me/licensed-states — the agent's own list.
  * POST /api/team/set-licensed-states — a leader, for their own downline
    (level_4 agency-wide, like every other Team tab write).

Fixture chain: RGA_1 -> MGA_1 -> GA_1 -> SA_1 -> AG_1, and MGA_1 -> GA_2 -> AG_2.
"""
import pytest

import server
from conftest import auth, make_session


async def profile(db, agent_id):
    return await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})


async def set_mine(client, token, codes):
    return await client.post("/api/me/licensed-states", headers=auth(token), json={"licensed_states": codes})


async def set_theirs(client, token, agent_id, codes):
    return await client.post("/api/team/set-licensed-states", headers=auth(token),
                             json={"agent_id": agent_id, "licensed_states": codes})


# ---------------- the list itself ----------------

async def test_agent_records_their_own_states_uppercased_deduplicated_sorted(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_mine(client, token, ["oh", " MI ", "OH", "mi", "tx"])
    assert r.status_code == 200, r.text
    assert r.json()["licensed_states"] == ["MI", "OH", "TX"]
    assert (await profile(seeded_db, "AG_1"))["licensed_states"] == ["MI", "OH", "TX"]


async def test_invalid_code_is_rejected_and_nothing_is_written(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_mine(client, token, ["MI", "XX", "Ohio"])
    assert r.status_code == 400
    assert "OHIO" in r.json()["detail"] and "XX" in r.json()["detail"]
    assert "licensed_states" not in (await profile(seeded_db, "AG_1"))


async def test_territories_are_not_accepted(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_mine(client, token, ["PR"])).status_code == 400
    assert (await set_mine(client, token, ["DC"])).status_code == 200


async def test_empty_list_clears_the_field_without_error(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_mine(client, token, ["MI"])).status_code == 200
    r = await set_mine(client, token, [])
    assert r.status_code == 200
    assert (await profile(seeded_db, "AG_1"))["licensed_states"] == []


async def test_resident_state_is_untouched(client, seeded_db):
    """`state` is the resident state the WAR export reads. A licensed-states
    write must never read or change it."""
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"state": "MI"}})
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_mine(client, token, ["OH", "IN"])).status_code == 200
    p = await profile(seeded_db, "AG_1")
    assert p["state"] == "MI"
    assert p["licensed_states"] == ["IN", "OH"]


async def test_self_write_is_audit_logged_like_set_tenure(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await set_mine(client, token, ["MI"])
    await set_mine(client, token, ["MI", "OH"])
    entries = [e async for e in seeded_db.audit_log.find({"action": "set_licensed_states_self"}, {"_id": 0})]
    assert len(entries) == 2
    assert entries[1]["agent_id"] == "AG_1"
    assert entries[1]["original_value"] == ["MI"]
    assert entries[1]["new_value"] == ["MI", "OH"]
    assert entries[1]["changed_by_name"] == "ag1"


async def test_pending_user_cannot_write(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="nobody@test.dev")
    assert (await set_mine(client, token, ["MI"])).status_code == 403


# ---------------- the team path ----------------

async def test_sa_sets_states_for_a_downline_agent(client, seeded_db):
    token = await make_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    r = await set_theirs(client, token, "AG_1", ["mi", "OH"])
    assert r.status_code == 200, r.text
    assert (await profile(seeded_db, "AG_1"))["licensed_states"] == ["MI", "OH"]
    entry = await seeded_db.audit_log.find_one({"action": "set_licensed_states"}, {"_id": 0})
    assert entry["agent_id"] == "AG_1" and entry["changed_by_name"] == "sa1"


async def test_ga_reaches_two_levels_down_but_not_sideways(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert (await set_theirs(client, token, "AG_1", ["MI"])).status_code == 200
    assert (await set_theirs(client, token, "AG_2", ["MI"])).status_code == 403
    assert "licensed_states" not in (await profile(seeded_db, "AG_2"))


async def test_an_agent_cannot_use_the_team_path(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_theirs(client, token, "AG_2", ["MI"])).status_code == 403


async def test_rga_is_agency_wide(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await set_theirs(client, token, "AG_2", ["FL"])).status_code == 200


async def test_leader_sets_their_own_from_the_profile_not_the_team_path(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert (await set_theirs(client, token, "GA_1", ["MI"])).status_code == 400
    assert (await set_mine(client, token, ["MI"])).status_code == 200


async def test_team_path_rejects_invalid_codes_and_archived_people(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    assert (await set_theirs(client, token, "AG_1", ["ZZ"])).status_code == 400
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    assert (await set_theirs(client, token, "AG_1", ["MI"])).status_code == 404


# ---------------- where the list is read ----------------

async def entry(db, *, agent_id, gross_alp):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}", "agent_id": agent_id, "office": "MCM",
        "sales_day": server.current_sales_day_str(),
        "sets": 2, "sits": 2, "sales": 1, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": float(gross_alp), "net_alp": float(gross_alp),
    })


async def test_team_rows_carry_the_list_with_and_without_production(client, seeded_db):
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"licensed_states": ["MI", "OH"]}})
    await entry(seeded_db, agent_id="AG_1", gross_alp=500)
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert rows["AG_1"]["licensed_states"] == ["MI", "OH"]
    # SA_1 has no entries and no field: the row still carries an empty list.
    assert rows["SA_1"]["licensed_states"] == []


async def test_history_carries_the_list_on_the_agent_block(client, seeded_db):
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"licensed_states": ["MI"]}})
    token = await make_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    body = (await client.get("/api/agents/AG_1/history", headers=auth(token))).json()
    assert body["agent"]["licensed_states"] == ["MI"]
    body = (await client.get("/api/agents/SA_1/history", headers=auth(token))).json()
    assert body["agent"]["licensed_states"] == []
