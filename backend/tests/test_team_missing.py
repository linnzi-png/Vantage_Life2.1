"""Missing Numbers per team per night (owner, 2026-09-19): downline-scoped for
leaders, whole company for level_4, grouped under the nearest level_2."""
from datetime import date, timedelta

import server
from conftest import make_session, auth


async def entry(db, *, agent_id, sales_day):
    await db.production_entries.insert_one({
        "entry_id": f"pe_{agent_id}_{sales_day}", "agent_id": agent_id, "sales_day": sales_day,
        "sets": 1, "sits": 1, "sales": 1, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 100.0, "net_alp": 100.0,
    })


def by_leader(day):
    return {(t["leader"] or {}).get("agent_id"): t for t in day["teams"]}


async def test_grouped_by_nearest_level2_and_scoped_to_downline(client, seeded_db):
    today = server.current_sales_day_str()
    await entry(seeded_db, agent_id="AG_1", sales_day=today)  # AG_1 submitted tonight
    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.get("/api/team/missing?days=2", headers=auth(ga1))
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "downline"
    assert [d["sales_day"] for d in body["days"]] == [today, (date.fromisoformat(today) - timedelta(days=1)).isoformat()]

    tonight = by_leader(body["days"][0])
    # GA_1's downline is SA_1 and AG_1. SA_1 (level_2) heads their own section;
    # AG_1 submitted, so SA_1's section lists only SA_1. GA_2's branch is not
    # GA_1's to see.
    assert set(tonight) == {"SA_1"}
    assert [p["agent_id"] for p in tonight["SA_1"]["missing"]] == ["SA_1"]
    assert tonight["SA_1"]["team_size"] == 2
    yesterday = by_leader(body["days"][1])
    assert [p["agent_id"] for p in yesterday["SA_1"]["missing"]] == ["AG_1", "SA_1"]
    assert body["days"][1]["total_missing"] == 2


async def test_level4_sees_every_team_and_agents_under_an_mga_file_under_it(client, seeded_db):
    # A producer reporting straight to the MGA with no SA/GA between.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_3", "name": "Agent Three", "email": "ag3@test.dev",
        "role": "level_1", "upline_id": "MGA_1", "office": "MCM",
    })
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    body = (await client.get("/api/team/missing?days=1", headers=auth(rga))).json()
    assert body["scope"] == "company"
    tonight = by_leader(body["days"][0])
    assert set(tonight) == {"GA_1", "GA_2", "SA_1", "MGA_1"}
    assert [p["agent_id"] for p in tonight["MGA_1"]["missing"]] == ["AG_3"]
    assert [p["agent_id"] for p in tonight["GA_2"]["missing"]] == ["AG_2", "GA_2"]
    assert tonight["MGA_1"]["leader"]["role"] == "level_3"


async def test_archived_and_non_producing_are_never_missing(client, seeded_db):
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    await seeded_db.agent_profiles.update_one({"agent_id": "SA_1"}, {"$set": {"non_producing": True}})
    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    body = (await client.get("/api/team/missing?days=1", headers=auth(ga1))).json()
    assert body["days"][0]["teams"] == []
    assert body["days"][0]["total_missing"] == 0


async def test_days_is_clamped_and_level1_is_refused(client, seeded_db):
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    body = (await client.get("/api/team/missing?days=99", headers=auth(rga))).json()
    assert len(body["days"]) == server.MISSING_DAYS_MAX
    ag = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/team/missing", headers=auth(ag))
    assert r.status_code == 403


async def admin_session(db, *, role, agent_id, email):
    token = await make_session(db, role=role, agent_id=agent_id, email=email)
    await db.users.update_one({"email": email}, {"$set": {"is_admin": True}})
    return token


async def test_in_house_admin_below_level4_reads_every_team_in_the_admin_view(client, seeded_db):
    """Afnan (2026-09-25): an SA with the in-house admin grant saw MISSING
    TONIGHT · 135 on the Team tab and "everyone submitted" on Missing
    Numbers, because this route read her own downline while the Team tab
    read the company. The admin view reads the company here too."""
    afnan = await admin_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    body = (await client.get("/api/team/missing?days=1", headers=auth(afnan))).json()
    assert body["scope"] == "company"
    tonight = by_leader(body["days"][0])
    assert "GA_2" in tonight  # a branch nowhere near her own
    assert [p["agent_id"] for p in tonight["GA_2"]["missing"]] == ["AG_2", "GA_2"]
    assert "SA_1" not in [p["agent_id"] for t in tonight.values() for p in t["missing"]]  # never herself

    # Agent view: her own downline, as before the grant.
    await client.post("/api/me/view-mode", json={"view_mode": "own"}, headers=auth(afnan))
    body = (await client.get("/api/team/missing?days=1", headers=auth(afnan))).json()
    assert body["scope"] == "downline"
    tonight = by_leader(body["days"][0])
    assert set(tonight) == {"SA_1"}
    assert [p["agent_id"] for p in tonight["SA_1"]["missing"]] == ["AG_1"]


async def test_in_house_admin_enters_numbers_outside_her_own_downline(client, seeded_db):
    """Missing Numbers exists to enter on people's behalf, so the admin grant
    enters agency-wide, in either view — the switch is not a permission."""
    afnan = await admin_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    today = server.current_sales_day_str()
    payload = {"target_agent_id": "AG_2", "sales_day": today, "sets": 2, "sits": 1, "sales": 1,
               "ots_sits": 0, "ots_sales": 0, "n1": 0, "refs_obtained": 0, "ref_sits": 0,
               "ref_sales": 0, "pos_sits": 0, "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
               "gross_alp": 500.0}
    r = await client.post("/api/pulse", json=payload, headers=auth(afnan))
    assert r.status_code == 200, r.text
    assert await seeded_db.production_entries.find_one({"agent_id": "AG_2", "sales_day": today})

    # A leader with no grant is still refused outside their downline.
    ga2 = await make_session(seeded_db, role="level_2", agent_id="GA_2", email="ga2@test.dev")
    r = await client.post("/api/pulse", json={**payload, "target_agent_id": "AG_1"}, headers=auth(ga2))
    assert r.status_code == 403
