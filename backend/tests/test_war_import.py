"""WAR spreadsheet import: parsing, admin gating, the nine-tab overlap rule,
and protection of agent-submitted entries.

Fixture workbooks are built in-memory to mirror the real WAR layout (summary
block on top, data section starting at the MGA/.../SETS header row) so the
column mapping is asserted rather than assumed.
"""
import io
from datetime import date, timedelta

import openpyxl
import pytest

import war_import
from conftest import auth, make_session

BOOTSTRAP_ADMIN = "linnzi@aoluxor.com"

# Metric values keyed by the canonical field names, used to assert the column
# mapping end to end. Deliberately all-distinct so a column shift can't pass.
SAMPLE = {
    "sets": 5, "sits": 4, "sales": 3, "ots_sits": 6, "ots_sales": 2,
    "n1": 7, "refs_obtained": 13, "ref_sits": 8, "ref_sales": 9,
    "pos_sits": 10, "pos_sales": 11, "vet_sits": 12, "vet_sales": 14,
    "alp": 802.0,
}

DAILY_TABS = ["Wed", "Thurs", "Fri", "Sat", "Sun", "Mon ", "Tues ", "Wed (2)", "Thurs (2)"]

HEADER_ROW = [
    "MGA", "GA", "SA", "LDR", "RESIDENT \nSTATE", "Agent",
    "SETS", "SITS", "SALES", "OTS SITS", "OTS SALES", "N1",
    "REF OBT", "REF SITS", "REF SALES", "POS SITS", "POS SALES",
    "VETS SITS", "VET SALES", "ALP", "Close Rate", "Show Rate",
]


def _agent_row(name, metrics, *, mga="Mohamed Aljahmi", ga="Ali Musa", state="MI"):
    row = [mga, ga, None, None, state, name] + [None] * 16
    for key, col in war_import.METRIC_COLUMNS.items():
        row[col] = metrics.get(key, 0)
    return row


