"""Shoutout pushes (owner, 2026-10-01; audience and copy 2026-10-02).

Every shoutout type pushes when it is created: Player's Club, First Deal,
Streak and a Platinum Rule post. Each goes to the registered tokens of the
active members of the person's team (sa_team_agent_ids, the grouping Missing
Numbers and the Team tab use), minus the person; a Platinum Rule goes to the
nominee's team. No token means no send, a failed send never fails the request
that made the shoutout, and a Player's Club re-run (a self-correction) that
finds the shoutout already there sends nothing.

Fixture (conftest): MCM = RGA_1 > MGA_1 > GA_1 > SA_1 > AG_1; AMP = GA_2 >
AG_2. AG_1's team is the subtree under SA_1, the nearest SA above AG_1: SA_1
and AG_1. GA_1, MGA_1 and RGA_1 share the office but are not on that team.
AG_3 (added by add_teammate) is a second agent under SA_1.
Requests go through the HTTP client, which runs a route's background tasks
before it returns, so a push is visible as soon as the call is.
"""
import logging

import pytest
import server
from conftest import auth, make_session

ALL = ["RGA_1", "MGA_1", "GA_1", "GA_2", "SA_1", "AG_1", "AG_2"]
TEAM_OF_AG_1 = ["tok_AG_3", "tok_SA_1"]  # AG_1's team minus AG_1, once AG_3 is added
BIG_DAY = 10500.0
PLAYERS_CLUB_BODY = "Agent One hit Player's Club ($10,000 in one day)"
FIRST_DEAL_BODY = "Agent One closed their first deal"
STREAK_BODY = "Agent One is on a 5-night streak"
PLATINUM_BODY = "Agent One was posted to the Platinum Wall"
REASON = "Drove two hours to cover a teammate's appointment after a family emergency."


@pytest.fixture()
def pushes(monkeypatch):
    """Every push the code under test asks for, as {tokens, title, body}. The
    upline check-in a pulse also sends is another feature; it is muted so this
    list holds shoutout pushes only."""
    sent = []

    async def fake_send(tokens, title, body):
        sent.append({"tokens": list(tokens), "title": title, "body": body})

    async def no_checkin(agent, sales_day):
        return None

    monkeypatch.setattr(server, "send_expo_push", fake_send)
    monkeypatch.setattr(server, "notify_upline_of_submission", no_checkin)
    return sent


class Deferred:
    """Stands in for FastAPI's BackgroundTasks: holds what a route queues."""

    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))

    async def run(self):
        for func, args, kwargs in self.tasks:
            await func(*args, **kwargs)


async def register(db, *agent_ids):
    for a in agent_ids:
        await db.push_tokens.insert_one({"user_id": f"u_{a}", "agent_id": a, "push_token": f"tok_{a}"})


def tokens_of(pushes):
    return sorted(t for p in pushes for t in p["tokens"])


async def add_teammate(db, agent_id="AG_3"):
    """A second agent under SA_1, so AG_1's team has two people besides AG_1."""
    await db.agent_profiles.insert_one(
        {"agent_id": agent_id, "name": "Agent Three", "email": f"{agent_id.lower()}@test.dev",
         "role": "level_1", "upline_id": "SA_1", "office": "MCM"})


async def agent_token(db, agent_id="AG_1"):
    return await make_session(db, role="level_1", agent_id=agent_id, email=f"{agent_id.lower()}@test.dev")


def days_ago(n):
    return (server.now_detroit() - server.timedelta(days=n)).date().isoformat()


async def removed_agent(db):
    """An archived profile on AG_1's team whose token row is still there:
    removing someone archives them and locks the login, but does not delete
    the token."""
    await db.agent_profiles.insert_one({
        "agent_id": "AG_X", "name": "Removed Person", "email": "x@test.dev", "role": "level_1",
        "upline_id": "SA_1", "office": "MCM", "archived": True})
    await register(db, "AG_X")


