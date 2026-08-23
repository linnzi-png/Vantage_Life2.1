"""Self-correction window (owner decisions, 2026-08-22): an agent restates
their own day's TRUE totals for all 14 fields within MAX_SELF_BUFFER_DAYS.
One is_adjustment/is_self_correction row carries per-field deltas — including
gross_alp (flows to the Platinum Wall, unlike the Manager Eraser) with net_alp
moved by the SAME delta. A correction repairs the streak; a first-time
backfill of a missed day does not. Only the Player's Club shoutout re-runs."""
import server
from conftest import auth, make_session


FULL = {
    "sets": 4, "sits": 3, "sales": 2, "ots_sits": 1, "ots_sales": 0,
    "n1": 1, "refs_obtained": 5, "ref_sits": 1, "ref_sales": 0,
    "pos_sits": 1, "pos_sales": 1, "vet_sits": 0, "vet_sales": 0,
    "gross_alp": 2500.0,
}


def days_ago(n: int) -> str:
    return (server.now_detroit() - server.timedelta(days=n)).date().isoformat()


async def agent_token(db):
    return await make_session(db, role="level_1", agent_id="AG_1", email="ag1@test.dev")


async def seed_entry(client, token, sales_day=None, **overrides):
    body = {**FULL, **overrides}
    if sales_day:
        body["sales_day"] = sales_day
    r = await client.post("/api/pulse", json=body, headers=auth(token))
    assert r.status_code == 200, r.text
    return r


# ---------------- window + targeting ----------------

