"""WAR integration endpoint: token gate, idempotent ingest, reconciliation."""
import pytest

import server
from war_integration import WAR_SOURCE

TOKEN = "test-war-token"
WEEK_START = "2026-05-06"  # a Wednesday
HEADERS = {"X-War-Token": TOKEN}


@pytest.fixture()
def war_token(monkeypatch):
    monkeypatch.setenv("WAR_IMPORT_TOKEN", TOKEN)
    return TOKEN


def row(name, day, **metrics):
    base = {"agent_name": name, "sales_day": day}
    base.update(metrics)
    return base


def payload(rows, office="Mohamed Aljahmi RGA", week_start=WEEK_START):
    return {"week_start": week_start, "office": office, "rows": rows}


async def app_pulse(db, agent_id, day, **metrics):
    """An app-entered pulse — identified by `entered_by`, as the real route writes it."""
    doc = {
        "entry_id": f"pe_app_{agent_id}_{day}",
        "agent_id": agent_id,
        "sales_day": day,
        "entered_by": "user_1",
        "is_adjustment": False,
    }
    doc.update(metrics)
    await db.production_entries.insert_one(doc)


# ---------------- token gate ----------------

async def test_missing_token_is_401(client, war_token):
    r = await client.get(f"/api/integrations/war/reconcile?week_start={WEEK_START}")
    assert r.status_code == 401


async def test_wrong_token_is_401(client, war_token):
    r = await client.get(
        f"/api/integrations/war/reconcile?week_start={WEEK_START}",
        headers={"X-War-Token": "wrong"},
    )
    assert r.status_code == 401


async def test_unset_token_disables_endpoint_with_503(client, monkeypatch):
    monkeypatch.delenv("WAR_IMPORT_TOKEN", raising=False)
    r = await client.get(
        f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
    )
    assert r.status_code == 503


async def test_import_requires_token(client, war_token):
    r = await client.post("/api/integrations/war/import", json=payload([]))
    assert r.status_code == 401


# ---------------- import ----------------

async def test_import_creates_agent_and_entry(client, seeded_db, war_token):
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Awni Shuaib", WEEK_START, sets=5, sits=1, sales=1, gross_alp=3360)]),
    )
    assert r.status_code == 200
    assert r.json()["inserted"] == 1

    agent = await seeded_db.agent_profiles.find_one({"name": "Awni Shuaib"})
    assert agent["role"] == "level_1"
    assert agent["upline_id"] is None

    entry = await seeded_db.production_entries.find_one({"agent_id": agent["agent_id"]})
    assert entry["source"] == WAR_SOURCE
    assert entry["sales_day"] == WEEK_START
    assert entry["sets"] == 5
    assert entry["gross_alp"] == 3360
    assert entry["net_alp"] == entry["gross_alp"]
    assert entry["submitted_on_time"] is True
    assert entry["is_adjustment"] is False
    # WAR rows carry no `entered_by` — that is what keeps them distinguishable
    # from app pulses during reconciliation.
    assert "entered_by" not in entry


async def test_import_matches_existing_agent_case_insensitively(client, seeded_db, war_token):
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("agent ONE", WEEK_START, sales=2)]),
    )
    assert r.json()["inserted"] == 1
    entry = await seeded_db.production_entries.find_one({"sales_day": WEEK_START})
    assert entry["agent_id"] == "AG_1"
    assert await seeded_db.agent_profiles.count_documents({}) == 7  # nothing created


async def test_import_is_idempotent(client, seeded_db, war_token):
    body = payload([row("Agent One", WEEK_START, sales=1, gross_alp=1000)])
    first = await client.post("/api/integrations/war/import", headers=HEADERS, json=body)
    second = await client.post("/api/integrations/war/import", headers=HEADERS, json=body)

    assert first.json()["inserted"] == 1
    assert second.json() == {
        "week_start": WEEK_START,
        "office": "Mohamed Aljahmi RGA",
        "rows_received": 1,
        "inserted": 0,
        "skipped": 1,
    }
    assert await seeded_db.production_entries.count_documents({"source": WAR_SOURCE}) == 1


async def test_import_does_not_dedup_against_app_pulses(client, seeded_db, war_token):
    """An app pulse for the same agent/day must not suppress the WAR row —
    holding both side by side is the whole point of reconciliation."""
    await app_pulse(seeded_db, "AG_1", WEEK_START, sales=1)
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=1)]),
    )
    assert r.json()["inserted"] == 1
    assert await seeded_db.production_entries.count_documents({"sales_day": WEEK_START}) == 2


async def test_import_rejects_day_outside_the_week(client, seeded_db, war_token):
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", "2026-05-16", sales=1)]),  # day 10
    )
    assert r.status_code == 400
    assert await seeded_db.production_entries.count_documents({}) == 0


async def test_import_accepts_the_full_nine_day_week(client, seeded_db, war_token):
    days = [f"2026-05-{d:02d}" for d in range(6, 15)]  # Wed 5/6 → Thurs 5/14
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", d, sales=1) for d in days]),
    )
    assert r.json()["inserted"] == 9


async def test_import_rejects_malformed_date_before_writing(client, seeded_db, war_token):
    r = await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload(
            [row("Agent One", WEEK_START, sales=1), row("Agent Two", "not-a-date", sales=1)]
        ),
    )
    assert r.status_code == 400
    assert await seeded_db.production_entries.count_documents({}) == 0