async def threshold_nomination(db, nomination_id="nom_t1", reason=REASON):
    """A nomination of AG_1 that has reached the endorsement threshold."""
    await db.nominations.insert_one({
        "nomination_id": nomination_id, "nominee_agent_id": "AG_1", "nominee_name": "Agent One",
        "nominee_office": "MCM", "nominator_agent_id": "AG_2", "nominator_name": "Agent Two",
        "reason": reason, "status": "threshold_met",
        "endorsements": [{"agent_id": a, "name": a, "ts": server.now_utc()} for a in ("GA_1", "MGA_1", "RGA_1")],
        "created_at": server.now_utc(),
    })


async def mga_token(db):
    return await make_session(db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")


def shoutout(kind="players_club", **over):
    return {"shoutout_id": "so_1", "type": kind, "agent_id": "AG_1", "agent_name": "Agent One",
            "office": "MCM", "sales_day": "2026-10-01", **over}


def players_club(**over):
    return shoutout("players_club", amount=BIG_DAY, **over)


def first_deal(**over):
    return shoutout("first_deal", **over)


def streak(**over):
    return shoutout("streak", **{"streak": 5, **over})


def platinum_rule(**over):
    return shoutout("platinum_rule", reason=REASON, **over)


# ---------------- Player's Club: the person's team ----------------

async def test_players_club_pushes_the_active_team_minus_the_person(client, seeded_db, pushes):
    await add_teammate(seeded_db)
    await seeded_db.agent_profiles.insert_one(
        {"agent_id": "AG_4", "name": "Agent Four", "email": "ag4@test.dev", "role": "level_1",
         "upline_id": "SA_1", "office": "MCM"})  # active, on the team, never registered a token
    await removed_agent(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    token = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json={"gross_alp": BIG_DAY}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "players_club", "agent_id": "AG_1"}) == 1
    assert len(pushes) == 1
    assert pushes[0]["title"] == "VantageLife"
    assert pushes[0]["body"] == PLAYERS_CLUB_BODY
    # SA_1's team minus AG_1. Not GA_1, MGA_1 or RGA_1 (same office, above the
    # SA), nobody from AMP, nobody removed, and no token means no send.
    assert tokens_of(pushes) == TEAM_OF_AG_1


