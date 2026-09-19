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


async def test_team_weeks_allows_level_1_scoped_to_office(client, seeded_db):
    """Per owner, 2026-09-13: /api/team/weeks no longer 403s a level_1 caller
    — it lists weeks from their own office (office_agent_ids), not their
    downline (an Agent has none). AG_1 and AG_2 sit in different offices."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1")   # AG_1's own office (MCM)
    await entry(seeded_db, day="2026-05-06", agent_id="AG_2")   # different office (AMP)
    r = await client.get("/api/team/weeks", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["weeks"] == ["2026-02-18"]


# ---------------- agent day: what one agent submitted on one date ----------------

async def test_agent_day_returns_totals_for_that_sales_day_only(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sets=10, sits=8, sales=3, n1=1, gross_alp=750.0)
    await entry(seeded_db, day="2026-02-19", agent_id="AG_1", sets=5, sits=4, sales=9, gross_alp=9000.0)  # different day

    r = await client.get("/api/agents/AG_1/day?sales_day=2026-02-18", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["sales_day"] == "2026-02-18"
    assert body["totals"]["sales"] == 3
    assert body["totals"]["gross_alp"] == 750.0
    assert body["has_entries"] is True
    assert body["entry_count"] == 1
    # 3 sales / 8 sits = 37.5% (close_rate never subtracts N1 twice)
    assert body["close_rate"] == 37.5
    # show_rate = (sits + n1) / sets = (8 + 1) / 10 = 90%
    assert body["show_rate"] == 90.0
    assert body["alp_per_sale"] == 250.0


async def test_agent_day_with_no_submission_is_a_clean_zero_not_an_error(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/agents/AG_1/day?sales_day=2026-02-18", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["has_entries"] is False
    assert body["entry_count"] == 0
    assert body["totals"]["sales"] == 0
    assert body["close_rate"] == 0
    assert body["show_rate"] == 0


async def test_agent_day_sums_multiple_entries_same_day(client, seeded_db):
    """A correction adds a second row for the same sales_day — the day view
    must show the true current total, same as the self-correction screen."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=2, gross_alp=400.0)
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=1, gross_alp=100.0, is_adjustment=True)
    body = (await client.get("/api/agents/AG_1/day?sales_day=2026-02-18", headers=auth(token))).json()
    assert body["totals"]["sales"] == 3
    assert body["totals"]["gross_alp"] == 500.0
    assert body["entry_count"] == 2


