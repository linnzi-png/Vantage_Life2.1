"""Roster office listing and merge.

One office recorded under two names splits its numbers everywhere offices are
listed, and agent_profiles is where that has to be fixed — it is the source of
truth every office lookup resolves through.
"""
import server
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"


async def admin_token(db):
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


# ---------------- gating ----------------

async def test_offices_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.get("/api/admin/offices", headers=auth(token))).status_code == 403


async def test_merge_requires_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/admin/merge-office", headers=auth(token),
                          json={"from_office": "MCM", "to_office": "AMP"})
    assert r.status_code == 403


# ---------------- listing ----------------

async def test_offices_lists_headcount_biggest_first(client, seeded_db):
    token = await admin_token(seeded_db)
    body = (await client.get("/api/admin/offices", headers=auth(token))).json()
    counts = {o["office"]: o["agents"] for o in body["offices"]}
    assert counts == {"MCM": 5, "AMP": 2}
    assert body["offices"][0]["office"] == "MCM"   # sorted by headcount


# ---------------- merging ----------------

async def test_merge_moves_every_agent(client, seeded_db):
    """The real case: one office under two names collapses into one."""
    token = await admin_token(seeded_db)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$set": {"office": "Mohamed Aljahmi RGA"}})

    r = await client.post("/api/admin/merge-office", headers=auth(token),
                          json={"from_office": "Mohamed Aljahmi RGA", "to_office": "MCM"})
    assert r.status_code == 200
    assert r.json()["agents_moved"] == 1

    offices = {o["office"] for o in (await client.get(
        "/api/admin/offices", headers=auth(token))).json()["offices"]}
    assert "Mohamed Aljahmi RGA" not in offices


async def test_merge_fixes_past_weeks_too(client, seeded_db):
    """Entries are not rewritten — offices resolve through the roster, so a
    merge corrects historical weeks as well as future ones."""
    token = await admin_token(seeded_db)
    await seeded_db.agent_profiles.update_one(
        {"agent_id": "AG_1"}, {"$set": {"office": "Mohamed Aljahmi RGA"}})
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_1", "agent_id": "AG_1", "office": "Mohamed Aljahmi RGA",
        "sales_day": "2026-02-18", "sets": 0, "sits": 2, "sales": 1, "ots_sits": 0,
        "ots_sales": 0, "n1": 0, "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0,
        "pos_sits": 0, "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
        "gross_alp": 500.0, "net_alp": 500.0,
    })
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")

    before = (await client.get("/api/vault/trends?office=MCM", headers=auth(rga))).json()
    assert before["series"] == []          # AG_1 sits under the stray name

    await client.post("/api/admin/merge-office", headers=auth(token),
                      json={"from_office": "Mohamed Aljahmi RGA", "to_office": "MCM"})

    after = (await client.get("/api/vault/trends?office=MCM", headers=auth(rga))).json()
    assert after["series"][0]["gross_alp"] == 500.0   # historical week now included


async def test_merge_rejects_unknown_source(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-office", headers=auth(token),
                          json={"from_office": "Nowhere", "to_office": "MCM"})
    assert r.status_code == 404


async def test_merge_rejects_same_name(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-office", headers=auth(token),
                          json={"from_office": "MCM", "to_office": "MCM"})
    assert r.status_code == 400


async def test_merge_rejects_blank_names(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/merge-office", headers=auth(token),
                          json={"from_office": "  ", "to_office": "MCM"})
    assert r.status_code == 400
