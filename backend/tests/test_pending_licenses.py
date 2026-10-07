"""Pending licenses and the weekly follow-up reminder (Linnzi, 2026-09-29).

A pending state is applied for and not yet issued. A code is never both active
and pending; issuing moves it. When a pending state is added, a push goes to
the agent every 7 days from the day it was added, until it is made active or
removed, if the "Remind me weekly to follow up" switch is on (default on).
One push per agent lists every code due that morning.
"""
from datetime import datetime

import pytz

import server
from conftest import auth, make_session

DETROIT = pytz.timezone("America/Detroit")


def _at(day, hour=6, minute=30, month=10):
    return DETROIT.localize(datetime(2026, month, day, hour, minute, 0))


async def mine(client, db, **body):
    token = await make_session(db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    body.setdefault("licensed_states", [])
    return await client.post("/api/me/licensed-states", headers=auth(token), json=body)


async def prof(db):
    return await db.agent_profiles.find_one({"agent_id": "AG_1"}, {"_id": 0})


def capture(monkeypatch):
    sent = []

    async def fake_send(tokens, title, body):
        sent.append((tuple(tokens), title, body))
    monkeypatch.setattr(server, "send_expo_push", fake_send)
    return sent


async def token_for(db, agent_id="AG_1"):
    await db.push_tokens.insert_one({"user_id": f"u_{agent_id}", "agent_id": agent_id, "push_token": f"ExponentPushToken[{agent_id}]"})


# ---------------- saving pending states ----------------

async def test_pending_states_save_with_the_day_they_were_added_and_the_switch_on(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "current_sales_day_str", lambda: "2026-10-01")
    r = await mine(client, seeded_db, licensed_states=["MI"], pending_states=["ne", "IA"])
    assert r.status_code == 200 and r.json()["pending_states"] == ["IA", "NE"]
    p = await prof(seeded_db)
    assert p["pending_added_at"] == {"IA": "2026-10-01", "NE": "2026-10-01"}
    assert p["pending_reminder"] == {"IA": True, "NE": True}


async def test_a_code_is_never_both_active_and_pending(client, seeded_db):
    await mine(client, seeded_db, licensed_states=["MI"], pending_states=["MI", "IA"])
    assert (await prof(seeded_db))["pending_states"] == ["IA"]


async def test_issuing_a_license_moves_it_from_pending_to_active(client, seeded_db):
    await mine(client, seeded_db, licensed_states=["MI"], pending_states=["IA", "NE"])
    # A build that predates pending states sends only the active list.
    await mine(client, seeded_db, licensed_states=["MI", "IA"])
    p = await prof(seeded_db)
    assert p["licensed_states"] == ["IA", "MI"] and p["pending_states"] == ["NE"]
    assert "IA" not in p["pending_added_at"] and "IA" not in p["pending_reminder"]


async def test_an_old_build_that_sends_no_pending_list_leaves_it_alone(client, seeded_db):
    await mine(client, seeded_db, pending_states=["IA"])
    await mine(client, seeded_db, licensed_states=["MI"])
    assert (await prof(seeded_db))["pending_states"] == ["IA"]


async def test_a_code_keeps_the_day_it_was_first_added(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "current_sales_day_str", lambda: "2026-10-01")
    await mine(client, seeded_db, pending_states=["IA"])
    monkeypatch.setattr(server, "current_sales_day_str", lambda: "2026-10-05")
    await mine(client, seeded_db, pending_states=["IA", "NE"])
    assert (await prof(seeded_db))["pending_added_at"] == {"IA": "2026-10-01", "NE": "2026-10-05"}


async def test_removing_a_pending_state_clears_its_reminder(client, seeded_db):
    await mine(client, seeded_db, pending_states=["IA", "NE"])
    await mine(client, seeded_db, pending_states=["NE"])
    p = await prof(seeded_db)
    assert p["pending_states"] == ["NE"] and set(p["pending_reminder"]) == {"NE"}


async def test_the_switch_off_is_stored_and_read_back(client, seeded_db):
    await mine(client, seeded_db, pending_states=["IA"], pending_reminder=False)
    assert (await prof(seeded_db))["pending_reminder"] == {"IA": False}
    assert server.pending_reminder_on(await prof(seeded_db)) is False


async def test_an_unknown_pending_code_is_a_400(client, seeded_db):
    assert (await mine(client, seeded_db, pending_states=["ZZ"])).status_code == 400


async def test_a_leader_sets_pending_for_their_downline_and_it_is_audited(client, seeded_db):
    token = await make_session(seeded_db, role="level_2", agent_id="GA_1", email="ga1@test.dev")
    r = await client.post("/api/team/set-licensed-states", headers=auth(token),
                          json={"agent_id": "AG_1", "licensed_states": ["MI"], "pending_states": ["IA"]})
    assert r.status_code == 200 and r.json()["pending_states"] == ["IA"]
    row = await seeded_db.audit_log.find_one({"action": "set_licensed_states", "agent_id": "AG_1"})
    assert row["new_value"] == ["MI"] and row["new_pending"] == ["IA"] and row["original_pending"] == []


# ---------------- which codes are due ----------------

def due(added, today, **over):
    prof = {"pending_states": ["IA"], "pending_added_at": {"IA": added}, "pending_reminder": {"IA": True}}
    prof.update(over)
    return server.pending_codes_due(prof, today)


def test_due_on_days_7_14_and_21_and_not_between():
    assert due("2026-10-01", "2026-10-08") == ["IA"]
    assert due("2026-10-01", "2026-10-15") == ["IA"]
    assert due("2026-10-01", "2026-10-22") == ["IA"]
    for today in ("2026-10-01", "2026-10-02", "2026-10-07", "2026-10-09", "2026-10-14", "2026-10-16"):
        assert due("2026-10-01", today) == []


def test_the_switch_off_means_no_reminder():
    assert due("2026-10-01", "2026-10-08", pending_reminder={"IA": False}) == []


def test_a_code_no_longer_pending_is_never_due():
    assert due("2026-10-01", "2026-10-08", pending_states=[]) == []


def test_a_missing_or_bad_date_is_skipped_not_an_error():
    assert due(None, "2026-10-08") == []
    assert due("not-a-date", "2026-10-08") == []


# ---------------- the 06:30 job ----------------

async def pend(db, codes, added, reminder=True):
    await db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {
        "pending_states": sorted(codes),
        "pending_added_at": {c: added for c in codes},
        "pending_reminder": {c: reminder for c in codes}}})


