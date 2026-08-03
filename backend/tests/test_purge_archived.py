"""Retention purge: deletes only old, archived, vault-backed entries."""
from datetime import datetime

import pytest

import server
from conftest import auth, make_session


@pytest.fixture()
def clock_2026(monkeypatch):
    fake = server.DETROIT_TZ.localize(datetime(2026, 8, 3, 12, 0))
    monkeypatch.setattr(server, "now_detroit", lambda: fake)
    return fake  # cutoff = 2025-08-03


async def _rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def _entry(db, entry_id, sales_day, *, archived=None, archived_week=None):
    doc = {"entry_id": entry_id, "agent_id": "AG_1", "office": "MCM",
           "sales_day": sales_day, "gross_alp": 100.0, "net_alp": 100.0, "sits": 1, "sales": 1}
    if archived is not None:
        doc["archived"] = archived
    if archived_week is not None:
        doc["archived_week"] = archived_week
    await db.production_entries.insert_one(doc)


async def _vault_week(db, week_start):
    await db.historical_vault.insert_one({"week_id": f"wk_{week_start}", "week_start": week_start, "totals": {}})


async def test_purges_only_old_backed_archived(client, seeded_db, clock_2026):
    await _vault_week(seeded_db, "2024-05-29")
    await _entry(seeded_db, "old_backed", "2024-06-01", archived=True, archived_week="2024-05-29")
    await _entry(seeded_db, "recent_archived", "2026-07-01", archived=True, archived_week="2026-07-01")
    await _entry(seeded_db, "old_active", "2024-06-01")  # never archived
    token = await _rga(seeded_db)

    r = await client.post("/api/admin/purge-archived", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries_purged"] == 1
    ids = {e["entry_id"] async for e in seeded_db.production_entries.find({}, {"entry_id": 1})}
    assert "old_backed" not in ids            # purged
    assert "recent_archived" in ids           # too recent
    assert "old_active" in ids                # active entries never touched


async def test_skips_week_missing_from_vault(client, seeded_db, clock_2026):
    # Old + archived, but no vault snapshot for its week → must NOT be purged.
    await _entry(seeded_db, "old_unbacked", "2024-06-01", archived=True, archived_week="2024-07-03")
    token = await _rga(seeded_db)

    r = await client.post("/api/admin/purge-archived", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entries_purged"] == 0
    assert body["entries_skipped_unbacked"] == 1
    assert "2024-07-03" in body["weeks_skipped_unbacked"]
    assert await seeded_db.production_entries.count_documents({"entry_id": "old_unbacked"}) == 1


async def test_dry_run_deletes_nothing(client, seeded_db, clock_2026):
    await _vault_week(seeded_db, "2024-05-29")
    await _entry(seeded_db, "old_backed", "2024-06-01", archived=True, archived_week="2024-05-29")
    token = await _rga(seeded_db)

    r = await client.post("/api/admin/purge-archived?dry_run=true", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["entries_purged"] == 1  # would purge…
    assert await seeded_db.production_entries.count_documents({"entry_id": "old_backed"}) == 1  # …but didn't


async def test_idempotent(client, seeded_db, clock_2026):
    await _vault_week(seeded_db, "2024-05-29")
    await _entry(seeded_db, "old_backed", "2024-06-01", archived=True, archived_week="2024-05-29")
    token = await _rga(seeded_db)
    first = await client.post("/api/admin/purge-archived", headers=auth(token))
    second = await client.post("/api/admin/purge-archived", headers=auth(token))
    assert first.json()["entries_purged"] == 1
    assert second.json()["entries_purged"] == 0


async def test_requires_level_4(client, seeded_db, clock_2026):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/admin/purge-archived", headers=auth(token))
    assert r.status_code == 403
