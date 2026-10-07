"""Team views: GET /api/team/branches (owner: MJ 2026-09-25; Linnzi 2026-09-26,
2026-09-29 and 2026-10-02).

Office-wide totals for every SA, GA or MGA team. A team is the leader plus
everyone under them, nested. The caller reads their own office; MJ's company
view reads every office, grouped, and his "own" switch narrows to his tree. A
team outside the caller's downline is a total and nothing else.

Fixture (conftest) plus `org()`:
  MCM: RGA_1 > MGA_1 > GA_1 > SA_1 > AG_1
                                   > SA_4 > AG_4
                    > GA_3 > SA_3 > AG_3
                    > GA_2 (office AMP) > AG_2 (AMP)
  AMP: RGA_2 > MGA_2 > GA_4 > AG_5
"""
import pytest

import server
from conftest import auth, make_session

DAY = "2026-09-10"


async def person(db, agent_id, role, upline, office="MCM", *, name=None, io_role=None, archived=False):
    doc = {"agent_id": agent_id, "name": name or agent_id.replace("_", " ").title(),
           "email": f"{agent_id.lower()}@test.dev", "role": role, "upline_id": upline, "office": office}
    if io_role:
        doc["io_role"] = io_role
    if archived:
        doc["archived"] = True
    await db.agent_profiles.insert_one(doc)


async def org(db):
    await person(db, "GA_3", "level_2", "MGA_1", io_role="GA")
    await person(db, "SA_3", "level_sa", "GA_3", io_role="SA")
    await person(db, "AG_3", "level_1", "SA_3")
    await person(db, "SA_4", "level_sa", "GA_1", io_role="SA")
    await person(db, "AG_4", "level_1", "SA_4")
    await person(db, "RGA_2", "level_4", None, "AMP")
    await person(db, "MGA_2", "level_3", "RGA_2", "AMP")
    await person(db, "GA_4", "level_2", "MGA_2", "AMP", io_role="GA")
    await person(db, "AG_5", "level_1", "GA_4", "AMP")


async def prod(db, agent_id, gross, *, sales=1, sits=2, sets=3, n1=0, refs=0, day=DAY):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}_{day}_{gross}", "agent_id": agent_id, "office": "MCM", "sales_day": day,
        "sets": sets, "sits": sits, "sales": sales, "ots_sits": 0, "ots_sales": 0, "n1": n1,
        "refs_obtained": refs, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0, "gross_alp": float(gross), "net_alp": float(gross)})


async def seed_production(db):
    """GA_1 team: 100 + 200 + 300 + 400 + 500 = 1500. SA_1 team 500, SA_4 team
    900, SA_3 team 500 (AG_3 alone)."""
    for aid, gross in (("GA_1", 100), ("SA_1", 200), ("AG_1", 300), ("SA_4", 400), ("AG_4", 500), ("AG_3", 500)):
        await prod(db, aid, gross)


async def get(client, token, **params):
    params.setdefault("start_day", DAY)
    params.setdefault("end_day", DAY)
    return await client.get("/api/team/branches", params=params, headers=auth(token))


async def as_(db, role, agent_id):
    return await make_session(db, role=role, agent_id=agent_id, email=f"{agent_id.lower()}@test.dev")


def lines_of(body, office=None):
    out = {}
    for sec in body["offices"]:
        if office is None or sec["office"] == office:
            out.update({ln["agent_id"]: ln for ln in sec["lines"]})
    return out


# ---------------- totals: the leader is in, and teams nest ----------------

