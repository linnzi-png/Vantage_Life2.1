"""Push Month goal (owner, 2026-09-19): one company-wide Gross ALP goal from
the 2026-09-18 sales day through 2026-10-30, read by every tier unscoped."""
from datetime import date, timedelta

import pytest

import server
from conftest import make_session, auth


async def entry(db, *, agent_id, sales_day, gross_alp, sales=1):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}_{sales_day}", "agent_id": agent_id,
        "sales_day": sales_day,
        "sets": 1, "sits": 1, "sales": sales, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": float(gross_alp), "net_alp": float(gross_alp),
    })


@pytest.fixture
def campaign(monkeypatch):
    """Pin the campaign around the current sales day so the assertions do not
    depend on when the suite runs."""
    today = date.fromisoformat(server.current_sales_day_str())
    start = today - timedelta(days=2)
    end = today + timedelta(days=10)
    monkeypatch.setattr(server, "PUSH_GOAL_ALP", 10000.0)
    monkeypatch.setattr(server, "PUSH_GOAL_START_DAY", start.isoformat())
    monkeypatch.setattr(server, "PUSH_GOAL_END_DAY", end.isoformat())
    return {"today": today, "start": start, "end": end}


async def test_totals_are_company_wide_and_windowed(client, seeded_db, campaign):
    start, today = campaign["start"], campaign["today"]
    # Both offices count; the night before the start does not.
    await entry(seeded_db, agent_id="AG_1", sales_day=start.isoformat(), gross_alp=1500)
    await entry(seeded_db, agent_id="AG_2", sales_day=today.isoformat(), gross_alp=2500, sales=2)
    await entry(seeded_db, agent_id="AG_1", sales_day=(start - timedelta(days=1)).isoformat(), gross_alp=9999)

    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/dashboard/push-goal", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["goal_alp"] == 10000.0
    assert body["total_alp"] == 4000.0
    assert body["total_sales"] == 3
    assert body["pct"] == 40.0
    assert body["remaining_alp"] == 6000.0
    assert body["show_countdown"] is False
    assert body["days_remaining"] == 10
    assert body["started"] is True and body["ended"] is False


async def test_by_day_lists_every_day_including_quiet_ones(client, seeded_db, campaign):
    start, today = campaign["start"], campaign["today"]
    await entry(seeded_db, agent_id="AG_1", sales_day=start.isoformat(), gross_alp=100)
    await entry(seeded_db, agent_id="AG_2", sales_day=today.isoformat(), gross_alp=300)
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    body = (await client.get("/api/dashboard/push-goal", headers=auth(token))).json()
    days = [d["sales_day"] for d in body["by_day"]]
    assert days == [(start + timedelta(days=i)).isoformat() for i in range(3)]
    alps = [d["alp"] for d in body["by_day"]]
    assert alps == [100.0, 0.0, 300.0]


async def test_by_office_resolves_through_roster_and_lists_zero_offices(client, seeded_db, campaign):
    today = campaign["today"]
    # AG_2 sits in AMP on the roster; the entry's own office label is stale.
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_stale", "agent_id": "AG_2", "office": "Old Name",
        "sales_day": today.isoformat(), "sets": 1, "sits": 1, "sales": 1,
        "ots_sits": 0, "ots_sales": 0, "n1": 0, "refs_obtained": 0, "ref_sits": 0,
        "ref_sales": 0, "pos_sits": 0, "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": 700.0, "net_alp": 700.0,
    })
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    body = (await client.get("/api/dashboard/push-goal", headers=auth(token))).json()
    offices = {o["office"]: o for o in body["by_office"]}
    assert offices["AMP"]["alp"] == 700.0
    assert offices["MCM"]["alp"] == 0.0
    assert body["by_office"][0]["office"] == "AMP"  # leader first


async def test_countdown_callout_switches_on_at_threshold(client, seeded_db, campaign):
    today = campaign["today"]
    await entry(seeded_db, agent_id="AG_1", sales_day=today.isoformat(), gross_alp=8000)
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    body = (await client.get("/api/dashboard/push-goal", headers=auth(token))).json()
    assert body["pct"] == 80.0
    assert body["show_countdown"] is True
    assert body["remaining_alp"] == 2000.0


async def test_past_goal_reports_over_100_and_zero_remaining(client, seeded_db, campaign):
    today = campaign["today"]
    await entry(seeded_db, agent_id="AG_1", sales_day=today.isoformat(), gross_alp=12500)
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    body = (await client.get("/api/dashboard/push-goal", headers=auth(token))).json()
    assert body["pct"] == 125.0
    assert body["remaining_alp"] == 0.0


async def test_pending_accounts_are_refused(client, seeded_db, campaign):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="nobody@test.dev")
    r = await client.get("/api/dashboard/push-goal", headers=auth(token))
    assert r.status_code == 403


async def test_goal_progress_metric():
    from metrics import goal_progress
    assert goal_progress(500, 1000) == 50
    assert goal_progress(1500, 1000) == 150
    assert goal_progress(5, 0) == 0
