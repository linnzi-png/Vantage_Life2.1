"""Read-only dashboard history: sales_day param validation, gate suppression."""
from datetime import date, timedelta

from conftest import auth, make_session


async def rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def test_summary_accepts_past_day(client, seeded_db):
    tok = await rga(seeded_db)
    past = (date.today() - timedelta(days=7)).isoformat()
    r = await client.get(f"/api/dashboard/summary?sales_day={past}", headers=auth(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sales_day"] == past
    assert body["is_history"] is True
    assert body["gate"] is None  # entry-window gate is meaningless for history


async def test_summary_rejects_future_and_garbage(client, seeded_db):
    tok = await rga(seeded_db)
    future = (date.today() + timedelta(days=2)).isoformat()
    assert (await client.get(f"/api/dashboard/summary?sales_day={future}", headers=auth(tok))).status_code == 400
    assert (await client.get("/api/dashboard/summary?sales_day=07/01/2026", headers=auth(tok))).status_code == 400


async def test_summary_today_keeps_gate(client, seeded_db):
    tok = await rga(seeded_db)
    r = await client.get("/api/dashboard/summary", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["is_history"] is False
    assert body["gate"] is not None


async def test_offices_accepts_past_day(client, seeded_db):
    tok = await rga(seeded_db)
    past = (date.today() - timedelta(days=7)).isoformat()
    r = await client.get(f"/api/dashboard/offices?sales_day={past}", headers=auth(tok))
    assert r.status_code == 200, r.text
    assert "offices" in r.json()
