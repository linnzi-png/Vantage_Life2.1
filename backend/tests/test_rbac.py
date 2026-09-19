"""RBAC visibility scoping: visible_agent_ids() BFS over upline_id, per tier."""
import server
from conftest import auth, make_session


async def test_level_1_sees_only_self(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_1", "agent_id": "AG_1"})
    assert ids == ["AG_1"]


async def test_level_2_sees_own_team_not_siblings(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_2", "agent_id": "GA_1"})
    assert set(ids) == {"GA_1", "SA_1", "AG_1"}
    assert "AG_2" not in ids and "GA_2" not in ids


async def test_level_3_sees_all_ga_rollups(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_3", "agent_id": "MGA_1"})
    assert set(ids) == {"MGA_1", "GA_1", "GA_2", "SA_1", "AG_1", "AG_2"}


async def test_level_4_sees_everything(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_4", "agent_id": "RGA_1"})
    assert ids is None  # None = unrestricted


async def test_agentless_user_sees_nothing(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_2", "agent_id": None})
    assert ids == []


async def test_office_agent_ids_scopes_level_1_to_office_not_downline(seeded_db):
    """AG_1 has no downline (level_1), so the Team tab uses office instead —
    same office boundary Platinum Wall already uses for level_1. AG_1's
    office (MCM) includes their own upline chain (SA_1/GA_1/MGA_1/RGA_1) but
    not AG_2/GA_2, who sit in office AMP."""
    ids = await server.office_agent_ids({"role": "level_1", "agent_id": "AG_1"})
    assert set(ids) == {"RGA_1", "MGA_1", "GA_1", "SA_1", "AG_1"}
    assert "AG_2" not in ids and "GA_2" not in ids


async def test_team_endpoint_scopes_level_1_to_their_sa_team(client, seeded_db):
    """Per owner, 2026-09-19 (MJ: "no one should see more than their SA
    team"): a level_1 reads the subtree under the nearest SA/GA above them,
    leader included. The rest of the chain comes back as contacts only."""
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_1B", "name": "Agent One B", "email": "ag1b@test.dev",
        "role": "level_1", "upline_id": "SA_1", "office": "MCM",
    })
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/team", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = {row["agent_id"] for row in body["team"]}
    assert ids == {"SA_1", "AG_1", "AG_1B"}
    assert [u["agent_id"] for u in body["uplines"]] == ["SA_1", "GA_1", "MGA_1", "RGA_1"]
    assert "gross_alp" not in body["uplines"][0]
    assert set(body["uplines"][0]) <= {"agent_id", "name", "phone", "email", "role", "io_role", "office"}


async def test_an_agent_straight_under_an_mga_reads_that_uplines_team(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_3", "name": "Agent Three", "email": "ag3@test.dev",
        "role": "level_1", "upline_id": "MGA_1", "office": "MCM",
    })
    token = await make_session(seeded_db, role="level_1", agent_id="AG_3", email="ag3@test.dev")
    ids = {row["agent_id"] for row in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert "MGA_1" in ids and "AG_3" in ids and "RGA_1" not in ids


async def test_a_plain_rga_reads_their_own_office(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
        "role": "level_4", "upline_id": None, "office": "Rival",
    })
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    ids = {row["agent_id"] for row in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert "RGA_2" not in ids
    assert {"RGA_1", "MGA_1", "GA_1", "SA_1", "AG_1", "AG_2"} <= ids  # office plus downline


async def test_level_1_cannot_add_or_remove_team_members(client, seeded_db):
    """The read-only Team tab widening must not touch write access — those
    stay behind their own level_2+ checks, unaffected by this change."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token),
                           json={"agent_id": "SA_1"})
    assert r.status_code == 403


# ---------------- what an Agent sees on the office Team tab ----------------
#
# Owner, 2026-09-14: any agent, whatever their tier, may see general team
# stats, their home office's sales numbers, any teammate's day/week/month
# production, and that teammate's basic ALP and close ratio. The judgement
# alerts — low close ratio, low average deal, no pulse — are for that person's
# uplines only. Neutral flags such as the rookie badge are not restricted.

async def test_level_1_team_rows_carry_no_judgement_alerts(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    # SA_1 sits in AG_1's office and has a deliberately terrible day: enough
    # sits for the ratio alert (5 of 15 = 33%), a small average deal ($200),
    # and AG_1 has no entry at all, which is what raises no_pulse.
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_bad", "agent_id": "SA_1", "office": "MCM",
        "sales_day": server.current_sales_day_str(),
        "sets": 20, "sits": 15, "sales": 5, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 1000.0, "net_alp": 1000.0,
    })
    rows = (await client.get("/api/team", headers=auth(token))).json()["team"]
    assert rows, "the office rollup should not be empty"
    for row in rows:
        assert not set(row["alerts"]) & server.UPLINE_ONLY_ALERTS, row
    # The numbers themselves are not withheld — only the assessment is.
    sa = next(r for r in rows if r["agent_id"] == "SA_1")
    assert sa["gross_alp"] == 1000.0
    assert sa["sales"] == 5
    assert sa["close_ratio"] == 33.3


async def test_upline_still_sees_the_judgement_alerts(client, seeded_db):
    """The same row, read by someone above them, keeps its flags."""
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_bad", "agent_id": "SA_1", "office": "MCM",
        "sales_day": server.current_sales_day_str(),
        "sets": 20, "sits": 15, "sales": 5, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 1000.0, "net_alp": 1000.0,
    })
    rows = (await client.get("/api/team", headers=auth(token))).json()["team"]
    sa = next(r for r in rows if r["agent_id"] == "SA_1")
    assert "low_close_ratio" in sa["alerts"]
    assert "low_avg_deal" in sa["alerts"]


# ---------------- office view for an upline ----------------
#
# Owner, 2026-09-19: a leader reads their own downline and nothing sideways;
# their uplines come back as contacts. in_my_downline still marks which rows
# are theirs to act on, since every write path stays downline-scoped.

async def test_a_leader_reads_their_downline_and_gets_uplines_as_contacts(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    body = (await client.get("/api/team", headers=auth(token))).json()
    rows = {r["agent_id"]: r for r in body["team"]}
    assert set(rows) == {"SA_1", "AG_1"}
    assert [u["agent_id"] for u in body["uplines"]] == ["GA_1", "MGA_1", "RGA_1"]


async def test_the_downline_flag_separates_my_team_from_myself(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert rows["AG_1"]["in_my_downline"] is True     # their agent
    assert rows["SA_1"]["in_my_downline"] is False    # themselves


async def test_judgement_alerts_are_stripped_outside_my_downline(client, seeded_db):
    """A level_1 reads their SA team's numbers; the assessment of a teammate
    is the upline's. AG_1 sees AG_1B's production and none of the flags."""
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_1B", "name": "Agent One B", "email": "ag1b@test.dev",
        "role": "level_1", "upline_id": "SA_1", "office": "MCM",
    })
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_bad", "agent_id": "AG_1B", "office": "MCM",
        "sales_day": server.current_sales_day_str(),
        "sets": 20, "sits": 15, "sales": 5, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 1000.0, "net_alp": 1000.0,
    })
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert not set(rows["AG_1B"]["alerts"]) & server.UPLINE_ONLY_ALERTS
    assert rows["AG_1B"]["gross_alp"] == 1000.0  # the numbers are still there


async def test_an_mga_keeps_a_downline_that_reaches_past_their_office(client, seeded_db):
    """GA_2 and AG_2 are in office AMP but report to MGA_1 in MCM. The office
    read must be a union with the downline, never a replacement for it."""
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert {"GA_2", "AG_2"} <= set(rows)
    assert rows["GA_2"]["in_my_downline"] is True


async def test_office_visibility_does_not_widen_any_write_path(client, seeded_db):
    """SA_1 can now see their own upline GA_1 on the board, and can do nothing
    to them: seeing the office and acting on it are separate rules."""
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    assert (await client.post("/api/team/remove-person", headers=auth(token),
                              json={"agent_id": "GA_1"})).status_code == 403
    assert (await client.post("/api/team/reassign", headers=auth(token),
                              json={"agent_id": "GA_1", "new_upline_agent_id": "SA_1"})).status_code == 403
