"""Self-registration (/join) tier mapping.

The public form lets someone roster themselves, so the tier it hands out is the
one place an unauthenticated request decides RBAC. These tests pin the mapping
itself: titles are the field's language, tiers are access, and the two are only
connected here.
"""
import pytest

import server


async def submit(client, **body):
    payload = {
        "first_name": "New", "last_name": "Person", "email": "new@test.dev",
        "phone": "5551234567", "title": "Agent", "is_rookie": True,
        "upline_agent_id": "GA_1", "website": "",
    }
    payload.update(body)
    return await client.post("/api/join/submit", json=payload)


async def test_ga_self_registers_at_level_2_not_level_3(client, seeded_db):
    """GA is a level_2 title (CLAUDE.md, per owner 2026-07-09). This map said
    level_3 until 2026-09-15, which handed every self-registered GA MGA-tier
    visibility over their whole branch."""
    r = await submit(client, title="GA", email="ga.new@test.dev")
    assert r.status_code == 200, r.text
    profile = await seeded_db.agent_profiles.find_one({"email": "ga.new@test.dev"}, {"_id": 0})
    assert profile["role"] == "level_2"
    assert profile["io_role"] == "GA"


async def test_sa_and_ga_land_on_the_same_tier(client, seeded_db):
    """SA and GA have identical permissions — the title is the only difference."""
    assert server.JOIN_TITLE_TIERS["SA"] == server.JOIN_TITLE_TIERS["GA"] == "level_2"


async def test_agent_and_trainee_are_level_1(client, seeded_db):
    assert server.JOIN_TITLE_TIERS["Agent"] == "level_1"
    assert server.JOIN_TITLE_TIERS["inTraining"] == "level_1"


async def test_no_title_can_self_register_above_level_3(client, seeded_db):
    """The cap exists so a public form can never mint a full-agency level_4."""
    assert all(t in ("level_1", "level_2", "level_3") for t in server.JOIN_TITLE_TIERS.values())


async def test_rga_is_capped_and_records_what_was_asked_for(client, seeded_db):
    r = await submit(client, title="RGA", email="rga.new@test.dev")
    assert r.status_code == 200, r.text
    profile = await seeded_db.agent_profiles.find_one({"email": "rga.new@test.dev"}, {"_id": 0})
    assert profile["role"] == "level_3"
    assert profile["requested_title"] == "RGA"
    assert profile["needs_review"] is True


async def test_an_unknown_title_is_refused(client, seeded_db):
    r = await submit(client, title="Grand Poobah", email="nope@test.dev")
    assert r.status_code == 400
