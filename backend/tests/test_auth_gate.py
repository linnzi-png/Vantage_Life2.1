"""The two-step auth model: authentication succeeds for anyone verified,
authorization (business data) is gated on the agent roster."""
from conftest import auth, make_session


async def test_pending_user_is_authenticated_but_not_authorized(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="stranger@test.dev")

    # Authenticated: /auth/me works
    me = await client.get("/api/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "pending"
    assert me.json()["role_label"] == "Pending Approval"

    # Not authorized: business data is 403, not 401
    team = await client.get("/api/team", headers=auth(token))
    assert team.status_code == 403

    pulse = await client.post("/api/pulse", json={"sets": 1}, headers=auth(token))
    assert pulse.status_code == 403


async def test_no_token_is_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


async def test_demo_login_returns_working_session(client, seeded_db):
    r = await client.post("/api/auth/demo-login", json={"level": "level_2"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_token"]
    assert body["user"]["role"] == "level_2"

    me = await client.get("/api/auth/me", headers=auth(body["session_token"]))
    assert me.status_code == 200


async def test_demo_login_rejects_unknown_level(client, seeded_db):
    r = await client.post("/api/auth/demo-login", json={"level": "level_99"})
    assert r.status_code == 400


async def test_roster_match_gets_real_role_no_match_gets_pending(seeded_db):
    import server
    # Email on the roster -> real role + agent_id
    user = await server.upsert_user_and_session("ga1@test.dev", "Ga One", None, "st_x1")
    assert user["role"] == "level_2"
    assert user["agent_id"] == "GA_1"

    # Email not on the roster -> pending, no agent_id, but sign-in still succeeds
    user = await server.upsert_user_and_session("nobody@test.dev", "Nobody", None, "st_x2")
    assert user["role"] == "pending"
    assert user["agent_id"] is None


async def test_email_matching_is_case_insensitive(seeded_db):
    import server
    user = await server.upsert_user_and_session("  GA1@Test.Dev ", "Ga One", None, "st_x3")
    assert user["role"] == "level_2"
