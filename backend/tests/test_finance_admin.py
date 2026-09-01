"""Financial Admin role (finance_admin): a standalone back-office role outside
the level_1..level_4 ladder. Covers require_finance_admin-style gating, the
RGA-untouchable guard on every roster mutation, read-only full-office scope,
and that it never gets a production identity (no Pulse, no Platinum Wall)."""
import io

import openpyxl

import server
from conftest import auth, make_session

FINANCE_EMAIL = "fa1@test.dev"


async def finance_admin_session(db, *, agent_id: str = "FA_1") -> str:
    await db.agent_profiles.insert_one({
        "agent_id": agent_id, "name": "Finance One", "email": FINANCE_EMAIL,
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    return await make_session(db, role="finance_admin", agent_id=agent_id, email=FINANCE_EMAIL)


async def rga_session(db, *, agent_id: str = "RGA_1", email: str = "rga1@test.dev") -> str:
    """A true RGA who also holds the is_admin flag — /admin/* roster-CRUD
    routes are gated by is_admin (a separate flag from the level_N tier; see
    require_admin), so a bare level_4 without it cannot reach them at all."""
    token = await make_session(db, role="level_4", agent_id=agent_id, email=email)
    await db.users.update_one({"email": email}, {"$set": {"is_admin": True}})
    return token


# ---------------- visible_agent_ids ----------------

async def test_finance_admin_gets_full_office_read_scope(seeded_db):
    ids = await server.visible_agent_ids({"role": "finance_admin", "agent_id": "FA_1"})
    assert ids is None  # same as level_4: unrestricted read


# ---------------- no production identity ----------------

async def test_finance_admin_cannot_reach_pulse_entry(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/pulse", headers=auth(token), json={
        "sets": 1, "sits": 1, "sales": 1, "ots_sits": 0, "ots_sales": 0, "n1": 0,
        "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0,
        "pos_sales": 0, "vet_sits": 0, "vet_sales": 0, "gross_alp": 100,
    })
    assert r.status_code == 403


async def test_finance_admin_fails_require_agent(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/team", headers=auth(token))  # require_level(2) -> require_agent
    assert r.status_code == 403


# ---------------- read scope: dashboards / vault ----------------

async def test_finance_admin_reads_dashboard_summary(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/dashboard/summary", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["is_full_agency"] is True


async def test_finance_admin_reads_vault_weeks(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/vault/weeks", headers=auth(token))
    assert r.status_code == 200


async def test_plain_agent_still_rejected_from_vault(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/vault/weeks", headers=auth(token))
    assert r.status_code == 403


# ---------------- roster mutations: level_1..level_3 only ----------------

async def test_finance_admin_can_add_level_1_person(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json={
        "name": "New Agent", "email": "newagent@test.dev", "office": "MCM",
        "role": "level_1", "upline_agent_id": "SA_1", "is_rookie": True,
    })
    assert r.status_code == 200


async def test_finance_admin_cannot_add_rga(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json={
        "name": "New RGA", "email": "newrga@test.dev", "office": "MCM",
        "role": "level_4", "is_rookie": True,
    })
    assert r.status_code == 403


async def test_finance_admin_cannot_add_another_finance_admin(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json={
        "name": "New FA", "email": "newfa@test.dev", "office": "",
        "role": "finance_admin",
    })
    assert r.status_code == 403


async def test_finance_admin_can_promote_agent_to_sa(client, seeded_db):
    # Agent -> SA promotion sets role: level_2 (SA is a title, not a tier).
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_2",
    })
    assert r.status_code == 200
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert agent["role"] == "level_2"


async def test_finance_admin_cannot_promote_to_rga(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "MGA_1", "role": "level_4",
    })
    assert r.status_code == 403


async def test_finance_admin_cannot_demote_an_rga(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "RGA_1", "role": "level_1",
    })
    assert r.status_code == 403


async def test_finance_admin_cannot_grant_finance_admin_role(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    assert r.status_code == 403


async def test_finance_admin_cannot_remove_an_rga(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/team/remove-person", headers=auth(token), json={"agent_id": "RGA_1"})
    assert r.status_code == 403


async def test_finance_admin_can_remove_a_level_1_agent(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/team/remove-person", headers=auth(token), json={"agent_id": "AG_2"})
    assert r.status_code == 200
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_2"})
    assert agent["archived"] is True  # soft archive, never a hard delete


async def test_finance_admin_cannot_manage_another_finance_admin(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_2", "name": "Finance Two", "email": "fa2@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    token = await finance_admin_session(seeded_db, agent_id="FA_1")
    r = await client.post("/api/team/remove-person", headers=auth(token), json={"agent_id": "FA_2"})
    assert r.status_code == 403


# ---------------- RGA grants/revokes finance_admin (RGA-only) ----------------

async def test_rga_can_grant_finance_admin_to_a_leaf_agent(client, seeded_db):
    token = await rga_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    assert r.status_code == 200
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert agent["role"] == "finance_admin"
    assert agent["upline_id"] is None  # no place in the ladder


async def test_rga_grant_blocked_if_target_has_active_reports(client, seeded_db):
    # GA_1 has SA_1/AG_1 reporting to it — converting would orphan the subtree.
    token = await rga_session(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "GA_1", "role": "finance_admin",
    })
    assert r.status_code == 400


async def test_is_admin_non_rga_can_grant_finance_admin(client, seeded_db):
    # Per owner (2026-09-01): is_admin is meant to have every capability the
    # highest RBAC tier (RGA) has, and then some — never excluded from
    # anything RGA can reach, including granting Financial Admin.
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    assert r.status_code == 200


async def test_plain_agent_cannot_grant_finance_admin(client, seeded_db):
    # Neither is_admin nor a true RGA — must still be blocked.
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    assert r.status_code == 403


# ---------------- RGA-gated routes stay RGA-only ----------------

async def test_finance_admin_rejected_from_wednesday_reset(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/wednesday-reset", headers=auth(token))
    assert r.status_code == 403


# ---------------- is_admin has full RGA control (has_full_control) --------
# Per owner (2026-09-01): is_admin is meant to hold every capability the
# highest RBAC tier (RGA) has, and then some — never excluded from anything
# RGA can reach. These routes used to be require_level(4)-only (true RGA
# tier), which silently excluded a plain is_admin account without level_4.

async def test_is_admin_non_rga_reaches_vault_weeks(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.get("/api/vault/weeks", headers=auth(token))
    assert r.status_code == 200


async def test_is_admin_non_rga_reaches_vault_trends(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.get("/api/vault/trends", headers=auth(token))
    assert r.status_code == 200


async def test_is_admin_non_rga_reaches_manager_audit(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.get("/api/manager/audit", headers=auth(token))
    assert r.status_code == 200


async def test_is_admin_non_rga_reaches_purge_archived(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/admin/purge-archived", headers=auth(token), params={"dry_run": True})
    assert r.status_code == 200


async def test_plain_agent_still_rejected_from_manager_audit(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/manager/audit", headers=auth(token))
    assert r.status_code == 403


async def test_finance_admin_rejected_from_purge_archived(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.post("/api/admin/purge-archived", headers=auth(token))
    assert r.status_code == 403


# ---------------- WAR upload: reused /admin/import-war-report ----------------

def _make_war_workbook() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Wed"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_finance_admin_can_call_war_import_endpoint(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    files = {"file": ("2026-09-02_office.xlsx", _make_war_workbook(),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/api/admin/import-war-report", headers=auth(token), files=files)
    # A near-empty workbook parses to zero rows — 200 proves the gate accepted
    # the finance_admin caller; the acceptance/dedup shape is covered by the
    # existing WAR-import test suite (test_import_cli.py et al), unchanged here.
    assert r.status_code == 200


async def test_plain_agent_rejected_from_war_import_endpoint(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    files = {"file": ("2026-09-02_office.xlsx", _make_war_workbook(),
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = await client.post("/api/admin/import-war-report", headers=auth(token), files=files)
    assert r.status_code == 403
