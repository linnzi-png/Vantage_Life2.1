"""Tenure set from the Team tab (owner, 2026-09-24): POST /api/team/set-tenure.

The SET TENURE badge and the morning nudge go to the person's upline, so the
upline must be able to act. Same gate as set-tier and set-licensed-states:
leaders (SA and above) inside their own downline, level_4 agency-wide,
is_admin and finance_admin agency-wide whatever tier their login carries.
Same audit_log shape as /admin/set-tenure, which stays the admin panel's path.

Fixture chain: RGA_1 -> MGA_1 -> GA_1 -> SA_1 -> AG_1, and MGA_1 -> GA_2 -> AG_2.
"""
import pytest

import server
from conftest import auth, make_session


async def set_tenure(client, token, agent_id, is_rookie):
    return await client.post("/api/team/set-tenure", headers=auth(token),
                             json={"agent_id": agent_id, "is_rookie": is_rookie})


async def tenure_of(db, agent_id):
    return (await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})).get("is_rookie")


async def test_sa_sets_a_downline_agents_tenure_and_it_is_audited(client, seeded_db):
    token = await make_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    assert await tenure_of(seeded_db, "AG_1") is None
    r = await set_tenure(client, token, "AG_1", True)
    assert r.status_code == 200, r.text
    assert await tenure_of(seeded_db, "AG_1") is True
    entry = await seeded_db.audit_log.find_one({"action": "set_tenure"}, {"_id": 0})
    assert entry["agent_id"] == "AG_1" and entry["changed_by_name"] == "sa1"
    assert entry["original_value"] is None and entry["new_value"] is True and entry["via"] == "team"
    # And back to veteran, in the same place.
    assert (await set_tenure(client, token, "AG_1", False)).status_code == 200
    assert await tenure_of(seeded_db, "AG_1") is False


async def test_ga_reaches_two_levels_down_but_not_sideways(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert (await set_tenure(client, token, "AG_1", False)).status_code == 200
    assert (await set_tenure(client, token, "AG_2", False)).status_code == 403
    assert await tenure_of(seeded_db, "AG_2") is None


async def test_an_agent_cannot_set_tenure_nor_their_own(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_tenure(client, token, "AG_2", True)).status_code == 403
    assert (await set_tenure(client, token, "AG_1", True)).status_code == 403


async def test_a_leader_does_not_set_their_own_tenure(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert (await set_tenure(client, token, "GA_1", False)).status_code == 400


async def test_rga_admin_grant_and_finance_admin_are_agency_wide(client, seeded_db):
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await set_tenure(client, rga, "AG_2", True)).status_code == 200
    afnan = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await seeded_db.users.update_one({"email": "ag1@test.dev"}, {"$set": {"is_admin": True}})
    assert (await set_tenure(client, afnan, "AG_2", False)).status_code == 200
    assert await tenure_of(seeded_db, "AG_2") is False
    fa = await make_session(seeded_db, role="finance_admin", agent_id=None, email="fa@test.dev")
    assert (await set_tenure(client, fa, "AG_2", True)).status_code == 200


async def test_archived_and_unknown_targets_are_404(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    assert (await set_tenure(client, token, "NOBODY", True)).status_code == 404
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    assert (await set_tenure(client, token, "AG_1", True)).status_code == 404


async def test_the_team_tab_row_reflects_the_change(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await set_tenure(client, token, "AG_1", True)
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(token))).json()["team"]}
    assert rows["AG_1"]["is_rookie"] is True and rows["AG_1"]["leaderboard_group"] == "rookie"
