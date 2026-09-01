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


async def test_reset_archives_and_retains_entries(client, seeded_db, detroit_clock):
    detroit_clock(2026, 7, 1, 14, 0)  # Wednesday 2:00 PM exactly
    token = await rga_token(seeded_db)
    await seeded_db.production_entries.insert_one(
        {"entry_id": "pe_1", "agent_id": "AG_1", "office": "MCM", "gross_alp": 500,
         "net_alp": 500, "sits": 2, "sales": 1}
    )
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    # Archive written to the vault…
    assert await seeded_db.historical_vault.count_documents({}) == 1
    # …and the entry is RETAINED as a transactional record, flagged archived —
    # not deleted (permanent per-agent history).
    assert await seeded_db.production_entries.count_documents({}) == 1
    assert await seeded_db.production_entries.count_documents({"archived": True}) == 1
    assert await seeded_db.production_entries.count_documents({"archived": {"$ne": True}}) == 0
    doc = await seeded_db.production_entries.find_one({"entry_id": "pe_1"})
    assert doc["archived_week"] == "2026-07-01"


async def test_reset_snapshot_scopes_to_current_week_only(client, seeded_db, detroit_clock):
    """A second reset must not re-count the prior week's retained entries."""
    detroit_clock(2026, 7, 1, 14, 0)
    token = await rga_token(seeded_db)
    await seeded_db.production_entries.insert_one(
        {"entry_id": "pe_w1", "agent_id": "AG_1", "office": "MCM", "gross_alp": 1000,
         "net_alp": 1000, "sits": 1, "sales": 1}
    )
    await client.post("/api/admin/wednesday-reset", headers=auth(token))

    # New week: one fresh (active) entry.
    detroit_clock(2026, 7, 8, 14, 0)
    await seeded_db.production_entries.insert_one(
        {"entry_id": "pe_w2", "agent_id": "AG_1", "office": "MCM", "gross_alp": 250,
         "net_alp": 250, "sits": 1, "sales": 1}
    )
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 200, r.text
    # Second snapshot reflects only the second week's $250, not $1250.
    latest = await seeded_db.historical_vault.find_one({"week_start": "2026-07-08"})
    assert latest["totals"]["gross_alp"] == 250


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


async def test_reset_allows_is_admin_without_level_4(client, seeded_db, detroit_clock):
    # Per owner (2026-09-01): is_admin holds every capability the highest
    # RBAC tier has, and then some — see has_full_control() in server.py.
    detroit_clock(2026, 7, 1, 14, 0)
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 200, r.text
