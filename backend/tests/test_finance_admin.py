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


async def test_finance_admin_reads_vault_trends(client, seeded_db):
    # Found by Codex review on #91: vault_trends was left on require_level(4)
    # while every other vault route was widened for finance_admin.
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/vault/trends", headers=auth(token))
    assert r.status_code == 200


async def test_plain_agent_still_rejected_from_vault(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/vault/weeks", headers=auth(token))
    assert r.status_code == 403


# ---------------- Company Health exports: all three formats ----------------
# Per owner (2026-09-17): finance_admin gets the full downloadable content from
# Company Health — the JSON backup, the per-agent CSV (otherwise EXPORT_EMAILS
# only) and the rebuilt WAR workbooks (otherwise is_admin only). FINANCE_EMAIL
# is deliberately NOT on EXPORT_EMAILS or ADMIN_EMAILS, so these grants come
# from the role alone.

async def _one_entry(db):
    await db.production_entries.insert_one({
        "entry_id": "pe_AG_1_2026-07-01", "agent_id": "AG_1", "office": "MCM",
        "sales_day": "2026-07-01", "sets": 3, "sits": 2, "sales": 1, "ots_sits": 0,
        "ots_sales": 0, "n1": 0, "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0,
        "pos_sits": 0, "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": 500.0, "net_alp": 500.0,
    })


async def test_finance_admin_exports_json(client, seeded_db):
    await _one_entry(seeded_db)
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01", headers=auth(token))
    assert r.status_code == 200, r.text
    assert "weekly_tabs" in r.json()


async def test_finance_admin_exports_csv(client, seeded_db):
    assert FINANCE_EMAIL not in server.EXPORT_EMAILS
    await _one_entry(seeded_db)
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=csv", headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.text.startswith("date,agent,office")
    assert "2026-07-01" in r.text


async def test_finance_admin_exports_war_workbook(client, seeded_db):
    assert FINANCE_EMAIL not in server.ADMIN_EMAILS
    await _one_entry(seeded_db)
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/vault/export?week_start=2026-07-01&format=xlsx&office=MCM",
                         headers=auth(token))
    assert r.status_code == 200, r.text
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert len(wb.sheetnames) > 0


async def test_finance_admin_session_advertises_can_export(client, seeded_db):
    """The UI hides the CSV button unless /auth/me says can_export — the
    server's answer must fold the role in, or the grant is invisible."""
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["user"]["can_export"] is True


# ---------------- Hierarchy Map + reassign (per owner, 2026-09-17) ----------------

async def test_finance_admin_reads_the_hierarchy_directory(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    r = await client.get("/api/hierarchy", headers=auth(token))
    assert r.status_code == 200
    assert any(a["agent_id"] == "AG_1" for a in r.json()["agents"])


async def _reassign(client, token, agent_id, new_upline):
    return await client.post("/api/team/reassign", headers=auth(token),
                             json={"agent_id": agent_id, "new_upline_agent_id": new_upline})


async def test_finance_admin_reassigns_agency_wide(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    # AG_1 (MCM, under SA_1) moves under GA_1 (MCM) — no downline scope at all.
    r = await _reassign(client, token, "AG_1", "GA_1")
    assert r.status_code == 200, r.text
    doc = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert doc["upline_id"] == "GA_1"
    # But not into another office: crossing an office boundary is for the
    # owner and MJ only (is_admin), not a Financial Admin (owner, 2026-09-22).
    assert (await _reassign(client, token, "AG_1", "GA_2")).status_code == 403
    # A leader too: MGA_1 may be moved (level_3 is inside the range).
    assert (await _reassign(client, token, "GA_1", "RGA_1")).status_code == 200


async def test_finance_admin_cannot_move_an_rga_or_a_finance_admin(client, seeded_db):
    token = await finance_admin_session(seeded_db)
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_2", "name": "Finance Two", "email": "fa2@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    assert (await _reassign(client, token, "RGA_1", "MGA_1")).status_code == 403
    assert (await _reassign(client, token, "FA_2", "MGA_1")).status_code == 403
    # Shape guard shared with uplines: the new upline sits at or above them.
    assert (await _reassign(client, token, "MGA_1", "AG_1")).status_code == 400
    # Codex on #142: a Financial Admin can be nobody's upline — role_level()
    # falls back to 1 for it, so without an explicit check a level_1 agent
    # would slip under one. Server-side, whoever asks.
    assert (await _reassign(client, token, "AG_1", "FA_2")).status_code == 400
    rga = await rga_session(seeded_db)
    assert (await _reassign(client, rga, "AG_1", "FA_2")).status_code == 400


async def test_finance_admin_who_is_also_admin_keeps_full_control(client, seeded_db):
    """Codex on #142: is_admin is an independent flag, so an account can hold
    both. Admin wins — the finance_admin limits apply only without it."""
    token = await finance_admin_session(seeded_db)
    await seeded_db.users.update_one({"email": FINANCE_EMAIL}, {"$set": {"is_admin": True}})
    # Moving an RGA is admin-only; a finance_admin+admin may.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
        "role": "level_4", "upline_id": None, "office": "AMP",
    })
    assert (await _reassign(client, token, "RGA_2", "RGA_1")).status_code == 200


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


async def test_revoking_finance_admin_requires_an_upline(client, seeded_db):
    # Found by Codex review on #91: moving finance_admin back to a level_N
    # tier without an upline orphans them — invisible to every team rollup.
    token = await rga_session(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_1",
    })
    assert r.status_code == 400


async def test_revoking_finance_admin_with_upline_restores_them(client, seeded_db):
    token = await rga_session(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_1", "upline_agent_id": "SA_1",
    })
    assert r.status_code == 200
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert agent["role"] == "level_1"
    assert agent["upline_id"] == "SA_1"


async def test_revoking_finance_admin_to_rga_needs_no_upline(client, seeded_db):
    # level_4 (RGA) is the one tier that's allowed to have no upline.
    token = await rga_session(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_4",
    })
    assert r.status_code == 200


async def test_revoking_finance_admin_rejects_self_as_upline(client, seeded_db):
    # Found by Codex review on #93: the upline lookup didn't reject the
    # target itself, which would self-cycle.
    token = await rga_session(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_1", "upline_agent_id": "AG_1",
    })
    assert r.status_code == 400


async def test_revoking_finance_admin_rejects_another_finance_admin_as_upline(client, seeded_db):
    # Found by Codex review on #93: another finance_admin has no place in
    # the ladder either — attaching under one recreates the same orphaning.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_2", "name": "Finance Two", "email": "fa2b@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    token = await rga_session(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "finance_admin",
    })
    r = await client.post("/api/admin/set-role", headers=auth(token), json={
        "agent_id": "AG_1", "role": "level_1", "upline_agent_id": "FA_2",
    })
    assert r.status_code == 400


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


async def test_is_admin_non_rga_can_force_reseed(client, seeded_db):
    # Found by Codex review on #93: force-reseed's gate checked
    # role == "level_4" directly instead of has_full_control(), leaving it
    # the one level_4-only route the is_admin widening missed.
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/seed", headers=auth(token), json={"force": True})
    assert r.status_code == 200
    assert r.json()["seeded"] is True


async def test_plain_agent_rejected_from_force_reseed(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/seed", headers=auth(token), json={"force": True})
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
