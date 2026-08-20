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
