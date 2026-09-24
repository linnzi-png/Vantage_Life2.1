"""The Team tab as a leaderboard (owner, 2026-09-16).

A team IS an office. Agents rank inside their tenure group — rookies,
veterans, and a third group for people nobody has recorded a tenure for —
leaders rank among leaders, and every rank runs on Gross ALP, the same measure
the Platinum Wall uses, so a position means the same thing on both screens.
"""
import pytest

import server
from conftest import auth, make_session


async def entry(db, *, agent_id, gross_alp, sales=1, office="MCM"):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}", "agent_id": agent_id, "office": office,
        "sales_day": server.current_sales_day_str(),
        "sets": 2, "sits": 2, "sales": sales, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": float(gross_alp), "net_alp": float(gross_alp),
    })


async def board(client, token):
    r = await client.get("/api/team", headers=auth(token))
    assert r.status_code == 200, r.text
    return {x["agent_id"]: x for x in r.json()["team"]}


async def add_agent(db, agent_id, *, upline, tenure, office="MCM"):
    doc = {"agent_id": agent_id, "name": agent_id, "email": f"{agent_id}@test.dev",
           "role": "level_1", "upline_id": upline, "office": office}
    if tenure is not None:
        doc["is_rookie"] = tenure
    await db.agent_profiles.insert_one(doc)


# ---------------- tenure groups ----------------

async def test_rookies_and_veterans_are_ranked_separately(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "ROOK_A", upline="SA_1", tenure=True)
    await add_agent(seeded_db, "ROOK_B", upline="SA_1", tenure=True)
    await add_agent(seeded_db, "VET_A", upline="SA_1", tenure=False)
    await entry(seeded_db, agent_id="ROOK_A", gross_alp=500)
    await entry(seeded_db, agent_id="ROOK_B", gross_alp=900)
    await entry(seeded_db, agent_id="VET_A", gross_alp=100)

    rows = await board(client, token)
    assert rows["ROOK_B"]["leaderboard_group"] == "rookie"
    assert (rows["ROOK_B"]["rank"], rows["ROOK_B"]["rank_of"]) == (1, 2)
    assert rows["ROOK_A"]["rank"] == 2
    # A veteran with the smallest number on the board is still 1st of the vets.
    assert rows["VET_A"]["leaderboard_group"] == "veteran"
    assert rows["VET_A"]["rank"] == 1


async def test_tenure_nobody_recorded_gets_its_own_group(client, seeded_db):
    """48 of the 217 active roster have no tenure. They rank together rather
    than being silently counted as veterans."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "UNSET_A", upline="SA_1", tenure=None)
    await entry(seeded_db, agent_id="UNSET_A", gross_alp=400)
    rows = await board(client, token)
    assert rows["UNSET_A"]["is_rookie"] is None
    assert rows["UNSET_A"]["leaderboard_group"] == "unset"
    assert rows["UNSET_A"]["rank"] == 1


# ---------------- leaders ----------------

async def test_leaders_rank_among_themselves_not_against_their_agents(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "BIG_AGENT", upline="SA_1", tenure=False)
    await entry(seeded_db, agent_id="BIG_AGENT", gross_alp=9000)
    await entry(seeded_db, agent_id="SA_1", gross_alp=300)
    await entry(seeded_db, agent_id="GA_1", gross_alp=600)

    rows = await board(client, token)
    assert rows["GA_1"]["leaderboard_group"] == "leader"
    assert rows["GA_1"]["rank"] == 1          # 600 beats SA_1's 300 …
    assert rows["SA_1"]["rank"] == 2
    assert rows["BIG_AGENT"]["rank"] == 1     # … and neither competes with the agent
    assert rows["BIG_AGENT"]["leaderboard_group"] == "veteran"


async def test_a_leader_row_carries_their_own_number_and_their_teams(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "AG_X", upline="SA_1", tenure=True)
    await entry(seeded_db, agent_id="SA_1", gross_alp=300, sales=1)
    await entry(seeded_db, agent_id="AG_1", gross_alp=1000, sales=2)
    await entry(seeded_db, agent_id="AG_X", gross_alp=700, sales=3)

    rows = await board(client, token)
    sa = rows["SA_1"]
    assert sa["gross_alp"] == 300.0                 # their own
    assert sa["team_gross_alp"] == 1700.0           # AG_1 + AG_X, not themselves
    assert sa["team_sales"] == 5
    assert sa["team_size"] == 2


async def test_a_leader_who_entered_nothing_keeps_the_rollup_and_takes_no_rank(client, seeded_db):
    """The usual case: leaders rarely enter their own numbers."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, agent_id="AG_1", gross_alp=1000)
    rows = await board(client, token)
    assert rows["SA_1"]["gross_alp"] == 0
    assert rows["SA_1"]["rank"] is None
    assert rows["SA_1"]["team_gross_alp"] == 1000.0


