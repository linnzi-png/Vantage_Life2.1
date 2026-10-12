"""Who the Team tab offers MY TEAM / MY DIRECT REPORTS to (Linnzi, 2026-10-10).

Everyone who is not an admin is offered the buttons. An admin account is only
offered them when its email is named in TEAM_SCOPE_TOGGLE_EMAILS (default
linnzi@aoluxor.com), so she can test them while every other admin does not see
them. /api/auth/me carries the answer as user.team_scope_toggle.
"""
import server
from conftest import auth, make_session


async def toggle_for(client, db, *, role, agent_id, email, flags=None):
    token = await make_session(db, role=role, agent_id=agent_id, email=email)
    if flags:
        await db.users.update_one({"email": email}, {"$set": flags})
    r = await client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["user"]["team_scope_toggle"]


async def test_a_non_admin_is_offered_the_buttons(client, seeded_db):
    got = await toggle_for(client, seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    assert got is True


async def test_the_named_admin_account_keeps_the_buttons(client, seeded_db):
    got = await toggle_for(client, seeded_db, role="level_4", agent_id="RGA_1", email="linnzi@aoluxor.com")
    assert got is True


async def test_another_bootstrap_admin_does_not_get_the_buttons(client, seeded_db):
    got = await toggle_for(client, seeded_db, role="level_4", agent_id="RGA_1", email="mj@aopremier.com")
    assert got is False


async def test_an_admin_granted_by_flag_does_not_get_the_buttons(client, seeded_db):
    got = await toggle_for(client, seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev",
                           flags={"is_admin": True})
    assert got is False


async def test_the_list_comes_from_the_environment_setting(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "TEAM_SCOPE_TOGGLE_EMAILS", {"ga1@test.dev"})
    named = await toggle_for(client, seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev",
                             flags={"is_admin": True})
    assert named is True
    unnamed = await toggle_for(client, seeded_db, role="level_4", agent_id="RGA_1", email="linnzi@aoluxor.com")
    assert unnamed is False