async def test_correction_inside_window_succeeds(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(2)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales": 3, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text


async def test_correction_outside_window_rejected(client, seeded_db):
    tok = await agent_token(seeded_db)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales_day": days_ago(4)}, headers=auth(tok))
    assert r.status_code == 400
    assert "self-edit window" in r.json()["detail"]


async def test_correction_requires_existing_entries(client, seeded_db):
    """A day with NO entries can't be corrected — first-time backfill goes
    through /api/pulse (and does not repair the streak)."""
    tok = await agent_token(seeded_db)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales_day": days_ago(1)}, headers=auth(tok))
    assert r.status_code == 400


async def test_correction_cannot_target_another_agent(client, seeded_db):
    """No target_agent_id path exists: even if the field is sent, the
    correction only ever lands on the caller's own agent_id."""
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    ag2 = await make_session(seeded_db, role="level_1", agent_id="AG_2", email="ag2@test.dev")
    await client.post("/api/pulse", json={**FULL, "sales_day": sd}, headers=auth(ag2))
    r = await client.post(
        "/api/pulse/correct",
        json={**FULL, "sales": 9, "sales_day": sd, "target_agent_id": "AG_2"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    adj = await seeded_db.production_entries.find_one({"is_self_correction": True}, {"_id": 0})
    assert adj["agent_id"] == "AG_1"
    assert await seeded_db.production_entries.count_documents({"agent_id": "AG_2", "is_adjustment": True}) == 0


# ---------------- adjustment row shape ----------------

async def test_correction_entry_flags_and_deltas(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)  # sales=2, sits=3, gross=2500
    r = await client.post(
        "/api/pulse/correct",
        json={**FULL, "sales": 3, "sits": 4, "gross_alp": 3000.0, "sales_day": sd},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    adj = await seeded_db.production_entries.find_one({"is_self_correction": True}, {"_id": 0})
    assert adj["is_adjustment"] is True
    assert adj["is_self_correction"] is True
    assert adj["source"] == "app"
    assert adj["sales"] == 1          # delta, not raw value
    assert adj["sits"] == 1
    assert adj["sets"] == 0
    assert adj["gross_alp"] == 500.0  # real delta — NOT zeroed like the Eraser
    assert adj["net_alp"] == 500.0    # same delta as gross (delta linkage)
    assert adj["entered_by"] == "user_level_1_AG_1"


async def test_correction_can_lower_totals(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post(
        "/api/pulse/correct",
        json={**FULL, "sales": 0, "gross_alp": 1000.0, "sales_day": sd},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    agg = await server.aggregate_full_pulse({"agent_id": "AG_1", "sales_day": sd})
    assert agg["sales"] == 0
    assert agg["gross_alp"] == 1000.0


async def test_correction_preserves_manager_offset_on_net_alp(client, seeded_db):
    """net_alp moves by the SAME delta as gross_alp, so a prior Manager Eraser
    offset survives instead of being collapsed back to gross."""
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)  # gross 2500 / net 2500
    rga = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    r = await client.post("/api/manager/erase", json={
        "agent_id": "AG_1", "sales_day": sd, "new_alp": 2000.0,
        "reason": "duplicate policy removed",
    }, headers=auth(rga))
    assert r.status_code == 200, r.text  # net now 2000, gross still 2500
    r = await client.post("/api/pulse/correct", json={**FULL, "gross_alp": 3500.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    agg = await server.aggregate_full_pulse({"agent_id": "AG_1", "sales_day": sd})
    assert agg["gross_alp"] == 3500.0
    assert agg["net_alp"] == 3000.0  # -500 manager offset preserved


async def test_no_change_correction_inserts_nothing(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200
    assert r.json().get("no_change") is True
    assert await seeded_db.production_entries.count_documents({"is_adjustment": True}) == 0


async def test_correction_idempotent_on_client_entry_id(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    body = {**FULL, "sales": 3, "sales_day": sd, "client_entry_id": "ce_retry_1"}
    r1 = await client.post("/api/pulse/correct", json=body, headers=auth(tok))
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/pulse/correct", json=body, headers=auth(tok))
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True
    assert await seeded_db.production_entries.count_documents({"is_self_correction": True}) == 1


# ---------------- aggregates: Platinum Wall / dashboard pick it up live ----------------

async def test_corrected_gross_alp_reaches_dashboard(client, seeded_db):
    """No special-casing anywhere: every surface sums production_entries live,
    so the corrected gross must fall out of existing aggregation code."""
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post("/api/pulse/correct", json={**FULL, "gross_alp": 4000.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/dashboard/summary?sales_day={sd}", headers=auth(tok))
    assert r.status_code == 200
    assert r.json()["total_alp"] == 4000.0


# ---------------- audit log ----------------

async def test_correction_writes_audit_row(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post(
        "/api/pulse/correct",
        json={**FULL, "sales": 3, "sales_day": sd, "reason": "typo on sales"},
        headers=auth(tok),
    )
    assert r.status_code == 200, r.text
    au = await seeded_db.audit_log.find_one({"action": "self_correct_pulse"}, {"_id": 0})
    assert au is not None
    assert au["agent_id"] == "AG_1"
    assert au["reason"] == "typo on sales"
    assert au["changes"]["sales"] == {"from": 2, "to": 3, "delta": 1}


async def test_correction_audit_reason_optional_but_spelled_out(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales": 3, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    au = await seeded_db.audit_log.find_one({"action": "self_correct_pulse"}, {"_id": 0})
    assert au["reason"] == "(no reason given)"


# ---------------- shoutouts: Player's Club only ----------------

async def test_correction_over_10k_triggers_players_club_once(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)  # 2500 — under threshold
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 0
    r = await client.post("/api/pulse/correct", json={**FULL, "gross_alp": 12000.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "players_club", "agent_id": "AG_1", "sales_day": sd}) == 1
    # Correcting again must not double-post (idempotent).
    r = await client.post("/api/pulse/correct", json={**FULL, "gross_alp": 13000.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "players_club", "agent_id": "AG_1", "sales_day": sd}) == 1


async def test_correction_under_10k_does_not_retract_shoutout(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd, gross_alp=11000.0)  # posts the shoutout
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 1
    r = await client.post("/api/pulse/correct", json={**FULL, "gross_alp": 8000.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "players_club"}) == 1  # still posted


async def test_correction_never_triggers_streak_or_first_deal(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    # Seed a zero-sale entry so the correction (adding the first sale) would be
    # the "first deal" if corrections ran that check — they must not.
    await seed_entry(client, tok, sales_day=sd, sales=0, gross_alp=0.0)
    r = await client.post("/api/pulse/correct", json={**FULL, "sales": 1, "gross_alp": 500.0, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert await seeded_db.shoutouts.count_documents({"type": "first_deal"}) == 0
    assert await seeded_db.shoutouts.count_documents({"type": "streak"}) == 0


# ---------------- streak semantics (owner, 2026-08-22) ----------------

async def test_correction_repairs_streak_for_existing_day(client, seeded_db, monkeypatch):
    """A correction of a day that HAS entries carries submitted_on_time: True,
    so a late-but-present day counts toward the streak after correction."""
    # Pin the clock to mid-afternoon so days_ago(1) is unambiguously a past
    # sales day (before 6 AM, the previous date is still the OPEN day).
    fake_2pm = server.DETROIT_TZ.localize(server.datetime(2026, 8, 4, 14, 0))
    monkeypatch.setattr(server, "now_detroit", lambda: fake_2pm)
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)  # backfill → not on time
    assert await seeded_db.production_entries.count_documents(
        {"agent_id": "AG_1", "sales_day": sd, "submitted_on_time": True}) == 0
    r = await client.post("/api/pulse/correct", json={**FULL, "sales": 3, "sales_day": sd}, headers=auth(tok))
    assert r.status_code == 200, r.text
    assert await seeded_db.production_entries.count_documents(
        {"agent_id": "AG_1", "sales_day": sd, "submitted_on_time": True}) == 1


async def test_backfill_of_missed_day_does_not_repair_streak(client, seeded_db, monkeypatch):
    """First-time entry for a previously-missed day posts via /api/pulse and is
    never on time — it fills the totals but does not repair the streak."""
    fake_2pm = server.DETROIT_TZ.localize(server.datetime(2026, 8, 4, 14, 0))
    monkeypatch.setattr(server, "now_detroit", lambda: fake_2pm)
    tok = await agent_token(seeded_db)
    sd = days_ago(2)
    await seed_entry(client, tok, sales_day=sd)
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1", "sales_day": sd}, {"_id": 0})
    assert entry["submitted_on_time"] is False


async def test_todays_self_entry_before_9pm_still_on_time(client, seeded_db, monkeypatch):
    """Regression guard for the backfill rule: an ordinary same-day entry
    before 9 PM keeps submitted_on_time True."""
    fake_8pm = server.DETROIT_TZ.localize(server.datetime(2026, 8, 4, 20, 0))
    monkeypatch.setattr(server, "now_detroit", lambda: fake_8pm)
    tok = await agent_token(seeded_db)
    r = await client.post("/api/pulse", json=FULL, headers=auth(tok))
    assert r.status_code == 200, r.text
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert entry["submitted_on_time"] is True


# ---------------- /api/pulse/me/day ----------------

async def test_pulse_me_day_returns_full_totals(client, seeded_db):
    tok = await agent_token(seeded_db)
    sd = days_ago(1)
    await seed_entry(client, tok, sales_day=sd)
    r = await client.get(f"/api/pulse/me/day?sales_day={sd}", headers=auth(tok))
    assert r.status_code == 200
    t = r.json()["totals"]
    for k, v in FULL.items():
        assert t[k] == v, f"{k}: {t[k]} != {v}"
    assert len(r.json()["entries"]) == 1


async def test_pulse_me_day_rejects_future_day(client, seeded_db):
    tok = await agent_token(seeded_db)
    r = await client.get("/api/pulse/me/day?sales_day=2099-01-01", headers=auth(tok))
    assert r.status_code == 400


# ---------------- source tag (issue #12 convention) ----------------

async def test_new_pulse_entries_are_source_tagged(client, seeded_db):
    tok = await agent_token(seeded_db)
    await seed_entry(client, tok)
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"}, {"_id": 0})
    assert entry["source"] == "app"
