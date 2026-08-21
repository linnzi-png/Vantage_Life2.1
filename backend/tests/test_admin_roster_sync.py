"""Full roster-sheet sync (/api/admin/roster-sync[/fix]).

Owner request (2026-08-21): the committed 2026-08-20 app sheet is the source
of truth for tier, display title, tenure, and the upline structure. The sync
applies all of it in one step, with two deliberate exceptions verified here:
tiers are only ever raised (demotions are reported for review, never applied),
and Partner / Senior Partner titles are never overwritten.
"""
import pytest

import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def test_roster_sync_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/admin/roster-sync", headers=auth(token))
    assert r.status_code == 403
    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    assert r.status_code == 403


async def test_sync_raises_tier_sets_title_tenure_and_upline(client, seeded_db):
    """The Eddie Leon shape: a WAR-minted L1 'Agent' profile for someone the
    sheet shows as a GA. The sync must raise him to level_2, title him GA,
    record his Veteran tenure, and put him under Joseph Gojcaj — and re-sync
    his linked login's role per the sign-in invariant."""
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "GOJCAJ", "name": "Joseph Gojcaj", "email": "joseph@aopremier.com",
         "role": "level_4", "io_role": "RGA", "upline_id": None, "office": "Gojcaj RGA",
         "is_rookie": False},
        {"agent_id": "EDDIE", "name": "Eddie Leon", "email": "eddieleon0627@gmail.com",
         "role": "level_1", "upline_id": None, "office": "Gojcaj RGA",
         "created_by_import": True},
    ])
    await seeded_db.users.insert_one(
        {"user_id": "u_e", "email": "eddieleon0627@gmail.com",
         "role": "level_1", "agent_id": "EDDIE"})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/roster-sync", headers=auth(token))
    assert r.status_code == 200
    changes = {c["agent_id"]: c for c in r.json()["changes"]}
    e = changes["EDDIE"]
    assert e["role"] == "level_2"
    assert e["io_role"] == "GA"
    assert e["is_rookie"] is False  # sheet tenure: Vet
    assert e["upline_id"] == "GOJCAJ"
    # Preview writes nothing.
    prof = await seeded_db.agent_profiles.find_one({"agent_id": "EDDIE"})
    assert prof["role"] == "level_1" and prof["upline_id"] is None

    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    assert r.status_code == 200
    prof = await seeded_db.agent_profiles.find_one({"agent_id": "EDDIE"})
    assert prof["role"] == "level_2"
    assert prof["io_role"] == "GA"
    assert prof["is_rookie"] is False
    assert prof["upline_id"] == "GOJCAJ"
    login = await seeded_db.users.find_one({"user_id": "u_e"})
    assert login["role"] == "level_2"
    assert await seeded_db.audit_log.find_one({"action": "roster_sheet_sync"}) is not None


async def test_sync_never_demotes_and_reports_for_review(client, seeded_db):
    """MJ Aljahmi is level_4 by explicit owner decision; the sheet structurally
    shows him as an MGA. The sync must leave his tier alone and surface the
    difference for review — and never overwrite his Partner title."""
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "MJ", "name": "Mohamed Aljahmi", "email": "mj@aopremier.com",
         "role": "level_4", "io_role": "Partner", "upline_id": None,
         "office": "MJ RGA", "is_rookie": False})
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    review = {d["agent_id"]: d for d in body["demotions_review"]}
    assert "MJ" in review and review["MJ"]["sheet_position"] == "MGA"

    prof = await seeded_db.agent_profiles.find_one({"agent_id": "MJ"})
    assert prof["role"] == "level_4"      # tier untouched
    assert prof["io_role"] == "Partner"   # protected title untouched


async def test_sync_creates_missing_sheet_people_under_their_upline(client, seeded_db):
    """Someone on the sheet with no profile at all gets created with the
    sheet's tier, title, tenure, and upline — and a pre-existing pending login
    gets linked."""
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "SNOOR", "name": "Snoor Qaradaghi",
         "email": "snoor.qaradaghi@gmail.com", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MJ RGA", "is_rookie": False})
    await seeded_db.users.insert_one(
        {"user_id": "u_k", "email": "villa.ktech@gmail.com", "role": "pending",
         "agent_id": None})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/roster-sync", headers=auth(token))
    assert "Kimberly Villacampa" in r.json()["to_create"]

    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    assert "Kimberly Villacampa" in r.json()["created"]
    kim = await seeded_db.agent_profiles.find_one({"name": "Kimberly Villacampa"})
    assert kim is not None
    assert kim["upline_id"] == "SNOOR"       # sheet: SA column = Snoor Qaradaghi
    assert kim["role"] == "level_1"
    assert kim["office"] == "MJ RGA"         # inherited from the upline
    login = await seeded_db.users.find_one({"user_id": "u_k"})
    assert login["agent_id"] == kim["agent_id"] and login["role"] == "level_1"


async def test_sync_reports_app_only_people_untouched(client, seeded_db):
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "GONE", "name": "Former Agent", "email": "",
         "role": "level_1", "upline_id": "GA_1", "office": "MJ RGA"})
    token = await admin_token(seeded_db)
    r = await client.get("/api/admin/roster-sync", headers=auth(token))
    names = {p["agent_id"] for p in r.json()["not_on_sheet"]}
    assert "GONE" in names
    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    prof = await seeded_db.agent_profiles.find_one({"agent_id": "GONE"})
    assert prof["role"] == "level_1" and prof["upline_id"] == "GA_1"


async def test_sync_corrects_wrong_upline_to_sheet(client, seeded_db):
    """Not just orphans: a profile linked under the WRONG upline gets
    re-pointed to the sheet's — Basel Musaed reports to Ali Eltanoukhi per the
    current sheet, wherever the app had him before."""
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "SNOOR", "name": "Snoor Qaradaghi",
         "email": "snoor.qaradaghi@gmail.com", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MJ RGA", "is_rookie": False},
        {"agent_id": "ELT", "name": "Ali Eltanoukhi", "email": "aeltanoukhi@gmail.com",
         "role": "level_2", "io_role": "SA", "upline_id": "GA_1", "office": "MJ RGA",
         "is_rookie": False},
        {"agent_id": "BASEL", "name": "Basel Musaed", "email": "baselmusaed3@gmail.com",
         "role": "level_1", "io_role": "Agent", "upline_id": "SNOOR",
         "office": "MJ RGA", "is_rookie": False},
    ])
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/roster-sync/fix", headers=auth(token))
    assert r.status_code == 200
    basel = await seeded_db.agent_profiles.find_one({"agent_id": "BASEL"})
    assert basel["upline_id"] == "ELT"