async def test_a_team_total_includes_the_leader_and_nests(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    token = await as_(seeded_db, "level_3", "MGA_1")
    ga = lines_of((await get(client, token, tier="ga")).json())
    # GA_1 = themselves + SA_1 + AG_1 + SA_4 + AG_4: the GA, and every SA team below.
    assert ga["GA_1"]["team_gross_alp"] == 1500.0
    assert ga["GA_1"]["team_sales"] == 5
    assert ga["GA_1"]["head_count"] == 5          # active people, the leader included
    sa = lines_of((await get(client, token, tier="sa")).json())
    assert sa["SA_1"]["team_gross_alp"] == 500.0   # SA_1 + AG_1
    assert sa["SA_4"]["team_gross_alp"] == 900.0
    assert sa["SA_1"]["head_count"] == 2
    # The SA teams add up to the GA team, less the GA's own number.
    assert sa["SA_1"]["team_gross_alp"] + sa["SA_4"]["team_gross_alp"] + 100.0 == ga["GA_1"]["team_gross_alp"]


async def test_the_team_view_and_the_branches_never_disagree(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    token = await as_(seeded_db, "level_4", "RGA_1")
    team = await client.get("/api/team", params={"start_day": DAY, "end_day": DAY}, headers=auth(token))
    rows = {r["agent_id"]: r for r in team.json()["team"]}
    ga = lines_of((await get(client, token, tier="ga")).json())
    sa = lines_of((await get(client, token, tier="sa")).json())
    for aid in ("GA_1", "GA_3"):
        assert rows[aid]["team_gross_alp"] == ga[aid]["team_gross_alp"]
        assert rows[aid]["team_sales"] == ga[aid]["team_sales"]
    for aid in ("SA_1", "SA_3", "SA_4"):
        assert rows[aid]["team_gross_alp"] == sa[aid]["team_gross_alp"]


async def test_a_removed_member_still_counts_in_the_total_but_not_in_the_head_count(client, seeded_db):
    await org(seeded_db)
    await person(seeded_db, "GONE", "level_1", "SA_1", archived=True)
    await prod(seeded_db, "GONE", 600)
    await prod(seeded_db, "AG_1", 300)
    sa = lines_of((await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json())
    assert sa["SA_1"]["team_gross_alp"] == 900.0
    assert sa["SA_1"]["head_count"] == 2           # SA_1 and AG_1; the removed person is not on the team today


async def test_an_archived_leader_has_no_team_line(client, seeded_db):
    await org(seeded_db)
    await seeded_db.agent_profiles.update_one({"agent_id": "SA_4"}, {"$set": {"archived": True}})
    sa = lines_of((await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json())
    assert "SA_4" not in sa and {"SA_1", "SA_3"} <= set(sa)


# ---------------- ratios come from metrics.py ----------------

async def test_the_ratios_use_the_metrics_module(client, seeded_db):
    await org(seeded_db)
    # AG_1: 4 sits, 6 refs, 3 sets-short: (sits 4 + n1 1) / sets 5 = 100%.
    await prod(seeded_db, "AG_1", 800, sales=2, sits=4, sets=5, n1=1, refs=6)
    sa = lines_of((await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json())
    line = sa["SA_1"]
    assert line["team_sits"] == 4 and line["team_refs"] == 6
    assert line["refs_per_sit"] == 1.5             # 6 / 4
    assert line["show_ratio"] == 100.0             # (4 + 1) / 5
    assert line["avg_alp"] == 400.0                # 800 / 2 sales
    assert line["close_ratio"] == 50.0             # 2 sales / 4 sits


async def test_a_team_with_no_sits_or_sales_has_zero_ratios(client, seeded_db):
    await org(seeded_db)
    sa = lines_of((await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json())
    line = sa["SA_1"]
    assert (line["refs_per_sit"], line["show_ratio"], line["avg_alp"], line["close_ratio"]) == (0, 0, 0, 0)
    assert line["team_gross_alp"] == 0


# ---------------- scope ----------------

async def test_a_leader_reads_only_their_own_office(client, seeded_db):
    await org(seeded_db)
    body = (await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="ga")).json()
    assert body["scope"] == "office"
    assert [s["office"] for s in body["offices"]] == ["MCM"]
    # GA_2 reports to MGA_1 but sits in AMP; GA_4 is AMP's own.
    assert set(lines_of(body)) == {"GA_1", "GA_3"}


async def test_mjs_company_view_is_one_section_per_office(client, seeded_db):
    await org(seeded_db)
    token = await as_(seeded_db, "level_4", "RGA_1")
    await seeded_db.users.update_one({"agent_id": "RGA_1"}, {"$set": {"is_admin": True}})
    body = (await get(client, token, tier="ga")).json()
    assert body["scope"] == "company"
    assert [s["office"] for s in body["offices"]] == ["MCM", "AMP"]   # his own office first
    assert set(lines_of(body, "MCM")) == {"GA_1", "GA_3"}
    assert set(lines_of(body, "AMP")) == {"GA_2", "GA_4"}


async def test_mjs_own_switch_limits_the_views_to_his_tree(client, seeded_db):
    await org(seeded_db)
    token = await as_(seeded_db, "level_4", "RGA_1")
    await seeded_db.users.update_one({"agent_id": "RGA_1"}, {"$set": {"is_admin": True, "view_mode": "own"}})
    body = (await get(client, token, tier="ga")).json()
    assert body["scope"] == "own"
    # Everything under RGA_1, whatever the office (GA_2 is in AMP); not RGA_2's GA_4.
    assert set(lines_of(body)) == {"GA_1", "GA_2", "GA_3"}


async def test_an_agent_is_turned_away(client, seeded_db):
    await org(seeded_db)
    r = await get(client, await as_(seeded_db, "level_1", "AG_1"), tier="sa")
    assert r.status_code == 403


async def test_a_bad_tier_is_a_400_and_sa_is_the_default(client, seeded_db):
    await org(seeded_db)
    token = await as_(seeded_db, "level_3", "MGA_1")
    assert (await get(client, token, tier="rga")).status_code == 400
    default = await client.get("/api/team/branches", params={"start_day": DAY, "end_day": DAY}, headers=auth(token))
    assert default.status_code == 200 and default.json()["tier"] == "sa"


async def test_candidates_are_chosen_by_tier_never_by_title(client, seeded_db):
    await org(seeded_db)
    # GA_3 carries an SA title but is a level_2: it is a GA team, not an SA team.
    await seeded_db.agent_profiles.update_one({"agent_id": "GA_3"}, {"$set": {"io_role": "SA"}})
    token = await as_(seeded_db, "level_3", "MGA_1")
    assert "GA_3" in lines_of((await get(client, token, tier="ga")).json())
    assert "GA_3" not in lines_of((await get(client, token, tier="sa")).json())


# ---------------- members: only for a team under the caller ----------------

async def test_a_leader_sees_totals_but_no_members_outside_their_downline(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    ga = lines_of((await get(client, await as_(seeded_db, "level_2", "GA_1"), tier="ga")).json())
    assert ga["GA_1"]["in_my_downline"] is True
    assert sorted(ga["GA_1"]["member_ids"]) == ["AG_1", "AG_4", "SA_1", "SA_4"]
    # GA_3 is a peer: the total is there, the people are not.
    assert ga["GA_3"]["in_my_downline"] is False
    assert ga["GA_3"]["member_ids"] == []
    assert ga["GA_3"]["team_gross_alp"] == 500.0
    sa = lines_of((await get(client, await as_(seeded_db, "level_2", "GA_1"), tier="sa")).json())
    assert sa["SA_1"]["member_ids"] == ["AG_1"] and sa["SA_3"]["member_ids"] == []


async def test_an_rga_reaches_every_team_in_their_scope(client, seeded_db):
    await org(seeded_db)
    ga = lines_of((await get(client, await as_(seeded_db, "level_4", "RGA_1"), tier="ga")).json())
    assert ga["GA_3"]["in_my_downline"] is True and ga["GA_3"]["member_ids"]


# ---------------- ranking, best and worst ----------------

async def test_ranks_share_a_place_on_a_tie(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    sa = lines_of((await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json())
    assert (sa["SA_4"]["team_rank"], sa["SA_1"]["team_rank"], sa["SA_3"]["team_rank"]) == (1, 2, 2)


async def test_best_and_worst_list_every_tied_team(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    body = (await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json()
    bw = body["offices"][0]["best_worst"]
    assert [x["agent_id"] for x in bw["alp"]["best"]] == ["SA_4"]
    assert sorted(x["agent_id"] for x in bw["alp"]["worst"]) == ["SA_1", "SA_3"]   # 500 each: both
    assert bw["alp"]["best"][0]["value"] == 900.0
    # Average ALP is a different race: SA_3 (500 a sale) leads, SA_1 (250) trails.
    assert [x["agent_id"] for x in bw["avg_alp"]["best"]] == ["SA_3"]
    assert [x["agent_id"] for x in bw["avg_alp"]["worst"]] == ["SA_1"]
    assert set(bw) == {"alp", "refs_per_sit", "show_ratio", "avg_alp"}


async def test_teams_with_nothing_are_listed_not_dropped(client, seeded_db):
    await org(seeded_db)
    body = (await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json()
    bw = body["offices"][0]["best_worst"]
    # Everyone is at $0: all of them are "best", and nobody is called out as worst.
    assert sorted(x["agent_id"] for x in bw["alp"]["best"]) == ["SA_1", "SA_3", "SA_4"]
    assert bw["alp"]["worst"] == []


async def test_a_zero_team_is_the_worst_when_others_have_numbers(client, seeded_db):
    await org(seeded_db)
    await prod(seeded_db, "AG_1", 300)
    bw = (await get(client, await as_(seeded_db, "level_3", "MGA_1"), tier="sa")).json()["offices"][0]["best_worst"]
    assert [x["agent_id"] for x in bw["alp"]["best"]] == ["SA_1"]
    assert sorted(x["agent_id"] for x in bw["alp"]["worst"]) == ["SA_3", "SA_4"]   # the $0 teams, both


# ---------------- competitors ----------------

async def test_competitors_are_the_top_three_same_tier_peers_in_the_callers_office(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    for ga, agent, gross in (("GA_5", "AG_6", 300), ("GA_6", "AG_7", 200), ("GA_7", "AG_8", 100)):
        await person(seeded_db, ga, "level_2", "MGA_1", io_role="GA")
        await person(seeded_db, agent, "level_1", ga)
        await prod(seeded_db, agent, gross)
    await prod(seeded_db, "AG_2", 9999)   # GA_2's team is in AMP: another office, never a peer of GA_1
    body = (await get(client, await as_(seeded_db, "level_2", "GA_1"), tier="sa")).json()
    comps = body["competitors"]
    assert [c["agent_id"] for c in comps] == ["GA_3", "GA_5", "GA_6"]   # 500, 300, 200; GA_7 (100) is fourth
    assert "GA_1" not in {c["agent_id"] for c in comps}                 # never the caller
    # Identity and the one number; no members, no other metrics.
    assert set(comps[0]) == {"agent_id", "name", "io_role", "office", "team_gross_alp"}
    assert comps[0]["team_gross_alp"] == 500.0


async def test_competitors_follow_the_callers_tier_not_the_requested_one(client, seeded_db):
    await org(seeded_db)
    await seed_production(seeded_db)
    token = await as_(seeded_db, "level_2", "GA_1")
    a = (await get(client, token, tier="sa")).json()["competitors"]
    b = (await get(client, token, tier="mga")).json()["competitors"]
    assert a == b


async def test_an_rgas_competitors_are_the_other_offices_rgas(client, seeded_db):
    await org(seeded_db)
    for rid, office, gross in (("RGA_3", "DTW", 800), ("RGA_4", "LAN", 600), ("RGA_5", "FLT", 400)):
        await person(seeded_db, rid, "level_4", None, office)
        await prod(seeded_db, rid, gross)
    await prod(seeded_db, "RGA_2", 1000)   # AMP's RGA: team includes themselves
    await prod(seeded_db, "RGA_1", 99999)  # the caller never competes with themselves
    await person(seeded_db, "RGA_6", "level_4", None, "MCM")   # a second RGA in the caller's office is no rival
    await prod(seeded_db, "RGA_6", 50000)
    body = (await get(client, await as_(seeded_db, "level_4", "RGA_1"), tier="sa")).json()
    comps = body["competitors"]
    assert [c["agent_id"] for c in comps] == ["RGA_2", "RGA_3", "RGA_4"]   # 1000, 800, 600; RGA_5 (400) is fourth
    assert {c["office"] for c in comps} == {"AMP", "DTW", "LAN"}


async def test_a_peer_total_nests_the_peers_whole_team(client, seeded_db):
    await org(seeded_db)
    await prod(seeded_db, "AG_5", 700)   # GA_4's agent; rolls up through GA_4 > MGA_2 > RGA_2
    comps = (await get(client, await as_(seeded_db, "level_4", "RGA_1"), tier="sa")).json()["competitors"]
    assert comps[0]["agent_id"] == "RGA_2" and comps[0]["team_gross_alp"] == 700.0


# ---------------- the window ----------------

async def test_the_default_window_is_month_to_date(client, seeded_db):
    await org(seeded_db)
    first, today = server.month_to_date_range()
    before = (server.datetime.fromisoformat(first) - server.timedelta(days=1)).date().isoformat()
    await prod(seeded_db, "AG_1", 300, day=today)
    await prod(seeded_db, "AG_1", 900, day=before)   # last month: outside the window
    token = await as_(seeded_db, "level_3", "MGA_1")
    r = await client.get("/api/team/branches", params={"tier": "sa"}, headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["start_day"], body["end_day"]) == (first, today)
    assert lines_of(body)["SA_1"]["team_gross_alp"] == 300.0


async def test_a_range_is_honoured_and_a_backwards_one_is_a_400(client, seeded_db):
    await org(seeded_db)
    await prod(seeded_db, "AG_1", 300, day="2026-09-10")
    await prod(seeded_db, "AG_1", 200, day="2026-09-11")
    await prod(seeded_db, "AG_1", 100, day="2026-09-13")
    token = await as_(seeded_db, "level_3", "MGA_1")
    body = (await get(client, token, tier="sa", start_day="2026-09-10", end_day="2026-09-12")).json()
    assert lines_of(body)["SA_1"]["team_gross_alp"] == 500.0
    assert (await get(client, token, tier="sa", start_day="2026-09-12", end_day="2026-09-10")).status_code == 400


async def test_a_line_carries_contact_details_for_a_team_outside_the_downline(client, seeded_db):
    await org(seeded_db)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "GA_3"}, {"$set": {"phone": "3135550142", "email": "ga3@agency.example"}})
    ga = lines_of((await get(client, await as_(seeded_db, "level_2", "GA_1"), tier="ga")).json())
    line = ga["GA_3"]
    assert line["in_my_downline"] is False and line["member_ids"] == []
    assert (line["phone"], line["email"], line["role"]) == ("3135550142", "ga3@agency.example", "level_2")
    assert ga["GA_1"]["phone"] == ""                  # no phone on file: empty, not absent
