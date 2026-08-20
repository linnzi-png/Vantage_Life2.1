"""Duplicate-profile detection and merge (/api/admin/duplicates,
/api/admin/merge-agents).

The bug these exist for: each import path spelled names its own way
("QARADAGHI, SNOOR" vs "Snoor Qaradaghi"), so exact-name lookups minted a
second profile for the same human. The person's downline then split across the
twins — their login saw only a fragment of their team, and that fragment read
$0 / "No Pulse" because the fragment's entries hung off the other twin.
"""
import pytest

import server
import war_import
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def seed_split_snoor(db):
    """Recreate the production shape: two profiles for the same SA, the login
    linked to one twin, the bulk of the downline hanging off the other."""
    await db.agent_profiles.insert_many([
        # The twin the login is linked to (proper-case, from the app sheet).
        {"agent_id": "SNOOR_LOGIN", "name": "Snoor Qaradaghi",
         "email": "snoor.qaradaghi@gmail.com", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MJ RGA"},
        # The twin the roster script created ("Last, First" spelling, no login).
        {"agent_id": "SNOOR_ROSTER", "name": "QARADAGHI, SNOOR",
         "email": "", "phone": "3137990462", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MJ RGA"},
        # Downline split across the twins.
        {"agent_id": "AG_NEW", "name": "Brian Kwende", "email": "kbrian1019@test.dev",
         "role": "level_1", "upline_id": "SNOOR_LOGIN", "office": "MJ RGA"},
        {"agent_id": "AG_OLD1", "name": "Shiko Qaradaghi", "email": "shiko@test.dev",
         "role": "level_1", "upline_id": "SNOOR_ROSTER", "office": "MJ RGA"},
        {"agent_id": "AG_OLD2", "name": "Basel Musaed", "email": "basel@test.dev",
         "role": "level_1", "upline_id": "SNOOR_ROSTER", "office": "MJ RGA"},
    ])


async def test_duplicates_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/admin/duplicates", headers=auth(token))
    assert r.status_code == 403
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "a", "remove_agent_id": "b"})
    assert r.status_code == 403


async def test_duplicates_groups_name_format_variants(client, seeded_db):
    await seed_split_snoor(seeded_db)
    await seeded_db.users.insert_one(
        {"user_id": "u_snoor", "email": "snoor.qaradaghi@gmail.com",
         "role": "level_2", "agent_id": "SNOOR_LOGIN"})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/duplicates", headers=auth(token))
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["reason"] == "same_name"
    assert {p["agent_id"] for p in g["profiles"]} == {"SNOOR_LOGIN", "SNOOR_ROSTER"}
    # Keeper suggestion: the profile a login is attached to.
    assert g["suggested_keep_agent_id"] == "SNOOR_LOGIN"
    by_id = {p["agent_id"]: p for p in g["profiles"]}
    assert by_id["SNOOR_ROSTER"]["downline_count"] == 2
    assert by_id["SNOOR_LOGIN"]["downline_count"] == 1
    assert by_id["SNOOR_LOGIN"]["logins_count"] == 1


async def test_duplicates_groups_shared_email(client, seeded_db):
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "T1", "name": "Tony Cacani", "email": "tony@test.dev",
         "role": "level_1", "upline_id": "GA_1", "office": "MJ RGA"},
        {"agent_id": "T2", "name": "Anthony Cacani", "email": "tony@test.dev",
         "role": "level_1", "upline_id": "GA_2", "office": "MJ RGA"},
    ])
    token = await admin_token(seeded_db)
    r = await client.get("/api/admin/duplicates", headers=auth(token))
    groups = r.json()["groups"]
    assert len(groups) == 1
    assert groups[0]["reason"] == "same_email"


