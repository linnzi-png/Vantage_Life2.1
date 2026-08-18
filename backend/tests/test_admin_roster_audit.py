"""Admin roster-audit endpoints (/api/admin/roster-audit[/fix]): require_admin
gating, dry-run safety, and that fix applies the CLI module's corrections.

The endpoints run the sync CLI audit (audit_roster_emails.py) in a worker
thread over a sync client, so the audited data lives in a mongomock db swapped
in for server._sync_roster_db — auth/session checks still go through the async
mock from conftest.
"""
import mongomock
import pytest

import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


@pytest.fixture()
def sync_db(monkeypatch):
    db = mongomock.MongoClient()["vantagelife_test"]
    monkeypatch.setattr(server, "_sync_roster_db", lambda: db)
    return db


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def test_roster_audit_requires_admin(client, seeded_db, sync_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/admin/roster-audit", headers=auth(token))
    assert r.status_code == 403
    r = await client.post("/api/admin/roster-audit/fix", headers=auth(token))
    assert r.status_code == 403


async def test_dry_run_reports_without_writing(client, seeded_db, sync_db):
    sync_db.agent_profiles.insert_one(
        {"agent_id": "A1", "name": "Landy Sitto",
         "email": "landy.sitto.ali@gmail.com", "role": "level_2"})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/roster-audit", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["fixed"] is False
    assert body["roster_size"] == 158  # 159 sheet rows minus the owner-excluded Annie Ransom
    assert {"name": "Landy Sitto", "db_email": "landy.sitto.ali@gmail.com",
            "sheet_email": "landy.sitto.ail@gmail.com"} in body["mismatches"]
    # dry run: nothing written
    assert sync_db.agent_profiles.find_one({"agent_id": "A1"})["email"] == "landy.sitto.ali@gmail.com"
    assert sync_db.audit_log.count_documents({}) == 0


async def test_fix_applies_corrections_and_attributes_admin(client, seeded_db, sync_db):
    sync_db.agent_profiles.insert_one(
        {"agent_id": "A1", "name": "Landy Sitto",
         "email": "landy.sitto.ali@gmail.com", "role": "level_2"})
    # She already signed in with the real address and is stuck on pending:
    sync_db.users.insert_one({"user_id": "u1", "email": "landy.sitto.ail@gmail.com",
                              "role": "pending", "agent_id": None})
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/roster-audit/fix", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["fixed"] is True and len(body["mismatches"]) == 1
    assert sync_db.agent_profiles.find_one({"agent_id": "A1"})["email"] == "landy.sitto.ail@gmail.com"
    linked = sync_db.users.find_one({"user_id": "u1"})
    assert linked["role"] == "level_2" and linked["agent_id"] == "A1"
    log = sync_db.audit_log.find_one({"action": "sync_email"})
    assert log["changed_by"].startswith("admin:user_")


async def test_report_shape_missing_and_extra(client, seeded_db, sync_db):
    sync_db.agent_profiles.insert_one(
        {"agent_id": "A9", "name": "Tyler Grant",
         "email": "tylergrant@cmail.live", "role": "level_1"})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/roster-audit", headers=auth(token))
    body = r.json()
    # Empty-ish DB: nearly the whole sheet is missing, demo seed shows as extra.
    assert len(body["missing"]) >= 150
    assert body["missing"][0].keys() == {"app_id", "name", "email"}
    assert {"name": "Tyler Grant", "email": "tylergrant@cmail.live",
            "role": "level_1"} in body["extra"]
    assert body["ok"] == 0 and body["ambiguous"] == [] and body["conflicts"] == []


async def test_report_surfaces_conflicts(client, seeded_db, sync_db):
    sync_db.agent_profiles.insert_one(
        {"agent_id": "A1", "name": "Timothy Noe", "email": "", "role": "level_1"})
    sync_db.agent_profiles.insert_one(
        {"agent_id": "A2", "name": "Timothy Noe Test",
         "email": "noetimothy1114@gmail.com", "role": "level_4"})
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/roster-audit/fix", headers=auth(token))
    body = r.json()
    conflict = next(c for c in body["conflicts"] if c["name"] == "Timothy Noe")
    assert conflict["holders"] == [
        {"name": "Timothy Noe Test", "role": "level_4", "agent_id": "A2"}]
    # even on the fix route, a conflicted email is never written
    assert sync_db.agent_profiles.find_one({"agent_id": "A1"})["email"] == ""
