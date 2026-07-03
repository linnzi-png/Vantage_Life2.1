"""Platinum Rule nominations: create, scoped visibility, endorse threshold, wall posting."""
import pytest

from conftest import auth, make_session

REASON = "Drove two hours to cover a teammate's appointment after a family emergency."


async def nominate(client, db, nominee="AG_1"):
    """AG_2 nominates `nominee`; returns (nomination_id, nominator_token)."""
    tok = await make_session(db, role="level_1", agent_id="AG_2", email="ag2@test.dev")
    r = await client.post("/api/nominations", json={"nominee_agent_id": nominee, "reason": REASON}, headers=auth(tok))
    assert r.status_code == 200, r.text
    return r.json()["nomination"]["nomination_id"], tok


async def test_any_agent_can_nominate(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db)
    nom = await seeded_db.nominations.find_one({"nomination_id": nom_id}, {"_id": 0})
    assert nom["status"] == "open"
    assert nom["nominee_agent_id"] == "AG_1"
    assert nom["reason"] == REASON


async def test_self_nomination_blocked(client, seeded_db):
    tok = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/nominations", json={"nominee_agent_id": "AG_1", "reason": REASON}, headers=auth(tok))
    assert r.status_code == 400


async def test_short_reason_rejected(client, seeded_db):
    tok = await make_session(seeded_db, role="level_1", agent_id="AG_2", email="ag2@test.dev")
    r = await client.post("/api/nominations", json={"nominee_agent_id": "AG_1", "reason": "nice"}, headers=auth(tok))
    assert r.status_code == 422


async def test_unknown_nominee_404(client, seeded_db):
    tok = await make_session(seeded_db, role="level_1", agent_id="AG_2", email="ag2@test.dev")
    r = await client.post("/api/nominations", json={"nominee_agent_id": "NOPE", "reason": REASON}, headers=auth(tok))
    assert r.status_code == 404


async def test_list_requires_ga_and_is_scoped(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db, nominee="AG_1")  # AG_1 is under GA_1

    # level_1 can't read the inbox at all
    ag = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1b@test.dev")
    assert (await client.get("/api/nominations", headers=auth(ag))).status_code == 403

    # GA_1 (nominee's upline) sees it
    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    got = (await client.get("/api/nominations", headers=auth(ga1))).json()["nominations"]
    assert [n["nomination_id"] for n in got] == [nom_id]

    # GA_2 (sibling team) does NOT see it
    ga2 = await make_session(seeded_db, role="level_2", agent_id="GA_2", email="ga2b@test.dev")
    assert (await client.get("/api/nominations", headers=auth(ga2))).json()["nominations"] == []

    # RGA sees everything
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert len((await client.get("/api/nominations", headers=auth(rga))).json()["nominations"]) == 1


async def test_endorse_dedup_and_threshold_flip(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db)
    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    mga = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")

    r1 = await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(ga1))
    assert r1.status_code == 200 and r1.json()["status"] == "open"

    # Same endorser twice → rejected
    dup = await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(ga1))
    assert dup.status_code == 400

    r2 = await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(mga))
    assert r2.json()["status"] == "open" and r2.json()["endorsement_count"] == 2

    # Third endorsement crosses the threshold
    r3 = await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(rga))
    assert r3.json()["status"] == "threshold_met" and r3.json()["endorsement_count"] == 3


async def test_level_1_cannot_endorse(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db)
    ag = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(ag))).status_code == 403


async def test_sibling_ga_cannot_endorse_outside_team(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db, nominee="AG_1")
    ga2 = await make_session(seeded_db, role="level_2", agent_id="GA_2", email="ga2b@test.dev")
    assert (await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(ga2))).status_code == 403


async def endorse_to_threshold(client, db, nom_id):
    for role, aid, mail in [("level_2", "GA_1", "e1@test.dev"), ("level_3", "MGA_1", "e2@test.dev"), ("level_4", "RGA_1", "e3@test.dev")]:
        tok = await make_session(db, role=role, agent_id=aid, email=mail)
        r = await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(tok))
        assert r.status_code == 200
    return tok  # rga token


async def test_post_to_wall_requires_threshold_and_level_3(client, seeded_db):
    nom_id, _ = await nominate(client, seeded_db)
    mga = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")

    # Below threshold → 400
    early = await client.post(f"/api/nominations/{nom_id}/post-to-wall", headers=auth(mga))
    assert early.status_code == 400

    await endorse_to_threshold(client, seeded_db, nom_id)

    # GA (level_2) can endorse but NOT post
    ga1 = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1c@test.dev")
    assert (await client.post(f"/api/nominations/{nom_id}/post-to-wall", headers=auth(ga1))).status_code == 403

    # MGA posts → platinum_rule shoutout lands on the wall
    r = await client.post(f"/api/nominations/{nom_id}/post-to-wall", headers=auth(mga))
    assert r.status_code == 200, r.text
    so = r.json()["shoutout"]
    assert so["type"] == "platinum_rule" and so["agent_id"] == "AG_1" and so["reason"] == REASON

    wall = await seeded_db.shoutouts.find_one({"type": "platinum_rule"}, {"_id": 0})
    assert wall is not None and wall["endorsement_count"] == 3

    # Nomination closed; can't post twice or endorse further
    nom = await seeded_db.nominations.find_one({"nomination_id": nom_id}, {"_id": 0})
    assert nom["status"] == "posted"
    again = await client.post(f"/api/nominations/{nom_id}/post-to-wall", headers=auth(mga))
    assert again.status_code == 400
    late = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="late@test.dev")
    assert (await client.post(f"/api/nominations/{nom_id}/endorse", headers=auth(late))).status_code == 400
