"""Platinum Wall: window selection and tenure bucketing.

The wall used to be pinned to the current sales day with no parameters, so every
historical day and every rolling window came back empty — it was the one section
the period selector could not reach. It also dropped any agent without an
explicit is_rookie, which is most of the roster.
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


async def rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def entry(db, *, day, agent_id, gross_alp, sales=1):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{day}_{agent_id}", "agent_id": agent_id, "office": "MCM",
        "sales_day": day, "sits": 2, "sales": sales, "n1": 0,
        "gross_alp": gross_alp, "net_alp": gross_alp,
        "submitted_at": server.DETROIT_TZ.localize(
            datetime(*[int(x) for x in day.split("-")], 20, 30)).astimezone(timezone.utc),
    })


# ---------------- window ----------------

async def test_historical_sales_day_populates_the_wall(client, seeded_db):
    """Regression: the wall was hardcoded to today, so imported history — which
    carries its own historical sales_day — could never appear."""
    token = await rga(seeded_db)
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"is_rookie": False}})
    await entry(seeded_db, day="2026-06-10", agent_id="AG_1", gross_alp=800)

    empty = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert empty["vets"] == []   # nothing today

    r = await client.get("/api/dashboard/platinum-wall?sales_day=2026-06-10", headers=auth(token))
    assert [v["agent_id"] for v in r.json()["vets"]] == ["AG_1"]


async def test_weekly_period_spans_the_reporting_week(client, seeded_db, detroit_now):
    detroit_now(2026, 7, 2, 10, 0)  # Thursday — week began Wed 7/1
    token = await rga(seeded_db)
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"is_rookie": False}})
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=300)
    await entry(seeded_db, day="2026-06-30", agent_id="AG_1", gross_alp=999)  # last week

    r = await client.get("/api/dashboard/platinum-wall?period=weekly", headers=auth(token))
    body = r.json()
    assert body["period"] == "weekly"
    assert body["vets"][0]["gross_alp"] == 300   # 6/30 is a different week


async def test_invalid_period_rejected(client, seeded_db):
    token = await rga(seeded_db)
    r = await client.get("/api/dashboard/platinum-wall?period=yearly", headers=auth(token))
    assert r.status_code == 400


# ---------------- tenure bucketing ----------------

async def test_unknown_tenure_lands_in_unranked_not_dropped(client, seeded_db):
    """Most of the roster has no tenure recorded — every import-created agent
    included. Dropping them hid top producers and made the wall look broken."""
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$unset": {"is_rookie": ""}})
    await entry(seeded_db, day=day, agent_id="AG_1", gross_alp=9000)

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert [u["agent_id"] for u in body["unranked"]] == ["AG_1"]
    assert body["vets"] == [] and body["rookies"] == []
    assert body["unranked"][0]["is_rookie"] is None


async def test_recorded_tenure_still_separates_vets_and_rookies(client, seeded_db):
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"is_rookie": False}})
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"is_rookie": True}})
    await entry(seeded_db, day=day, agent_id="AG_1", gross_alp=500)
    await entry(seeded_db, day=day, agent_id="AG_2", gross_alp=400)

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert [v["agent_id"] for v in body["vets"]] == ["AG_1"]
    assert [r["agent_id"] for r in body["rookies"]] == ["AG_2"]
    assert body["unranked"] == []


async def test_each_bucket_caps_at_three_by_alp(client, seeded_db):
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    for i in range(5):
        aid = f"VET_{i}"
        await seeded_db.agent_profiles.insert_one(
            {"agent_id": aid, "name": f"Vet {i}", "office": "MCM",
             "role": "level_1", "upline_id": "GA_1", "is_rookie": False})
        await entry(seeded_db, day=day, agent_id=aid, gross_alp=100 * (i + 1))

    vets = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()["vets"]
    assert [v["agent_id"] for v in vets] == ["VET_4", "VET_3", "VET_2"]  # top 3, descending


# ---------------- RBAC ----------------

async def test_wall_is_scoped_to_the_viewers_team(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"is_rookie": False}})
    await entry(seeded_db, day=day, agent_id="AG_2", gross_alp=9999)  # another GA's downline

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert all(v["agent_id"] != "AG_2" for v in body["vets"] + body["unranked"])
