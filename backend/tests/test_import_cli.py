"""CLI backfill script (import_xlsx_war.py): dry-run accounting, roster
matching, and the overlap rule.

The CLI writes with sync pymongo rather than motor, so these use mongomock
directly instead of the async fixtures in conftest.
"""
import io
from datetime import date

import mongomock
import openpyxl
import pytest

import import_xlsx_war as cli
import war_import
from test_war_import import SAMPLE, DAILY_TABS, build_workbook


@pytest.fixture()
def db():
    return mongomock.MongoClient()["vantagelife_test"]


def write_workbook(tmp_path, name, per_tab):
    buf = build_workbook(per_tab=per_tab)
    p = tmp_path / name
    p.write_bytes(buf.getvalue())
    return str(p)


def new_stats():
    return {"inserted": 0, "replaced": 0, "protected": 0, "skipped": 0,
            "file_errors": 0, "unmatched": {}, "created": set(), "simulated": set()}


def seed(db, *names):
    db.agent_profiles.insert_many(
        [{"agent_id": f"AG{i}", "name": n, "role": "level_1"} for i, n in enumerate(names)])


# ---------------- roster matching ----------------

def test_unmatched_agents_are_reported_not_created(db, tmp_path):
    f = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed": [("Nobody Here", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)

    assert stats["inserted"] == 0
    assert stats["skipped"] == 1
    assert stats["unmatched"]["Nobody Here"]["ga"] == "Ali Musa"
    assert db.agent_profiles.count_documents({}) == 0
    assert db.production_entries.count_documents({}) == 0


def test_create_missing_opts_into_creation(db, tmp_path):
    f = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed": [("Nobody Here", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=True)

    assert stats["inserted"] == 1
    assert db.agent_profiles.count_documents({"name": "Nobody Here"}) == 1


def test_roster_match_is_case_insensitive(db, tmp_path):
    seed(db, "Agent One")
    f = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed": [("AGENT ONE", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)
    assert stats["inserted"] == 1
    assert stats["skipped"] == 0


# ---------------- dry run ----------------

def test_dry_run_writes_nothing(db, tmp_path):
    seed(db, "Agent One")
    f = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed": [("Agent One", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=True, create_missing=False)

    assert stats["inserted"] == 1               # reports what it would do ...
    assert db.production_entries.count_documents({}) == 0   # ... writes nothing


def test_dry_run_totals_match_a_live_run_across_overlapping_files(db, tmp_path):
    """Regression: a dry run writes nothing, so without tracking simulated
    writes the two days each report shares with the next get counted as new
    twice — inflating the preview above what a live run actually produces."""
    seed(db, "Agent One")
    first = write_workbook(tmp_path, "2026-02-18_MJ.xlsx",
                           {"Wed (2)": [("Agent One", SAMPLE)]})
    second = write_workbook(tmp_path, "2026-02-25_MJ.xlsx",
                            {"Wed": [("Agent One", SAMPLE)]})

    dry = new_stats()
    for f in (first, second):
        cli.import_xlsx_file(db, f, dry, dry_run=True, create_missing=False)

    live_db = mongomock.MongoClient()["live"]
    seed(live_db, "Agent One")
    live = new_stats()
    for f in (first, second):
        cli.import_xlsx_file(live_db, f, live, dry_run=False, create_missing=False)

    assert (dry["inserted"], dry["replaced"]) == (live["inserted"], live["replaced"])
    assert (live["inserted"], live["replaced"]) == (1, 1)


# ---------------- overlap rule ----------------

def test_later_file_wins_on_overlapping_days(db, tmp_path):
    seed(db, "Agent One")
    stale = dict(SAMPLE, alp=0.0, sits=1)
    corrected = dict(SAMPLE, alp=520.0, sits=2)
    first = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed (2)": [("Agent One", stale)]})
    second = write_workbook(tmp_path, "2026-02-25_MJ.xlsx", {"Wed": [("Agent One", corrected)]})

    stats = new_stats()
    for f in (first, second):
        cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)

    entries = list(db.production_entries.find({"sales_day": "2026-02-25"}))
    assert len(entries) == 1, "overlap must update in place, never duplicate the day"
    assert entries[0]["gross_alp"] == 520.0
    assert stats["replaced"] == 1


def test_agent_submitted_entries_are_never_replaced(db, tmp_path):
    seed(db, "Agent One")
    db.production_entries.insert_one({
        "entry_id": "pe_manual", "agent_id": "AG0", "sales_day": "2026-02-18",
        "gross_alp": 12345.0, "source": "pulse",
    })
    f = write_workbook(tmp_path, "2026-02-18_MJ.xlsx", {"Wed": [("Agent One", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)

    assert stats["protected"] == 1
    assert db.production_entries.find_one({"entry_id": "pe_manual"})["gross_alp"] == 12345.0


# ---------------- filename / week-start guards ----------------

def test_non_wednesday_filename_is_skipped(db, tmp_path):
    f = write_workbook(tmp_path, "2026-02-19_MJ.xlsx", {"Wed": [("Agent One", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)
    assert stats["file_errors"] == 1
    assert stats["inserted"] == 0


def test_undated_filename_is_skipped(db, tmp_path):
    f = write_workbook(tmp_path, "MJ_War_Report.xlsx", {"Wed": [("Agent One", SAMPLE)]})
    stats = new_stats()
    cli.import_xlsx_file(db, f, stats, dry_run=False, create_missing=False)
    assert stats["file_errors"] == 1


def test_collect_files_sorts_chronologically_and_expands_dirs(tmp_path):
    for n in ("2026-03-04_MJ.xlsx", "2026-02-18_MJ.xlsx", "2026-02-25_MJ.xlsx"):
        write_workbook(tmp_path, n, {"Wed": [("Agent One", SAMPLE)]})
    (tmp_path / "notes.txt").write_text("ignored")

    got = [f.rsplit("/", 1)[-1] for f in cli.collect_files([str(tmp_path)])]
    assert got == ["2026-02-18_MJ.xlsx", "2026-02-25_MJ.xlsx", "2026-03-04_MJ.xlsx"]
