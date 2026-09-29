"""The guided walkthrough shows once per person, ever (batch 2, PR A): the
record is tour_completed_at on the users doc, stamped by POST /api/me/tour-done."""
import pytest
from conftest import auth, make_session

pytestmark = pytest.mark.asyncio


async def test_new_account_has_no_stamp_and_me_reports_it(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["user"].get("tour_completed_at") is None


async def test_tour_done_stamps_once_and_is_idempotent(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r1 = await client.post("/api/me/tour-done", headers=auth(token))
    assert r1.status_code == 200, r1.text
    first = r1.json()["tour_completed_at"]
    assert first
    r2 = await client.post("/api/me/tour-done", headers=auth(token))
    assert r2.status_code == 200
    assert r2.json()["tour_completed_at"] == first
    me = await client.get("/api/auth/me", headers=auth(token))
    assert me.json()["user"]["tour_completed_at"] == first


async def test_pending_account_can_dismiss_the_tour(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="nobody@test.dev")
    r = await client.post("/api/me/tour-done", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["tour_completed_at"]


async def test_role_change_leaves_the_stamp_alone(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    before = (await client.post("/api/me/tour-done", headers=auth(token))).json()["tour_completed_at"]
    await seeded_db.users.update_one({"email": "ag1@test.dev"}, {"$set": {"role": "level_sa"}})
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"role": "level_sa"}})
    me = await client.get("/api/auth/me", headers=auth(token))
    assert me.json()["user"]["role"] == "level_sa"
    assert me.json()["user"]["tour_completed_at"] == before


async def test_signed_out_caller_is_refused(client, seeded_db):
    r = await client.post("/api/me/tour-done")
    assert r.status_code == 401
