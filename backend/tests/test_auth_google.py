"""Direct Google sign-in (/api/auth/google): claim validation and the
two-step authentication/authorization contract.

Token *verification* (signature/JWKS) is exercised at the claim-check layer by
stubbing the decode path; the roster-linking behavior goes through the real
upsert_user_and_session against the mock db.
"""
import pytest

import server
from conftest import auth


@pytest.fixture()
def google_configured(monkeypatch):
    monkeypatch.setattr(server, "GOOGLE_CLIENT_IDS", {"ios-client-id", "web-client-id"})


def fake_claims(**over):
    claims = {"sub": "g-123", "email": "ga1@test.dev",
              "name": "Ga One", "picture": "http://p/x.png"}
    claims.update(over)
    return claims


async def test_unconfigured_returns_503(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server, "GOOGLE_CLIENT_IDS", set())
    r = await client.post("/api/auth/google", json={"id_token": "whatever"})
    assert r.status_code == 503


async def test_rostered_agent_gets_role_and_session(client, seeded_db, google_configured, monkeypatch):
    async def fake_verify(tok):
        assert tok == "tok-1"
        return fake_claims()
    monkeypatch.setattr(server, "verify_google_token", fake_verify)

    r = await client.post("/api/auth/google", json={"id_token": "tok-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "ga1@test.dev"
    assert body["user"]["role"] == "level_2" and body["user"]["agent_id"] == "GA_1"
    # session works for authenticated routes
    me = await client.get("/api/auth/me", headers=auth(body["session_token"]))
    assert me.status_code == 200


async def test_unrostered_identity_lands_on_pending_not_error(client, seeded_db, google_configured, monkeypatch):
    async def fake_verify(tok):
        return fake_claims(email="stranger@gmail.com", sub="g-999")
    monkeypatch.setattr(server, "verify_google_token", fake_verify)

    r = await client.post("/api/auth/google", json={"id_token": "tok-2"})
    assert r.status_code == 200  # authentication always succeeds
    assert r.json()["user"]["role"] == "pending"
    assert r.json()["user"]["agent_id"] is None


async def test_claim_checks_reject_bad_issuer_audience_and_unverified_email(client, seeded_db, google_configured, monkeypatch):
    # Exercise verify_google_token's own claim gates by stubbing everything
    # below it (JWKS fetch + signature decode).
    async def fake_jwks(force=False):
        return [{"kid": "k1"}]
    monkeypatch.setattr(server, "_fetch_google_jwks", fake_jwks)
    monkeypatch.setattr(server.apple_jwt, "get_unverified_header", lambda t: {"kid": "k1"})

    def decode_to(payload):
        monkeypatch.setattr(server.apple_jwt, "decode", lambda *a, **k: payload)

    good = {"iss": "https://accounts.google.com", "aud": "ios-client-id",
            "sub": "g-1", "email": "x@y.com", "email_verified": True}

    decode_to({**good, "iss": "https://evil.example"})
    r = await client.post("/api/auth/google", json={"id_token": "t"})
    assert r.status_code == 401 and "issuer" in r.json()["detail"]

    decode_to({**good, "aud": "someone-elses-client"})
    r = await client.post("/api/auth/google", json={"id_token": "t"})
    assert r.status_code == 401 and "audience" in r.json()["detail"]

    decode_to({**good, "email_verified": False})
    r = await client.post("/api/auth/google", json={"id_token": "t"})
    assert r.status_code == 401 and "verified" in r.json()["detail"]

    decode_to(good)
    r = await client.post("/api/auth/google", json={"id_token": "t"})
    assert r.status_code == 200
