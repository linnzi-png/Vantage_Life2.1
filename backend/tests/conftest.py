"""Shared fixtures: in-memory Mongo, seeded agent hierarchy, session helpers."""
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Must be set before importing server (it reads env at import time).
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "vantagelife_test")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import httpx
from mongomock_motor import AsyncMongoMockClient

import server


@pytest.fixture()
def mock_db(monkeypatch):
    """Swap server.db for an in-memory mock so no real Mongo is touched."""
    client = AsyncMongoMockClient()
    db = client["vantagelife_test"]
    monkeypatch.setattr(server, "db", db)
    return db


# Hierarchy used across tests (upline_id points at the agent above):
#
#   RGA_1 (level_4)
#     └─ MGA_1 (level_3)
#          ├─ GA_1 (level_2)
#          │    ├─ SA_1 (level_1, io_role SA — title-based endorser)
#          │    │    └─ AG_1 (level_1)
#          │    └─ (AG_1's upline is SA_1)
#          └─ GA_2 (level_2)
#               └─ AG_2 (level_1)
HIERARCHY = [
    {"agent_id": "RGA_1", "name": "Rga One", "email": "rga1@test.dev", "role": "level_4", "upline_id": None, "office": "MCM"},
    {"agent_id": "MGA_1", "name": "Mga One", "email": "mga1@test.dev", "role": "level_3", "upline_id": "RGA_1", "office": "MCM"},
    {"agent_id": "GA_1", "name": "Ga One", "email": "ga1@test.dev", "role": "level_2", "upline_id": "MGA_1", "office": "MCM"},
    {"agent_id": "GA_2", "name": "Ga Two", "email": "ga2@test.dev", "role": "level_2", "upline_id": "MGA_1", "office": "AMP"},
    {"agent_id": "SA_1", "name": "Sa One", "email": "sa1@test.dev", "role": "level_1", "io_role": "SA", "upline_id": "GA_1", "office": "MCM"},
    {"agent_id": "AG_1", "name": "Agent One", "email": "ag1@test.dev", "role": "level_1", "upline_id": "SA_1", "office": "MCM"},
    {"agent_id": "AG_2", "name": "Agent Two", "email": "ag2@test.dev", "role": "level_1", "upline_id": "GA_2", "office": "AMP"},
]


@pytest.fixture()
async def seeded_db(mock_db):
    await mock_db.agent_profiles.insert_many([dict(a) for a in HIERARCHY])
    return mock_db


@pytest.fixture()
async def client(seeded_db):
    transport = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def make_session(db, *, role: str, agent_id, email: str) -> str:
    """Insert a user + 7-day session directly; returns the bearer token."""
    token = f"st_test_{role}_{agent_id or 'none'}"
    await db.users.insert_one({
        "user_id": f"user_{role}_{agent_id or 'none'}",
        "email": email,
        "name": email.split("@")[0],
        "picture": "",
        "role": role,
        "agent_id": agent_id,
        "created_at": datetime.now(timezone.utc),
    })
    await db.user_sessions.insert_one({
        "user_id": f"user_{role}_{agent_id or 'none'}",
        "session_token": token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": datetime.now(timezone.utc),
    })
    return token


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
