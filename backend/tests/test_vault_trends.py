"""Health-dashboard trend series: week bucketing, office filtering, and the
N1-excluded Close Rate.

These read production_entries rather than historical_vault, which is what lets
Close Rate honour the N1 rule — vault snapshots only store ALP/sits/sales.
"""
import pytest

import server
from conftest import auth, make_session


async def rga_token(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def entry(db, *, day, office="MJ RGA", agent_id="AG_1", **metrics):
    doc = {
        "entry_id": f"pe_{day}_{agent_id}_{office}",
        "agent_id": agent_id, "office": office, "sales_day": day,
        "sets": 0, "sits": 0, "sales": 0, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 0.0, "net_alp": 0.0,
    }
    doc.update(metrics)
    await db.production_entries.insert_one(doc)


# ---------------- gating ----------------

async def test_trends_requires_level_4(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/vault/trends", headers=auth(token))
    assert r.status_code == 403


async def test_trends_rejects_unauthenticated(client, seeded_db):
    assert (await client.get("/api/vault/trends")).status_code == 401


# ---------------- week bucketing ----------------

def test_week_start_for_day_snaps_to_the_wednesday_on_or_before():
    # 2026-02-18 is a Wednesday; the reporting week runs Wed→Tue.
    assert server.week_start_for_day("2026-02-18") == "2026-02-18"
    assert server.week_start_for_day("2026-02-19") == "2026-02-18"  # Thu
    assert server.week_start_for_day("2026-02-24") == "2026-02-18"  # Tue
    assert server.week_start_for_day("2026-02-25") == "2026-02-25"  # next Wed


async def test_days_roll_up_into_their_reporting_week(client, seeded_db):
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", sales=1, gross_alp=100.0)
    await entry(seeded_db, day="2026-02-24", agent_id="AG_2", sales=2, gross_alp=200.0)
    await entry(seeded_db, day="2026-02-25", agent_id="AG_3", sales=4, gross_alp=400.0)

    r = await client.get("/api/vault/trends", headers=auth(token))
    series = {w["week_start"]: w for w in r.json()["series"]}
    assert series["2026-02-18"]["sales"] == 3        # Wed + Tue same week
    assert series["2026-02-18"]["gross_alp"] == 300.0
    assert series["2026-02-25"]["sales"] == 4        # next Wed starts a new week
    assert series["2026-02-18"]["agent_count"] == 2


async def test_series_is_ordered_oldest_first(client, seeded_db):
    token = await rga_token(seeded_db)
    for d in ("2026-03-04", "2026-02-18", "2026-02-25"):
        await entry(seeded_db, day=d, sales=1)
    weeks = [w["week_start"] for w in (await client.get("/api/vault/trends", headers=auth(token))).json()["series"]]
    assert weeks == sorted(weeks)


# ---------------- close rate ----------------

async def test_close_rate_does_not_subtract_n1(client, seeded_db):
    """Sales 3, Sits 10, N1 2 → 3/10 = 30%. N1 is already out of Sits, so the
    old 3/(10-2) = 37.5% double-excluded and inflated the score."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", sales=3, sits=10, n1=2)
    week = (await client.get("/api/vault/trends", headers=auth(token))).json()["series"][0]
    assert week["close_rate"] == 30.0
    assert week["n1"] == 2   # still reported, just not in the denominator


async def test_close_rate_is_zero_with_no_sits(client, seeded_db):
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", sales=0, sits=0, n1=4)
    assert (await client.get("/api/vault/trends", headers=auth(token))).json()["series"][0]["close_rate"] == 0


async def test_show_rate_and_alp_per_sale(client, seeded_db):
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", sets=10, sits=4, sales=2, gross_alp=1000.0)
    w = (await client.get("/api/vault/trends", headers=auth(token))).json()["series"][0]
    assert w["show_rate"] == 40.0
    assert w["alp_per_sale"] == 500.0


# ---------------- office filtering ----------------

async def test_office_filter_narrows_the_series(client, seeded_db):
    """Offices resolve through agent_profiles: AG_1 is in MCM, AG_2 in AMP."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", gross_alp=100.0, sales=1)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", gross_alp=900.0, sales=9)

    everyone = (await client.get("/api/vault/trends", headers=auth(token))).json()["series"][0]
    assert everyone["gross_alp"] == 1000.0
    assert everyone["office_count"] == 2

    mcm = (await client.get("/api/vault/trends?office=MCM", headers=auth(token))).json()["series"][0]
    assert mcm["gross_alp"] == 100.0
    assert mcm["office_count"] == 1


async def test_one_office_under_two_entry_names_stays_one_office(client, seeded_db):
    """Regression: a WAR sheet header ("Mohamed Aljahmi RGA") differs from the
    roster name ("MCM"), so grouping by the entry's stored office showed a
    single office as two tabs and split its totals across them."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1",
                office="MCM", gross_alp=100.0, sales=1)
    await entry(seeded_db, day="2026-02-19", agent_id="AG_1",
                office="Mohamed Aljahmi RGA", gross_alp=250.0, sales=2)

    body = (await client.get("/api/vault/trends", headers=auth(token))).json()
    assert "Mohamed Aljahmi RGA" not in body["offices"]

    week = body["series"][0]
    assert week["office_count"] == 1
    # Both days belong to the same agent, so both roll into that agent's office.
    assert week["gross_alp"] == 350.0

    mcm = (await client.get("/api/vault/trends?office=MCM", headers=auth(token))).json()
    assert mcm["series"][0]["gross_alp"] == 350.0


async def test_filtering_an_office_with_no_members_returns_nothing(client, seeded_db):
    """An empty member list must match no entries — not fall through to the
    whole agency, which an absent filter would do."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", gross_alp=500.0)
    r = await client.get("/api/vault/trends?office=Nowhere", headers=auth(token))
    assert r.json()["series"] == []


async def test_offices_come_from_the_roster_not_the_entries(client, seeded_db):
    """Tabs are built from agent_profiles — the source of truth — matching
    /dashboard/offices and the Wednesday reset."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", office="Some Sheet Name")

    for path in ("/api/vault/offices", "/api/vault/trends"):
        offices = (await client.get(path, headers=auth(token))).json()["offices"]
        assert offices == ["AMP", "MCM"], f"{path} returned {offices}"


async def test_weeks_limit_keeps_the_most_recent(client, seeded_db):
    token = await rga_token(seeded_db)
    for d in ("2026-02-18", "2026-02-25", "2026-03-04"):
        await entry(seeded_db, day=d, sales=1)
    r = await client.get("/api/vault/trends?weeks=2", headers=auth(token))
    assert [w["week_start"] for w in r.json()["series"]] == ["2026-02-25", "2026-03-04"]


async def test_archived_entries_are_still_included(client, seeded_db):
    """The Wednesday reset flags entries archived but retains them; history must
    not vanish from the dashboard when a week is closed out."""
    token = await rga_token(seeded_db)
    await entry(seeded_db, day="2026-02-18", sales=5, gross_alp=500.0)
    await seeded_db.production_entries.update_many({}, {"$set": {"archived": True}})
    series = (await client.get("/api/vault/trends", headers=auth(token))).json()["series"]
    assert len(series) == 1 and series[0]["sales"] == 5


async def test_empty_dataset_returns_an_empty_series(client, seeded_db):
    """No production yet: no weeks, but the roster's offices still list so the
    tabs render instead of the screen looking broken."""
    token = await rga_token(seeded_db)
    body = (await client.get("/api/vault/trends", headers=auth(token))).json()
    assert body["series"] == []
    assert body["offices"] == ["AMP", "MCM"]
