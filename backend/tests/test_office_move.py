"""Moving a person into another office (owner, 2026-09-22).

  - a move under an upline in another office sets the person's office from
    that upline, so the whole hierarchy above them is the new office's
  - only an admin (the owner, MJ) may cross an office boundary; the existing
    within-downline reassign for level_2+ is unchanged
  - move_downline (default on) takes the person's downline along, office and
    all; off leaves the direct reports under the moved person's former upline
  - /admin/set-office corrects one record's office with no hierarchy change

Fixture: RGA_1 → MGA_1 → {GA_1 → SA_1 → AG_1 (MCM), GA_2 → AG_2 (AMP)}.
"""
import pytest

from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def profile(db, agent_id):
    return await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})


@pytest.mark.anyio
async def test_admin_move_across_offices_rehomes_the_person(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "GA_2"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["office"] == "AMP" and body["office_changed"] is True
    p = await profile(seeded_db, "AG_1")
    assert p["upline_id"] == "GA_2" and p["office"] == "AMP"
    log = await seeded_db.audit_log.find_one({"action": "reassign_agent", "agent_id": "AG_1"})
    assert log["old_office"] == "MCM" and log["new_office"] == "AMP"


@pytest.mark.anyio
async def test_downline_moves_with_them_by_default(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "SA_1", "new_upline_agent_id": "GA_2"})
    assert r.status_code == 200, r.text
    assert r.json()["downline_moved"] == ["AG_1"]
    sa = await profile(seeded_db, "SA_1")
    ag = await profile(seeded_db, "AG_1")
    assert sa["upline_id"] == "GA_2" and sa["office"] == "AMP"
    # Still reports to SA_1, now filed in AMP with them.
    assert ag["upline_id"] == "SA_1" and ag["office"] == "AMP"


@pytest.mark.anyio
async def test_downline_stays_under_former_upline_when_toggle_is_off(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "SA_1", "new_upline_agent_id": "GA_2",
                                "move_downline": False})
    assert r.status_code == 200, r.text
    assert r.json()["downline_left"] == ["AG_1"]
    sa = await profile(seeded_db, "SA_1")
    ag = await profile(seeded_db, "AG_1")
    assert sa["upline_id"] == "GA_2" and sa["office"] == "AMP"
    # Parked under SA_1's former upline, office untouched.
    assert ag["upline_id"] == "GA_1" and ag["office"] == "MCM"
    log = await seeded_db.audit_log.find_one({"action": "reassign_agent", "agent_id": "SA_1"})
    assert log["downline_left_under"] == "GA_1" and log["downline_left"] == ["AG_1"]


@pytest.mark.anyio
async def test_toggle_off_needs_a_former_upline_to_park_under(client, seeded_db):
    # RGA_1 is a root: leaving its downline behind has nowhere to put them.
    # Give it somewhere to go first so the only thing being tested is the guard.
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
         "role": "level_4", "upline_id": None, "office": "AMP"})
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "RGA_1", "new_upline_agent_id": "RGA_2",
                                "move_downline": False})
    assert r.status_code == 400
    assert "no upline" in r.json()["detail"]


@pytest.mark.anyio
async def test_a_leader_cannot_cross_an_office_boundary(client, seeded_db):
    # MGA_1 has both GA_1 (MCM) and GA_2 (AMP) in their downline, so the old
    # rule would let them move AG_1 under GA_2. Office crossing is admin-only.
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "GA_2"})
    assert r.status_code == 403
    assert "another office" in r.json()["detail"]
    assert (await profile(seeded_db, "AG_1"))["office"] == "MCM"


@pytest.mark.anyio
async def test_a_leader_still_moves_within_their_own_office(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "GA_1"})
    assert r.status_code == 200, r.text
    assert r.json()["office_changed"] is False
    p = await profile(seeded_db, "AG_1")
    assert p["upline_id"] == "GA_1" and p["office"] == "MCM"


@pytest.mark.anyio
async def test_set_office_corrects_one_record_only(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-office", headers=auth(token),
                          json={"agent_id": "SA_1", "office": "AMP"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True
    sa = await profile(seeded_db, "SA_1")
    ag = await profile(seeded_db, "AG_1")
    assert sa["office"] == "AMP" and sa["upline_id"] == "GA_1"
    assert ag["office"] == "MCM"  # downline deliberately untouched
    log = await seeded_db.audit_log.find_one({"action": "set_office", "agent_id": "SA_1"})
    assert log["old_office"] == "MCM" and log["new_office"] == "AMP"


@pytest.mark.anyio
async def test_set_office_is_admin_only_and_validates(client, seeded_db):
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.post("/api/admin/set-office", headers=auth(rga),
                              json={"agent_id": "SA_1", "office": "AMP"})).status_code == 403
    token = await admin_token(seeded_db)
    assert (await client.post("/api/admin/set-office", headers=auth(token),
                              json={"agent_id": "SA_1", "office": "  "})).status_code == 400
    assert (await client.post("/api/admin/set-office", headers=auth(token),
                              json={"agent_id": "NOPE", "office": "AMP"})).status_code == 404


@pytest.mark.anyio
async def test_orphan_repair_follows_the_same_office_rule(client, seeded_db):
    # /admin/set-upline is the other route that sets an upline; it must not be
    # the back door that leaves someone filed in the wrong office.
    await seeded_db.agent_profiles.update_one({"agent_id": "SA_1"}, {"$set": {"upline_id": None}})
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-upline", headers=auth(token),
                          json={"agent_id": "SA_1", "upline_agent_id": "GA_2"})
    assert r.status_code == 200, r.text
    assert r.json()["office"] == "AMP" and r.json()["office_changed"] is True
    sa = await profile(seeded_db, "SA_1")
    ag = await profile(seeded_db, "AG_1")
    assert sa["upline_id"] == "GA_2" and sa["office"] == "AMP"
    assert ag["upline_id"] == "SA_1" and ag["office"] == "AMP"
    log = await seeded_db.audit_log.find_one({"action": "set_upline", "agent_id": "SA_1"})
    assert log["old_office"] == "MCM" and log["downline_moved"] == ["AG_1"]
