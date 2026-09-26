"""The morning tenure nudge (owner, 2026-09-24).

With the 06:30 Detroit job, every upline gets ONE push naming the people
under them whose tenure nobody has set, every day until it is set. Recipient
is the nearest SA or GA in the chain, otherwise the MGA or RGA the person
reports to directly (the Missing Numbers grouping). Archived and
non-producing profiles are skipped; leaders are never candidates.

Fixture: RGA_1 -> MGA_1 -> {GA_1 -> SA_1 -> AG_1, GA_2 -> AG_2}, tenure unset everywhere.
"""
from datetime import datetime

import pytz

import server

DETROIT = pytz.timezone("America/Detroit")


def _at(hour, minute, day=27):
    return DETROIT.localize(datetime(2026, 7, day, hour, minute, 0))


async def token_for(db, agent_id):
    await db.push_tokens.insert_one({"user_id": f"u_{agent_id}", "agent_id": agent_id, "push_token": f"ExponentPushToken[{agent_id}]"})


def capture(monkeypatch):
    sent = []

    async def fake_send(tokens, title, body):
        sent.append((tuple(tokens), title, body))
    monkeypatch.setattr(server, "send_expo_push", fake_send)
    return sent


async def test_nothing_before_0630(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db, "SA_1")
    r = await server.run_tenure_nudge(_at(6, 29))
    assert r["due"] is False and sent == []


async def test_one_push_per_upline_naming_everyone_with_the_approved_copy(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "AG_3", "name": "Zed Third", "role": "level_1", "upline_id": "SA_1", "office": "MCM"})
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"name": "Agent One"}})
    await token_for(seeded_db, "SA_1")
    await token_for(seeded_db, "GA_2")
    r = await server.run_tenure_nudge(_at(6, 30))
    assert r["due"] is True and r["notified"] == 2
    by_token = {s[0][0]: s for s in sent}
    assert by_token["ExponentPushToken[SA_1]"][1] == "VantageLife"
    assert by_token["ExponentPushToken[SA_1]"][2] == \
        "Tenure not set: Agent One, Zed Third. Open their card on the Team tab to mark Rookie or Veteran."
    assert by_token["ExponentPushToken[GA_2]"][2] == \
        "Tenure not set: Agent Two. Open their card on the Team tab to mark Rookie or Veteran."


async def test_once_a_day_until_set_then_it_stops(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db, "SA_1")
    await token_for(seeded_db, "GA_2")
    assert (await server.run_tenure_nudge(_at(6, 30)))["notified"] == 2
    assert (await server.run_tenure_nudge(_at(9, 0)))["notified"] == 0     # same day: logged already
    assert len(sent) == 2
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"is_rookie": True}})
    r = await server.run_tenure_nudge(_at(6, 30, day=28))                    # next morning
    assert r["notified"] == 1 and sent[-1][0] == ("ExponentPushToken[GA_2]",)


async def test_falls_back_to_the_mga_or_rga_when_no_sa_or_ga_is_above(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "AG_D", "name": "Direct Report", "role": "level_1", "upline_id": "MGA_1", "office": "MCM"})
    await token_for(seeded_db, "MGA_1")
    r = await server.run_tenure_nudge(_at(7, 0))
    assert r["notified"] == 1
    assert sent[0][0] == ("ExponentPushToken[MGA_1]",) and "Direct Report" in sent[0][2]


async def test_archived_non_producing_leaders_and_set_people_are_never_candidates(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"non_producing": True}})
    # GA_1 and SA_1 have no tenure either, but leaders are never in the group.
    await token_for(seeded_db, "SA_1")
    await token_for(seeded_db, "GA_1")
    await token_for(seeded_db, "GA_2")
    await token_for(seeded_db, "MGA_1")
    r = await server.run_tenure_nudge(_at(7, 0))
    assert r["uplines"] == 0 and r["notified"] == 0 and sent == []


async def test_an_upline_with_no_push_token_is_counted_not_crashed(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    r = await server.run_tenure_nudge(_at(7, 0))
    assert r["uplines"] == 2 and r["notified"] == 0 and r["skipped_no_token"] == 2 and sent == []


async def test_admin_manual_trigger(client, seeded_db, monkeypatch):
    from conftest import auth, make_session
    capture(monkeypatch)
    monkeypatch.setattr(server, "now_detroit", lambda: _at(7, 0))
    await seeded_db.users.insert_one({"user_id": "u_admin", "email": "admin@test.dev", "name": "Admin", "role": "pending", "is_admin": True})
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    await seeded_db.users.update_one({"email": "rga1@test.dev"}, {"$set": {"is_admin": True}})
    r = await client.post("/api/admin/run-tenure-nudge", headers=auth(token))
    assert r.status_code == 200 and r.json()["due"] is True
