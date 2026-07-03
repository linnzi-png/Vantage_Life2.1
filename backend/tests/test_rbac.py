"""RBAC visibility scoping: visible_agent_ids() BFS over upline_id, per tier."""
import server
from conftest import auth, make_session


async def test_level_1_sees_only_self(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_1", "agent_id": "AG_1"})
    assert ids == ["AG_1"]


async def test_level_2_sees_own_team_not_siblings(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_2", "agent_id": "GA_1"})
    assert set(ids) == {"GA_1", "AG_1"}
    assert "AG_2" not in ids and "GA_2" not in ids


async def test_level_3_sees_all_ga_rollups(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_3", "agent_id": "MGA_1"})
    assert set(ids) == {"MGA_1", "GA_1", "GA_2", "AG_1", "AG_2"}


async def test_level_4_sees_everything(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_4", "agent_id": "RGA_1"})
    assert ids is None  # None = unrestricted


async def test_agentless_user_sees_nothing(seeded_db):
    ids = await server.visible_agent_ids({"role": "level_2", "agent_id": None})
    assert ids == []


async def test_team_endpoint_requires_level_2(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/team", headers=auth(token))
    assert r.status_code == 403