# ---------------- reconcile ----------------

async def test_reconcile_perfect_match(client, seeded_db, war_token):
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sets=5, sits=3, sales=1, gross_alp=1000)]),
    )
    await app_pulse(seeded_db, "AG_1", WEEK_START, sets=5, sits=3, sales=1, gross_alp=1000)

    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()

    assert body["agent_days_compared"] == 1
    assert body["agent_days_fully_matched"] == 1
    assert body["cells_compared"] == 14  # the 14 nightly metrics
    assert body["cells_matched"] == 14
    assert body["match_rate_pct"] == 100.0
    assert body["discrepancy_count"] == 0
    assert body["war_only_agent_days"] == 0
    assert body["app_only_agent_days"] == 0
    assert len(body["days"]) == 9


async def test_reconcile_reports_metric_mismatch(client, seeded_db, war_token):
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=3, sits=4)]),
    )
    await app_pulse(seeded_db, "AG_1", WEEK_START, sales=1, sits=4)

    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()

    assert body["cells_compared"] == 14
    assert body["cells_matched"] == 13
    assert body["agent_days_fully_matched"] == 0
    assert body["discrepancy_count"] == 1
    d = body["discrepancies"][0]
    assert d["agent"] == "Agent One"
    assert d["metric"] == "sales"
    assert (d["war"], d["app"], d["delta"]) == (3, 1, 2)
    assert d["in_war"] is True and d["in_app"] is True


async def test_reconcile_flags_one_sided_agent_days(client, seeded_db, war_token):
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=2)]),
    )
    await app_pulse(seeded_db, "AG_2", WEEK_START, sales=7)

    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()

    assert body["agent_days_compared"] == 0
    assert body["cells_compared"] == 0
    assert body["match_rate_pct"] == 0.0
    assert body["war_only_agent_days"] == 1
    assert body["app_only_agent_days"] == 1

    by_agent = {d["agent"]: d for d in body["discrepancies"]}
    assert by_agent["Agent One"]["in_war"] is True
    assert by_agent["Agent One"]["in_app"] is False
    assert by_agent["Agent Two"]["in_war"] is False
    assert by_agent["Agent Two"]["in_app"] is True


async def test_reconcile_sums_multiple_app_rows_per_day(client, seeded_db, war_token):
    """The app appends corrections rather than overwriting, so the day's app
    total is the sum of its rows."""
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=3)]),
    )
    await app_pulse(seeded_db, "AG_1", WEEK_START, sales=1)
    await app_pulse(seeded_db, "AG_1", WEEK_START + "x", sales=99)  # different day, ignored
    await seeded_db.production_entries.insert_one(
        {
            "entry_id": "pe_app_2",
            "agent_id": "AG_1",
            "sales_day": WEEK_START,
            "entered_by": "user_1",
            "is_adjustment": False,
            "sales": 2,
        }
    )

    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()
    assert body["discrepancy_count"] == 0  # 1 + 2 == 3


async def test_reconcile_ignores_adjustment_rows(client, seeded_db, war_token):
    """An eraser row restates the day and would double-count against WAR."""
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=1, gross_alp=1000)]),
    )
    await app_pulse(seeded_db, "AG_1", WEEK_START, sales=1, gross_alp=1000)
    await seeded_db.production_entries.insert_one(
        {
            "entry_id": "pe_adj",
            "agent_id": "AG_1",
            "sales_day": WEEK_START,
            "entered_by": "user_1",
            "is_adjustment": True,
            "gross_alp": 500,
        }
    )

    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()
    assert body["discrepancy_count"] == 0


async def test_reconcile_ignores_days_outside_the_week(client, seeded_db, war_token):
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sales=1)]),
    )
    body = (
        await client.get(
            "/api/integrations/war/reconcile?week_start=2026-05-20", headers=HEADERS
        )
    ).json()
    assert body["agent_days_compared"] == 0
    assert body["war_only_agent_days"] == 0


async def test_reconcile_rejects_bad_week_start(client, seeded_db, war_token):
    r = await client.get(
        "/api/integrations/war/reconcile?week_start=05-06-2026", headers=HEADERS
    )
    assert r.status_code == 400


async def test_reconcile_metrics_match_the_pulse_schema(client, seeded_db, war_token):
    """The endpoint must track PulseIn rather than a hardcoded copy of it."""
    body = (
        await client.get(
            f"/api/integrations/war/reconcile?week_start={WEEK_START}", headers=HEADERS
        )
    ).json()
    assert body["metrics"] == [
        "sets", "sits", "sales", "ots_sits", "ots_sales", "n1",
        "refs_obtained", "ref_sits", "ref_sales", "pos_sits", "pos_sales",
        "vet_sits", "vet_sales", "gross_alp",
    ]
    assert "n1" in body["metrics"]  # reconciled as a field; never fed into Close Rate


async def test_war_rows_are_excluded_from_nothing_they_should_not_be(client, seeded_db, war_token):
    """Sanity: the ingest writes no Close Rate or aggregate field of its own —
    all metric math stays in metrics.py."""
    await client.post(
        "/api/integrations/war/import",
        headers=HEADERS,
        json=payload([row("Agent One", WEEK_START, sits=5, n1=2, sales=1)]),
    )
    entry = await seeded_db.production_entries.find_one({"source": WAR_SOURCE})
    assert "close_rate" not in entry
    assert "eligible_sits" not in entry