def build_workbook(office="Mohamed Aljahmi RGA", per_tab=None):
    """per_tab: {tab_name: [(agent_name, metrics_dict), ...]}"""
    per_tab = per_tab or {}
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for tab in DAILY_TABS:
        ws = wb.create_sheet(tab)
        # Summary block: office name sits at row 2, column 2.
        ws.append([None, "ALP", None])
        ws.append([None, office, 8084])
        ws.append([None, None, None])
        ws.append(HEADER_ROW)
        for name, metrics in per_tab.get(tab, []):
            ws.append(_agent_row(name, metrics))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def upload_files(buf, filename):
    return {"file": (filename, buf.getvalue(),
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


async def admin_token(db):
    return await make_session(db, role="pending", agent_id=None, email=BOOTSTRAP_ADMIN)


# ---------------- pure parsing ----------------

def test_parse_maps_every_metric_column():
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    parsed = war_import.parse_workbook(buf, date(2026, 2, 18))
    assert parsed["office"] == "Mohamed Aljahmi RGA"
    rows = parsed["days"]["2026-02-18"]
    assert len(rows) == 1
    for key, expected in SAMPLE.items():
        assert rows[0][key] == expected, f"column mismatch for {key}"


def test_parse_skips_rows_with_no_activity():
    zeros = {k: 0 for k in war_import.METRIC_COLUMNS}
    buf = build_workbook(per_tab={"Wed": [("Idle Agent", zeros), ("Busy Agent", SAMPLE)]})
    parsed = war_import.parse_workbook(buf, date(2026, 2, 18))
    names = [r["name"] for r in parsed["days"]["2026-02-18"]]
    assert names == ["Busy Agent"]


def test_nine_tabs_span_nine_days_from_the_week_start():
    per_tab = {tab: [("Agent One", SAMPLE)] for tab in DAILY_TABS}
    parsed = war_import.parse_workbook(build_workbook(per_tab=per_tab), date(2026, 2, 18))
    assert sorted(parsed["days"]) == [
        (date(2026, 2, 18) + timedelta(days=i)).isoformat() for i in range(9)
    ]


def test_week_start_from_filename():
    assert war_import.week_start_from_filename(
        "2026-02-18_MJ_War_Report.xlsx") == date(2026, 2, 18)
    assert war_import.week_start_from_filename("MJ_War_Report.xlsx") is None


def test_build_entry_carries_n1_without_folding_it_into_sales():
    entry = war_import.build_entry("AG_1", "MJ RGA", "2026-02-18", SAMPLE)
    assert entry["n1"] == 7
    assert entry["sales"] == 3          # N1 is a write-off category, never summed in
    assert entry["gross_alp"] == 802.0
    assert entry["net_alp"] == 802.0
    assert entry["source"] == war_import.WAR_IMPORT_SOURCE


# ---------------- endpoint gating ----------------

async def test_import_rejects_non_admin(client, seeded_db):
    token = await make_session(seeded_db, role="level_4", agent_id="RGA_1", email="rga1@test.dev")
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.status_code == 403


async def test_import_rejects_unauthenticated(client, seeded_db):
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"))
    assert r.status_code == 401


async def test_import_rejects_non_wednesday_week_start(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-19_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.status_code == 400
    assert "Wednesday" in r.json()["detail"]


async def test_import_rejects_undated_filename(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.status_code == 400


async def test_import_rejects_non_xlsx(client, seeded_db):
    token = await admin_token(seeded_db)
    r = await client.post("/api/admin/import-war-report",
                          files={"file": ("2026-02-18_notes.txt", b"nope", "text/plain")},
                          headers=auth(token))
    assert r.status_code == 400


# ---------------- writing entries ----------------

async def test_import_writes_entries_for_roster_agents(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["inserted"] == 1
    assert body["week_start"] == "2026-02-18"

    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"})
    assert entry["sales_day"] == "2026-02-18"
    assert entry["n1"] == 7
    assert entry["sales"] == 3
    assert entry["gross_alp"] == 802.0


async def test_agent_name_match_is_case_insensitive(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("AGENT ONE", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.json()["inserted"] == 1
    assert await seeded_db.production_entries.count_documents({"agent_id": "AG_1"}) == 1


async def test_unmatched_agents_are_reported_not_orphaned(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Nobody Here", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    body = r.json()
    assert body["inserted"] == 0
    assert body["skipped_unmatched"] == 1
    assert body["unmatched"][0]["name"] == "Nobody Here"
    assert body["unmatched"][0]["mga"] == "Mohamed Aljahmi"
    # No orphan profile created — it would be invisible in every team rollup.
    assert await seeded_db.agent_profiles.count_documents({"name": "Nobody Here"}) == 0


async def test_create_missing_opts_into_agent_creation(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Nobody Here", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          data={"create_missing": "true"},
                          headers=auth(token))
    body = r.json()
    assert body["created_agents"] == ["Nobody Here"]
    assert body["inserted"] == 1
    assert await seeded_db.agent_profiles.count_documents({"name": "Nobody Here"}) == 1


async def test_dry_run_writes_nothing(client, seeded_db):
    token = await admin_token(seeded_db)
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          data={"dry_run": "true"},
                          headers=auth(token))
    body = r.json()
    assert body["dry_run"] is True
    assert body["inserted"] == 1          # reports what it would do ...
    assert await seeded_db.production_entries.count_documents({}) == 0  # ... but writes nothing


# ---------------- the nine-tab overlap rule ----------------

async def test_later_file_wins_on_overlapping_days(client, seeded_db):
    """Week N's 'Wed (2)' and week N+1's 'Wed' are the same sales day. The later
    report carries the correction, so it must replace the earlier value."""
    token = await admin_token(seeded_db)

    stale = dict(SAMPLE, alp=0.0, sits=1)
    first = build_workbook(per_tab={"Wed (2)": [("Agent One", stale)]})
    r1 = await client.post("/api/admin/import-war-report",
                           files=upload_files(first, "2026-02-18_MJ_War_Report.xlsx"),
                           headers=auth(token))
    # 2026-02-18 + 7 days = 2026-02-25, which is the next report's "Wed".
    assert r1.json()["days"] == ["2026-02-25"]
    assert r1.json()["inserted"] == 1

    corrected = dict(SAMPLE, alp=520.0, sits=2)
    second = build_workbook(per_tab={"Wed": [("Agent One", corrected)]})
    r2 = await client.post("/api/admin/import-war-report",
                           files=upload_files(second, "2026-02-25_MJ_War_Report.xlsx"),
                           headers=auth(token))
    body = r2.json()
    assert body["replaced"] == 1
    assert body["inserted"] == 0

    entries = [e async for e in seeded_db.production_entries.find(
        {"agent_id": "AG_1", "sales_day": "2026-02-25"})]
    assert len(entries) == 1, "overlap must update in place, never duplicate the day"
    assert entries[0]["gross_alp"] == 520.0
    assert entries[0]["sits"] == 2


async def test_reimporting_the_same_file_is_idempotent(client, seeded_db):
    token = await admin_token(seeded_db)
    for _ in range(2):
        buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
        await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert await seeded_db.production_entries.count_documents(
        {"agent_id": "AG_1", "sales_day": "2026-02-18"}) == 1


async def test_agent_submitted_entries_are_never_replaced(client, seeded_db):
    """A backfill must not overwrite what an agent entered in the app."""
    token = await admin_token(seeded_db)
    await seeded_db.production_entries.insert_one({
        "entry_id": "pe_manual", "agent_id": "AG_1", "sales_day": "2026-02-18",
        "sales": 99, "gross_alp": 12345.0, "source": "pulse",
    })
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    body = r.json()
    assert body["protected"] == 1
    assert body["replaced"] == 0

    kept = await seeded_db.production_entries.find_one({"entry_id": "pe_manual"})
    assert kept["gross_alp"] == 12345.0
    assert kept["sales"] == 99


# ---------------- mixed-office guard ----------------

async def test_single_office_file_reports_no_foreign_offices(client, seeded_db):
    token = await admin_token(seeded_db)
    # AG_1 and SA_1 are both in MCM.
    buf = build_workbook(per_tab={"Wed": [("Agent One", SAMPLE), ("Sa One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    body = r.json()
    assert body["foreign_offices"] == []
    assert body["roster_offices"] == {"MCM": 2}


async def test_file_mixing_offices_is_flagged(client, seeded_db):
    """A WAR file should cover one office. Agents from elsewhere mean the sheet
    lists the wrong people — the failure that let one office's totals swallow
    another's when the entry carried the file's office."""
    token = await admin_token(seeded_db)
    # AG_1/SA_1/GA_1 are MCM; AG_2 is AMP.
    buf = build_workbook(per_tab={"Wed": [
        ("Agent One", SAMPLE), ("Sa One", SAMPLE), ("Ga One", SAMPLE), ("Agent Two", SAMPLE),
    ]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          data={"dry_run": "true"},
                          headers=auth(token))
    body = r.json()
    assert body["roster_offices"] == {"MCM": 3, "AMP": 1}
    assert body["foreign_offices"] == [{"office": "AMP", "rows": 1}]


async def test_entries_are_stamped_with_the_roster_office_not_the_sheet(client, seeded_db):
    """The sheet header says one thing, the roster another; the roster wins, or
    the same office appears twice in anything grouped by office."""
    token = await admin_token(seeded_db)
    buf = build_workbook(office="Mohamed Aljahmi RGA",
                         per_tab={"Wed": [("Agent One", SAMPLE)]})
    r = await client.post("/api/admin/import-war-report",
                          files=upload_files(buf, "2026-02-18_MJ_War_Report.xlsx"),
                          headers=auth(token))
    assert r.json()["office"] == "Mohamed Aljahmi RGA"   # what the sheet said
    entry = await seeded_db.production_entries.find_one({"agent_id": "AG_1"})
    assert entry["office"] == "MCM"                       # what the roster says


# ---------------- parser: silent rows are reported, not discarded ----------
#
# The audit tool needs the names a tab leaves blank in order to tell "not
# mentioned in this file" from "reported as nothing". The importer's own
# behaviour is unchanged — only rows with activity are written.

def test_parse_reports_silent_rows_separately_from_active_ones():
    buf = build_workbook(per_tab={"Wed": [("Busy Agent", SAMPLE), ("Idle Agent", {})]})
    parsed = war_import.parse_workbook(buf, date(2026, 2, 18))
    assert [r["name"] for r in parsed["days"]["2026-02-18"]] == ["Busy Agent"]
    assert parsed["silent"]["2026-02-18"] == ["Idle Agent"]


def test_silent_rows_are_reported_even_for_a_tab_with_no_activity():
    buf = build_workbook(per_tab={"Wed": [("Idle Agent", {})]})
    parsed = war_import.parse_workbook(buf, date(2026, 2, 18))
    assert "2026-02-18" not in parsed["days"], "a day nobody produced on writes no entries"
    assert parsed["silent"]["2026-02-18"] == ["Idle Agent"]
