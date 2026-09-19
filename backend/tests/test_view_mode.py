"""The More-tab view switch (owner, 2026-09-19): a level_4 admin narrows to
their own team, an admin below level_4 reads as the agent they are. A
preference on the users doc; never a change to the is_admin grant."""
import server
from conftest import make_session, auth


async def add_rga(db, agent_id, office):
    await db.agent_profiles.insert_one({
        "agent_id": agent_id, "name": agent_id, "email": f"{agent_id.lower()}@test.dev",
        "role": "level_4", "upline_id": None, "office": office,
    })


async def entry(db, *, agent_id, gross_alp):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}", "agent_id": agent_id,
        "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 1, "sales": 1, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": float(gross_alp), "net_alp": float(gross_alp),
    })


async def admin_session(db, *, role, agent_id, email):
    token = await make_session(db, role=role, agent_id=agent_id, email=email)
    await db.users.update_one({"email": email}, {"$set": {"is_admin": True}})
    return token


async def test_me_reports_the_switch_only_to_admins_with_an_agent_link(client, seeded_db):
    mj = await admin_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    me = (await client.get("/api/auth/me", headers=auth(mj))).json()["user"]
    assert me["view_mode"] == "full" and me["can_toggle_view"] is True

    # An admin with no agent link (Morgan) has nothing to narrow to.
    morgan = await admin_session(seeded_db, role="pending", agent_id=None, email="morgan@test.dev")
    me = (await client.get("/api/auth/me", headers=auth(morgan))).json()["user"]
    assert me["can_toggle_view"] is False

    # A plain RGA is not offered it either — narrowing is MJ's request.
    await add_rga(seeded_db, "RGA_2", "Rival")
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_2", email="rga2@test.dev")
    me = (await client.get("/api/auth/me", headers=auth(rga))).json()["user"]
    assert me["can_toggle_view"] is False
    r = await client.post("/api/me/view-mode", json={"view_mode": "own"}, headers=auth(rga))
    assert r.status_code == 403


async def test_bad_value_is_refused(client, seeded_db):
    mj = await admin_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/me/view-mode", json={"view_mode": "everything"}, headers=auth(mj))
    assert r.status_code == 400


async def test_level4_admin_own_view_narrows_reads_to_their_downline(client, seeded_db):
    # A rival office with its own RGA, outside RGA_1's tree.
    await add_rga(seeded_db, "RGA_2", "Rival")
    await entry(seeded_db, agent_id="AG_1", gross_alp=1000)   # RGA_1's tree
    await entry(seeded_db, agent_id="RGA_2", gross_alp=5000)  # not
    mj = await admin_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")

    full = (await client.get("/api/dashboard/summary", headers=auth(mj))).json()
    assert full["is_full_agency"] is True and full["total_alp"] == 6000.0

    r = await client.post("/api/me/view-mode", json={"view_mode": "own"}, headers=auth(mj))
    assert r.status_code == 200
    own = (await client.get("/api/dashboard/summary", headers=auth(mj))).json()
    assert own["is_full_agency"] is False and own["total_alp"] == 1000.0

    team = (await client.get("/api/team", headers=auth(mj))).json()["team"]
    ids = {row["agent_id"] for row in team}
    assert "AG_1" in ids and "AG_2" in ids  # the whole downline, across offices
    assert "RGA_2" not in ids

    wall = (await client.get("/api/dashboard/platinum-wall", headers=auth(mj))).json()
    wall_ids = {w["agent_id"] for w in wall["vets"] + wall["rookies"] + wall.get("unranked", [])}
    assert "RGA_2" not in wall_ids and "AG_1" in wall_ids

    # Flipping back restores the agency without a re-login.
    await client.post("/api/me/view-mode", json={"view_mode": "full"}, headers=auth(mj))
    back = (await client.get("/api/dashboard/summary", headers=auth(mj))).json()
    assert back["is_full_agency"] is True and back["total_alp"] == 6000.0


async def test_level1_admin_own_view_reads_the_board_as_a_plain_agent(client, seeded_db):
    afnan = await admin_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, agent_id="SA_1", gross_alp=100)

    # Admin view: the whole office is hers to act on, as it is for any admin.
    team = (await client.get("/api/team", headers=auth(afnan))).json()["team"]
    assert {row["agent_id"]: row["in_my_downline"] for row in team}["SA_1"] is True

    await client.post("/api/me/view-mode", json={"view_mode": "own"}, headers=auth(afnan))
    team = (await client.get("/api/team", headers=auth(afnan))).json()["team"]
    rows = {row["agent_id"]: row for row in team}
    assert rows["SA_1"]["in_my_downline"] is False
    assert "no_pulse" not in rows["GA_1"]["alerts"]  # judgement alerts stripped, as for any agent
    # Still her office, exactly as a level_1 reads it.
    assert "AG_2" not in rows

    # The grant itself is untouched: admin routes keep working in either view.
    r = await client.get("/api/admin/people", headers=auth(afnan))
    assert r.status_code == 200
