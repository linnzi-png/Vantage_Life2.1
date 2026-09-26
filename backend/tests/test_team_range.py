"""The Team tab's date range (owner, 2026-09-24).

GET /api/team takes start_day / end_day (any inclusive range of sales days;
one day is start == end), defaults to month to date when nothing is asked
for, still honours the old period / week_start for builds that predate the
range picker, and echoes start_day / end_day for every path. Rows carry
overall_rank / overall_rank_of: everyone in an office ranked together on
their own Gross ALP, leaders included, gross_alp > 0 only, while rank /
rank_of / leaderboard_group stay for old builds.

GET /api/agents/{id}/day takes the same range; without it, it is exactly
the single-day call it always was.

Fixture: RGA_1 (MCM) -> MGA_1 (MCM) -> {GA_1 (MCM) -> SA_1 (MCM) -> AG_1 (MCM),
GA_2 (AMP) -> AG_2 (AMP)}.
"""
from datetime import datetime

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


async def entry(db, *, day, agent_id, gross_alp, sales=1, sits=2, office="MCM"):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{day}_{agent_id}_{int(gross_alp)}", "agent_id": agent_id, "office": office,
        "sales_day": day, "sets": 3, "sits": sits, "sales": sales, "ots_sits": 0, "ots_sales": 0,
        "n1": 0, "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": float(gross_alp), "net_alp": float(gross_alp),
    })


