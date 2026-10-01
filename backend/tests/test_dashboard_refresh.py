"""Dashboard visual refresh, backend half (additive fields only).

Summary gains by_office, by_day, total_close_ratio and deltas; the Platinum Wall
gains top10_vets / top10_rookies and no longer ranks anyone at $0.
"""
import itertools
from datetime import datetime

import pytest

import server
from conftest import auth, make_session

_seq = itertools.count(1)


@pytest.fixture()
def detroit_now(monkeypatch):
    def set_time(y, m, d, hh, mm=0):
        fake = server.DETROIT_TZ.localize(datetime(y, m, d, hh, mm))
        monkeypatch.setattr(server, "now_detroit", lambda: fake)
        return fake
    return set_time


@pytest.fixture()
def thursday(detroit_now):
    """Thu 2026-07-02 10:00 Detroit: sales day 7/2, week began Wed 7/1."""
    return detroit_now(2026, 7, 2, 10, 0)


async def rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def entry(db, *, day, agent_id, gross_alp, sales=1, sits=2):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{next(_seq)}", "agent_id": agent_id, "office": "MCM",
        "sales_day": day, "sits": sits, "sales": sales, "n1": 0,
        "gross_alp": gross_alp, "net_alp": gross_alp, "submitted_at": server.now_utc(),
    })


async def profile(db, agent_id, *, office="MCM", is_rookie=None, **extra):
    doc = {"agent_id": agent_id, "name": f"Agent {agent_id}", "office": office, **extra}
    if is_rookie is not None:
        doc["is_rookie"] = is_rookie
    await db.agent_profiles.insert_one(doc)


async def summary(client, token, query=""):
    r = await client.get(f"/api/dashboard/summary{query}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


async def seed_mixed_week(db):
    """Production across both seeded offices, a blank-office agent and an
    entry whose agent has no profile at all."""
    await profile(db, "BLANK_1", office="")
    await entry(db, day="2026-07-01", agent_id="AG_1", gross_alp=500, sales=2, sits=4)
    await entry(db, day="2026-07-02", agent_id="AG_2", gross_alp=300, sales=1, sits=3)
    await entry(db, day="2026-07-02", agent_id="BLANK_1", gross_alp=200, sales=1, sits=1)
    await entry(db, day="2026-07-02", agent_id="GHOST_9", gross_alp=100, sales=1, sits=2)


# ---------------- by_office ----------------

@pytest.mark.parametrize("query", ["", "?period=weekly", "?period=monthly"])
async def test_by_office_sums_equal_agency_totals(client, seeded_db, thursday, query):
    await seed_mixed_week(seeded_db)
    body = await summary(client, await rga(seeded_db), query)
    rows = body["by_office"]
    assert sum(r["gross_alp"] for r in rows) == pytest.approx(body["total_alp"])
    assert sum(r["sales"] for r in rows) == body["total_sales"]
    assert sum(r["sits"] for r in rows) == body["total_sits"]


async def test_by_office_files_blank_and_profileless_under_unassigned(client, seeded_db, thursday):
    await seed_mixed_week(seeded_db)
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    unassigned = [r for r in body["by_office"] if r["office"] == server.UNASSIGNED_OFFICE]
    assert len(unassigned) == 1
    assert unassigned[0]["gross_alp"] == 300   # 200 blank-office + 100 no profile
    assert unassigned[0]["sales"] == 2


async def test_by_office_omits_unassigned_when_it_is_zero(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=500)
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    assert server.UNASSIGNED_OFFICE not in [r["office"] for r in body["by_office"]]


async def test_by_office_lists_every_office_including_zero_production(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=500)
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    offices = {r["office"]: r for r in body["by_office"]}
    assert {"MCM", "AMP"} <= set(offices)
    assert any(r["gross_alp"] == 0 and r["close_ratio"] == 0 for r in offices.values())


async def test_by_office_close_ratio_comes_from_metrics(client, seeded_db, thursday):
    await seed_mixed_week(seeded_db)
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    for r in body["by_office"]:
        assert r["close_ratio"] == round(server.metrics.close_rate(r["sales"], r["sits"]), 1)
    assert body["total_close_ratio"] == round(
        server.metrics.close_rate(body["total_sales"], body["total_sits"]), 1)


async def test_by_office_period_switches_the_window(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=100)
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=200)
    await entry(seeded_db, day="2026-06-15", agent_id="AG_1", gross_alp=400)

    async def office_total(query):
        body = await summary(client, await rga(seeded_db), query)
        return sum(r["gross_alp"] for r in body["by_office"])

    assert await office_total("") == 100
    assert await office_total("?period=weekly") == 300
    assert await office_total("?period=monthly") == 300   # 6/15 is last month
    assert await office_total("?sales_day=2026-06-15") == 400