async def test_merge_dry_run_writes_nothing(client, seeded_db):
    await seed_split_snoor(seeded_db)
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "SNOOR_LOGIN",
                                "remove_agent_id": "SNOOR_ROSTER", "dry_run": True})
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True
    assert body["children_repointed"] == 2
    assert "phone" in body["adopted_fields"]
    # Nothing changed.
    assert await seeded_db.agent_profiles.find_one({"agent_id": "SNOOR_ROSTER"}) is not None
    shiko = await seeded_db.agent_profiles.find_one({"agent_id": "AG_OLD1"})
    assert shiko["upline_id"] == "SNOOR_ROSTER"
    assert await seeded_db.audit_log.count_documents({}) == 0


async def test_merge_reunites_team_view(client, seeded_db):
    """The Snoor regression end-to-end: before the merge his login's Team tab
    misses the agents (and production) hanging off his duplicate; after the
    merge everyone and their numbers roll up under the login profile."""
    await seed_split_snoor(seeded_db)
    sd = server.current_sales_day_str()
    await seeded_db.production_entries.insert_many([
        {"entry_id": "e1", "agent_id": "AG_OLD1", "sales_day": sd, "office": "MJ RGA",
         "gross_alp": 1200.0, "net_alp": 1100.0, "sits": 3, "sales": 2, "n1": 0,
         "refs_obtained": 0, "submitted_at": server.now_utc()},
    ])
    snoor_token = await make_session(
        seeded_db, role="level_2", agent_id="SNOOR_LOGIN", email="snoor.qaradaghi@gmail.com")

    r = await client.get("/api/team", headers=auth(snoor_token))
    ids_before = {t["agent_id"] for t in r.json()["team"]}
    assert "AG_OLD1" not in ids_before  # the bug: half the team invisible

    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "SNOOR_LOGIN",
                                "remove_agent_id": "SNOOR_ROSTER"})
    assert r.status_code == 200
    assert r.json()["children_repointed"] == 2

    r = await client.get("/api/team", headers=auth(snoor_token))
    team = {t["agent_id"]: t for t in r.json()["team"]}
    assert {"SNOOR_LOGIN", "AG_NEW", "AG_OLD1", "AG_OLD2"} <= set(team)
    assert team["AG_OLD1"]["gross_alp"] == 1200.0  # production visible again

    # The duplicate is gone; the keeper adopted the blank fields.
    assert await seeded_db.agent_profiles.find_one({"agent_id": "SNOOR_ROSTER"}) is None
    kept = await seeded_db.agent_profiles.find_one({"agent_id": "SNOOR_LOGIN"})
    assert kept["phone"] == "3137990462"
    audit = await seeded_db.audit_log.find_one({"action": "merge_agents"})
    assert audit["agent_id"] == "SNOOR_LOGIN" and audit["merged_agent_id"] == "SNOOR_ROSTER"


async def test_merge_moves_entries_and_drops_war_restatements(client, seeded_db):
    await seed_split_snoor(seeded_db)
    await seeded_db.production_entries.insert_many([
        # Same sales_day on both twins, both WAR-imported → restated rows,
        # keeping both would double-count the day.
        {"entry_id": "k1", "agent_id": "SNOOR_LOGIN", "sales_day": "2026-08-13",
         "gross_alp": 900.0, "source": war_import.WAR_IMPORT_SOURCE},
        {"entry_id": "r1", "agent_id": "SNOOR_ROSTER", "sales_day": "2026-08-13",
         "gross_alp": 900.0, "source": war_import.WAR_IMPORT_SOURCE},
        # App-submitted entry on the duplicate → always moves.
        {"entry_id": "r2", "agent_id": "SNOOR_ROSTER", "sales_day": "2026-08-14",
         "gross_alp": 500.0},
    ])
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "SNOOR_LOGIN",
                                "remove_agent_id": "SNOOR_ROSTER"})
    body = r.json()
    assert body["entries_moved"] == 1
    assert body["entries_dropped_war_duplicates"] == 1
    assert await seeded_db.production_entries.find_one({"entry_id": "r1"}) is None
    moved = await seeded_db.production_entries.find_one({"entry_id": "r2"})
    assert moved["agent_id"] == "SNOOR_LOGIN"
    assert await seeded_db.production_entries.count_documents({"agent_id": "SNOOR_ROSTER"}) == 0


