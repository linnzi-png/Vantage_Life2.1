"""Brevo text messages (batch 2, PR C): E.164 normalisation, sending only to
people who opted in at their current number, the unavailable state while
unconfigured, the HTTP call to Brevo, and the sms_log."""
import json

import httpx
import pytest
import server
from conftest import auth, make_session

pytestmark = pytest.mark.asyncio

ADMIN = "linnzi@aoluxor.com"  # bootstrap admin


def configure(monkeypatch, on=True):
    monkeypatch.setenv("SMS_ENABLED", "true" if on else "false")
    monkeypatch.setenv("BREVO_API_KEY", "key_test")
    monkeypatch.setenv("BREVO_SMS_SENDER", "+18005550123")


@pytest.fixture()
def texts(monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append({"to": to, "text": text})
        return {"ok": True, "status": 201, "response": {"messageId": 1}}

    async def no_push(tokens, title, text):
        return None

    monkeypatch.setattr(server, "send_brevo_sms", fake_send)
    monkeypatch.setattr(server, "send_expo_push", no_push)
    monkeypatch.setattr(server, "SMS_SEND_DELAY_SECONDS", 0)
    return sent


async def opt_in(db, agent_id, phone, consent_phone=None, status="opted_in"):
    await db.agent_profiles.update_one({"agent_id": agent_id}, {"$set": {
        "phone": phone,
        "sms_consent": {"status": status, "changed_at": server.now_utc(), "source": "more_tab",
                        "phone": consent_phone if consent_phone is not None else phone},
    }})


async def admin_token(db):
    return await make_session(db, role="pending", agent_id=None, email=ADMIN)


def announcement(send_sms=True, scope="agency", office=None):
    return {
        "title": "Team tab date range",
        "cards": [{"heading": "Pick any dates", "body": "One button."}],
        "audience": {"scope": scope, **({"office": office} if office else {})},
        "send_sms": send_sms,
    }


@pytest.mark.parametrize("raw,expected", [
    ("(734) 555-0100", "+17345550100"),
    ("734-555-0100", "+17345550100"),
    ("734.555.0100", "+17345550100"),
    ("7345550100", "+17345550100"),
    ("1 734 555 0100", "+17345550100"),
    ("+1 (734) 555-0100", "+17345550100"),
    ("+1 (734) 555-0100 ext 123", None),
    ("734-555-0100 x12", None),
    ("734-555-0100 ext. 5", None),
    ("(734) 555-0100 #4", None),
    ("734/555/0100", None),
    ("734 555+0100", None),
    ("+44 20 7946 0958", "+442079460958"),
    ("", None),
    (None, None),
    ("555-0100", None),
    ("0345550100", None),
    ("123456789012", None),
    ("call me", None),
])
def test_normalize_phone_e164(raw, expected):
    assert server.normalize_phone_e164(raw) == expected


def test_message_is_the_title_then_the_opt_out_line():
    assert server.announcement_sms_text("Team tab date range") == (
        "Team tab date range. Turn off texts in the VantageLife More tab.")
    assert server.announcement_sms_text("New look!") == "New look. Turn off texts in the VantageLife More tab."


def test_configured_needs_flag_key_and_sender(monkeypatch):
    configure(monkeypatch)
    assert server.sms_configured() is True
    monkeypatch.setenv("SMS_ENABLED", "false")
    assert server.sms_configured() is False
    configure(monkeypatch)
    monkeypatch.setenv("BREVO_API_KEY", "")
    assert server.sms_configured() is False
    configure(monkeypatch)
    monkeypatch.setenv("BREVO_SMS_SENDER", "")
    assert server.sms_configured() is False


async def test_unconfigured_reports_unavailable_and_refuses_sms(client, seeded_db, monkeypatch):
    configure(monkeypatch, on=False)
    token = await admin_token(seeded_db)
    r = await client.get("/api/announcements/sms-status", headers=auth(token))
    assert r.json() == {"available": False}
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert r.status_code == 400
    assert await seeded_db.announcements.count_documents({}) == 0


async def test_configured_reports_available(client, seeded_db, monkeypatch):
    configure(monkeypatch)
    token = await admin_token(seeded_db)
    r = await client.get("/api/announcements/sms-status", headers=auth(token))
    assert r.json() == {"available": True}


async def test_only_opted_in_people_are_texted(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")
    await opt_in(seeded_db, "AG_2", "(313) 555-0111", status="opted_out")
    # SA_1 has a phone but was never asked.
    await seeded_db.agent_profiles.update_one({"agent_id": "SA_1"}, {"$set": {"phone": "(248) 555-0122"}})
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert r.status_code == 200, r.text
    assert [t["to"] for t in texts] == ["+17345550100"]
    assert texts[0]["text"] == "Team tab date range. Turn off texts in the VantageLife More tab."
    a = r.json()["announcement"]
    # The request returns before the batch; the count lands when it finishes.
    assert a["sms_queued"] is True and a["sms_count"] == 0
    stored = await seeded_db.announcements.find_one({"announcement_id": a["announcement_id"]})
    assert stored["sms_count"] == 1 and stored["sms_sent_at"]
    # People who never opted in leave no trace in the log either.
    rows = [row async for row in seeded_db.sms_log.find({})]
    assert [(row["agent_id"], row["status"]) for row in rows] == [("AG_1", "sent")]
    assert rows[0]["to"] == "***0100"


async def test_no_texts_unless_the_admin_asks_for_them(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement(send_sms=False))
    assert r.status_code == 200
    assert texts == [] and r.json()["announcement"]["sms_count"] == 0
    assert r.json()["announcement"]["sms_queued"] is False


async def test_office_audience_limits_the_texts(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")  # MCM
    await opt_in(seeded_db, "AG_2", "(313) 555-0111")  # AMP
    token = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(token), json=announcement(scope="office", office="AMP"))
    assert [t["to"] for t in texts] == ["+13135550111"]


async def test_archived_profiles_are_not_texted(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_1"}, {"$set": {"archived": True}})
    token = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert texts == []


async def test_changed_number_needs_a_fresh_opt_in(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0199", consent_phone="(734) 555-0100")
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert texts == []
    stored = await seeded_db.announcements.find_one({"announcement_id": r.json()["announcement"]["announcement_id"]})
    assert stored["sms_count"] == 0
    row = await seeded_db.sms_log.find_one({"agent_id": "AG_1"})
    assert row["status"] == "skipped" and "opt in again" in row["reason"]


async def test_formatting_only_difference_is_the_same_number(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "734-555-0100", consent_phone="(734) 555-0100")
    token = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert [t["to"] for t in texts] == ["+17345550100"]


async def test_unnormalisable_number_is_skipped_and_logged(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "555-0100")
    await opt_in(seeded_db, "AG_2", "(313) 555-0111")
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    assert [t["to"] for t in texts] == ["+13135550111"]
    stored = await seeded_db.announcements.find_one({"announcement_id": r.json()["announcement"]["announcement_id"]})
    assert stored["sms_count"] == 1
    row = await seeded_db.sms_log.find_one({"agent_id": "AG_1"})
    assert row["status"] == "skipped" and row["reason"] == "phone does not normalise" and row["to"] is None


async def test_one_failure_does_not_stop_the_batch(client, seeded_db, monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(server, "SMS_SEND_DELAY_SECONDS", 0)

    async def no_push(tokens, title, text):
        return None

    async def flaky(to, text):
        if to == "+17345550100":
            return {"ok": False, "status": 400, "response": {"code": "invalid_parameter"}}
        return {"ok": True, "status": 201, "response": {"messageId": 2}}

    monkeypatch.setattr(server, "send_expo_push", no_push)
    monkeypatch.setattr(server, "send_brevo_sms", flaky)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")
    await opt_in(seeded_db, "AG_2", "(313) 555-0111")
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/announcements", headers=auth(token), json=announcement())
    stored = await seeded_db.announcements.find_one({"announcement_id": r.json()["announcement"]["announcement_id"]})
    assert stored["sms_count"] == 1
    statuses = {row["agent_id"]: row["status"] async for row in seeded_db.sms_log.find({})}
    assert statuses == {"AG_1": "error", "AG_2": "sent"}


async def test_sms_log_is_admin_only_newest_first_with_names(client, seeded_db, monkeypatch, texts):
    configure(monkeypatch)
    await opt_in(seeded_db, "AG_1", "(734) 555-0100")
    admin = await admin_token(seeded_db)
    await client.post("/api/admin/announcements", headers=auth(admin), json=announcement())
    r = await client.get("/api/admin/sms-log", headers=auth(admin))
    assert r.status_code == 200
    rows = r.json()["sms_log"]
    assert rows[0]["name"] == "Agent One" and rows[0]["office"] == "MCM" and rows[0]["status"] == "sent"
    agent = await make_session(seeded_db, role="level_1", agent_id="AG_1", email="ag1@test.dev")
    assert (await client.get("/api/admin/sms-log", headers=auth(agent))).status_code == 403


async def test_brevo_request_shape_and_failure_handling(monkeypatch):
    configure(monkeypatch)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": 7, "smsCount": 1})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(server.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    result = await server.send_brevo_sms("+17345550100", "Hello. Turn off texts in the VantageLife More tab.")
    assert result["ok"] is True and result["status"] == 201
    assert seen["url"] == "https://api.brevo.com/v3/transactionalSMS/sms"
    assert seen["key"] == "key_test"
    assert seen["body"] == {
        "sender": "+18005550123", "recipient": "+17345550100",
        "content": "Hello. Turn off texts in the VantageLife More tab.",
        "type": "transactional", "tag": "vantagelife-announcement",
    }

    monkeypatch.setattr(server.httpx, "AsyncClient", lambda **kw: real_client(
        transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"code": "invalid_parameter"})), **kw))
    bad = await server.send_brevo_sms("+17345550100", "x")
    assert bad["ok"] is False and bad["status"] == 400

    def boom(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(server.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(boom), **kw))
    down = await server.send_brevo_sms("+17345550100", "x")
    assert down["ok"] is False and down["status"] is None


async def test_response_returns_before_the_batch_runs(client, seeded_db, monkeypatch):
    """The slow part (one request and a pause per person) must not hold the
    request open: the route answers while the batch has not started."""
    configure(monkeypatch)
    started = []

    async def no_push(tokens, title, text):
        return None

    monkeypatch.setattr(server, "send_expo_push", no_push)
    deferred = []

    class Capture:
        def add_task(self, func, *args, **kwargs):
            deferred.append((func, args, kwargs))

    async def fake_sms(doc, recipient_ids):
        started.append(doc["announcement_id"])
        return 3

    monkeypatch.setattr(server, "send_announcement_sms", fake_sms)
    token = await admin_token(seeded_db)
    doc = {"title": "T", "cards": [{"heading": "h", "body": "b"}],
           "audience": {"scope": "agency"}, "send_sms": True}
    r = await server.admin_create_announcement(
        server.AnnouncementIn(**doc), Capture(), {"user_id": "u_admin", "name": "Admin"})
    assert started == [] and len(deferred) == 1
    assert r["announcement"]["sms_queued"] is True
    func, args, kwargs = deferred[0]
    await func(*args, **kwargs)
    stored = await seeded_db.announcements.find_one({"announcement_id": r["announcement"]["announcement_id"]})
    assert started and stored["sms_count"] == 3 and stored["sms_sent_at"]


async def test_a_crashing_batch_is_logged_not_raised(seeded_db):
    async def boom(doc, recipient_ids):
        raise RuntimeError("brevo exploded")

    await seeded_db.announcements.insert_one({"announcement_id": "ann_x", "sms_count": 0, "sms_sent_at": None})
    await server._deliver_announcement_sms(boom, {"announcement_id": "ann_x"}, [])
    stored = await seeded_db.announcements.find_one({"announcement_id": "ann_x"})
    assert stored["sms_sent_at"] is None
