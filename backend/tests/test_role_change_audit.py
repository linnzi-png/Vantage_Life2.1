"""Role changes write an audit_log entry.

Adding, removing, reassigning and merging people have always been logged, but
the two routes that change a tier were not — so a wrong tier left no record of
who set it or what it was before. That gap is what made the GA-at-MGA-tier
cleanup guesswork (see backend/audit_ga_tier.py, which has to infer intent from
creation records because no promotion was ever recorded).
"""
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db) -> str:
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


async def entries(db, action: str) -> list:
    return [e async for e in db.audit_log.find({"action": action}, {"_id": 0})]


# ---------------- /admin/set-role ----------------

async def test_set_role_writes_audit_entry(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "AG_1", "role": "level_2"})
    assert r.status_code == 200

    rows = await entries(seeded_db, "set_role")
    assert len(rows) == 1
    e = rows[0]
    assert e["agent_id"] == "AG_1"
    assert e["agent_name"] == "Agent One"
    # The point of the entry: what it was, what it became, and who did it.
    assert e["original_value"] == "level_1"
    assert e["new_value"] == "level_2"
    assert e["changed_by_name"] is not None
    assert e["audit_id"].startswith("au_")


async def test_set_role_records_the_tier_left_behind(client, seeded_db):
    # Two changes in a row: the second must record level_2 as the origin, not
    # the original level_1 — otherwise the trail cannot be walked backwards.
    token = await admin_token(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token),
                      json={"agent_id": "AG_1", "role": "level_2"})
    await client.post("/api/admin/set-role", headers=auth(token),
                      json={"agent_id": "AG_1", "role": "level_3"})

    rows = sorted(await entries(seeded_db, "set_role"), key=lambda e: e["new_value"])
    assert [(e["original_value"], e["new_value"]) for e in rows] == [
        ("level_1", "level_2"),
        ("level_2", "level_3"),
    ]


async def test_rejected_set_role_writes_nothing(client, seeded_db):
    # An invalid role is refused before any write; the log must not gain a row
    # for a change that never happened.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "AG_1", "role": "level_9"})
    assert r.status_code == 400
    assert await entries(seeded_db, "set_role") == []


async def test_set_role_records_upline_move_into_finance_admin(client, seeded_db):
    # Converting to finance_admin also clears upline_id. The entry should
    # describe the whole edit, not just the tier half.
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/set-role", headers=auth(token),
                          json={"agent_id": "AG_1", "role": "finance_admin"})
    assert r.status_code == 200

    e = (await entries(seeded_db, "set_role"))[0]
    assert e["new_value"] == "finance_admin"
    assert e["old_upline_id"] == "SA_1"
    assert e["new_upline_id"] is None


async def test_set_role_without_upline_move_omits_those_fields(client, seeded_db):
    # A plain tier change does not touch the upline, so those keys stay off the
    # entry rather than claiming a move that did not happen.
    token = await admin_token(seeded_db)
    await client.post("/api/admin/set-role", headers=auth(token),
                      json={"agent_id": "AG_1", "role": "level_2"})
    e = (await entries(seeded_db, "set_role"))[0]
    assert "old_upline_id" not in e
    assert "new_upline_id" not in e


# ---------------- /me/role ----------------

async def test_self_role_switch_writes_audit_entry(client, seeded_db):
    # The one route where someone raises their own tier — gated on
    # can_switch_role, which is exactly why it needs a record.
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$set": {"role": "level_1"}})
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await seeded_db.users.update_many({"email": "ag1@test.dev"},
                                      {"$set": {"can_switch_role": True}})

    r = await client.post("/api/me/role", headers=auth(token), json={"role": "level_4"})
    assert r.status_code == 200

    rows = await entries(seeded_db, "self_set_role")
    assert len(rows) == 1
    e = rows[0]
    assert e["agent_id"] == "AG_1"
    assert e["original_value"] == "level_1"
    assert e["new_value"] == "level_4"
    # Self-service: the actor and the subject are the same person.
    assert e["changed_by"] is not None


async def test_self_role_switch_denied_writes_nothing(client, seeded_db):
    # Without can_switch_role the request is refused, so nothing is logged.
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/me/role", headers=auth(token), json={"role": "level_4"})
    assert r.status_code == 403
    assert await entries(seeded_db, "self_set_role") == []