async def test_merge_relinks_login_and_takes_higher_tier(client, seeded_db):
    """Keeper may be the WAR-minted level_1 twin holding the downline while the
    login + real tier live on the other; the merge must not demote anyone."""
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "W_KEEP", "name": "Waleed Othman", "email": "",
         "role": "level_1", "upline_id": None, "office": "MJ RGA",
         "created_by_import": True},
        {"agent_id": "W_DROP", "name": "OTHMAN, WALEEDJASHOLIH",
         "email": "willothman.ao@test.dev", "role": "level_2", "io_role": "SA",
         "upline_id": "SA_1", "office": "MJ RGA"},
    ])
    await seeded_db.users.insert_one(
        {"user_id": "u_w", "email": "willothman.ao@test.dev",
         "role": "level_2", "agent_id": "W_DROP"})
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "W_KEEP", "remove_agent_id": "W_DROP"})
    assert r.status_code == 200
    body = r.json()
    assert body["final_role"] == "level_2"
    assert body["final_upline_id"] == "SA_1"  # adopted: keeper had none

    kept = await seeded_db.agent_profiles.find_one({"agent_id": "W_KEEP"})
    assert kept["role"] == "level_2"
    assert kept["upline_id"] == "SA_1"
    assert kept["email"] == "willothman.ao@test.dev"
    assert kept["io_role"] == "SA"
    assert kept["created_by_import"] is False
    u = await seeded_db.users.find_one({"user_id": "u_w"})
    assert u["agent_id"] == "W_KEEP" and u["role"] == "level_2"


async def test_merge_keeper_pointing_at_duplicate_adopts_its_upline(client, seeded_db):
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "D_KEEP", "name": "Sam Malushi", "email": "sam@test.dev",
         "role": "level_1", "upline_id": "D_DROP", "office": "MJ RGA"},
        {"agent_id": "D_DROP", "name": "MALUSHI, SAM", "email": "",
         "role": "level_1", "upline_id": "SA_1", "office": "MJ RGA"},
    ])
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "D_KEEP", "remove_agent_id": "D_DROP"})
    assert r.status_code == 200
    kept = await seeded_db.agent_profiles.find_one({"agent_id": "D_KEEP"})
    assert kept["upline_id"] == "SA_1"  # not left dangling at the deleted twin


async def test_merge_rejects_same_profile_and_unknown_ids(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "GA_1", "remove_agent_id": "GA_1"})
    assert r.status_code == 400
    r = await client.post("/api/admin/merge-agents", headers=auth(token),
                          json={"keep_agent_id": "GA_1", "remove_agent_id": "nope"})
    assert r.status_code == 404


async def test_find_profile_by_person_name_matches_format_variants(seeded_db):
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "SNOOR_ROSTER", "name": "QARADAGHI, SNOOR",
         "email": "snoor@test.dev", "role": "level_2", "upline_id": "GA_1",
         "office": "MJ RGA"})
    p = await server.find_profile_by_person_name("Snoor Qaradaghi")
    assert p and p["agent_id"] == "SNOOR_ROSTER"
    # Exact match still wins outright.
    p = await server.find_profile_by_person_name("QARADAGHI, SNOOR")
    assert p and p["agent_id"] == "SNOOR_ROSTER"
    assert await server.find_profile_by_person_name("Nobody Here") is None


async def test_find_profile_prefers_login_email_twin(seeded_db):
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "NO_EMAIL", "name": "Snoor Qaradaghi", "email": "",
         "role": "level_1", "upline_id": None, "office": "Unassigned"},
        {"agent_id": "WITH_EMAIL", "name": "QARADAGHI, SNOOR",
         "email": "snoor@test.dev", "role": "level_2", "upline_id": "GA_1",
         "office": "MJ RGA"},
    ])
    p = await server.find_profile_by_person_name("Qaradaghi Snoor")
    assert p and p["agent_id"] == "WITH_EMAIL"