async def test_a_leaders_rollup_follows_their_downline_past_their_own_office(client, seeded_db):
    """GA_2 and AG_2 sit in office AMP but report to MGA_1 in MCM."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await entry(seeded_db, agent_id="AG_2", gross_alp=800, office="AMP")
    rows = await board(client, token)
    assert rows["MGA_1"]["team_gross_alp"] == 800.0


# ---------------- ranking rule ----------------

async def test_nobody_with_nothing_produced_is_ranked(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    rows = await board(client, token)
    assert all(r["rank"] is None for r in rows.values())


async def test_rank_is_gross_alp_and_ignores_sales_count(client, seeded_db):
    """Same measure as the Platinum Wall: a big case outranks more small ones."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "VOLUME", upline="SA_1", tenure=False)
    await add_agent(seeded_db, "PREMIUM", upline="SA_1", tenure=False)
    await entry(seeded_db, agent_id="VOLUME", gross_alp=400, sales=9)
    await entry(seeded_db, agent_id="PREMIUM", gross_alp=1500, sales=1)
    rows = await board(client, token)
    assert rows["PREMIUM"]["rank"] == 1
    assert rows["VOLUME"]["rank"] == 2


# ---------------- what the two Codex findings were about ----------------

async def test_rank_is_per_office_so_a_standing_means_one_thing(client, seeded_db):
    """This list is not always one office: an MGA's downline reaches past
    theirs and MJ reads the agency. Pooling them would race an MCM veteran
    against an AMP one, and would give the same person a different rank
    depending on who was looking."""
    await add_agent(seeded_db, "MCM_VET", upline="SA_1", tenure=False, office="MCM")
    await add_agent(seeded_db, "AMP_VET", upline="GA_2", tenure=False, office="AMP")
    await entry(seeded_db, agent_id="MCM_VET", gross_alp=500, office="MCM")
    await entry(seeded_db, agent_id="AMP_VET", gross_alp=9000, office="AMP")

    # The MGA's downline spans both offices — and each is ranked on its own.
    mga = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    rows = await board(client, mga)
    assert rows["MCM_VET"]["rank"] == 1
    assert rows["AMP_VET"]["rank"] == 1

    # And the SA who runs MCM_VET sees the same number the MGA sees.
    mate = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    assert (await board(client, mate))["MCM_VET"]["rank"] == 1


async def test_a_removed_members_production_still_rolls_up(client, seeded_db):
    """Removing someone archives them and keeps their production and upline_id
    on purpose — their row still shows those numbers, so the leader's total
    printed above them has to include them."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "GONE", upline="SA_1", tenure=False)
    await seeded_db.agent_profiles.update_one({"agent_id": "GONE"}, {"$set": {"archived": True}})
    await entry(seeded_db, agent_id="GONE", gross_alp=600)

    rows = await board(client, token)
    assert rows["GONE"]["archived"] is True
    assert rows["GONE"]["gross_alp"] == 600.0        # the row shows it …
    assert rows["SA_1"]["team_gross_alp"] == 600.0   # … so the rollup counts it
    # Head count is who is on the team today: AG_1 alone, not the archived row.
    assert rows["SA_1"]["team_size"] == 1


# ---------------- archived people and the unset group ----------------

async def test_archived_person_never_lands_in_tenure_not_set(client, seeded_db):
    """A removed member's production stays on the board for its window
    ("history is history"), but TENURE NOT SET is a prompt to go record
    someone's tenure, and nobody sets tenure on a person who has been removed
    (owner, 2026-09-24). They file with the veterans instead."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await add_agent(seeded_db, "GONE_A", upline="SA_1", tenure=None)
    await seeded_db.agent_profiles.update_one({"agent_id": "GONE_A"}, {"$set": {"archived": True}})
    await add_agent(seeded_db, "UNSET_B", upline="SA_1", tenure=None)
    await entry(seeded_db, agent_id="GONE_A", gross_alp=700)
    await entry(seeded_db, agent_id="UNSET_B", gross_alp=300)

    rows = await board(client, token)
    assert rows["GONE_A"]["archived"] is True
    assert rows["GONE_A"]["leaderboard_group"] == "veteran"
    assert rows["GONE_A"]["rank"] == 1
    # The live person with no tenure still gets the nudge group, ranked alone.
    assert rows["UNSET_B"]["leaderboard_group"] == "unset"
    assert (rows["UNSET_B"]["rank"], rows["UNSET_B"]["rank_of"]) == (1, 1)
