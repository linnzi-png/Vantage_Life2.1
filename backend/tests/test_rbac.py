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


async def test_team_endpoint_scopes_level_1_to_office(client, seeded_db):
    """Per owner, 2026-09-13: /api/team no longer 403s a level_1 caller — it
    returns their own office's rollup instead of the old blanket refusal."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/team", headers=auth(token))
    assert r.status_code == 200, r.text
    ids = {row["agent_id"] for row in r.json()["team"]}
    assert ids == {"RGA_1", "MGA_1", "GA_1", "SA_1", "AG_1"}


async def test_level_1_cannot_add_or_remove_team_members(client, seeded_db):
    """The read-only Team tab widening must not touch write access — those
    stay behind their own level_2+ checks, unaffected by this change."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token),
                           json={"agent_id": "SA_1"})
    assert r.status_code == 403