async def test_nothing_before_0630(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA"], "2026-10-01")
    r = await server.run_pending_license_reminders(_at(8, 6, 29))
    assert r["due"] is False and sent == []


async def test_fires_on_day_7_14_and_21_with_the_approved_copy(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["NE", "IA"], "2026-10-01")
    for day in (8, 15, 22):
        assert (await server.run_pending_license_reminders(_at(day)))["notified"] == 1
    assert [s[2] for s in sent] == ["Follow up on your pending license: IA, NE"] * 3
    assert sent[0][1] == "VantageLife"


async def test_quiet_on_the_days_between(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA"], "2026-10-01")
    for day in (2, 7, 9, 14):
        assert (await server.run_pending_license_reminders(_at(day)))["notified"] == 0
    assert sent == []


async def test_one_push_per_agent_and_once_a_day(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA", "NE"], "2026-10-01")
    assert (await server.run_pending_license_reminders(_at(8)))["notified"] == 1
    assert (await server.run_pending_license_reminders(_at(8, 9, 0)))["notified"] == 0
    assert len(sent) == 1


async def test_a_code_moved_to_active_stops_the_reminder(client, seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA"], "2026-10-01")
    await mine(client, seeded_db, licensed_states=["IA"])
    assert (await server.run_pending_license_reminders(_at(8)))["notified"] == 0
    assert sent == []


async def test_the_switch_off_stops_the_reminder(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA"], "2026-10-01", reminder=False)
    assert (await server.run_pending_license_reminders(_at(8)))["notified"] == 0
    assert sent == []


async def test_an_archived_agent_is_not_reminded(seeded_db, monkeypatch):
    sent = capture(monkeypatch)
    await token_for(seeded_db)
    await pend(seeded_db, ["IA"], "2026-10-01")
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    assert (await server.run_pending_license_reminders(_at(8)))["notified"] == 0
