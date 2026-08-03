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

def person(**overrides) -> dict:
    """Valid add-person payload; tests override the field under scrutiny."""
    base = {"name": "New Guy", "email": "new@test.dev", "role": "level_1",
            "is_rookie": True, "upline_agent_id": "GA_1"}
    base.update(overrides)
    return base


async def test_add_person_requires_valid_email_and_name(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(email="not-an-email"))
    assert r.status_code == 400


async def test_add_person_requires_tenure(client, seeded_db):
    # No default, no silent fallback: a create request without an explicit
    # Veteran/Rookie choice is rejected with a message the form can surface.
    token = await admin_token(seeded_db)
    payload = person()
    del payload["is_rookie"]
    r = await client.post("/api/admin/add-person", headers=auth(token), json=payload)
    assert r.status_code == 400
    assert "Tenure" in r.json()["detail"]

    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(is_rookie=None))
    assert r.status_code == 400


async def test_add_person_requires_upline_below_rga(client, seeded_db):
    # Team rollups walk upline_id — an uplineless sub-RGA agent would be
    # invisible in every GA/MGA team view.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(upline_agent_id=None))
    assert r.status_code == 400
    assert "Upline" in r.json()["detail"]


async def test_add_person_rga_needs_no_upline(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(role="level_4", upline_agent_id=None))
    assert r.status_code == 200
    assert r.json()["agent"]["upline_id"] is None


async def test_add_person_rejects_duplicate_email(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(name="Dupe", email="ag1@test.dev"))
    assert r.status_code == 409


async def test_add_person_unknown_upline_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(upline_agent_id="NOPE"))
    assert r.status_code == 404


async def test_add_person_creates_profile(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(email="New@Test.Dev", phone="(313) 555-0100",
                                      io_role="Agent", is_rookie=False))
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["email"] == "new@test.dev"  # normalized
    assert agent["phone"] == "3135550100"
    assert agent["upline_id"] == "GA_1"
    assert agent["is_rookie"] is False
    profile = await seeded_db.agent_profiles.find_one({"email": "new@test.dev"})
    assert profile is not None and profile["role"] == "level_1"
    assert profile["is_rookie"] is False
    assert profile["joined_at"] is not None


async def test_add_person_writes_audit_entry(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json=person())
    assert r.status_code == 200
    entry = await seeded_db.audit_log.find_one({"action": "add_agent"})
    assert entry is not None
    assert entry["agent_id"] == r.json()["agent"]["agent_id"]
    assert entry["agent_name"] == "New Guy"
    assert entry["is_rookie"] is True
    assert entry["upline_id"] == "GA_1"
    assert entry["changed_by"]  # who added whom is always attributable


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
                          json=person(name="Early Bird", email="early@test.dev"))
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "early@test.dev"})
    assert u["role"] == "level_1"
    assert u["agent_id"] == r.json()["agent"]["agent_id"]


async def test_created_agent_visible_in_uplines_team_scope(client, seeded_db):
    # (a) of the feature goal: the new agent appears in the right GA's team
    # rollup — and NOT in a sibling GA's — once they have production today.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token),
                          json=person(upline_agent_id="GA_2"))
    new_id = r.json()["agent"]["agent_id"]
    await seeded_db.production_entries.insert_one({
        "entry_id": "e_new", "agent_id": new_id, "office": "MJ RGA",
        "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 2, "sales": 1, "n1": 0, "refs_obtained": 0,
        "gross_alp": 1500, "net_alp": 1500,
        "submitted_at": server.now_utc(), "submitted_on_time": True,
    })

    ga2 = await make_session(seeded_db, role="level_2", agent_id="GA_2", email="ga2@test.dev")
    ids = [m["agent_id"] for m in (await client.get("/api/team", headers=auth(ga2))).json()["team"]]
    assert new_id in ids

    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    ids = [m["agent_id"] for m in (await client.get("/api/team", headers=auth(ga1))).json()["team"]]
    assert new_id not in ids


async def test_created_rookie_lands_in_platinum_wall_rookie_bucket(client, seeded_db):
    # (b) of the feature goal: tenure chosen at creation drives the Platinum
    # Wall split with zero display-code changes.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/add-person", headers=auth(token), json=person(is_rookie=True))
    new_id = r.json()["agent"]["agent_id"]
    await seeded_db.production_entries.insert_one({
        "entry_id": "e_rook", "agent_id": new_id, "office": "MJ RGA",
        "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 2, "sales": 1, "n1": 0, "refs_obtained": 0,
        "gross_alp": 2000, "net_alp": 2000,
        "submitted_at": server.now_utc(), "submitted_on_time": True,
    })
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    wall = (await client.get("/api/dashboard/platinum-wall", headers=auth(rga))).json()
    assert new_id in [a["agent_id"] for a in wall["rookies"]]
    assert new_id not in [a["agent_id"] for a in wall["vets"]]


async def test_unknown_tenure_excluded_from_platinum_wall(client, seeded_db):
    # A rostered agent whose tenure was never recorded (no is_rookie field) must
    # NOT be bucketed as a veteran — unknown is its own state, so the agent shows
    # in neither wall list until leadership records tenure in the Admin panel.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_UNK", "name": "No Tenure", "office": "MJ RGA",
        "role": "level_1", "upline_id": "GA_1", "email": "unk@test.dev",
        # is_rookie deliberately absent — tenure unknown
    })
    # High gross so a mis-bucket would put it at the top of the vets list.
    await seeded_db.production_entries.insert_one({
        "entry_id": "e_unk", "agent_id": "AG_UNK", "office": "MJ RGA",
        "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 2, "sales": 1, "n1": 0, "refs_obtained": 0,
        "gross_alp": 9000, "net_alp": 9000,
        "submitted_at": server.now_utc(), "submitted_on_time": True,
    })
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    wall = (await client.get("/api/dashboard/platinum-wall", headers=auth(rga))).json()
    assert "AG_UNK" not in [a["agent_id"] for a in wall["vets"]]
    assert "AG_UNK" not in [a["agent_id"] for a in wall["rookies"]]


# ---------------- POST /api/admin/set-tenure ----------------

async def test_set_tenure_unknown_agent_404(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-tenure", headers=auth(token),
                          json={"agent_id": "NOPE", "is_rookie": True})
    assert r.status_code == 404


async def test_set_tenure_records_choice_and_audits(client, seeded_db):
    # Resolution path for pre-existing agents whose tenure was never recorded:
    # AG_1 has no is_rookie field (unknown) until an admin explicitly sets it.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-tenure", headers=auth(token),
                          json={"agent_id": "AG_1", "is_rookie": True})
    assert r.status_code == 200
    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert profile["is_rookie"] is True
    entry = await seeded_db.audit_log.find_one({"action": "set_tenure"})
    assert entry is not None
    assert entry["original_value"] is None  # was unknown, not defaulted
    assert entry["new_value"] is True


async def test_people_reports_tenure_including_unknown(client, seeded_db):
    # The Admin roster distinguishes recorded tenure from never-recorded
    # (missing key) so the unknowns stay visibly unresolved.
    token = await admin_token(seeded_db)
    await client.post("/api/admin/set-tenure", headers=auth(token),
                      json={"agent_id": "AG_1", "is_rookie": True})
    r = await client.get("/api/admin/people", headers=auth(token))
    people = {p["agent_id"]: p for p in r.json()["people"]}
    assert people["AG_1"]["is_rookie"] is True
    assert "is_rookie" not in people["AG_2"]  # unknown stays unknown


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
