"""Morgans Secret Sauce — the one-sheet weekly recognition report."""
import io

import openpyxl

import secret_sauce
from conftest import auth, make_session

WEEK = "2026-07-01"  # a Wednesday


async def _add(db, agent_id, office, sales_day, **metrics):
    doc = {
        "entry_id": f"pe_{agent_id}_{sales_day}", "agent_id": agent_id, "office": office,
        "sales_day": sales_day, "sets": 0, "sits": 0, "sales": 0, "ots_sits": 0, "ots_sales": 0,
        "n1": 0, "refs_obtained": 0, "ref_sits": 0, "ref_sales": 0, "pos_sits": 0, "pos_sales": 0,
        "vet_sits": 0, "vet_sales": 0, "gross_alp": 0.0, "net_alp": 0.0,
    }
    doc.update(metrics)
    await db.production_entries.insert_one(doc)


async def _rga(db):
    return await make_session(db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")


async def _sheet(client, db):
    r = await client.get(f"/api/vault/secret-sauce?week_start={WEEK}", headers=auth(await _rga(db)))
    assert r.status_code == 200, r.text
    assert "spreadsheetml" in r.headers["content-type"]
    assert "Morgans_Secret_Sauce" in r.headers["content-disposition"]
    return openpyxl.load_workbook(io.BytesIO(r.content)).active


def _block(ws, row, col):
    """The 4 data rows under a block anchored at (row, col): [(mga, name, value)]."""
    return [(ws.cell(row + 2 + n, col).value, ws.cell(row + 2 + n, col + 1).value,
             ws.cell(row + 2 + n, col + 2).value) for n in range(secret_sauce.TOP_N)]


# ---------------- layout ----------------

async def test_four_blocks_two_across(client, seeded_db):
    ws = await _sheet(client, seeded_db)
    assert ws["A1"].value == "Top 4 Producers"
    assert ws["E1"].value == "Top Rookie Producers"
    assert ws["A8"].value == "Top Plus Lead Sales"
    assert ws["E8"].value == "Top Plus Leads Collected"
    assert (ws["A2"].value, ws["B2"].value, ws["C2"].value) == ("MGA", "Agent", "ALP")
    assert (ws["E9"].value, ws["F9"].value, ws["G9"].value) == ("MGA", "Agent", "Refs")
    assert ws["C9"].value == "Sales"


# ---------------- ranking ----------------

async def test_veterans_and_rookies_rank_separately_on_weekly_alp(client, seeded_db):
    await seeded_db.agent_profiles.update_one({"agent_id": "AG_2"}, {"$set": {"is_rookie": True}})
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", gross_alp=1000.0)
    await _add(seeded_db, "AG_1", "MCM", "2026-07-03", gross_alp=500.0)   # same week: summed
    await _add(seeded_db, "GA_1", "MCM", "2026-07-02", gross_alp=2000.0)  # a leader ranks too
    await _add(seeded_db, "AG_2", "AMP", "2026-07-02", gross_alp=300.0)   # rookie
    await _add(seeded_db, "AG_1", "MCM", "2026-07-08", gross_alp=9999.0)  # next week: excluded
    ws = await _sheet(client, seeded_db)

    vets = _block(ws, 1, 1)
    assert vets[0] == ("MGA ONE", "Ga One", 2000.0)
    assert vets[1] == ("MGA ONE", "Agent One", 1500.0)
    assert vets[2] == (None, None, None), "no zero producers, no padding names"

    rookies = _block(ws, 1, 5)
    assert rookies[0] == ("MGA ONE", "Agent Two", 300.0)
    assert rookies[1] == (None, None, None)
    assert "Agent Two" not in [v[1] for v in vets], "a rookie never ranks as a veteran"


async def test_plus_lead_blocks_use_referral_metrics(client, seeded_db):
    await _add(seeded_db, "AG_1", "MCM", "2026-07-01", refs_obtained=45, ref_sales=1, sales=6)
    await _add(seeded_db, "AG_2", "AMP", "2026-07-01", refs_obtained=26, ref_sales=3, sales=1)
    ws = await _sheet(client, seeded_db)
    # Plus Lead Sales = ref_sales, NOT total sales.
    assert [r[1:] for r in _block(ws, 8, 1)[:2]] == [("Agent Two", 3), ("Agent One", 1)]
    # Plus Leads Collected = refs_obtained.
    assert [r[1:] for r in _block(ws, 8, 5)[:2]] == [("Agent One", 45), ("Agent Two", 26)]


async def test_top_n_caps_each_block(client, seeded_db):
    for i, aid in enumerate(["AG_1", "AG_2", "GA_1", "GA_2", "SA_1", "MGA_1"]):
        await _add(seeded_db, aid, "MCM", "2026-07-01", gross_alp=100.0 * (i + 1))
    ws = await _sheet(client, seeded_db)
    vets = _block(ws, 1, 1)
    assert [v[2] for v in vets] == [600.0, 500.0, 400.0, 300.0]
    # An MGA has no MGA above them: the column is blank, not their own name.
    assert vets[0][1] == "Mga One" and vets[0][0] is None
    assert ws.cell(7, 1).value is None, "nothing spills past the fourth row"


# ---------------- access ----------------

async def test_finance_admin_and_admin_can_pull_it(client, seeded_db):
    await seeded_db.agent_profiles.insert_one({
        "agent_id": "FA_1", "name": "Finance One", "email": "fa1@test.dev",
        "role": "finance_admin", "upline_id": None, "office": "",
    })
    fa = await make_session(seeded_db, role="finance_admin", agent_id="FA_1", email="fa1@test.dev")
    assert (await client.get(f"/api/vault/secret-sauce?week_start={WEEK}", headers=auth(fa))).status_code == 200


async def test_mga_is_refused(client, seeded_db):
    token = await make_session(seeded_db, role="level_3", agent_id="MGA_1", email="mga1@test.dev")
    assert (await client.get(f"/api/vault/secret-sauce?week_start={WEEK}", headers=auth(token))).status_code == 403


async def test_week_start_must_be_a_wednesday(client, seeded_db):
    r = await client.get("/api/vault/secret-sauce?week_start=2026-07-02", headers=auth(await _rga(seeded_db)))
    assert r.status_code == 400
