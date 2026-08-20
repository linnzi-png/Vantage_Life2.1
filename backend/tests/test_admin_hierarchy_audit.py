"""Bulk upline repair (/api/admin/hierarchy-audit[/fix]).

Production carried ~150 agents with no upline — every one invisible in their
upline's Team tab, because team rollups BFS DOWN agent_profiles.upline_id.
These routes re-link orphans from the hierarchy the committed roster scripts
record (import_roster.py / import_missing_roster.py), tolerant of the
name-format drift ("QARADAGHI, SNOOR" vs "Snoor Qaradaghi") that split the
data in the first place.
"""
import pytest

import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def seed_orphaned_snoor_team(db):
    """Snoor exists (proper-case spelling, has the login email) and his agents
    exist as WAR-import orphans with no upline — the production shape."""
    await db.agent_profiles.insert_many([
        {"agent_id": "SNOOR", "name": "Snoor Qaradaghi",
         "email": "snoor.qaradaghi@gmail.com", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MJ RGA"},
        # Sheet rows list "QARADAGHI, SNOOR" as their upline; the orphans
        # themselves carry the WAR spelling of their own names.
        {"agent_id": "SHIKO", "name": "Shiko Qaradaghi", "email": "",
         "role": "level_1", "upline_id": None, "office": "MJ RGA",
         "created_by_import": True},
        {"agent_id": "BASEL", "name": "MUSAED, BASEL", "email": "",
         "role": "level_1", "upline_id": None, "office": "MJ RGA",
         "created_by_import": True},
        # Dangling upline counts as orphaned too.
        {"agent_id": "MAHER", "name": "Maher Altairi", "email": "",
         "role": "level_1", "upline_id": "agent_deleted", "office": "MJ RGA"},
        # Not on any committed sheet — must stay for manual assignment.
        {"agent_id": "MYSTERY", "name": "Totally Unknown", "email": "",
         "role": "level_1", "upline_id": None, "office": "MJ RGA"},
    ])


async def test_hierarchy_audit_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/admin/hierarchy-audit", headers=auth(token))
    assert r.status_code == 403
    r = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    assert r.status_code == 403


async def test_audit_proposes_sheet_uplines_without_writing(client, seeded_db):
    await seed_orphaned_snoor_team(seeded_db)
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/hierarchy-audit", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    proposals = {p["agent_id"]: p for p in body["proposals"]}
    # Shiko + Basel report to Snoor on the committed sheet; both name formats
    # ("Shiko Qaradaghi" / "MUSAED, BASEL") must resolve.
    assert proposals["SHIKO"]["upline_agent_id"] == "SNOOR"
    assert proposals["BASEL"]["upline_agent_id"] == "SNOOR"
    # Unknown person is reported, not guessed at.
    unresolved = {u["agent_id"]: u for u in body["unresolved"]}
    assert unresolved["MYSTERY"]["reason"] == "not_on_sheet"
    # Dry-run: nothing written.
    shiko = await seeded_db.agent_profiles.find_one({"agent_id": "SHIKO"})
    assert shiko["upline_id"] is None


async def test_fix_relinks_and_restores_team_view(client, seeded_db):
    """End-to-end on the reported bug: Snoor's Team tab misses his orphaned
    agents entirely; after the bulk fix they (and their production) appear."""
    await seed_orphaned_snoor_team(seeded_db)
    sd = server.current_sales_day_str()
    await seeded_db.production_entries.insert_one(
        {"entry_id": "e1", "agent_id": "SHIKO", "sales_day": sd, "office": "MJ RGA",
         "gross_alp": 800.0, "net_alp": 700.0, "sits": 2, "sales": 1, "n1": 0,
         "refs_obtained": 0, "submitted_at": server.now_utc()})
    snoor_token = await make_session(
        seeded_db, role="level_2", agent_id="SNOOR", email="snoor.qaradaghi@gmail.com")

    r = await client.get("/api/team", headers=auth(snoor_token))
    assert "SHIKO" not in {t["agent_id"] for t in r.json()["team"]}

    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    assert r.status_code == 200
    applied = {p["agent_id"] for p in r.json()["applied"]}
    assert {"SHIKO", "BASEL"} <= applied
    assert "MYSTERY" not in applied

    r = await client.get("/api/team", headers=auth(snoor_token))
    team = {t["agent_id"]: t for t in r.json()["team"]}
    assert {"SHIKO", "BASEL"} <= set(team)
    assert team["SHIKO"]["gross_alp"] == 800.0

    audit = await seeded_db.audit_log.find_one({"action": "hierarchy_bulk_relink"})
    assert audit is not None and audit["applied_count"] >= 2


async def test_fix_is_idempotent(client, seeded_db):
    await seed_orphaned_snoor_team(seeded_db)
    token = await admin_token(seeded_db)
    r1 = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    first = len(r1.json()["applied"])
    assert first >= 2
    r2 = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    assert len(r2.json()["applied"]) == 0  # already linked agents are left alone


async def test_orphan_duplicate_of_linked_profile_is_merged(client, seeded_db):
    """The Waleed shape: the roster twin is linked under an SA, while the
    WAR-minted orphan twin carries the downline and entries. The bulk fix must
    merge the twins (keeper = the one with the login), not report not_on_sheet."""
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "W_LINKED", "name": "OTHMAN, WALEEDJASHOLIH",  # roster mashed the name — twins match by email
         "email": "willothman.ao@test.dev", "role": "level_1",
         "upline_id": "SA_1", "office": "MJ RGA"},
        {"agent_id": "W_ORPHAN", "name": "Waleed Othman", "email": "willothman.ao@test.dev",
         "role": "level_1", "upline_id": None, "office": "MJ RGA",
         "created_by_import": True},
        # A child hanging off the orphan twin must end up under the keeper.
        {"agent_id": "W_CHILD", "name": "Some Child", "email": "",
         "role": "level_1", "upline_id": "W_ORPHAN", "office": "MJ RGA"},
    ])
    await seeded_db.users.insert_one(
        {"user_id": "u_w", "email": "willothman.ao@test.dev",
         "role": "level_1", "agent_id": "W_LINKED"})
    await seeded_db.production_entries.insert_one(
        {"entry_id": "we1", "agent_id": "W_ORPHAN", "sales_day": "2026-08-14",
         "gross_alp": 400.0})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/hierarchy-audit", headers=auth(token))
    body = r.json()
    merges = {m["remove_agent_id"]: m for m in body["merges"]}
    assert "W_ORPHAN" in merges
    assert merges["W_ORPHAN"]["keep_agent_id"] == "W_LINKED"
    assert "W_ORPHAN" not in {u["agent_id"] for u in body["unresolved"]}

    r = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    assert r.status_code == 200
    assert any(m["keep_agent_id"] == "W_LINKED" and m["remove_agent_id"] == "W_ORPHAN"
               for m in r.json()["merged"])

    # One profile left, still linked; child and entry moved to it.
    assert await seeded_db.agent_profiles.find_one({"agent_id": "W_ORPHAN"}) is None
    kept = await seeded_db.agent_profiles.find_one({"agent_id": "W_LINKED"})
    assert kept["upline_id"] == "SA_1"
    child = await seeded_db.agent_profiles.find_one({"agent_id": "W_CHILD"})
    assert child["upline_id"] == "W_LINKED"
    entry = await seeded_db.production_entries.find_one({"entry_id": "we1"})
    assert entry["agent_id"] == "W_LINKED"