# ---------------- by_day ----------------

async def test_by_day_daily_is_seven_zero_filled_days_ending_on_the_chosen_day(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=100)
    await entry(seeded_db, day="2026-06-29", agent_id="AG_1", gross_alp=250)
    body = await summary(client, await rga(seeded_db))
    days = body["by_day"]
    assert [d["sales_day"] for d in days] == [
        "2026-06-26", "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02"]
    assert {d["sales_day"]: d["gross_alp"] for d in days}["2026-06-29"] == 250
    assert days[-1]["gross_alp"] == 100
    assert days[0]["gross_alp"] == 0


async def test_by_day_follows_a_historical_day(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-06-10", agent_id="AG_1", gross_alp=800)
    body = await summary(client, await rga(seeded_db), "?sales_day=2026-06-10")
    assert body["by_day"][-1] == {"sales_day": "2026-06-10", "gross_alp": 800}
    assert len(body["by_day"]) == 7


async def test_by_day_weekly_covers_the_window_and_matches_the_total(client, seeded_db, thursday):
    await seed_mixed_week(seeded_db)
    await entry(seeded_db, day="2026-06-30", agent_id="AG_1", gross_alp=999)   # last week
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    days = body["by_day"]
    assert days[0]["sales_day"] == "2026-07-01"
    assert sum(d["gross_alp"] for d in days) == pytest.approx(body["total_alp"])


async def test_by_day_monthly_starts_on_the_first(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=120)
    body = await summary(client, await rga(seeded_db), "?period=monthly")
    assert body["by_day"][0] == {"sales_day": "2026-07-01", "gross_alp": 120}
    assert sum(d["gross_alp"] for d in body["by_day"]) == pytest.approx(body["total_alp"])


# ---------------- deltas ----------------

async def test_deltas_daily_versus_yesterday(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=600, sales=3, sits=6)   # 50%
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=400, sales=2, sits=8)   # 25%
    body = await summary(client, await rga(seeded_db))
    d = body["deltas"]
    assert d["alp"] == 50.0
    assert d["sales"] == 50.0
    assert d["sits"] == -25.0
    assert d["close_ratio"] == round(
        server.metrics.close_rate(3, 6) - server.metrics.close_rate(2, 8), 1)   # points, not percent


async def test_deltas_are_none_without_a_previous_window(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=600)
    body = await summary(client, await rga(seeded_db))
    assert body["deltas"] == {"alp": None, "sales": None, "sits": None, "close_ratio": None}


async def test_deltas_weekly_compare_against_the_previous_week(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=300)
    await entry(seeded_db, day="2026-06-26", agent_id="AG_1", gross_alp=200)   # previous week
    body = await summary(client, await rga(seeded_db), "?period=weekly")
    assert body["deltas"]["alp"] == 50.0


async def test_existing_summary_fields_survive(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=600)
    await entry(seeded_db, day="2026-07-01", agent_id="AG_1", gross_alp=300)
    body = await summary(client, await rga(seeded_db))
    assert body["total_alp"] == 600
    assert body["delta_pct_vs_yesterday"] == 100.0


# ---------------- /dashboard/offices reuses the same breakdown ----------------

async def test_offices_route_still_serves_its_old_keys(client, seeded_db, thursday):
    await entry(seeded_db, day="2026-07-02", agent_id="AG_1", gross_alp=600, sales=3)
    token = await rga(seeded_db)
    r = await client.get("/api/dashboard/offices", headers=auth(token))
    assert r.status_code == 200, r.text
    rows = r.json()
    rows = rows if isinstance(rows, list) else rows.get("offices", rows)
    assert rows and {"office", "alp", "sales", "avg_deal"} <= set(rows[0])


# ---------------- Platinum Wall top 10 ----------------

