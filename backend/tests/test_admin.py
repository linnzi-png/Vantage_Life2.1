"""Admin panel endpoints: require_admin gating, roster management, flag grants,
and the self-service role switcher (/api/me/role)."""
import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"  # in the default ADMIN_EMAILS set


async def admin_token(db) -> str:
    """Session for a bootstrap admin (no is_admin flag needed, no agent link needed)."""
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


# ---------------- require_admin gating ----------------

async def test_admin_endpoints_reject_non_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.get("/api/admin/people", headers=auth(token))
    assert r.status_code == 403


async def test_admin_endpoints_reject_unauthenticated(client, seeded_db):
    r = await client.get("/api/admin/people")
    assert r.status_code == 401


async def test_bootstrap_admin_email_allowed_without_flag(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.get("/api/admin/people", headers=auth(token))
    assert r.status_code == 200


async def test_is_admin_flag_grants_access(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await seeded_db.users.update_one({"email": "ag1@test.dev"}, {"$set": {"is_admin": True}})
    r = await client.get("/api/admin/people", headers=auth(token))
    assert r.status_code == 200


# ---------------- GET /api/admin/people ----------------

async def test_people_lists_roster_with_flags(client, seeded_db):
    # GA_1 has a login with can_switch_role; AG_2 has never signed in.
    await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await seeded_db.users.update_one({"email": "ga1@test.dev"}, {"$set": {"can_switch_role": True}})
    token = await admin_token(seeded_db)

    r = await client.get("/api/admin/people", headers=auth(token))
    assert r.status_code == 200
    people = {p["agent_id"]: p for p in r.json()["people"]}
    assert people["GA_1"]["has_login"] is True
    assert people["GA_1"]["can_switch_role"] is True
    assert people["AG_2"]["has_login"] is False
    assert people["AG_2"]["can_switch_role"] is False


# ---------------- POST /api/admin/set-role ----------------

async def test_set_role_rejects_invalid_role(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "AG_1", "role": "level_9"})
    assert r.status_code == 400


async def test_set_role_unknown_agent_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "NOPE", "role": "level_2"})
    assert r.status_code == 404


async def test_set_role_updates_profile_and_linked_login(client, seeded_db):
    # The invariant: role writes hit agent_profiles (source of truth) AND users.
    await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "AG_1", "role": "level_2"})
    assert r.status_code == 200

    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert profile["role"] == "level_2"
    u = await seeded_db.users.find_one({"email": "ag1@test.dev"})
    assert u["role"] == "level_2"
    assert u["agent_id"] == "AG_1"


# ---------------- POST /api/admin/add-person ----------------

async def test_add_person_requires_valid_email_and_name(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json={"name": "New Guy", "email": "not-an-email", "role": "level_1"})
    assert r.status_code == 400


async def test_add_person_rejects_duplicate_email(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json={"name": "Dupe", "email": "ag1@test.dev", "role": "level_1"})
    assert r.status_code == 409


async def test_add_person_unknown_upline_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json={"name": "New Guy", "email": "new@test.dev",
                                "role": "level_1", "upline_agent_id": "NOPE"})
    assert r.status_code == 404


async def test_add_person_creates_profile(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json={"name": "New Guy", "email": "New@Test.Dev", "phone": "(313) 555-0100",
                                "role": "level_1", "io_role": "Agent", "upline_agent_id": "GA_1"})
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["email"] == "new@test.dev"  # normalized
    assert agent["phone"] == "3135550100"
    assert agent["upline_id"] == "GA_1"
    profile = await seeded_db.agent_profiles.find_one({"email": "new@test.dev"})
    assert profile is not None and profile["role"] == "level_1"


async def test_add_person_links_pending_login(client, seeded_db):
    # Signed in before being rostered: users doc holds role "pending", no agent_id.
    # (Inserted directly — make_session derives user_id from role+agent_id and
    # would collide with the pending/None bootstrap-admin session.)
    await seeded_db.users.insert_one({
        "user_id": "user_early", "email": "early@test.dev", "name": "early",
        "role": "pending", "agent_id": None,
    })
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json={"name": "Early Bird", "email": "early@test.dev", "role": "level_1"})
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "early@test.dev"})
    assert u["role"] == "level_1"
    assert u["agent_id"] == r.json()["agent"]["agent_id"]


# ---------------- POST /api/admin/set-flags ----------------

async def test_set_flags_requires_at_least_one_flag(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-flags", headers=auth(token),
                          json={"email": "ag1@test.dev"})
    assert r.status_code == 400


async def test_set_flags_unknown_login_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-flags", headers=auth(token),
                          json={"email": "never-signed-in@test.dev", "can_switch_role": True})
    assert r.status_code == 404


async def test_set_flags_grants_and_revokes(client, seeded_db):
    await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    token = await admin_token(seeded_db)

    r = await client.post("/api/admin/set-flags", headers=auth(token),
                          json={"email": "GA1@test.dev", "can_switch_role": True, "is_admin": True})
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "ga1@test.dev"})
    assert u["can_switch_role"] is True and u["is_admin"] is True

    r = await client.post("/api/admin/set-flags", headers=auth(token),
                          json={"email": "ga1@test.dev", "is_admin": False})
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "ga1@test.dev"})
    assert u["is_admin"] is False and u["can_switch_role"] is True  # untouched flag preserved


# ---------------- POST /api/me/role (self-service switcher) ----------------

async def test_self_role_requires_can_switch_role_flag(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/me/role", headers=auth(token), json={"role": "level_1"})
    assert r.status_code == 403


async def test_self_role_blocked_for_pending_users(client, seeded_db):
    token = await make_session(seeded_db, role="pending", agent_id=None, email="pending@test.dev")
    await seeded_db.users.update_one({"email": "pending@test.dev"}, {"$set": {"can_switch_role": True}})
    r = await client.post("/api/me/role", headers=auth(token), json={"role": "level_1"})
    assert r.status_code == 403  # require_agent rejects unlinked accounts even with the flag


async def test_self_role_rejects_invalid_role(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await seeded_db.users.update_one({"email": "ga1@test.dev"}, {"$set": {"can_switch_role": True}})
    r = await client.post("/api/me/role", headers=auth(token), json={"role": "pending"})
    assert r.status_code == 400


async def test_self_role_switch_updates_both_collections(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    await seeded_db.users.update_one({"email": "ga1@test.dev"}, {"$set": {"can_switch_role": True}})

    r = await client.post("/api/me/role", headers=auth(token), json={"role": "level_4"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "level_4"
    assert body["role_label"] == server.LEVELS["level_4"]
    # Survives the login re-derivation: agent_profiles is updated too.
    profile = await seeded_db.agent_profiles.find_one({"agent_id": "GA_1"})
    assert profile["role"] == "level_4"
    u = await seeded_db.users.find_one({"email": "ga1@test.dev"})
    assert u["role"] == "level_4"
