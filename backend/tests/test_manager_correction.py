"""Manager correction endpoint: opened from RGA-only to MGA+RGA, scoped to
the acting user's own downline (mirrors can_enter_for used by /api/pulse)."""
import server
from conftest import auth, make_session


ERASE = {"agent_id": "AG_1", "sales_day": "2026-07-20", "new_alp": 5000.0, "reason": "Corrected duplicate entry"}


async def test_ga_still_rejected_from_correction(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/manager/erase", json=ERASE, headers=auth(token))
    assert r.status_code == 403


async def test_mga_can_correct_own_downline(client, seeded_db):
    # MGA_1 -> GA_1 -> SA_1 -> AG_1
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/manager/erase", json=ERASE, headers=auth(token))
    assert r.status_code == 200, r.text


async def test_mga_cannot_correct_outside_downline(client, seeded_db):
    # A second MGA with no relation to AG_1's branch.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "MGA_2", "name": "Mga Two", "email": "mga2@test.dev",
        "role": "level_3", "upline_id": "RGA_1", "office": "MCM",
    })
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_2", email="mga2@test.dev")
    r = await client.post("/api/manager/erase", json=ERASE, headers=auth(token))
    assert r.status_code == 403


async def test_rga_can_correct_anyone(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/manager/erase", json=ERASE, headers=auth(token))
    assert r.status_code == 200, r.text
