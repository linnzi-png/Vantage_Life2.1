"""Team dashboard row: GET /api/team/dashboard (owner: MJ 2026-09-25; Linnzi
2026-09-26 and 2026-09-29).

The caller's own read scope broken down by SA team on Daily / Weekly / Monthly,
with each person's licensed states and an exact-code state filter.

Fixture (conftest): RGA_1 > MGA_1 > GA_1 > SA_1 > AG_1, and GA_2 (office AMP).
"""
from datetime import date, timedelta

import server
from conftest import auth, make_session

TODAY = server.current_sales_day_str()
OLD = (date.fromisoformat(TODAY) - timedelta(days=60)).isoformat()


async def prod(db, agent_id, gross, *, sales=1, sits=2, day=None):
    day = day or TODAY
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}_{day}_{gross}", "agent_id": agent_id, "office": "MCM", "sales_day": day,
        "sets": 3, "sits": sits, "sales": sales, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0, "gross_alp": float(gross), "net_alp": float(gross)})


async def states(db, agent_id, licensed, pending=None):
    await db.agent_profiles.update_one(
        {"agent_id": agent_id},
        {"$set": {"licensed_states": licensed, "pending_states": pending or []}})


async def as_(db, role, agent_id):
    return await make_session(db, role=role, agent_id=agent_id, email=f"{agent_id.lower()}@test.dev")


async def get(client, token, **params):
    return await client.get("/api/team/dashboard", params=params, headers=auth(token))


def team_of(body, leader_id):
    return next((t for t in body["teams"] if t["leader"]["agent_id"] == leader_id), None)


async def test_people_are_grouped_by_the_same_team_missing_numbers_uses(client, seeded_db):
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token)).json()
    assert {m["agent_id"] for m in team_of(body, "SA_1")["members"]} == {"SA_1", "AG_1"}
    assert {m["agent_id"] for m in team_of(body, "GA_1")["members"]} == {"GA_1"}


async def test_all_three_windows_carry_totals_and_close_ratio(client, seeded_db):
    await prod(seeded_db, "SA_1", 200, sales=1, sits=2)
    await prod(seeded_db, "AG_1", 300, sales=1, sits=2)
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token)).json()
    t = team_of(body, "SA_1")["totals"]
    for period in ("daily", "weekly", "monthly"):
        assert t[period]["gross_alp"] == 500.0
        assert t[period]["sales"] == 2
        assert t[period]["close_ratio"] == 50.0
        assert body["periods"][period]["end_day"] == TODAY
    assert body["total"]["monthly"]["gross_alp"] == 500.0


async def test_production_outside_every_window_is_left_out(client, seeded_db):
    await prod(seeded_db, "AG_1", 900, day=OLD)
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token)).json()
    assert body["total"]["monthly"]["gross_alp"] == 0


async def test_each_person_carries_their_licensed_states(client, seeded_db):
    await states(seeded_db, "AG_1", ["MI", "OH"])
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token)).json()
    members = {m["agent_id"]: m for t in body["teams"] for m in t["members"]}
    assert members["AG_1"]["licensed_states"] == ["MI", "OH"]


async def test_the_state_filter_is_an_exact_code_match_and_totals_follow_it(client, seeded_db):
    await states(seeded_db, "SA_1", ["MI", "OH"])
    await states(seeded_db, "AG_1", ["OH"])
    await states(seeded_db, "GA_1", ["MI"])
    await prod(seeded_db, "SA_1", 200)
    await prod(seeded_db, "AG_1", 300)
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token, state="mi")).json()
    assert body["state"] == "MI"
    assert {m["agent_id"] for t in body["teams"] for m in t["members"]} == {"SA_1", "GA_1"}
    assert team_of(body, "SA_1")["totals"]["monthly"]["gross_alp"] == 200.0
    assert team_of(body, "SA_1")["head_count"] == 1


async def test_a_pending_state_does_not_match_the_filter(client, seeded_db):
    await states(seeded_db, "AG_1", [], pending=["IA"])
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token, state="IA")).json()
    assert body["teams"] == []


async def test_a_state_nobody_holds_is_an_empty_list_and_still_offers_the_real_ones(client, seeded_db):
    await states(seeded_db, "AG_1", ["MI"])
    token = await as_(seeded_db, "level_2", "GA_1")
    body = (await get(client, token, state="WY")).json()
    assert body["teams"] == []
    assert body["total"]["monthly"]["gross_alp"] == 0
    assert body["available_states"] == ["MI"]


async def test_an_unknown_state_is_a_400(client, seeded_db):
    token = await as_(seeded_db, "level_2", "GA_1")
    assert (await get(client, token, state="ZZ")).status_code == 400


async def test_an_agent_sees_only_their_own_sa_team(client, seeded_db):
    token = await as_(seeded_db, "level_1", "AG_1")
    body = (await get(client, token)).json()
    ids = {m["agent_id"] for t in body["teams"] for m in t["members"]}
    assert ids <= {"SA_1", "AG_1"}
    assert "GA_1" not in ids


async def test_an_archived_person_is_not_listed(client, seeded_db):
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    token = await as_(seeded_db, "level_2", "GA_1")
    ids = {m["agent_id"] for t in (await get(client, token)).json()["teams"] for m in t["members"]}
    assert "AG_1" not in ids
