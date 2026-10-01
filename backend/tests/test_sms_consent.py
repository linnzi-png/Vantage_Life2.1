"""Text-message consent (batch 2, PR 0): the recorded opt-in Brevo's
registration and the TCPA require before any announcement text goes out."""
import pytest
from conftest import auth, make_session

pytestmark = pytest.mark.asyncio


async def give_phone(db, agent_id="AG_1", phone="(734) 555-0100"):
    await db.agent_profiles.update_one({"agent_id": agent_id}, {"$set": {"phone": phone}})


async def set_consent(client, token, opted_in, source=None):
    body = {"opted_in": opted_in}
    if source is not None:
        body["source"] = source
    return await client.post("/api/me/sms-consent", headers=auth(token), json=body)


async def test_profile_starts_with_no_consent_record(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["agent"].get("sms_consent") is None


async def test_opt_in_is_recorded_with_source_timestamp_and_audit(client, seeded_db):
    await give_phone(seeded_db)
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_consent(client, token, True, "onboarding_card")
    assert r.status_code == 200, r.text
    consent = r.json()["sms_consent"]
    assert consent["status"] == "opted_in"
    assert consent["source"] == "onboarding_card"
    assert consent["changed_at"]
    assert consent["phone"] == "(734) 555-0100"

    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert profile["sms_consent"]["status"] == "opted_in"
    assert profile["sms_consent"]["source"] == "onboarding_card"

    audit = await seeded_db.audit_log.find_one({"action": "sms_consent", "agent_id": "AG_1"})
    assert audit is not None
    assert audit["original_value"] is None
    assert audit["new_value"] == "opted_in"
    assert audit["source"] == "onboarding_card"

    me = await client.get("/api/auth/me", headers=auth(token))
    assert me.json()["agent"]["sms_consent"]["status"] == "opted_in"


async def test_opt_out_replaces_opt_in_and_audits_the_change(client, seeded_db):
    await give_phone(seeded_db)
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    await set_consent(client, token, True, "onboarding_card")
    r = await set_consent(client, token, False, "more_tab")
    assert r.status_code == 200
    assert r.json()["sms_consent"]["status"] == "opted_out"
    assert r.json()["sms_consent"]["phone"] is None
    audits = [a async for a in seeded_db.audit_log.find({"action": "sms_consent", "agent_id": "AG_1"})]
    assert len(audits) == 2
    # Both rows can share a clock tick, so pick the change by what it did, not by ts.
    latest = next(a for a in audits if a["new_value"] == "opted_out")
    assert latest["original_value"] == "opted_in"
    assert latest["new_value"] == "opted_out"
    assert latest["source"] == "more_tab"


async def test_source_defaults_to_more_tab_and_unknown_source_is_rejected(client, seeded_db):
    await give_phone(seeded_db)
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_consent(client, token, True)
    assert r.status_code == 200
    assert r.json()["sms_consent"]["source"] == "more_tab"
    r = await set_consent(client, token, True, "carrier_pigeon")
    assert r.status_code == 400


async def test_accounts_without_a_profile_cannot_consent(client, seeded_db):
    pending = await make_session(seeded_db, role="pending", agent_id=None, email="nobody@test.dev")
    r = await set_consent(client, pending, True, "onboarding_card")
    assert r.status_code in (401, 403)


async def test_opt_in_without_a_phone_is_refused_and_nothing_is_written(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_consent(client, token, True, "onboarding_card")
    assert r.status_code == 400
    profile = await seeded_db.agent_profiles.find_one({"agent_id": "AG_1"})
    assert profile.get("sms_consent") is None
    assert await seeded_db.audit_log.find_one({"action": "sms_consent"}) is None


async def test_opt_out_without_a_phone_is_still_recorded(client, seeded_db):
    token = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await set_consent(client, token, False, "onboarding_card")
    assert r.status_code == 200
    assert r.json()["sms_consent"]["status"] == "opted_out"
