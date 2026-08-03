"""Team Production scoreboard period windows: daily / weekly / monthly.

Weekly & monthly are anchored to the Wednesday 2:00 PM America/Detroit cutoff
and filter on submitted_at; daily keeps the 6 AM sales-day boundary.
"""
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
    """A Detroit wall-clock moment expressed as an aware UTC datetime."""
    return server.DETROIT_TZ.localize(datetime(y, m, d, hh, mm)).astimezone(timezone.utc)


async def rga_token(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def add_entry(db, *, sales_day, submitted_at, gross_alp, agent_id="AG_1", office="MCM"):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{sales_day}_{int(gross_alp)}",
        "agent_id": agent_id, "office": office, "sales_day": sales_day,
        "sets": 0, "sits": 1, "sales": 1, "n1": 0, "refs_obtained": 0,
        "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0,
        "gross_alp": gross_alp, "net_alp": gross_alp,
        "submitted_at": submitted_at, "submitted_on_time": True,
    })


def row_for(payload, agent_id="AG_1"):
    return next(r for r in payload["team"] if r["agent_id"] == agent_id)


async def test_default_period_is_weekly(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 2, 10, 0)  # Thursday
    token = await rga_token(seeded_db)
    r = await client.get("/api/team", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["period"] == "weekly"


async def test_invalid_period_rejected(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 2, 10, 0)
    token = await rga_token(seeded_db)
    r = await client.get("/api/team?period=yearly", headers=auth(token))
    assert r.status_code == 400


async def test_weekly_uses_wednesday_2pm_cutoff(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 2, 10, 0)  # Thursday — active week began Wed 7/1 2 PM
    token = await rga_token(seeded_db)
    # Before the cutoff (Wed 10 AM) — excluded from the weekly window.
    await add_entry(seeded_db, sales_day="2026-07-01",
                    submitted_at=det_utc(2026, 7, 1, 10, 0), gross_alp=999)
    # After the cutoff (Wed 8 PM) — included.
    await add_entry(seeded_db, sales_day="2026-07-01",
                    submitted_at=det_utc(2026, 7, 1, 20, 0), gross_alp=500)
    r = await client.get("/api/team?period=weekly", headers=auth(token))
    assert row_for(r.json())["gross_alp"] == 500


async def test_weekly_resets_to_zero_at_cutoff(client, seeded_db, detroit_now):
    token = await rga_token(seeded_db)
    # An entry from last week (submitted Tue before this Wednesday's cutoff).
    await add_entry(seeded_db, sales_day="2026-06-30",
                    submitted_at=det_utc(2026, 6, 30, 20, 0), gross_alp=750)
    # The instant the clock passes Wed 7/1 2:00 PM, the weekly window starts
    # there, so last week's entry falls out and the board reads $0.
    detroit_now(2026, 7, 1, 14, 1)
    r = await client.get("/api/team?period=weekly", headers=auth(token))
    assert row_for(r.json())["gross_alp"] == 0
    assert "no_pulse" in row_for(r.json())["alerts"]


async def test_monthly_spans_from_first_of_month(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 15, 12, 0)
    token = await rga_token(seeded_db)
    # Prior month — excluded.
    await add_entry(seeded_db, sales_day="2026-06-20",
                    submitted_at=det_utc(2026, 6, 20, 20, 0), gross_alp=1000)
    # Two July entries across different weeks — both included and summed,
    # proving monthly reaches back past the weekly cutoff into retained data.
    await add_entry(seeded_db, sales_day="2026-07-02",
                    submitted_at=det_utc(2026, 7, 2, 20, 0), gross_alp=300)
    await add_entry(seeded_db, sales_day="2026-07-10",
                    submitted_at=det_utc(2026, 7, 10, 20, 0), gross_alp=200)
    r = await client.get("/api/team?period=monthly", headers=auth(token))
    assert row_for(r.json())["gross_alp"] == 500


async def test_daily_uses_sales_day_boundary(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 15, 12, 0)  # current sales_day == 2026-07-15
    token = await rga_token(seeded_db)
    # Today's sales_day, regardless of submission time — counted.
    await add_entry(seeded_db, sales_day="2026-07-15",
                    submitted_at=det_utc(2026, 7, 15, 8, 0), gross_alp=400)
    # Yesterday's sales_day — excluded from daily.
    await add_entry(seeded_db, sales_day="2026-07-14",
                    submitted_at=det_utc(2026, 7, 14, 20, 0), gross_alp=900)
    r = await client.get("/api/team?period=daily", headers=auth(token))
    assert row_for(r.json())["gross_alp"] == 400
