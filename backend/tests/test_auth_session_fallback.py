"""Temporary Emergent fallback (/api/auth/session): kept alongside /api/auth/auth0
only so devices still on the pre-Auth0 OTA bundle can keep signing in during
rollout — see EMERGENT_AUTH_URL in server.py. Delete this test file alongside
the route once that fallback is removed.
"""
import server
from conftest import auth


class _FakeResponse:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self._data = data

    def json(self):
        return self._data


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        assert headers == {"X-Session-ID": "sid-1"}
        return _FakeResponse(200, {
            "email": "ga1@test.dev", "name": "Ga One", "picture": "http://p/x.png",
            "session_token": "st_fallback_1",
        })


async def test_rostered_agent_gets_role_and_session(client, seeded_db, monkeypatch):
    monkeypatch.setattr(server.httpx, "AsyncClient", _FakeAsyncClient)

    r = await client.post("/api/auth/session", json={"session_id": "sid-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "ga1@test.dev"
    assert body["user"]["role"] == "level_2" and body["user"]["agent_id"] == "GA_1"
    me = await client.get("/api/auth/me", headers=auth(body["session_token"]))
    assert me.status_code == 200


async def test_invalid_session_id_rejected(client, seeded_db, monkeypatch):
    class _FailingClient(_FakeAsyncClient):
        async def get(self, url, headers=None):
            return _FakeResponse(401, {})

    monkeypatch.setattr(server.httpx, "AsyncClient", _FailingClient)
    r = await client.post("/api/auth/session", json={"session_id": "bad"})
    assert r.status_code == 401
