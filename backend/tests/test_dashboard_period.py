"""Dashboard summary/offices period windows (daily default unchanged)."""
from datetime import datetime, timezone

import pytest

import server
from conftest import auth, make_session


@pytest.fixture()
def detroit_now(monkeypatch):
    def set_time(y, m, d, hh, mm=0):
        fake = server.DETROIT_TZ.localize(datetime(y, m, d, hh, mm))
        monkeypatch.setattr(server, "now_detroit", lambda: fake)
        return fake
    return set_time


def det_utc(y, m, d, hh, mm=0):
    return server.DETROIT_TZ.localize(datetime(y, m, d, hh, mm)).astimezone(timezone.utc)


async def _rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def _entry(db, *, sales_day, submitted_at, gross_alp, agent_id="AG_1", office="MCM"):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{sales_day}_{int(gross_alp)}_{agent_id}", "agent_id": agent_id, "office": office,
        "sales_day": sales_day, "sits": 1, "sales": 1, "n1": 0,
        "gross_alp": gross_alp, "net_alp": gross_alp, "submitted_at": submitted_at,
    })


async def test_summary_daily_default_unchanged(client, seeded_db):
    sd = server.current_sales_day_str()
    await _entry(seeded_db, sales_day=sd, submitted_at=server.now_utc(), gross_alp=700)
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "daily"
    assert body["total_alp"] == 700


async def test_summary_weekly_window_is_by_sales_day(client, seeded_db, detroit_now):
    """The Wednesday 2 PM cutoff still picks WHICH week is current, but the
    window matches sales_day — production belongs to the day it was sold, not
    the moment it was typed in. Both entries below were sold on Wed 7/1, which
    is inside the active week, so submission time is irrelevant to the total."""
    detroit_now(2026, 7, 2, 10, 0)  # Thursday — active week began Wed 7/1
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=500)
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 10, 0), gross_alp=999)
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary?period=weekly", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["total_alp"] == 1499


async def test_summary_weekly_excludes_days_before_the_week_opened(client, seeded_db, detroit_now):
    """A deal sold Tuesday belongs to the previous week even if it was entered
    after this week's Wednesday cutoff — the old submitted_at rule pulled it
    into the wrong week."""
    detroit_now(2026, 7, 2, 10, 0)
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=500)
    await _entry(seeded_db, sales_day="2026-06-30", submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=999)
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary?period=weekly", headers=auth(token))
    assert r.json()["total_alp"] == 500


async def test_summary_weekly_includes_backfilled_history(client, seeded_db, detroit_now):
    """Regression: imported entries carry submitted_at of their historical date,
    so the old rule hid every backfilled day from Weekly and Monthly while Daily
    showed it fine."""
    detroit_now(2026, 7, 2, 10, 0)
    await _entry(seeded_db, sales_day="2026-07-01",
                 submitted_at=det_utc(2026, 7, 1, 20, 30), gross_alp=250)
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary?period=weekly", headers=auth(token))
    assert r.json()["total_alp"] == 250


async def test_summary_weekly_delta_vs_previous_window(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 2, 10, 0)
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=400)  # this week
    await _entry(seeded_db, sales_day="2026-06-25", submitted_at=det_utc(2026, 6, 25, 20, 0), gross_alp=100)  # prev week
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary?period=weekly", headers=auth(token))
    body = r.json()
    assert body["total_alp"] == 400
    assert body["delta_pct_vs_yesterday"] == 300.0  # (400-100)/100


async def test_summary_monthly_window(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 15, 12, 0)
    await _entry(seeded_db, sales_day="2026-07-02", submitted_at=det_utc(2026, 7, 2, 20, 0), gross_alp=300)
    await _entry(seeded_db, sales_day="2026-06-20", submitted_at=det_utc(2026, 6, 20, 20, 0), gross_alp=999)  # prev month
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/summary?period=monthly", headers=auth(token))
    assert r.json()["total_alp"] == 300


async def test_offices_weekly_window(client, seeded_db, detroit_now):
    """Offices use the same sales_day window as the summary above them, so the
    two can never disagree about which days they are counting."""
    detroit_now(2026, 7, 2, 10, 0)
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=300)
    await _entry(seeded_db, sales_day="2026-07-01", submitted_at=det_utc(2026, 7, 1, 10, 0), gross_alp=50)
    await _entry(seeded_db, sales_day="2026-06-30", submitted_at=det_utc(2026, 6, 30, 20, 0), gross_alp=999)
    token = await _rga(seeded_db)
    r = await client.get("/api/dashboard/offices?period=weekly", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["period"] == "weekly"
    mcm = next(o for o in body["offices"] if o["office"] == "MCM")
    assert mcm["alp"] == 350   # both 7/1 days; the 6/30 entry is last week

    summary = (await client.get("/api/dashboard/summary?period=weekly", headers=auth(token))).json()
    assert sum(o["alp"] for o in body["offices"]) == summary["total_alp"]


async def test_invalid_period_rejected(client, seeded_db):
    token = await _rga(seeded_db)
    assert (await client.get("/api/dashboard/summary?period=yearly", headers=auth(token))).status_code == 400
    assert (await client.get("/api/dashboard/offices?period=yearly", headers=auth(token))).status_code == 400
