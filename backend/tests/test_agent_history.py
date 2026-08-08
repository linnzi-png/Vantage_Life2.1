"""Per-agent weekly history and the Team screen's historical week view.

RBAC is the point of most of these: history is business data, so it must be
reachable only through visible_agent_ids() — an agent sees themselves, an
upline sees their downline, and nobody sees sideways.
"""
import pytest

import server
from conftest import auth, make_session


async def entry(db, *, day, agent_id, office="MJ RGA", **m):
    doc = {
        "entry_id": f"pe_{day}_{agent_id}", "agent_id": agent_id, "office": office,
        "sales_day": day,
        "sets": 0, "sits": 0, "sales": 0, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 0.0, "net_alp": 0.0,
    }
    doc.update(m)
    await db.production_entries.insert_one(doc)


# ---------------- agent history: RBAC ----------------

async def test_agent_can_read_their_own_history(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=2, gross_alp=500.0)
    r = await client.get("/api/agents/AG_1/history", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["series"][0]["gross_alp"] == 500.0
    assert r.json()["agent"]["agent_id"] == "AG_1"


async def test_agent_cannot_read_a_peers_history(client, seeded_db):
    """AG_1 and AG_2 sit in different downlines — no sideways visibility."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", sales=9, gross_alp=9000.0)
    r = await client.get("/api/agents/AG_2/history", headers=auth(token))
    assert r.status_code == 403


async def test_upline_can_read_a_downline_agents_history(client, seeded_db):
    """GA_1 → SA_1 → AG_1, so GA_1 may read AG_1."""
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=3, gross_alp=750.0)
    r = await client.get("/api/agents/AG_1/history", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["series"][0]["sales"] == 3


async def test_ga_cannot_read_another_gas_downline(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", gross_alp=1.0)
    assert (await client.get("/api/agents/AG_2/history", headers=auth(token))).status_code == 403


async def test_rga_can_read_anyone(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", sales=4)
    assert (await client.get("/api/agents/AG_2/history", headers=auth(token))).status_code == 200


async def test_history_rejects_pending_users(client, seeded_db):
    """A user with no agent link must not reach business data."""
    token = await make_session(seeded_db, role="pending", agent_id=None, email="nobody@test.dev")
    assert (await client.get("/api/agents/AG_1/history", headers=auth(token))).status_code == 403


async def test_history_404s_for_an_unknown_agent(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/agents/NOPE/history", headers=auth(token))).status_code == 404


# ---------------- agent history: content ----------------

async def test_history_buckets_by_reporting_week_with_plain_close_rate(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=3, sits=10, n1=2, gross_alp=300.0)
    await entry(seeded_db, day="2026-02-24", agent_id="AG_1", sales=1, sits=2, gross_alp=100.0)  # same week
    await entry(seeded_db, day="2026-02-25", agent_id="AG_1", sales=1, gross_alp=50.0)           # next week

    series = (await client.get("/api/agents/AG_1/history", headers=auth(token))).json()["series"]
    assert [w["week_start"] for w in series] == ["2026-02-18", "2026-02-25"]
    first = series[0]
    assert first["gross_alp"] == 400.0
    # 4 sales / 12 sits = 33.3%. N1 is not subtracted — it is already excluded
    # from Sits at entry, so the old 4/(12-2) = 40% counted it twice.
    assert first["close_rate"] == 33.3


async def test_history_weeks_limit_keeps_most_recent(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    for d in ("2026-02-18", "2026-02-25", "2026-03-04"):
        await entry(seeded_db, day=d, agent_id="AG_1", sales=1)
    r = await client.get("/api/agents/AG_1/history?weeks=2", headers=auth(token))
    assert [w["week_start"] for w in r.json()["series"]] == ["2026-02-25", "2026-03-04"]


async def test_history_is_empty_for_an_agent_with_no_entries(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/agents/AG_1/history", headers=auth(token))).json()["series"] == []


# ---------------- team: historical week ----------------

async def test_team_week_start_pulls_that_week_only(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=2, gross_alp=200.0)
    await entry(seeded_db, day="2026-02-24", agent_id="AG_1", sales=1, gross_alp=100.0)  # same week
    await entry(seeded_db, day="2026-02-25", agent_id="AG_1", sales=9, gross_alp=900.0)  # next week

    r = await client.get("/api/team?week_start=2026-02-18", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["week_start"] == "2026-02-18"
    assert body["period"] is None
    row = next(t for t in body["team"] if t["agent_id"] == "AG_1")
    assert row["gross_alp"] == 300.0   # Wed + Tue, not the following Wed


async def test_team_week_start_must_be_a_wednesday(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/team?week_start=2026-02-19", headers=auth(token))
    assert r.status_code == 400
    assert "Wednesday" in r.json()["detail"]


async def test_team_historical_week_still_respects_rbac(client, seeded_db):
    """A GA viewing a past week sees only their own downline."""
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", gross_alp=100.0)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", gross_alp=999.0)
    ids = {t["agent_id"] for t in (await client.get(
        "/api/team?week_start=2026-02-18", headers=auth(token))).json()["team"]}
    assert "AG_2" not in ids


async def test_team_without_week_start_keeps_period_behavior(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    body = (await client.get("/api/team?period=weekly", headers=auth(token))).json()
    assert body["period"] == "weekly"
    assert body["week_start"] is None


# ---------------- team: week picker options ----------------

async def test_team_weeks_lists_weeks_with_data_newest_first(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    for d in ("2026-02-18", "2026-02-24", "2026-03-04"):
        await entry(seeded_db, day=d, agent_id="AG_1")
    r = await client.get("/api/team/weeks", headers=auth(token))
    assert r.json()["weeks"] == ["2026-03-04", "2026-02-18"]


async def test_team_weeks_is_scoped_to_the_callers_team(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1")   # in GA_1's downline
    await entry(seeded_db, day="2026-05-06", agent_id="AG_2")   # not
    assert (await client.get("/api/team/weeks", headers=auth(token))).json()["weeks"] == ["2026-02-18"]


async def test_team_weeks_requires_level_2(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await client.get("/api/team/weeks", headers=auth(token))).status_code == 403
