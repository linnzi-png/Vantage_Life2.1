"""Push token registration and the 9 PM escalation scheduler.

run_pulse_escalation_check() is tested directly (not through the 60s loop) by
monkeypatching now_detroit() to land inside a specific stage's fire window.
"""
from datetime import datetime
import pytz
import server
from conftest import auth, make_session

DETROIT = pytz.timezone("America/Detroit")


def _at(hour, minute):
    return DETROIT.localize(datetime(2026, 7, 27, hour, minute, 0))


# ---------------- push token registration ----------------

async def test_register_push_token(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.post("/api/push/register", json={"push_token": "ExponentPushToken[abc]"}, headers=auth(token))
    assert r.status_code == 200
    doc = await seeded_db.push_tokens.find_one({"user_id": "user_level_1_AG_1"})
    assert doc["push_token"] == "ExponentPushToken[abc]"
    assert doc["agent_id"] == "AG_1"


async def test_register_push_token_upserts(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await client.post("/api/push/register", json={"push_token": "old"}, headers=auth(token))
    await client.post("/api/push/register", json={"push_token": "new"}, headers=auth(token))
    docs = [d async for d in seeded_db.push_tokens.find({"user_id": "user_level_1_AG_1"})]
    assert len(docs) == 1 and docs[0]["push_token"] == "new"


async def test_unregister_push_token(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await client.post("/api/push/register", json={"push_token": "abc"}, headers=auth(token))
    r = await client.post("/api/push/unregister", headers=auth(token))
    assert r.status_code == 200
    assert await seeded_db.push_tokens.find_one({"user_id": "user_level_1_AG_1"}) is None


# ---------------- escalation stage matching ----------------

def test_stage_matches_within_fire_window():
    assert server._current_escalation_stage(_at(21, 2))["stage"] == "reminder"
    assert server._current_escalation_stage(_at(21, 30))["stage"] == "overdue"
    assert server._current_escalation_stage(_at(23, 30))["stage"] == "window_closing"


def test_stage_none_outside_any_window():
    assert server._current_escalation_stage(_at(21, 10)) is None
    assert server._current_escalation_stage(_at(20, 59)) is None


# ---------------- run_pulse_escalation_check ----------------

async def test_escalation_skips_agents_who_already_submitted(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 0))
    async def fake_send(tokens, title, body):
        pass
    monkeypatch.setattr(server, "send_expo_push", fake_send)
    today = server.current_sales_day_str()
    await seeded_db.production_entries.insert_one({
        "entry_id": "e1", "agent_id": "AG_1", "office": "MCM", "sales_day": today,
        "sets": 1, "sits": 1, "sales": 1, "n1": 0, "gross_alp": 100, "net_alp": 100,
    })
    result = await server.run_pulse_escalation_check()
    assert result["stage"] == "reminder"
    # Candidates are all level_1/level_2 agents: AG_1, AG_2, GA_1, GA_2, SA_1.
    # AG_1 submitted, so the remaining 4 are still missing their own reminder.
    assert result["agent_notified"] == 4


async def test_escalation_never_checks_mga_or_rga_for_their_own_pulse(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 0))
    result = await server.run_pulse_escalation_check()
    # Candidates are level_1/level_2 only: AG_1, AG_2, GA_1, GA_2, SA_1 — never MGA_1/RGA_1.
    assert result["agent_notified"] == 5
    # 9:00 PM has ancestor_reach 0 — no upline messages fire at all yet.
    assert result["upline_notified"] == 0


async def test_escalation_is_idempotent_same_stage_same_day(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 0))
    async def fake_send(tokens, title, body):
        pass
    monkeypatch.setattr(server, "send_expo_push", fake_send)
    first = await server.run_pulse_escalation_check()
    second = await server.run_pulse_escalation_check()
    assert first["agent_notified"] > 0
    assert second["agent_notified"] == 0  # notification_log blocks the resend


