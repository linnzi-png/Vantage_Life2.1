"""Upline-driven tier changes from the Team tab (/api/team/set-tier).

Owner's decision tree (2026-09-14): an upline may change the tier of someone in
their own downline, in either direction, but only to a tier strictly below their
own. is_admin and finance_admin get the same control agency-wide. level_4 and
the Financial Admin role stay in the Admin Panel.

Fixture chain: RGA_1 -> MGA_1 -> GA_1 -> SA_1 -> AG_1, and MGA_1 -> GA_2 -> AG_2
in a second office.
"""
import pytest

import server
from conftest import auth, make_session


async def set_tier(client, token, **body):
    return await client.post("/api/team/set-tier", headers=auth(token), json=body)


async def role_of(db, agent_id: str) -> str:
    return (await db.agent_profiles.find_one({"agent_id": agent_id}, {"_id": 0, "role": 1}))["role"]


# ---------------- the promotion itself ----------------

async def test_mga_promotes_a_downline_agent_and_sets_the_title(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_1", role="level_2", io_role="GA")
    assert r.status_code == 200, r.text
    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert profile["role"] == "level_2"
    assert profile["io_role"] == "GA"


async def test_promotion_syncs_the_linked_login_so_no_re_login_is_needed(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_tier(client, token, agent_id="AG_1", role="level_2", io_role="SA")).status_code == 200
    user = await seeded_db.users.find_one({"email": "ag1@test.dev"}, {"_id": 0, "role": 1})
    assert user["role"] == "level_2"


async def test_promotion_is_written_to_the_audit_log(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    await set_tier(client, token, agent_id="AG_1", role="level_2", io_role="SA")
    entry = await seeded_db.audit_log.find_one({"agent_id": "AG_1", "action": "set_role"}, {"_id": 0})
    assert entry is not None
    assert entry["original_value"] == "level_1"
    assert entry["new_value"] == "level_2"
    assert entry["new_io_role"] == "SA"


# ---------------- the ceiling ----------------

async def test_an_upline_cannot_promote_to_their_own_tier(client, seeded_db):
    """Strictly below: an MGA may not mint another MGA who would then read
    their book."""
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_1", role="level_3")
    assert r.status_code == 403
    assert await role_of(seeded_db, "AG_1") == "level_1"


async def test_an_upline_cannot_change_someone_at_their_own_tier(client, seeded_db):
    """GA_1 and SA_1 are both level_2, so a GA cannot retier their own SA."""
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await set_tier(client, token, agent_id="SA_1", role="level_1")
    assert r.status_code == 403


async def test_nobody_sets_level_4_here(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await set_tier(client, token, agent_id="AG_1", role="level_4")).status_code == 403


async def test_an_rgas_own_tier_is_not_changed_here(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "RGA_2", "name": "Rga Two", "email": "rga2@test.dev",
        "role": "level_4", "upline_id": None, "office": "MCM",
    })
    assert (await set_tier(client, token, agent_id="RGA_2", role="level_3")).status_code == 403


# ---------------- scope ----------------

async def test_an_upline_cannot_reach_another_branch(client, seeded_db):
    """AG_2 sits under GA_2, not under GA_1."""
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_2", role="level_1", io_role="Builder")
    assert r.status_code == 403


async def test_an_agent_cannot_change_anyone(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await set_tier(client, token, agent_id="SA_1", role="level_1")).status_code == 403


async def test_nobody_changes_their_own_tier(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    assert (await set_tier(client, token, agent_id="MGA_1", role="level_2")).status_code == 400


# ---------------- the two shape guards ----------------

async def test_cannot_raise_someone_above_their_own_upline(client, seeded_db):
    """AG_1 reports to SA_1 (level_2). Making them level_3 would invert the
    chain — their rollup would flow up through a lower tier."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_1", role="level_3")
    assert r.status_code == 400
    assert "Move them under someone" in r.json()["detail"]


async def test_cannot_lower_someone_who_still_has_direct_reports(client, seeded_db):
    """SA_1 runs AG_1. Dropping SA_1 to level_1 would leave AG_1 attached to
    someone who can no longer see them."""
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await set_tier(client, token, agent_id="SA_1", role="level_1")
    assert r.status_code == 400
    assert "direct report" in r.json()["detail"]


async def test_lowering_is_allowed_once_they_have_no_reports(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    # Move AG_1 off SA_1 so SA_1 is childless, then demote.
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"upline_id": "GA_1"}})
    r = await set_tier(client, token, agent_id="SA_1", role="level_1", io_role="Agent")
    assert r.status_code == 200, r.text
    assert await role_of(seeded_db, "SA_1") == "level_1"


# ---------------- admin and finance_admin ----------------

async def test_finance_admin_may_change_tiers_agency_wide(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_1", "name": "Fin Admin", "email": "fa@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    token = await make_session(seeded_db, role="finance_admin", agent_id="FA_1", email="fa@test.dev")
    r = await set_tier(client, token, agent_id="AG_2", role="level_2", io_role="SA")
    assert r.status_code == 200, r.text
    assert await role_of(seeded_db, "AG_2") == "level_2"


async def test_a_finance_admin_account_is_not_retiered_here(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_1", "name": "Fin Admin", "email": "fa@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await set_tier(client, token, agent_id="FA_1", role="level_2")
    assert r.status_code == 400
    assert "Admin Panel" in r.json()["detail"]


# ---------------- input validation ----------------

async def test_an_unknown_title_is_refused(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_1", role="level_2", io_role="Grand Poobah")
    assert r.status_code == 400


async def test_a_no_op_is_refused(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await set_tier(client, token, agent_id="AG_1", role="level_1")
    assert r.status_code == 400
