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


# ---------------- Scope ----------------
# Owner, 2026-09-22: the dashboard is universal. Every agent, leader and office
# sees the same agency-wide wall, whatever the More-tab view switch says (that
# switch narrows the Team tab only).

async def test_wall_is_agency_wide_for_a_ga(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"is_rookie": False}})
    await entry(seeded_db, day=day, agent_id="AG_2", gross_alp=9999)  # another GA's downline, other office

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert "AG_2" in [v["agent_id"] for v in body["vets"]]
    assert body["scope"] == "agency"


async def test_level_1_sees_the_whole_agency_not_just_themselves(client, seeded_db):
    """Regression: scoping the wall by visible_agent_ids (built for personal
    Nightly Numbers privacy) once reduced an Agent's candidate pool to just
    their own agent_id — a "team of one." An Agent sees the same agency-wide
    leaderboard everyone else does."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    day = server.current_sales_day_str()
    # AG_3: same office (MCM) as AG_1, but not AG_1's upline or downline.
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "AG_3", "name": "Agent Three", "office": "MCM",
         "role": "level_1", "upline_id": "GA_1", "is_rookie": False})
    await entry(seeded_db, day=day, agent_id="AG_3", gross_alp=7500)

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert "AG_3" in [v["agent_id"] for v in body["vets"]]


async def test_level_1_sees_the_other_offices_too(client, seeded_db):
    """The wall no longer stops at the viewer's office: an MCM Agent sees an
    AMP producer on the same board."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"is_rookie": False}})
    await entry(seeded_db, day=day, agent_id="AG_2", gross_alp=9999)  # office AMP, not AG_1's MCM

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert "AG_2" in [v["agent_id"] for v in body["vets"]]
    # And the office roll-up is the whole agency for an Agent as well.
    offices = (await client.get("/api/dashboard/offices", headers=auth(token))).json()
    names = {o["office"] for o in offices["offices"]}
    assert {"MCM", "AMP"} <= names


# ---------------- Top 3 Veterans exclusion ----------------
# Owner, 2026-09-23: a record flag, exclude_from_platinum_vets, keeps a veteran
# out of the Top 3 Veterans slots only. The next veteran moves up; nothing else
# about the person changes.

async def _five_vets(db, day):
    for i in range(5):
        aid = f"VET_{i}"
        await db.agent_profiles.insert_one(
            {"agent_id": aid, "name": f"Vet {i}", "office": "MCM",
             "role": "level_1", "upline_id": "GA_1", "is_rookie": False})
        await entry(db, day=day, agent_id=aid, gross_alp=100 * (i + 1))


async def test_excluded_vet_is_skipped_and_the_next_moves_up(client, seeded_db):
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    await _five_vets(seeded_db, day)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "VET_4"}, {"$set": {"exclude_from_platinum_vets": True}})

    vets = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()["vets"]
    assert [v["agent_id"] for v in vets] == ["VET_3", "VET_2", "VET_1"]


async def test_exclusion_flag_false_changes_nothing(client, seeded_db):
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    await _five_vets(seeded_db, day)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "VET_4"}, {"$set": {"exclude_from_platinum_vets": False}})

    vets = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()["vets"]
    assert [v["agent_id"] for v in vets] == ["VET_4", "VET_3", "VET_2"]


async def test_archived_person_never_lands_in_tenure_not_set(client, seeded_db):
    """TENURE NOT SET is a prompt to go set it, and nobody sets tenure on a
    removed person (owner, 2026-09-24). Their production still counts for the
    window, but they never appear in that panel."""
    token = await rga(seeded_db)
    day = server.current_sales_day_str()
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$unset": {"is_rookie": ""}, "$set": {"archived": True}})
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$unset": {"is_rookie": ""}})
    await entry(seeded_db, day=day, agent_id="AG_1", gross_alp=9000)
    await entry(seeded_db, day=day, agent_id="AG_2", gross_alp=100)

    body = (await client.get("/api/dashboard/platinum-wall", headers=auth(token))).json()
    assert [u["agent_id"] for u in body["unranked"]] == ["AG_2"]
    assert body["unranked"][0]["archived"] is False