async def wall(client, token, query=""):
    r = await client.get(f"/api/dashboard/platinum-wall{query}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


async def seed_roster(db, n_vets, n_rookies):
    """Distinct, strictly descending Gross ALP so ranks are unambiguous."""
    for i in range(n_vets):
        await profile(db, f"V{i:02d}", is_rookie=False)
        await entry(db, day="2026-07-02", agent_id=f"V{i:02d}", gross_alp=5000 - i * 10)
    for i in range(n_rookies):
        await profile(db, f"R{i:02d}", is_rookie=True)
        await entry(db, day="2026-07-02", agent_id=f"R{i:02d}", gross_alp=4000 - i * 10)


async def test_top10_lists_are_capped_ranked_and_start_with_the_top_three(client, seeded_db, thursday):
    await seed_roster(seeded_db, 14, 12)
    body = await wall(client, await rga(seeded_db))
    assert len(body["top10_vets"]) == 10 and len(body["top10_rookies"]) == 10
    assert [r["rank"] for r in body["top10_vets"]] == list(range(1, 11))
    alps = [r["gross_alp"] for r in body["top10_vets"]]
    assert alps == sorted(alps, reverse=True)
    assert [v["agent_id"] for v in body["vets"]] == [r["agent_id"] for r in body["top10_vets"][:3]]
    assert [v["agent_id"] for v in body["rookies"]] == [r["agent_id"] for r in body["top10_rookies"][:3]]


async def test_top10_rows_carry_only_leaderboard_fields(client, seeded_db, thursday):
    await seed_roster(seeded_db, 2, 1)
    body = await wall(client, await rga(seeded_db))
    for row in body["top10_vets"] + body["top10_rookies"]:
        assert set(row) == {"rank", "agent_id", "name", "office", "gross_alp"}


async def test_top10_splits_by_tenure(client, seeded_db, thursday):
    await seed_roster(seeded_db, 3, 3)
    body = await wall(client, await rga(seeded_db))
    assert {r["agent_id"][0] for r in body["top10_vets"]} == {"V"}
    assert {r["agent_id"][0] for r in body["top10_rookies"]} == {"R"}


async def test_top10_respects_the_vet_exclusion_flag_and_promotes_the_next_vet(client, seeded_db, thursday):
    await seed_roster(seeded_db, 12, 0)
    await seeded_db.agent_profiles.update_one({"agent_id": "V00"}, {"$set": {"exclude_from_platinum_vets": True}})
    body = await wall(client, await rga(seeded_db))
    ids = [r["agent_id"] for r in body["top10_vets"]]
    assert "V00" not in ids
    assert ids[0] == "V01" and len(ids) == 10 and ids[-1] == "V10"
    assert "V00" not in [v["agent_id"] for v in body["vets"]]


async def test_exclusion_flag_does_not_touch_rookies(client, seeded_db, thursday):
    await seed_roster(seeded_db, 0, 2)
    await seeded_db.agent_profiles.update_one({"agent_id": "R00"}, {"$set": {"exclude_from_platinum_vets": True}})
    body = await wall(client, await rga(seeded_db))
    assert body["top10_rookies"][0]["agent_id"] == "R00"


async def test_nobody_at_zero_is_ranked_anywhere_on_the_wall(client, seeded_db, thursday):
    await profile(seeded_db, "VZ", is_rookie=False)
    await profile(seeded_db, "RZ", is_rookie=True)
    await profile(seeded_db, "UZ")
    await profile(seeded_db, "V1", is_rookie=False)
    await entry(seeded_db, day="2026-07-02", agent_id="V1", gross_alp=100)
    for aid in ("VZ", "RZ", "UZ"):
        await entry(seeded_db, day="2026-07-02", agent_id=aid, gross_alp=0)
    body = await wall(client, await rga(seeded_db))
    assert [v["agent_id"] for v in body["vets"]] == ["V1"]
    assert body["rookies"] == [] and body["top10_rookies"] == []
    assert body["unranked"] == []
    assert [r["agent_id"] for r in body["top10_vets"]] == ["V1"]


async def test_archived_rookie_still_ranks_but_archived_unranked_does_not(client, seeded_db, thursday):
    await profile(seeded_db, "RA", is_rookie=True, archived=True)
    await profile(seeded_db, "UA", archived=True)
    await profile(seeded_db, "UB")
    await entry(seeded_db, day="2026-07-02", agent_id="RA", gross_alp=300)
    await entry(seeded_db, day="2026-07-02", agent_id="UA", gross_alp=200)
    await entry(seeded_db, day="2026-07-02", agent_id="UB", gross_alp=100)
    body = await wall(client, await rga(seeded_db))
    assert [r["agent_id"] for r in body["top10_rookies"]] == ["RA"]
    assert [u["agent_id"] for u in body["unranked"]] == ["UB"]


async def test_top10_period_switches_the_window(client, seeded_db, thursday):
    await profile(seeded_db, "V1", is_rookie=False)
    await entry(seeded_db, day="2026-07-02", agent_id="V1", gross_alp=100)
    await entry(seeded_db, day="2026-07-01", agent_id="V1", gross_alp=200)
    await entry(seeded_db, day="2026-06-15", agent_id="V1", gross_alp=400)
    token = await rga(seeded_db)
    assert (await wall(client, token))["top10_vets"][0]["gross_alp"] == 100
    assert (await wall(client, token, "?period=weekly"))["top10_vets"][0]["gross_alp"] == 300
    assert (await wall(client, token, "?period=monthly"))["top10_vets"][0]["gross_alp"] == 300
    assert (await wall(client, token, "?sales_day=2026-06-15"))["top10_vets"][0]["gross_alp"] == 400