async def test_orphan_twin_with_login_kept_and_adopts_linked_upline(client, seeded_db):
    """Reverse shape: the orphan twin holds the login (so it must be kept) and
    the linked twin holds the upline — the keeper adopts it during the merge."""
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "K_ORPHAN", "name": "Husein Ghasham",
         "email": "ghashuss@test.dev", "role": "level_1", "upline_id": None,
         "office": "MJ RGA"},
        {"agent_id": "K_LINKED", "name": "GHASHAM, HUSEIN", "email": "",
         "role": "level_1", "upline_id": "SA_1", "office": "MJ RGA"},
    ])
    await seeded_db.users.insert_one(
        {"user_id": "u_h", "email": "ghashuss@test.dev",
         "role": "level_1", "agent_id": "K_ORPHAN"})
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/hierarchy-audit/fix", headers=auth(token))
    assert r.status_code == 200
    merged = r.json()["merged"]
    assert any(m["keep_agent_id"] == "K_ORPHAN" and m["remove_agent_id"] == "K_LINKED"
               for m in merged)
    kept = await seeded_db.agent_profiles.find_one({"agent_id": "K_ORPHAN"})
    assert kept["upline_id"] == "SA_1"  # adopted from the merged twin
    assert await seeded_db.agent_profiles.find_one({"agent_id": "K_LINKED"}) is None