async def test_an_upline_entering_the_numbers_spares_the_person_and_reaches_only_the_team(client, seeded_db, pushes):
    await add_teammate(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    ga = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/pulse", json={"gross_alp": BIG_DAY, "target_agent_id": "AG_1"}, headers=auth(ga))
    assert r.status_code == 200, r.text
    assert len(pushes) == 1 and pushes[0]["body"] == PLAYERS_CLUB_BODY
    assert tokens_of(pushes) == TEAM_OF_AG_1  # GA_1 typed it; the team is still SA_1's


async def test_a_leader_s_shoutout_goes_to_the_team_under_the_nearest_sa_or_ga(seeded_db, pushes):
    await register(seeded_db, *ALL)
    # SA_1 sits under GA_1: the team is GA_1's subtree (GA_1, SA_1, AG_1) minus SA_1.
    await server.push_shoutout(players_club(agent_id="SA_1", agent_name="Sa One"))
    assert tokens_of(pushes) == ["tok_AG_1", "tok_GA_1"]
    # AG_2 sits straight under GA_2, and AMP's team is the other office's only.
    pushes.clear()
    await server.push_shoutout(players_club(agent_id="AG_2", agent_name="Agent Two", office="AMP"))
    assert tokens_of(pushes) == ["tok_GA_2"]


async def test_under_10k_is_no_shoutout_and_no_push(client, seeded_db, pushes):
    await register(seeded_db, *ALL)
    token = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json={"gross_alp": 9999.0}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({}) == 0
    assert pushes == []


# ---------------- Platinum Rule: the nominee's team ----------------

async def test_platinum_rule_pushes_the_nominees_active_team_minus_the_nominee(client, seeded_db, pushes):
    await add_teammate(seeded_db)
    await removed_agent(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    await threshold_nomination(seeded_db)
    r = await client.post("/api/nominations/nom_t1/post-to-wall", headers=auth(await mga_token(seeded_db)))
    assert r.status_code == 200, r.text
    assert len(pushes) == 1
    assert pushes[0]["title"] == "VantageLife"
    assert pushes[0]["body"] == PLATINUM_BODY
    # The nominee's team only: the poster (MGA_1), the other office and the removed person stay out.
    assert tokens_of(pushes) == TEAM_OF_AG_1


# ---------------- First Deal and Streak push too ----------------

async def test_first_deal_and_streak_are_created_and_pushed_to_the_team(client, seeded_db, pushes, monkeypatch):
    fake_2pm = server.DETROIT_TZ.localize(server.datetime(2026, 8, 4, 14, 0))
    monkeypatch.setattr(server, "now_detroit", lambda: fake_2pm)
    await add_teammate(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    # Four earlier on-time days with no sales: today's first sale is the first
    # deal, and today is the fifth on-time day in a row.
    for n in range(1, 5):
        await seeded_db.production_entries.insert_one({
            "entry_id": f"pe_old{n}", "agent_id": "AG_1", "office": "MCM", "sales_day": days_ago(n),
            "sales": 0, "sits": 0, "gross_alp": 0, "net_alp": 0, "submitted_on_time": True})
    token = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json={"sales": 1, "sits": 2, "gross_alp": 900.0}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "first_deal"}) == 1
    assert await seeded_db.shoutouts.count_documents({"type": "streak"}) == 1
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 0
    assert sorted(p["body"] for p in pushes) == sorted([FIRST_DEAL_BODY, STREAK_BODY])
    assert all(sorted(p["tokens"]) == TEAM_OF_AG_1 for p in pushes)


async def test_first_deal_and_streak_helpers_queue_a_push_only_when_they_insert(seeded_db):
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"}, {"_id": 0})
    entry = {"agent_id": "AG_1", "sales_day": days_ago(0), "sales": 1, "sits": 1, "gross_alp": 500.0,
             "net_alp": 500.0, "office": "MCM", "submitted_on_time": True}
    await seeded_db.production_entries.insert_one(dict(entry, entry_id="pe_today"))
    for n in range(1, 5):
        await seeded_db.production_entries.insert_one(dict(
            entry, entry_id=f"pe_o{n}", sales_day=days_ago(n), sales=0, gross_alp=0.0, net_alp=0.0))
    queued = server.BackgroundTasks()
    await server.maybe_trigger_shoutouts(agent, entry, queued)
    assert len(queued.tasks) == 2  # first deal and a 5-night streak, both new
    await server.maybe_trigger_shoutouts(agent, entry, queued)
    assert len(queued.tasks) == 2  # both already there: nothing more is queued


@pytest.mark.parametrize("kind", ["something_added_later", "", None])
async def test_a_type_nobody_listed_does_not_push(seeded_db, pushes, kind):
    await register(seeded_db, *ALL)
    await server.push_shoutout(shoutout(kind))
    assert pushes == []


# ---------------- no token, no team, no push ----------------

async def test_no_tokens_means_no_push_and_no_error(client, seeded_db, pushes):
    token = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json={"gross_alp": BIG_DAY}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 1
    await threshold_nomination(seeded_db)
    r = await client.post("/api/nominations/nom_t1/post-to-wall", headers=auth(await mga_token(seeded_db)))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "platinum_rule"}) == 1
    assert pushes == []
    # Nothing was logged as sent either, so a token that registers later is not blocked.
    assert await seeded_db.notification_log.count_documents({"stage": {"$regex": "^shoutout_"}}) == 0


async def test_a_token_that_only_the_person_holds_sends_nothing(seeded_db, pushes):
    await register(seeded_db, "AG_1")
    await server.push_shoutout(players_club())
    await server.push_shoutout(platinum_rule(), "nom_1")
    assert pushes == []


