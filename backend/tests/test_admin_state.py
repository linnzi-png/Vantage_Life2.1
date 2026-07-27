"""admin/set-state: resident-state field for the WAR-sheet-parity backup export."""
import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def test_set_state_unknown_agent_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-state", headers=auth(token),
                          json={"agent_id": "NOPE", "state": "MI"})
    assert r.status_code == 404


async def test_set_state_requires_two_letter_code(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-state", headers=auth(token),
                          json={"agent_id": "AG_1", "state": "Michigan"})
    assert r.status_code == 400


async def test_set_state_records_and_audits(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-state", headers=auth(token),
                          json={"agent_id": "AG_1", "state": "mi"})
    assert r.status_code == 200
    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert profile["state"] == "MI"  # normalized upper
    entry = await seeded_db.audit_log.find_one({"action": "set_state"})
    assert entry is not None
    assert entry["new_value"] == "MI"


async def test_add_person_accepts_state(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json={
        "name": "New Guy", "email": "newstate@test.dev", "role": "level_1",
        "is_rookie": True, "upline_agent_id": "GA_1", "state": "oh",
    })
    assert r.status_code == 200
    profile = await seeded_db.agent_profiles.find_one({"email": "newstate@test.dev"})
    assert profile["state"] == "OH"
