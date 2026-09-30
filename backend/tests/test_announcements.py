"""What's New announcements (batch 2, PR B): admin creation with an immediate
push, per-user seen state held server-side, audience by office, and the
backlog cut-off at account creation."""
from datetime import datetime, timedelta, timezone

import pytest
import server
from conftest import auth, make_session

pytestmark = pytest.mark.asyncio

ADMIN = "linnzi@aoluxor.com"  # bootstrap admin


async def admin_token(db):
    return await make_session(db, role="pending", agent_id=None, email=ADMIN)


def body(title="Team tab date range", scope="agency", office=None, cards=None, send_sms=False):
    return {
        "title": title,
        "cards": cards if cards is not None else [
            {"heading": "Pick any dates", "body": "One button replaces Daily / Weekly / Monthly."},
            {"heading": "One ranked list", "body": "Everyone ranked together on ALP."},
        ],
        "audience": {"scope": scope, **({"office": office} if office else {})},
        "send_sms": send_sms,
    }


@pytest.fixture()
def pushes(monkeypatch):
    sent = []

    async def fake_send(tokens, title, text):
        sent.append({"tokens": list(tokens), "title": title, "body": text})

    monkeypatch.setattr(server, "send_expo_push", fake_send)
    return sent


async def register_token(db, agent_id, token):
    await db.push_tokens.insert_one({"user_id": f"u_{agent_id}", "agent_id": agent_id, "push_token": token})


async def test_admin_creates_and_pushes_to_the_whole_agency(client, seeded_db, pushes):
    await register_token(seeded_db, "AG_1", "tok_ag1")
    await register_token(seeded_db, "AG_2", "tok_ag2")
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=body())
    assert r.status_code == 200, r.text
    a = r.json()["announcement"]
    assert a["announcement_id"].startswith("ann_")
    assert a["push_count"] == 2 and a["push_sent_at"]
    assert a["sms_count"] == 0 and a["sms_sent_at"] is None
    assert len(pushes) == 1
    assert pushes[0]["title"] == "What's New" and pushes[0]["body"] == "Team tab date range"
    assert sorted(pushes[0]["tokens"]) == ["tok_ag1", "tok_ag2"]
    audit = await seeded_db.audit_log.find_one({"action": "create_announcement"})
    assert audit and audit["new_value"]["push_count"] == 2


async def test_office_audience_pushes_only_that_office_and_skips_archived(client, seeded_db, pushes):
    await register_token(seeded_db, "AG_1", "tok_ag1")   # MCM
    await register_token(seeded_db, "AG_2", "tok_ag2")   # AMP
    await register_token(seeded_db, "SA_1", "tok_sa1")   # MCM, archived below
    await seeded_db.agent_profiles.update_one({"agent_id": "SA_1"}, {"$set": {"archived": True}})
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=body(scope="office", office="MCM"))
    assert r.status_code == 200, r.text
    assert pushes[0]["tokens"] == ["tok_ag1"]
    assert r.json()["announcement"]["push_count"] == 1


async def test_unseen_respects_audience_and_seen_state_across_devices(client, seeded_db, pushes):
    admin = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(admin), json=body(title="For everyone"))
    r = await client.post("/api/admin/announcements", headers=auth(admin), json=body(title="MCM only", scope="office", office="MCM"))
    mcm_id = r.json()["announcement"]["announcement_id"]

    # Accounts created BEFORE the announcements so the backlog rule lets them through.
    past = datetime.now(timezone.utc) - timedelta(days=1)
    ag1 = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    ag2 = await make_session(seeded_db, role="level_1", agent_id="AG_2", email="ag2@test.dev")
    await seeded_db.users.update_many({}, {"$set": {"created_at": past}})

    u1 = await client.get("/api/announcements/unseen", headers=auth(ag1))
    assert [a["title"] for a in u1.json()["announcements"]] == ["MCM only", "For everyone"]
    u2 = await client.get("/api/announcements/unseen", headers=auth(ag2))
    assert [a["title"] for a in u2.json()["announcements"]] == ["For everyone"]

    # AG_1 dismisses the MCM one on this device; a "second device" (same
    # account, fresh call) must not see it again.
    s = await client.post(f"/api/announcements/{mcm_id}/seen", headers=auth(ag1))
    assert s.status_code == 200
    s2 = await client.post(f"/api/announcements/{mcm_id}/seen", headers=auth(ag1))
    assert s2.status_code == 200  # idempotent
    again = await client.get("/api/announcements/unseen", headers=auth(ag1))
    assert [a["title"] for a in again.json()["announcements"]] == ["For everyone"]
    assert await seeded_db.announcement_seen.count_documents({"user_id": {"$regex": "AG_1"}}) == 1

    # History still lists it for AG_1, and never the MCM one for AG_2.
    h1 = await client.get("/api/announcements/history", headers=auth(ag1))
    assert [a["title"] for a in h1.json()["announcements"]] == ["MCM only", "For everyone"]
    h2 = await client.get("/api/announcements/history", headers=auth(ag2))
    assert [a["title"] for a in h2.json()["announcements"]] == ["For everyone"]


async def test_new_account_gets_no_backlog(client, seeded_db, pushes):
    admin = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(admin), json=body(title="Old news"))
    # Account created after the announcement: make_session stamps created_at = now.
    ag1 = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    r = await client.get("/api/announcements/unseen", headers=auth(ag1))
    assert r.json()["announcements"] == []
    # But it is still in their history.
    h = await client.get("/api/announcements/history", headers=auth(ag1))
    assert [a["title"] for a in h.json()["announcements"]] == ["Old news"]


async def test_validation_and_gates(client, seeded_db, pushes):
    admin = await admin_token(seeded_db)
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(title="  "))).status_code == 400
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(cards=[]))).status_code == 400
    too_many = [{"heading": f"h{i}", "body": "b"} for i in range(7)]
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(cards=too_many))).status_code == 400
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(cards=[{"heading": "", "body": "x"}]))).status_code == 400
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(scope="office"))).status_code == 400
    assert (await client.post("/api/admin/announcements", headers=auth(admin), json=body(send_sms=True))).status_code == 400
    assert pushes == []
    # Nothing was written by the failures.
    assert await seeded_db.announcements.count_documents({}) == 0

    agent = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    assert (await client.post("/api/admin/announcements", headers=auth(agent), json=body())).status_code == 403
    assert (await client.get("/api/admin/announcements", headers=auth(agent))).status_code == 403
    assert (await client.get("/api/announcements/sms-status", headers=auth(admin))).json() == {"available": False}

    await client.post("/api/admin/announcements", headers=auth(admin), json=body())
    lst = await client.get("/api/admin/announcements", headers=auth(admin))
    assert len(lst.json()["announcements"]) == 1
    assert (await client.post("/api/announcements/ann_nope/seen", headers=auth(agent))).status_code == 404
