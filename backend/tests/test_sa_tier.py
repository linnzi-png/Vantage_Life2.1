"""The SA tier (owner, 2026-09-22): Agent < SA < GA < MGA < RGA.

  - level_sa ranks between level_1 and level_2 (role_level 1.5), so every
    "strictly below your own tier" rule gives: GA makes SA, SA makes Agents
    only, MGA makes GA
  - an SA is a leader: reads and enters for their own downline, appears on the
    leader board, heads a team in Missing Numbers, is a "my SA team" root
  - migrate_sa_tier() moves SA-titled level_2 profiles (and their logins) to
    level_sa once; GA-titled ones stay

Fixture: RGA_1 → MGA_1 → {GA_1 → SA_1 (level_sa) → AG_1, GA_2 → AG_2}.
"""
import server
from conftest import auth, make_session


def test_the_ladder_orders_sa_between_agent_and_ga():
    assert server.role_level("level_1") < server.role_level("level_sa") < server.role_level("level_2") \
        < server.role_level("level_3") < server.role_level("level_4")
    assert server.is_leader_role("level_sa") and not server.is_leader_role("level_1")
    assert server.role_level("garbage") == 1


async def test_an_sa_reads_and_enters_for_their_own_downline_only(client, seeded_db):
    token = await make_session(seeded_db, role="level_sa", agent_id="SA_1", email="sa1@test.dev")
    team = (await client.get("/api/team", headers=auth(token))).json()["team"]
    ids = {r["agent_id"] for r in team}
    assert "AG_1" in ids and "SA_1" in ids
    assert "GA_1" not in ids and "AG_2" not in ids
    # Proxy entry for their agent works; for a sibling branch it does not.
    body = {"sets": 1, "sits": 1, "sales": 0, "ots_sits": 0, "ots_sales": 0, "n1": 0, "refs_obtained": 0,
            "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0, "vet_sits": 0, "vet_sales": 0,
            "gross_alp": 0}
    assert (await client.post("/api/pulse", headers=auth(token), json={**body, "target_agent_id": "AG_1"})).status_code == 200
    assert (await client.post("/api/pulse", headers=auth(token), json={**body, "target_agent_id": "AG_2"})).status_code == 403


async def test_an_agents_sa_team_roots_at_the_sa(client, seeded_db):
    ids = await server.sa_team_agent_ids("AG_1")
    assert set(ids) == {"SA_1", "AG_1"}


async def test_sa_heads_a_team_in_missing_numbers_and_gets_the_ladder(client, seeded_db):
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    day = (await client.get("/api/team/missing?days=1", headers=auth(rga))).json()["days"][0]
    leaders = {t["leader"]["agent_id"] for t in day["teams"] if t.get("leader")}
    assert "SA_1" in leaders
    missing = {m["agent_id"] for t in day["teams"] for m in t["missing"]}
    assert "SA_1" in missing and "AG_1" in missing  # an SA owes a nightly pulse
    assert "MGA_1" not in missing


async def test_migration_moves_sa_titled_level_2_once(seeded_db):
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": "OLD_SA", "name": "Old Sa", "email": "oldsa@test.dev", "role": "level_2", "io_role": "SA",
         "upline_id": "GA_1", "office": "MCM"},
        {"agent_id": "OLD_GA", "name": "Old Ga", "email": "oldga@test.dev", "role": "level_2", "io_role": "GA",
         "upline_id": "MGA_1", "office": "MCM"},
    ])
    await make_session(seeded_db, role="level_2", agent_id="OLD_SA", email="oldsa@test.dev")
    assert await server.migrate_sa_tier() == 1
    sa = await seeded_db.agent_profiles.find_one({"agent_id": "OLD_SA"}, {"_id": 0})
    ga = await seeded_db.agent_profiles.find_one({"agent_id": "OLD_GA"}, {"_id": 0})
    assert sa["role"] == "level_sa" and sa["io_role"] == "SA"
    assert ga["role"] == "level_2"
    user = await seeded_db.users.find_one({"email": "oldsa@test.dev"}, {"_id": 0})
    assert user["role"] == "level_sa"
    assert await server.migrate_sa_tier() == 0


async def test_admin_tier_buttons_keep_the_title_in_step(client, seeded_db):
    admin = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    # SA_1 up to the GA tier: title follows.
    r = await client.post("/api/admin/set-role", headers=auth(admin), json={"agent_id": "SA_1", "role": "level_2"})
    assert r.status_code == 200, r.text
    p = await seeded_db.agent_profiles.find_one({"agent_id": "SA_1"}, {"_id": 0})
    assert p["role"] == "level_2" and p["io_role"] == "GA"
    # And back down to the SA tier.
    r = await client.post("/api/admin/set-role", headers=auth(admin), json={"agent_id": "SA_1", "role": "level_sa"})
    assert r.status_code == 200, r.text
    p = await seeded_db.agent_profiles.find_one({"agent_id": "SA_1"}, {"_id": 0})
    assert p["role"] == "level_sa" and p["io_role"] == "SA"