async def test_agent_gets_personal_wording_not_upline_wording(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 30))  # "overdue", reach=1
    # SA_1 has already submitted their own numbers, so the only message they
    # get is the roll-call about AG_1 — isolates the two message types cleanly.
    # (now_detroit is patched first so current_sales_day_str() reflects the
    # same fixed date the check itself will use.)
    await seeded_db.production_entries.insert_one({
        "entry_id": "e_sa1", "agent_id": "SA_1", "office": "MCM", "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 1, "sales": 1, "n1": 0, "gross_alp": 100, "net_alp": 100,
    })
    await seeded_db.push_tokens.insert_many([
        {"user_id": "u_ag1", "agent_id": "AG_1", "push_token": "tok_ag1"},
        {"user_id": "u_sa1", "agent_id": "SA_1", "push_token": "tok_sa1"},
    ])
    captured = []
    async def fake_send(tokens, title, body):
        captured.append((set(tokens), body))
    monkeypatch.setattr(server, "send_expo_push", fake_send)

    await server.run_pulse_escalation_check()

    agent_msg = next(body for tokens, body in captured if tokens == {"tok_ag1"})
    upline_msg = next(body for tokens, body in captured if tokens == {"tok_sa1"})
    assert agent_msg == "Your 9 PM pulse is late. Submit now to keep your streak."
    assert upline_msg == "Agent One has not submitted numbers."
    assert agent_msg != upline_msg


async def test_mga_excluded_from_upline_reach_before_final_stage(seeded_db, monkeypatch):
    # 10:30 PM would reach 3 ancestors by depth (SA, GA, MGA) under the old
    # design — MGA must now be filtered out until the final stage.
    monkeypatch.setattr(server, "now_detroit", lambda: _at(22, 30))
    await seeded_db.push_tokens.insert_many([
        {"user_id": "u_sa1", "agent_id": "SA_1", "push_token": "tok_sa1"},
        {"user_id": "u_ga1", "agent_id": "GA_1", "push_token": "tok_ga1"},
        {"user_id": "u_mga1", "agent_id": "MGA_1", "push_token": "tok_mga1"},
    ])
    captured = []
    async def fake_send(tokens, title, body):
        captured.append(set(tokens))
    monkeypatch.setattr(server, "send_expo_push", fake_send)

    await server.run_pulse_escalation_check()

    all_notified = set().union(*captured) if captured else set()
    assert "tok_sa1" in all_notified
    assert "tok_ga1" in all_notified
    assert "tok_mga1" not in all_notified  # excluded — not the final stage yet


async def test_mga_and_rga_included_at_final_stage(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(23, 30))  # window_closing, full chain
    await seeded_db.push_tokens.insert_many([
        {"user_id": "u_mga1", "agent_id": "MGA_1", "push_token": "tok_mga1"},
        {"user_id": "u_rga1", "agent_id": "RGA_1", "push_token": "tok_rga1"},
    ])
    captured = []
    async def fake_send(tokens, title, body):
        captured.append(set(tokens))
    monkeypatch.setattr(server, "send_expo_push", fake_send)

    await server.run_pulse_escalation_check()

    all_notified = set().union(*captured) if captured else set()
    assert "tok_mga1" in all_notified
    assert "tok_rga1" in all_notified


async def test_upline_gets_one_consolidated_message_naming_every_missing_downline(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 30))  # reach=1: direct upline only
    # Give SA_1 a second direct report so one upline has two missing agents.
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "AG_3", "name": "Agent Three", "email": "ag3@test.dev",
        "role": "level_1", "upline_id": "SA_1", "office": "MCM",
    })
    # SA_1 already submitted their own numbers — isolates the roll-call push
    # about their downline from their own personal reminder. now_detroit is
    # already patched above, so this reflects the same fixed test date.
    await seeded_db.production_entries.insert_one({
        "entry_id": "e_sa1", "agent_id": "SA_1", "office": "MCM", "sales_day": server.current_sales_day_str(),
        "sets": 1, "sits": 1, "sales": 1, "n1": 0, "gross_alp": 100, "net_alp": 100,
    })
    await seeded_db.push_tokens.insert_one({"user_id": "u_sa1", "agent_id": "SA_1", "push_token": "tok_sa1"})
    captured = []
    async def fake_send(tokens, title, body):
        captured.append((set(tokens), body))
    monkeypatch.setattr(server, "send_expo_push", fake_send)

    result = await server.run_pulse_escalation_check()

    sa1_calls = [c for c in captured if c[0] == {"tok_sa1"}]
    assert len(sa1_calls) == 1  # ONE push to SA_1, not two separate ones
    assert "Agent One" in sa1_calls[0][1]
    assert "Agent Three" in sa1_calls[0][1]
    # Other candidates (e.g. AG_2 -> GA_2) also generate their own upline
    # entries at this stage; the consolidation being tested is per-recipient
    # (asserted above), not a claim that SA_1 is the only recipient this run.
    assert result["upline_notified"] >= 1


async def test_admin_manual_trigger(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(21, 0))
    token = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/admin/run-notification-check", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["stage"] == "reminder"
