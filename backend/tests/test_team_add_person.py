"""POST /api/team/add-person — any upline (level_2+) onboards a new member
DIRECTLY UNDER THEMSELVES: upline forced to the requester, office inherited,
so the new member rolls up the existing chain to MGA/RGA automatically."""
from conftest import auth, make_session


def person(**overrides) -> dict:
    base = {"name": "New Recruit", "email": "recruit@test.dev",
            "role": "level_1", "io_role": "Agent", "is_rookie": True}
    base.update(overrides)
    return base


async def test_level_1_cannot_add(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token), json=person())
    assert r.status_code == 403


async def test_unauthenticated_rejected(client, seeded_db):
    r = await client.post("/api/team/add-person", json=person())
    assert r.status_code == 401


async def test_sa_adds_agent_directly_under_self(client, seeded_db):
    # SA_1 (level_2, upline GA_1) adds an Agent: upline must be SA_1 itself,
    # office inherited from SA_1 — so the recruit chains SA_1 → GA_1 → MGA_1 → RGA_1.
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token), json=person())
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["upline_id"] == "SA_1"
    assert agent["office"] == "MCM"
    assert agent["role"] == "level_1"
    # Full chain resolves to the top via existing upline links.
    chain = []
    cur = agent
    while cur and cur.get("upline_id"):
        cur = await seeded_db.agent_profiles.find_one({"agent_id": cur["upline_id"]})
        chain.append(cur["agent_id"])
    assert chain == ["SA_1", "GA_1", "MGA_1", "RGA_1"]


async def test_upline_cannot_be_chosen_by_client(client, seeded_db):
    # A client-supplied upline_agent_id is ignored — placement is always under self.
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(upline_agent_id="RGA_1"))
    assert r.status_code == 200
    assert r.json()["agent"]["upline_id"] == "SA_1"


async def test_cannot_add_at_or_above_own_level(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_2", io_role="SA"))
    assert r.status_code == 403


async def test_mga_can_add_sa(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_2", io_role="SA"))
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["upline_id"] == "MGA_1"
    assert agent["io_role"] == "SA"


async def test_tenure_required(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(is_rookie=None))
    assert r.status_code == 400


async def test_duplicate_email_409(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(email="ag1@test.dev"))
    assert r.status_code == 409


async def test_recruit_first_signin_links_by_email(client, seeded_db):
    # A pre-existing "pending" login with the recruit's email gets linked immediately.
    await make_session(seeded_db, role="pending", agent_id=None, email="recruit@test.dev")
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token), json=person())
    assert r.status_code == 200
    u = await seeded_db.users.find_one({"email": "recruit@test.dev"})
    assert u["role"] == "level_1"
    assert u["agent_id"] == r.json()["agent"]["agent_id"]


async def test_sa_adds_trainee_as_level_1(client, seeded_db):
    # The Team tab's TRAINEE chip sends the existing `inTraining` title at
    # level_1 — a title, not an access tier. An SA onboarding their own trainee
    # is the whole point of the option, so it must land under them like any
    # other recruit and must not confer tier above level_1.
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_1", io_role="inTraining"))
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["role"] == "level_1"
    assert agent["io_role"] == "inTraining"
    assert agent["upline_id"] == "SA_1"


async def test_trainee_title_does_not_grant_tier(client, seeded_db):
    # Guard the title/tier split: `inTraining` paired with a higher role is
    # still rejected on the role, so the title can never be a back door.
    token = await make_session(seeded_db, role="level_2", agent_id="SA_1", email="sa1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_2", io_role="inTraining"))
    assert r.status_code == 403


async def test_mga_adds_ga_at_level_2(client, seeded_db):
    # GA is a level_2 title (CLAUDE.md; import_roster.py seeds all three
    # production GAs at level_2). The Team tab sent level_3 for the GA chip
    # until 2026-09, which gave every GA added there MGA-tier visibility.
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_2", io_role="GA"))
    assert r.status_code == 200
    agent = r.json()["agent"]
    assert agent["role"] == "level_2"
    assert agent["io_role"] == "GA"
    assert agent["upline_id"] == "MGA_1"


async def test_ga_cannot_be_added_at_mga_tier(client, seeded_db):
    # An MGA may not mint another level_3 from this sheet — level_3 is not
    # strictly below level_3. Guards the tier the GA chip must never send again.
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_3", io_role="GA"))
    assert r.status_code == 403


async def test_ga_added_by_ga_is_rejected(client, seeded_db):
    # GA and SA are the same tier, so a level_2 upline cannot add either —
    # only level_1 recruits. This is what stops a GA cloning their own tier.
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/team/add-person", headers=auth(token),
                          json=person(role="level_2", io_role="GA"))
    assert r.status_code == 403