async def test_a_person_with_no_one_on_their_team_pushes_nobody(seeded_db, pushes):
    await register(seeded_db, *ALL)
    # RGA_1 has no upline, so the team is just them.
    await server.push_shoutout(players_club(agent_id="RGA_1", agent_name="Rga One"))
    await server.push_shoutout(shoutout("streak", agent_id="RGA_1", agent_name="Rga One", streak=6))
    assert pushes == []


async def test_a_shoutout_without_a_person_pushes_nobody(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await server.push_shoutout(players_club(agent_id=None))
    assert pushes == []


# ---------------- a failed push never fails the request ----------------

@pytest.mark.parametrize("breaks", ["send_expo_push", "shoutout_team_recipient_ids"])
async def test_a_failing_push_never_fails_a_players_club_request(client, seeded_db, pushes, monkeypatch, caplog, breaks):
    await register(seeded_db, *ALL)

    async def boom(*args, **kwargs):
        raise RuntimeError("expo is down")

    monkeypatch.setattr(server, breaks, boom)
    caplog.set_level(logging.WARNING, logger="server")
    token = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json={"gross_alp": BIG_DAY}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["entry"]["gross_alp"] == BIG_DAY
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 1
    assert "Shoutout push failed" in caplog.text


@pytest.mark.parametrize("breaks", ["send_expo_push", "shoutout_team_recipient_ids"])
async def test_a_failing_push_never_fails_a_platinum_post(client, seeded_db, pushes, monkeypatch, caplog, breaks):
    await register(seeded_db, *ALL)

    async def boom(*args, **kwargs):
        raise RuntimeError("expo is down")

    monkeypatch.setattr(server, breaks, boom)
    caplog.set_level(logging.WARNING, logger="server")
    await threshold_nomination(seeded_db)
    r = await client.post("/api/nominations/nom_t1/post-to-wall", headers=auth(await mga_token(seeded_db)))
    assert r.status_code == 200, r.text
    assert r.json()["shoutout"]["type"] == "platinum_rule"
    assert await seeded_db.shoutouts.count_documents({"type": "platinum_rule"}) == 1
    assert (await seeded_db.nominations.find_one({"nomination_id": "nom_t1"}))["status"] == "posted"
    assert "Shoutout push failed" in caplog.text


# ---------------- corrections ----------------

async def test_a_correction_that_first_takes_the_day_over_10k_pushes_once(client, seeded_db, pushes):
    await add_teammate(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    token = await agent_token(seeded_db)
    sd = days_ago(1)
    r = await client.post("/api/pulse", json={"gross_alp": 2500.0, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert pushes == []
    r = await client.post("/api/pulse/correct", json={"gross_alp": 12000.0, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert len(pushes) == 1 and pushes[0]["body"] == PLAYERS_CLUB_BODY  # the line, not the corrected $12,000
    assert tokens_of(pushes) == TEAM_OF_AG_1
    # Correcting again finds the shoutout already there.
    r = await client.post("/api/pulse/correct", json={"gross_alp": 13000.0, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert len(pushes) == 1


async def test_a_correction_that_finds_the_shoutout_already_there_sends_nothing(client, seeded_db, pushes):
    await register(seeded_db, *ALL)
    token = await agent_token(seeded_db)
    sd = days_ago(1)
    r = await client.post("/api/pulse", json={"gross_alp": 11000.0, "sales_day": sd}, headers=auth(token))
    assert r.status_code == 200, r.text
    assert len(pushes) == 1  # the entry itself pushed, once
    # Forget that send, so that only "nothing was inserted" can keep the count at one.
    await seeded_db.notification_log.delete_many({"stage": "shoutout_players_club"})
    for alp in (12000.0, 8000.0):  # up, then back under the line
        r = await client.post("/api/pulse/correct", json={"gross_alp": alp, "sales_day": sd}, headers=auth(token))
        assert r.status_code == 200, r.text
    assert len(pushes) == 1
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 1


async def test_the_helper_queues_a_push_only_when_it_inserts_a_shoutout(seeded_db):
    agent = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"}, {"_id": 0})
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_1", "agent_id": "AG_1", "office": "MCM", "sales_day": "2026-08-03",
        "sales": 0, "sits": 0, "gross_alp": 11000.0, "net_alp": 11000.0})
    queued = server.BackgroundTasks()
    await server.maybe_trigger_players_club(agent, "2026-08-03", queued)
    assert len(queued.tasks) == 1
    await server.maybe_trigger_players_club(agent, "2026-08-03", queued)  # already there: a no-op
    assert len(queued.tasks) == 1
    await server.maybe_trigger_players_club(agent, "2026-08-02", queued)  # no production that day
    assert len(queued.tasks) == 1


# ---------------- after the response ----------------

async def test_the_pulse_route_queues_the_push_instead_of_sending_it(seeded_db, pushes):
    await register(seeded_db, *ALL)
    deferred = Deferred()
    user = {"user_id": "user_level_1_AG_1", "name": "Agent One", "role": "level_1", "agent_id": "AG_1"}
    r = await server.submit_pulse(server.PulseIn(gross_alp=BIG_DAY), deferred, user)
    assert r["ok"] is True
    assert pushes == [] and len(deferred.tasks) == 1  # the response is ready and nothing has gone out
    await deferred.run()
    assert len(pushes) == 1 and pushes[0]["body"] == PLAYERS_CLUB_BODY


async def test_the_post_route_queues_the_push_instead_of_sending_it(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await threshold_nomination(seeded_db)
    deferred = Deferred()
    user = {"user_id": "user_level_3_MGA_1", "name": "Mga One", "role": "level_3", "agent_id": "MGA_1"}
    r = await server.post_nomination_to_wall("nom_t1", deferred, user)
    assert r["ok"] is True
    assert pushes == [] and len(deferred.tasks) == 1
    await deferred.run()
    assert len(pushes) == 1 and pushes[0]["body"] == PLATINUM_BODY


# ---------------- one push per shoutout ----------------

async def test_one_player_and_day_never_pushes_twice(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await server.push_shoutout(players_club())
    await server.push_shoutout(players_club(shoutout_id="so_2"))  # a racing duplicate insert
    assert len(pushes) == 1
    await server.push_shoutout(players_club(shoutout_id="so_3", sales_day="2026-10-02"))  # another day
    assert len(pushes) == 2


async def test_a_first_deal_pushes_once_per_person(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await server.push_shoutout(first_deal())
    await server.push_shoutout(first_deal(shoutout_id="so_2"))  # a racing duplicate insert
    assert len(pushes) == 1 and pushes[0]["body"] == FIRST_DEAL_BODY


async def test_a_streak_pushes_once_per_length(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await server.push_shoutout(streak())
    await server.push_shoutout(streak(shoutout_id="so_2"))  # a racing duplicate insert
    assert len(pushes) == 1 and pushes[0]["body"] == STREAK_BODY
    await server.push_shoutout(streak(shoutout_id="so_3", sales_day="2026-10-02", streak=6))  # the next night
    assert len(pushes) == 2 and pushes[1]["body"] == "Agent One is on a 6-night streak"


async def test_one_nomination_pushes_once_and_a_second_one_pushes_again(seeded_db, pushes):
    await register(seeded_db, *ALL)
    await server.push_shoutout(platinum_rule(), "nom_1")
    await server.push_shoutout(platinum_rule(shoutout_id="so_1b"), "nom_1")  # a double tap
    assert len(pushes) == 1
    await server.push_shoutout(platinum_rule(shoutout_id="so_2"), "nom_2")  # same person, same day, new nomination
    assert len(pushes) == 2


# ---------------- Expo: logging and the 100-message limit ----------------

class _ExpoReply:
    def __init__(self, tickets):
        self._tickets = tickets

    def json(self):
        return {"data": self._tickets}


class _ExpoRecorder:
    """Stands in for httpx.AsyncClient against Expo: records each request's
    messages and answers every one with an ok ticket."""

    def __init__(self, requests):
        self.requests = requests

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json, headers):
        self.requests.append(json)
        return _ExpoReply([{"status": "ok", "id": f"r{i}"} for i, _ in enumerate(json)])


async def test_every_send_is_logged_and_a_large_team_push_goes_out_in_slices(seeded_db, monkeypatch):
    requests = []
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kw: _ExpoRecorder(requests))
    await seeded_db.agent_profiles.insert_many([
        {"agent_id": f"X{i}", "name": f"Extra {i}", "email": f"x{i}@test.dev", "role": "level_1",
         "upline_id": "SA_1", "office": "MCM"} for i in range(150)])
    await seeded_db.push_tokens.insert_many([
        {"user_id": f"ux{i}", "agent_id": f"X{i}", "push_token": f"tok_x{i}"} for i in range(150)])
    await server.push_shoutout(platinum_rule(), "nom_1")
    # Expo takes 100 messages a request at most; 150 recipients are two requests.
    assert [len(batch) for batch in requests] == [100, 50]
    assert {m["title"] for batch in requests for m in batch} == {"VantageLife"}
    rows = [r async for r in seeded_db.push_log.find({}, {"_id": 0})]
    assert len(rows) == 150
    assert {r["status"] for r in rows} == {"ok"}
    assert {r["title"] for r in rows} == {"VantageLife"}
    assert {r["body"] for r in rows} == {PLATINUM_BODY}
    assert {r["agent_id"] for r in rows} == {f"X{i}" for i in range(150)}
    sent = await seeded_db.notification_log.find_one({"stage": "shoutout_platinum_rule:nom_1"}, {"_id": 0})
    assert sent["agent_id"] == "AG_1" and sent["sales_day"] == "2026-10-01"


async def test_a_players_club_send_is_logged_for_the_team_only(seeded_db, monkeypatch):
    requests = []
    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kw: _ExpoRecorder(requests))
    await add_teammate(seeded_db)
    await register(seeded_db, *ALL, "AG_3")
    await server.push_shoutout(players_club())
    assert [sorted(m["to"] for m in batch) for batch in requests] == [TEAM_OF_AG_1]
    rows = [r async for r in seeded_db.push_log.find({}, {"_id": 0})]
    assert sorted(r["agent_id"] for r in rows) == ["AG_3", "SA_1"]
    assert {r["body"] for r in rows} == {PLAYERS_CLUB_BODY}
    sent = await seeded_db.notification_log.find_one({"stage": "shoutout_players_club"}, {"_id": 0})
    assert sent["agent_id"] == "AG_1" and sent["sales_day"] == "2026-10-01"


# ---------------- copy ----------------

def test_copy_names_the_person_and_uses_the_shoutouts_tab_labels():
    assert server._players_club_push_body("Marcus Alwatan") == "Marcus Alwatan hit Player's Club ($10,000 in one day)"
    assert server._first_deal_push_body("Marcus Alwatan") == "Marcus Alwatan closed their first deal"
    assert server._streak_push_body("Marcus Alwatan", 7) == "Marcus Alwatan is on a 7-night streak"
    assert server._platinum_rule_push_body("Joylynn Harris") == "Joylynn Harris was posted to the Platinum Wall"
    assert server.SHOUTOUT_PUSH_TITLE == "VantageLife"


def test_the_player_s_club_push_names_the_line_not_the_persons_total():
    assert server.PLAYERS_CLUB_DAILY_ALP == 10000
    body = server._players_club_push_body("Marcus Alwatan")
    assert f"${server.PLAYERS_CLUB_DAILY_ALP:,} in one day" in body
    assert "10,500" not in body  # BIG_DAY's total is never in the copy
