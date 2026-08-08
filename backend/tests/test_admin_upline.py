"""Orphan reporting and upline repair.

visible_agent_ids() walks DOWN agent_profiles.upline_id, so an agent with a null
or dangling upline is unreachable by every team rollup, and one broken link
severs that agent's whole subtree. Every WAR-import-created agent starts this
way. Before these endpoints there was no way to see or fix that without direct
database access.
"""
import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db):
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


# ---------------- gating ----------------

async def test_orphans_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/admin/orphans", headers=auth(token))).status_code == 403


async def test_set_upline_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "AG_1", "upline_agent_id": "GA_1"})
    assert r.status_code == 403


# ---------------- orphan listing ----------------

async def test_seeded_hierarchy_has_no_orphans(client, seeded_db):
    token = await admin_token(seeded_db)
    assert (await client.get("/api/admin/orphans", headers=auth(token))).json()["orphans"] == []


async def test_null_upline_is_reported(client, seeded_db):
    token = await admin_token(seeded_db)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$set": {"upline_id": None, "created_by_import": True}})
    orphans = (await client.get("/api/admin/orphans", headers=auth(token))).json()["orphans"]
    row = next(o for o in orphans if o["agent_id"] == "AG_1")
    assert row["reason"] == "no_upline"
    assert row["created_by_import"] is True


async def test_dangling_upline_is_reported(client, seeded_db):
    token = await admin_token(seeded_db)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$set": {"upline_id": "GONE_999"}})
    orphans = (await client.get("/api/admin/orphans", headers=auth(token))).json()["orphans"]
    assert next(o for o in orphans if o["agent_id"] == "AG_1")["reason"] == "dangling_upline"


async def test_root_rga_is_not_an_orphan(client, seeded_db):
    """A level_4 legitimately has no upline — flagging it would be noise."""
    token = await admin_token(seeded_db)
    await seeded_db.agent_profiles.update_one({"agent_id": "RGA_1"}, {"$set": {"upline_id": None}})
    orphans = (await client.get("/api/admin/orphans", headers=auth(token))).json()["orphans"]
    assert all(o["agent_id"] != "RGA_1" for o in orphans)


# ---------------- repair ----------------

async def test_set_upline_makes_an_orphan_visible_again(client, seeded_db):
    """The whole point: an orphan is invisible to its upline's rollup until the
    link is repaired."""
    token = await admin_token(seeded_db)
    ga = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"upline_id": None}})

    before = {t["agent_id"] for t in (await client.get("/api/team", headers=auth(ga))).json()["team"]}
    assert "AG_1" not in before

    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "AG_1", "upline_agent_id": "GA_1"})
    assert r.status_code == 200

    after = {t["agent_id"] for t in (await client.get("/api/team", headers=auth(ga))).json()["team"]}
    assert "AG_1" in after


async def test_set_upline_rejects_a_cycle(client, seeded_db):
    """GA_1 -> SA_1 -> AG_1 already exists; pointing GA_1 at AG_1 would loop and
    make downline_agent_ids unable to reach either branch from above."""
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "GA_1", "upline_agent_id": "AG_1"})
    assert r.status_code == 400
    assert "loop" in r.json()["detail"].lower()


async def test_set_upline_rejects_self(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "AG_1", "upline_agent_id": "AG_1"})
    assert r.status_code == 400


async def test_set_upline_rejects_unknown_agents(client, seeded_db):
    token = await admin_token(seeded_db)
    assert (await client.post("/api/admin/set-upline", headers=auth(token),
                              json={"agent_id": "NOPE", "upline_agent_id": "GA_1"})).status_code == 404
    assert (await client.post("/api/admin/set-upline", headers=auth(token),
                              json={"agent_id": "AG_1", "upline_agent_id": "NOPE"})).status_code == 404


async def test_detaching_is_only_allowed_for_an_rga(client, seeded_db):
    """Clearing a non-RGA's upline recreates the exact invisibility this
    endpoint exists to fix."""
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "AG_1", "upline_agent_id": None})
    assert r.status_code == 400

    ok = await client.post("/api/admin/set-upline", headers=auth(token),
                           json={"agent_id": "RGA_1", "upline_agent_id": None})
    assert ok.status_code == 200
    assert ok.json()["upline_id"] is None