async def test_agent_day_defaults_to_today_when_sales_day_omitted(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/agents/AG_1/day", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["sales_day"] == server.current_sales_day_str()


async def test_agent_day_rejects_a_future_date(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/agents/AG_1/day?sales_day=2099-01-01", headers=auth(token))
    assert r.status_code == 400


async def test_agent_cannot_read_a_peers_day(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", sales=9, gross_alp=9000.0)
    r = await client.get("/api/agents/AG_2/day?sales_day=2026-02-18", headers=auth(token))
    assert r.status_code == 403


async def test_upline_can_read_a_downline_agents_day(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sales=3, gross_alp=750.0)
    r = await client.get("/api/agents/AG_1/day?sales_day=2026-02-18", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["totals"]["sales"] == 3


async def test_agent_day_404s_for_an_unknown_agent(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/agents/NOPE/day?sales_day=2026-02-18", headers=auth(token))).status_code == 404


# ---------------- coaching card visibility ----------------
#
# Owner rule (2026-09-13): everyone ABOVE an agent in that agent's own chain —
# SA, GA, MGA, RGA — may see their coaching card. Nobody at or below them may,
# and nobody sideways. The server answers this with `coaching_visible` so the
# client never decides it by comparing tiers: SA and GA are both level_2, so a
# tier comparison denies a GA their own SA's card.

async def coaching(client, token, agent_id: str) -> bool:
    r = await client.get(f"/api/agents/{agent_id}/history", headers=auth(token))
    assert r.status_code == 200
    return r.json()["coaching_visible"]


async def test_every_upline_tier_sees_an_agents_coaching_card(client, seeded_db):
    """AG_1's chain is SA_1 → GA_1 → MGA_1 → RGA_1; all four are above him."""
    for agent_id, role in (("SA_1", "level_2"), ("GA_1", "level_2"),
                           ("MGA_1", "level_3"), ("RGA_1", "level_4")):
        token = await make_session(seeded_db, role=role, agent_id=agent_id,
                                   email=f"{agent_id.lower()}@test.dev")
        assert await coaching(client, token, "AG_1") is True, agent_id


async def test_ga_sees_their_own_sas_coaching_card(client, seeded_db):
    """The case a tier comparison gets wrong: GA_1 is SA_1's upline, but both
    are level_2, so `viewer_level > agent_level` would deny it."""
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert await coaching(client, token, "SA_1") is True


async def test_nobody_sees_their_own_coaching_card(client, seeded_db):
    for agent_id, role in (("AG_1", "level_1"), ("SA_1", "level_2"), ("RGA_1", "level_4")):
        token = await make_session(seeded_db, role=role, agent_id=agent_id,
                                   email=f"{agent_id.lower()}@test.dev")
        assert await coaching(client, token, agent_id) is False, agent_id


async def test_downline_never_reads_an_upline(client, seeded_db):
    """Since 2026-09-19 an upline is a contact, not a row: SA_1 cannot open
    GA_1's history at all, so the coaching question never arises. The two
    rules stay separate — read scope is team_scope_agent_ids, coaching is
    is_upline_of — which is why the 403 comes first here."""
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.get("/api/agents/GA_1/history", headers=auth(token))
    assert r.status_code == 403


async def test_rga_does_not_read_another_rga(client, seeded_db):
    """Since 2026-09-19 a plain RGA reads their own office; a peer RGA in
    another office is out of scope entirely. MJ (the admin grant) reads the
    company and still gets no coaching card on a peer — is_upline_of decides."""
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
        "role": "level_4", "upline_id": None, "office": "AMP",
    })
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/agents/RGA_2/history", headers=auth(token))).status_code == 403
    await seeded_db.users.update_one({"email": "rga1@test.dev"}, {"$set": {"is_admin": True}})
    assert await coaching(client, token, "RGA_2") is False


async def test_finance_admin_reads_history_without_coaching(client, seeded_db):
    """finance_admin has full read scope but sits outside the ladder, so it is
    nobody's upline."""
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_1", "name": "Fin Admin", "email": "fa@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    token = await make_session(seeded_db, role="finance_admin", agent_id="FA_1", email="fa@test.dev")
    assert await coaching(client, token, "AG_1") is False


# ---------------- weekly Sit Rate ----------------

async def test_weekly_show_rate_adds_n1_back_into_the_numerator(client, seeded_db):
    """Sit Rate is always (Sits + N1) / Sets (owner, 2026-09-13). The weekly
    series used to compute a bare sits / sets, which disagreed with the day
    drill-down, the agent card and the WAR export."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1", sets=10, sits=6, n1=2, sales=3)
    series = (await client.get("/api/agents/AG_1/history", headers=auth(token))).json()["series"]
    assert series[0]["show_rate"] == 80.0  # (6 + 2) / 10, not 6 / 10


# ---------------- an Agent reading an office teammate's card ----------------

async def test_level_1_can_read_an_office_teammates_history(client, seeded_db):
    """An agent may see their SA team's production (owner, 2026-09-19). SA_1
    runs AG_1's team, so the card opens with numbers."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="SA_1", sales=4, sits=8, gross_alp=900.0)
    r = await client.get("/api/agents/SA_1/history", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["series"][0]["gross_alp"] == 900.0


async def test_level_1_can_read_an_sa_teammates_day(client, seeded_db):
    """Since 2026-09-19 the team is the SA team: AG_1 reads a teammate under
    the same SA, and the SA who runs the team, but not the GA above them."""
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_1B", "name": "Agent One B", "email": "ag1b@test.dev",
        "role": "level_1", "upline_id": "SA_1", "office": "MCM",
    })
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_1B", sales=2, sits=5, sets=6, gross_alp=400.0)
    r = await client.get("/api/agents/AG_1B/day?sales_day=2026-02-18", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["totals"]["sales"] == 2
    assert (await client.get("/api/agents/GA_1/day?sales_day=2026-02-18", headers=auth(token))).status_code == 403


async def test_level_1_still_cannot_read_another_office(client, seeded_db):
    """The widening is the caller's own office and nothing else — AG_2 is in AMP."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await entry(seeded_db, day="2026-02-18", agent_id="AG_2", sales=9, gross_alp=9000.0)
    assert (await client.get("/api/agents/AG_2/history", headers=auth(token))).status_code == 403
    assert (await client.get("/api/agents/AG_2/day?sales_day=2026-02-18",
                             headers=auth(token))).status_code == 403


async def test_level_1_gets_the_numbers_but_never_the_coaching_card(client, seeded_db):
    """Production is the office's; coaching stays the upline's. An agent is
    nobody's upline, so coaching_visible is false even for a teammate they can
    now read in full."""
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert await coaching(client, token, "SA_1") is False
