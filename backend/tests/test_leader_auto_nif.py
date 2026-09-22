"""Leaders' pulse is NIF by default (owner, 2026-09-22).

  - at 06:30 Detroit the server files an automatic NIF for every active
    MGA/RGA (level_3 / level_4 by tier) with no entry for the sales day that
    closed at 06:00; nothing before 06:30, nothing for older days, never twice
  - a leader's own real entry for that day replaces the automatic one
  - for those tiers the gate banner stays open, the streak is exempt and the
    Team tab files no "no_pulse" flag on their row overnight

Fixture: RGA_1 (level_4) → MGA_1 (level_3) → {GA_1 → SA_1 → AG_1, GA_2 → AG_2}.
"""
from datetime import datetime

import pytz

import server
from conftest import auth, make_session

DETROIT = pytz.timezone("America/Detroit")


def _at(hour, minute, day=27):
    return DETROIT.localize(datetime(2026, 7, day, hour, minute, 0))


async def _entries(db, agent_id, sales_day):
    return [e async for e in db.production_entries.find({"agent_id": agent_id, "sales_day": sales_day}, {"_id": 0})]


async def test_files_nif_for_leaders_only_after_0630(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 29))
    r = await server.run_leader_auto_nif()
    assert r["due"] is False and r["filed"] == 0
    assert await seeded_db.production_entries.count_documents({"auto_nif": True}) == 0

    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 30))
    r = await server.run_leader_auto_nif()
    assert r["due"] is True and r["sales_day"] == "2026-07-26"
    assert sorted(r["agent_ids"]) == ["MGA_1", "RGA_1"]
    e = (await _entries(seeded_db, "MGA_1", "2026-07-26"))[0]
    assert e["is_nif"] is True and e["auto_nif"] is True and e["source"] == "auto"
    assert e["gross_alp"] == 0 and e["sales"] == 0 and e["sits"] == 0
    assert e["entered_by"] == "system"
    # Agents, SAs and GAs are never touched — the 9 PM ladder is theirs.
    for aid in ("GA_1", "GA_2", "SA_1", "AG_1", "AG_2"):
        assert await _entries(seeded_db, aid, "2026-07-26") == []


async def test_idempotent_and_skips_leaders_who_entered(seeded_db, monkeypatch):
    # RGA_1 entered real numbers for 07-26 during the night.
    await seeded_db.production_entries.insert_one(
        {"entry_id": "pe_real", "agent_id": "RGA_1", "sales_day": "2026-07-26", "office": "MCM",
         "gross_alp": 500, "sales": 1, "sits": 2, "is_nif": False, "source": "app"})
    monkeypatch.setattr(server, "now_detroit", lambda: _at(7, 0))
    r = await server.run_leader_auto_nif()
    assert r["agent_ids"] == ["MGA_1"]
    assert len(await _entries(seeded_db, "RGA_1", "2026-07-26")) == 1
    # Later ticks that day file nothing more.
    monkeypatch.setattr(server, "now_detroit", lambda: _at(23, 15))
    r = await server.run_leader_auto_nif()
    assert r["filed"] == 0
    assert len(await _entries(seeded_db, "MGA_1", "2026-07-26")) == 1


async def test_only_the_day_that_just_closed_is_filled(seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 45, day=28))
    r = await server.run_leader_auto_nif()
    assert r["sales_day"] == "2026-07-27"
    assert await seeded_db.production_entries.count_documents({"auto_nif": True, "sales_day": "2026-07-26"}) == 0


async def test_non_producing_and_archived_leaders_are_skipped(seeded_db, monkeypatch):
    await seeded_db.agent_profiles.update_one({"agent_id": "MGA_1"}, {"$set": {"non_producing": True}})
    await seeded_db.agent_profiles.update_one({"agent_id": "RGA_1"}, {"$set": {"archived": True}})
    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 31))
    r = await server.run_leader_auto_nif()
    assert r["filed"] == 0


async def test_a_real_entry_replaces_the_automatic_one(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 31))
    await server.run_leader_auto_nif()
    assert len(await _entries(seeded_db, "MGA_1", "2026-07-26")) == 1
    # MGA_1 comes in at 9 AM and enters yesterday's real numbers themselves.
    monkeypatch.setattr(server, "now_detroit", lambda: _at(9, 0))
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    r = await client.post("/api/pulse", headers=auth(token), json={
        "sales_day": "2026-07-26", "sets": 3, "sits": 2, "sales": 1, "ots_sits": 0, "ots_sales": 0,
        "n1": 0, "refs_obtained": 1, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0, "gross_alp": 1200})
    assert r.status_code == 200, r.text
    left = await _entries(seeded_db, "MGA_1", "2026-07-26")
    assert len(left) == 1 and left[0]["gross_alp"] == 1200 and not left[0].get("auto_nif")


async def test_leader_gate_streak_and_no_pulse_are_switched_off(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(22, 0))  # deep in the yellow window
    mga = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    today = (await client.get("/api/pulse/me/today", headers=auth(mga))).json()
    assert today["auto_nif"] is True and today["gate"]["state"] == "open"
    streak = (await client.get("/api/pulse/me/streak", headers=auth(mga))).json()
    assert streak == {"streak": 0, "exempt": True}
    # An agent still sees the real gate and no exemption.
    ag = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    today = (await client.get("/api/pulse/me/today", headers=auth(ag))).json()
    assert today["auto_nif"] is False and today["gate"]["state"] == "warning"
    assert "exempt" not in (await client.get("/api/pulse/me/streak", headers=auth(ag))).json()
    # RGA_1's board: MGA_1 has no entry yet, but carries no no_pulse flag; GA_1 does.
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    rows = {r["agent_id"]: r for r in (await client.get("/api/team", headers=auth(rga))).json()["team"]}
    assert "no_pulse" not in rows["MGA_1"]["alerts"]
    assert "no_pulse" in rows["GA_1"]["alerts"]


async def test_manual_trigger_is_admin_only(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "now_detroit", lambda: _at(6, 31))
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.post("/api/admin/run-leader-auto-nif", headers=auth(rga))).status_code == 403
    admin = await make_session(seeded_db, role="pending", agent_id=None, email="linnzi@aoluxor.com")
    r = await client.post("/api/admin/run-leader-auto-nif", headers=auth(admin))
    assert r.status_code == 200 and r.json()["filed"] == 2
