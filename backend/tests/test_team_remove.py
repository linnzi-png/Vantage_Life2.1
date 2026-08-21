"""Remove-from-team (archive + detach), downline cascade, GA+ reassign, and
admin restore — the owner's decision tree:

  - remove: anyone in your own downline strictly below your tier (so GA cannot
    remove SA, RGA cannot remove RGA); admin removes anyone but themselves
  - cascade: the removed leader's direct reports go to their former upline
  - reassign afterwards: GA, MGA, RGA (not SA — a title-only distinction at
    tier 2); admin anywhere
  - nothing is deleted: history keeps aggregating, login drops to pending
"""
import pytest

import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def profile(db, agent_id):
    return await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0})


def remove(agent_id, **extra) -> dict:
    return {"agent_id": agent_id, **extra}


# ---------------- permission matrix ----------------

async def test_sa_can_remove_their_agent(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("AG_1"))
    assert r.status_code == 200
    assert (await profile(seeded_db, "AG_1"))["archived"] is True


async def test_ga_cannot_remove_sa_same_tier(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("SA_1"))
    assert r.status_code == 403
    assert not (await profile(seeded_db, "SA_1")).get("archived")


async def test_mga_can_remove_ga(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("GA_2"))
    assert r.status_code == 200


async def test_rga_can_remove_mga_but_not_rga(client, seeded_db):
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
         "role": "level_4", "upline_id": "RGA_1", "office": "MCM"})
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("MGA_1"))
    assert r.status_code == 200
    # Same tier, even for RGA: admin-only (owner decision #2).
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("RGA_2"))
    assert r.status_code == 403


async def test_admin_can_remove_rga(client, seeded_db):
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
         "role": "level_4", "upline_id": "RGA_1", "office": "MCM"})
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("RGA_2"))
    assert r.status_code == 200


async def test_level_1_cannot_remove(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("AG_2"))
    assert r.status_code == 403


async def test_cannot_remove_outside_own_downline(client, seeded_db):
    # GA_2's branch holds AG_2 only; AG_1 belongs to GA_1's branch.
    token = await make_session(seeded_db, role="level_2", agent_id="GA_2", email="ga2@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("AG_1"))
    assert r.status_code == 403


async def test_cannot_remove_self(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("MGA_1"))
    assert r.status_code == 400


# ---------------- cascade ----------------

async def test_cascade_reassigns_downline_to_former_upline(client, seeded_db):
    # MGA_1 removes GA_1: GA_1's direct report SA_1 moves under MGA_1 (GA_1's
    # former upline); AG_1 stays under SA_1 — subtrees move intact.
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("GA_1"))
    assert r.status_code == 200
    assert r.json()["plan"]["children_count"] == 1
    ga1 = await profile(seeded_db, "GA_1")
    assert ga1["archived"] is True
    assert ga1["former_upline_id"] == "MGA_1"
    assert ga1["upline_id"] == "MGA_1"  # kept: history stays in the hierarchy walk
    assert (await profile(seeded_db, "SA_1"))["upline_id"] == "MGA_1"
    assert (await profile(seeded_db, "AG_1"))["upline_id"] == "SA_1"


async def test_dry_run_changes_nothing(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token),
                          json=remove("GA_1", dry_run=True))
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["plan"]["children_count"] == 1
    assert body["plan"]["destination_upline"]["agent_id"] == "MGA_1"
    assert not (await profile(seeded_db, "GA_1")).get("archived")
    assert (await profile(seeded_db, "SA_1"))["upline_id"] == "GA_1"


async def test_removing_root_requires_promoting_a_direct_report(client, seeded_db):
    # RGA_1 has no upline, so the cascade has nowhere to go: the admin must
    # promote one of RGA_1's direct reports into their spot (owner decision #1).
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
         "role": "level_4", "upline_id": "RGA_1", "office": "MCM"})
    token = await admin_token(seeded_db)
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("RGA_1"))
    assert r.status_code == 400  # no destination chosen

    # Promoting MGA_1 (level_3) to the top is refused — only an RGA may have no upline.
    r = await client.post("/api/team/remove-person", headers=auth(token),
                          json=remove("RGA_1", destination_upline_agent_id="MGA_1"))
    assert r.status_code == 400

    r = await client.post("/api/team/remove-person", headers=auth(token),
                          json=remove("RGA_1", destination_upline_agent_id="RGA_2"))
    assert r.status_code == 200
    assert (await profile(seeded_db, "RGA_2"))["upline_id"] is None  # promoted to root
    assert (await profile(seeded_db, "MGA_1"))["upline_id"] == "RGA_2"  # sibling follows


# ---------------- what removal means ----------------

async def test_removed_login_drops_to_pending_now_and_on_next_signin(client, seeded_db):
    await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(token), json=remove("AG_1"))
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "ag1@test.dev"})
    assert u["role"] == "pending" and u["agent_id"] is None
    # A fresh sign-in must not re-link the archived profile.
    fresh = await server.upsert_user_and_session("ag1@test.dev", "Agent One", None, "st_fresh")
    assert fresh["role"] == "pending" and fresh["agent_id"] is None


