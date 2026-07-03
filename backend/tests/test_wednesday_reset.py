"""Wednesday-reset time gate: RGA-only, and only Wednesday >= 2 PM America/Detroit."""
from datetime import datetime

import pytest

import server
from conftest import auth, make_session


@pytest.fixture()
def detroit_clock(monkeypatch):
    """Pin now_detroit() to a chosen local time."""
    def set_time(y, m, d, hh, mm=0):
        fake = server.DETROIT_TZ.localize(datetime(y, m, d, hh, mm))
        monkeypatch.setattr(server, "now_detroit", lambda: fake)
        return fake
    return set_time


async def rga_token(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def test_reset_allowed_wednesday_after_2pm(client, seeded_db, detroit_clock):
    detroit_clock(2026, 7, 1, 14, 0)  # Wednesday 2:00 PM exactly
    token = await rga_token(seeded_db)
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # Archive written, active entries cleared
    assert await seeded_db.historical_vault.count_documents({}) == 1
    assert await seeded_db.production_entries.count_documents({}) == 0


async def test_reset_blocked_wednesday_before_2pm(client, seeded_db, detroit_clock):
    detroit_clock(2026, 7, 1, 13, 59)  # Wednesday 1:59 PM
    token = await rga_token(seeded_db)
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 403
    assert await seeded_db.historical_vault.count_documents({}) == 0


async def test_reset_blocked_on_non_wednesday_even_after_2pm(client, seeded_db, detroit_clock):
    detroit_clock(2026, 7, 2, 15, 0)  # Thursday 3:00 PM
    token = await rga_token(seeded_db)
    # Insert an entry to prove nothing gets deleted on a blocked call
    await seeded_db.production_entries.insert_one({"agent_id": "AG_1", "gross_alp": 100})
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 403
    assert await seeded_db.production_entries.count_documents({}) == 1


async def test_reset_still_requires_level_4(client, seeded_db, detroit_clock):
    detroit_clock(2026, 7, 1, 15, 0)  # valid time, insufficient tier
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 403