async def team(client, token, query=""):
    r = await client.get(f"/api/team{query}", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    return body, {x["agent_id"]: x for x in body["team"]}


# ---------------- windows ----------------

async def test_single_day_is_start_equal_to_end(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await entry(seeded_db, day="2026-09-16", agent_id="AG_1", gross_alp=500)
    await entry(seeded_db, day="2026-09-17", agent_id="AG_1", gross_alp=900)
    body, rows = await team(client, await rga(seeded_db), "?start_day=2026-09-16&end_day=2026-09-16")
    assert rows["AG_1"]["gross_alp"] == 500
    assert (body["start_day"], body["end_day"]) == ("2026-09-16", "2026-09-16")
    assert body["period"] is None and body["week_start"] is None


async def test_a_week_and_a_whole_month_are_just_ranges(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await entry(seeded_db, day="2026-08-01", agent_id="AG_1", gross_alp=100)
    await entry(seeded_db, day="2026-08-31", agent_id="AG_1", gross_alp=200)
    await entry(seeded_db, day="2026-09-01", agent_id="AG_1", gross_alp=400)
    await entry(seeded_db, day="2026-09-07", agent_id="AG_1", gross_alp=800)
    token = await rga(seeded_db)
    _, rows = await team(client, token, "?start_day=2026-09-01&end_day=2026-09-07")
    assert rows["AG_1"]["gross_alp"] == 1200
    _, rows = await team(client, token, "?start_day=2026-08-01&end_day=2026-08-31")
    assert rows["AG_1"]["gross_alp"] == 300


async def test_month_to_date_is_the_default_and_follows_the_sales_day(client, seeded_db, detroit_now):
    # 1:00 AM on Oct 1 is still the Sep 30 sales day, so the window is all of September.
    detroit_now(2026, 10, 1, 1, 0)
    await entry(seeded_db, day="2026-08-31", agent_id="AG_1", gross_alp=1)
    await entry(seeded_db, day="2026-09-01", agent_id="AG_1", gross_alp=10)
    await entry(seeded_db, day="2026-09-30", agent_id="AG_1", gross_alp=100)
    body, rows = await team(client, await rga(seeded_db))
    assert (body["start_day"], body["end_day"]) == ("2026-09-01", "2026-09-30")
    assert rows["AG_1"]["gross_alp"] == 110


async def test_future_and_start_after_end_are_rejected(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    token = await rga(seeded_db)
    assert (await client.get("/api/team?start_day=2026-09-20&end_day=2026-09-25", headers=auth(token))).status_code == 400
    assert (await client.get("/api/team?start_day=2026-09-20&end_day=2026-09-10", headers=auth(token))).status_code == 400
    assert (await client.get("/api/team?start_day=not-a-day&end_day=2026-09-10", headers=auth(token))).status_code == 400


async def test_missing_end_runs_through_today_and_missing_start_is_one_day(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    token = await rga(seeded_db)
    body, _ = await team(client, token, "?start_day=2026-09-20")
    assert (body["start_day"], body["end_day"]) == ("2026-09-20", "2026-09-24")
    body, _ = await team(client, token, "?end_day=2026-09-20")
    assert (body["start_day"], body["end_day"]) == ("2026-09-20", "2026-09-20")


async def test_old_period_and_week_start_requests_still_work_and_echo_the_window(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)  # Thursday; the reporting week began Wed 9/23 2 PM
    await entry(seeded_db, day="2026-09-23", agent_id="AG_1", gross_alp=50)
    token = await rga(seeded_db)
    body, rows = await team(client, token, "?period=weekly")
    assert body["period"] == "weekly"
    assert (body["start_day"], body["end_day"]) == ("2026-09-23", "2026-09-24")
    assert rows["AG_1"]["gross_alp"] == 50
    body, _ = await team(client, token, "?period=daily")
    assert (body["start_day"], body["end_day"]) == ("2026-09-24", "2026-09-24")
    body, _ = await team(client, token, "?week_start=2026-09-16")
    assert body["week_start"] == "2026-09-16"
    assert (body["start_day"], body["end_day"]) == ("2026-09-16", "2026-09-22")


async def test_range_wins_over_period_when_both_are_sent(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    body, _ = await team(client, await rga(seeded_db), "?period=weekly&start_day=2026-09-01&end_day=2026-09-02")
    assert body["period"] is None
    assert (body["start_day"], body["end_day"]) == ("2026-09-01", "2026-09-02")


async def test_range_still_respects_team_scope(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await entry(seeded_db, day="2026-09-10", agent_id="AG_2", gross_alp=999, office="AMP")
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    _, rows = await team(client, token, "?start_day=2026-09-01&end_day=2026-09-24")
    assert "AG_2" not in rows


# ---------------- overall rank ----------------

async def add_agent(db, agent_id, *, upline, tenure, office="MCM", role="level_1"):
    doc = {"agent_id": agent_id, "name": agent_id, "email": f"{agent_id}@test.dev",
           "role": role, "upline_id": upline, "office": office}
    if tenure is not None:
        doc["is_rookie"] = tenure
    await db.agent_profiles.insert_one(doc)


async def test_overall_rank_runs_across_groups_per_office(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await add_agent(seeded_db, "ROOK", upline="SA_1", tenure=True)
    await add_agent(seeded_db, "VET", upline="SA_1", tenure=False)
    await add_agent(seeded_db, "UNSET", upline="SA_1", tenure=None)
    await entry(seeded_db, day="2026-09-10", agent_id="VET", gross_alp=300)
    await entry(seeded_db, day="2026-09-10", agent_id="SA_1", gross_alp=900)   # a leader, on their own sales
    await entry(seeded_db, day="2026-09-10", agent_id="ROOK", gross_alp=500)
    await entry(seeded_db, day="2026-09-10", agent_id="UNSET", gross_alp=100)
    await entry(seeded_db, day="2026-09-10", agent_id="AG_2", gross_alp=5000, office="AMP")  # other office
    _, rows = await team(client, await rga(seeded_db))
    # MCM, one list: SA_1 900, ROOK 500, VET 300, UNSET 100.
    assert [(rows[a]["overall_rank"], rows[a]["overall_rank_of"]) for a in ("SA_1", "ROOK", "VET", "UNSET")] == \
        [(1, 4), (2, 4), (3, 4), (4, 4)]
    # The old per-group standings are still there for builds that read them.
    assert rows["ROOK"]["rank"] == 1 and rows["ROOK"]["leaderboard_group"] == "rookie"
    assert rows["VET"]["rank"] == 1 and rows["VET"]["leaderboard_group"] == "veteran"
    assert rows["SA_1"]["rank"] == 1 and rows["SA_1"]["leaderboard_group"] == "leader"
    # Nobody at $0 is ranked, and AMP is its own race.
    assert rows["AG_1"]["overall_rank"] is None and rows["AG_1"]["overall_rank_of"] is None
    assert (rows["AG_2"]["overall_rank"], rows["AG_2"]["overall_rank_of"]) == (1, 1)


# ---------------- /agents/{id}/day ----------------

async def test_agent_day_without_dates_is_still_the_single_current_day(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await entry(seeded_db, day="2026-09-01", agent_id="AG_1", gross_alp=1000)
    await entry(seeded_db, day="2026-09-24", agent_id="AG_1", gross_alp=70)
    body = (await client.get("/api/agents/AG_1/day", headers=auth(await rga(seeded_db)))).json()
    assert (body["sales_day"], body["start_day"], body["end_day"]) == ("2026-09-24",) * 3
    assert body["totals"]["gross_alp"] == 70 and body["entry_count"] == 1


async def test_agent_day_sums_a_range_and_counts_every_entry(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    await entry(seeded_db, day="2026-09-15", agent_id="AG_1", gross_alp=100, sales=1, sits=4)
    await entry(seeded_db, day="2026-09-16", agent_id="AG_1", gross_alp=300, sales=2, sits=4)
    await entry(seeded_db, day="2026-09-17", agent_id="AG_1", gross_alp=999)  # outside
    r = await client.get("/api/agents/AG_1/day?start_day=2026-09-15&end_day=2026-09-16", headers=auth(await rga(seeded_db)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["sales_day"], body["start_day"], body["end_day"]) == ("2026-09-16", "2026-09-15", "2026-09-16")
    assert body["totals"]["gross_alp"] == 400 and body["totals"]["sales"] == 3 and body["totals"]["sits"] == 8
    assert body["entry_count"] == 2 and body["has_entries"] is True
    assert body["close_rate"] == 37.5  # 3 / 8
    assert body["alp_per_sale"] == round(400 / 3, 2)


async def test_agent_day_range_is_validated_and_scoped(client, seeded_db, detroit_now):
    detroit_now(2026, 9, 24, 12, 0)
    token = await rga(seeded_db)
    assert (await client.get("/api/agents/AG_1/day?start_day=2026-09-20&end_day=2026-09-10", headers=auth(token))).status_code == 400
    assert (await client.get("/api/agents/AG_1/day?start_day=2026-09-20&end_day=2026-09-30", headers=auth(token))).status_code == 400
    ga = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert (await client.get("/api/agents/AG_2/day?start_day=2026-09-01&end_day=2026-09-02", headers=auth(ga))).status_code == 403