async def test_history_stays_on_team_board_but_roster_hides_them(client, seeded_db):
    await seeded_db.production_entries.insert_one({
        "entry_id": "e1", "agent_id": "AG_1", "sales_day": server.current_sales_day_str(),
        "submitted_at": server.now_utc(), "gross_alp": 1000, "net_alp": 800,
        "sits": 2, "sales": 1, "n1": 0, "refs_obtained": 0,
    })
    sa = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/remove-person", headers=auth(sa), json=remove("AG_1"))
    assert r.status_code == 200

    mga = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.get("/api/team?period=daily", headers=auth(mga))
    rows = {x["agent_id"]: x for x in r.json()["team"]}
    # Already-logged production stays on the board, flagged archived...
    assert rows["AG_1"]["archived"] is True
    assert rows["AG_1"]["gross_alp"] == 1000
    # ...and archived members never appear as lingering no-pulse rows.
    weekly = await client.get("/api/team?period=weekly", headers=auth(mga))
    assert all(not (x["archived"] and x["alerts"] == ["no_pulse"]) for x in weekly.json()["team"])

    directory = await client.get("/api/agents/directory", headers=auth(mga))
    assert "AG_1" not in {a["agent_id"] for a in directory.json()["agents"]}

    admin = await admin_token(seeded_db)
    people = (await client.get("/api/admin/people", headers=auth(admin))).json()
    assert "AG_1" not in {p["agent_id"] for p in people["people"]}
    assert "AG_1" in {p["agent_id"] for p in people["archived"]}
    assert people["summary"]["roster"] == 6  # 7 seeded minus the removed agent


async def test_no_new_entries_for_removed_agent(client, seeded_db):
    sa = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    await client.post("/api/team/remove-person", headers=auth(sa), json=remove("AG_1"))
    r = await client.post("/api/pulse", headers=auth(sa),
                          json={"target_agent_id": "AG_1", "gross_alp": 100, "sits": 1, "sales": 1})
    assert r.status_code == 400


async def test_add_person_with_archived_email_says_restore(client, seeded_db):
    sa = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    await client.post("/api/team/remove-person", headers=auth(sa), json=remove("AG_1"))
    admin = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(admin),
                          json={"name": "Agent One Again", "email": "ag1@test.dev",
                                "role": "level_1", "is_rookie": True, "upline_agent_id": "GA_1"})
    assert r.status_code == 409
    assert "restore" in r.json()["detail"].lower()


# ---------------- reassign ----------------

async def test_sa_title_cannot_reassign(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "SA_1"})
    assert r.status_code == 403


async def test_ga_can_reassign_within_downline(client, seeded_db):
    # GA_1 (no SA title) pulls AG_1 from under SA_1 to directly under themselves.
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "GA_1"})
    assert r.status_code == 200
    assert (await profile(seeded_db, "AG_1"))["upline_id"] == "GA_1"


async def test_ga_cannot_reassign_same_tier_or_outside(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    # SA_1 is GA_1's downline but the same tier.
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "SA_1", "new_upline_agent_id": "GA_1"})
    assert r.status_code == 403
    # AG_2 is in a sibling branch.
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_2", "new_upline_agent_id": "GA_1"})
    assert r.status_code == 403
    # New upline outside GA_1's downline.
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_1", "new_upline_agent_id": "GA_2"})
    assert r.status_code == 403


async def test_mga_reassigns_across_branches_and_cycles_blocked(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/reassign", headers=auth(token),
                          json={"agent_id": "AG_2", "new_upline_agent_id": "GA_1"})
    assert r.status_code == 200
    assert (await profile(seeded_db, "AG_2"))["upline_id"] == "GA_1"
    # Admin path still refuses loops: GA_1 under their own descendant AG_1.
    admin = await admin_token(seeded_db)
    r = await client.post("/api/team/reassign", headers=auth(admin),
                          json={"agent_id": "GA_1", "new_upline_agent_id": "AG_1"})
    assert r.status_code == 400


# ---------------- restore ----------------

async def test_admin_restores_under_new_upline_and_relinks_login(client, seeded_db):
    await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    sa = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    await client.post("/api/team/remove-person", headers=auth(sa), json=remove("AG_1"))

    admin = await admin_token(seeded_db)
    # Restoring a non-RGA needs an upline.
    r = await client.post("/api/admin/unarchive-person", headers=auth(admin),
                          json={"agent_id": "AG_1"})
    assert r.status_code == 400
    r = await client.post("/api/admin/unarchive-person", headers=auth(admin),
                          json={"agent_id": "AG_1", "upline_agent_id": "GA_2"})
    assert r.status_code == 200
    ag1 = await profile(seeded_db, "AG_1")
    assert ag1["archived"] is False and ag1["upline_id"] == "GA_2"
    u = await seeded_db.users.find_one({"email": "ag1@test.dev"})
    assert u["role"] == "level_1" and u["agent_id"] == "AG_1"


async def test_restore_rejects_active_person_and_archived_upline(client, seeded_db):
    sa = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    await client.post("/api/team/remove-person", headers=auth(sa), json=remove("AG_1"))
    admin = await admin_token(seeded_db)
    r = await client.post("/api/admin/unarchive-person", headers=auth(admin),
                          json={"agent_id": "AG_2", "upline_agent_id": "GA_2"})
    assert r.status_code == 400  # not archived
    r = await client.post("/api/admin/unarchive-person", headers=auth(admin),
                          json={"agent_id": "AG_1", "upline_agent_id": "AG_1"})
    assert r.status_code == 404  # archived upline is not a valid destination
