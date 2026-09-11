"""fix_office_name_split.py: rename correctness, dry-run safety, and the
merge-on-collision path for a week that has both office names present."""
import sys
from pathlib import Path

import mongomock
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fix_office_name_split as migration

OLD = "Montzer Alwatan RGA"
NEW = "Alwatan RGA"


@pytest.fixture()
def db():
    return mongomock.MongoClient()["vantagelife_test"]


def seed_entries(db):
    db.production_entries.insert_many([
        {"entry_id": "pe_1", "agent_id": "A1", "office": OLD, "sales_day": "2026-06-01",
         "gross_alp": 100, "net_alp": 100, "sits": 2, "sales": 1},
        {"entry_id": "pe_2", "agent_id": "A1", "office": OLD, "sales_day": "2026-06-02",
         "gross_alp": 200, "net_alp": 200, "sits": 3, "sales": 2},
        {"entry_id": "pe_3", "agent_id": "A2", "office": NEW, "sales_day": "2026-09-01",
         "gross_alp": 50, "net_alp": 50, "sits": 1, "sales": 1},
        # A different office entirely must never be touched.
        {"entry_id": "pe_4", "agent_id": "A3", "office": "MCM", "sales_day": "2026-06-01",
         "gross_alp": 999, "net_alp": 999, "sits": 9, "sales": 9},
    ])


def test_dry_run_changes_nothing(db):
    seed_entries(db)
    before = list(db.production_entries.find({}, {"_id": 0}))

    n = migration.fix_production_entries(db, OLD, NEW, fix=False)

    assert n == 2  # would rename 2 docs
    assert list(db.production_entries.find({}, {"_id": 0})) == before  # nothing actually changed
    assert db.production_entries.count_documents({"office": OLD}) == 2


def test_fix_renames_production_entries_and_preserves_totals(db):
    seed_entries(db)
    before_new = migration.office_checksum(db, NEW)["production_entries"]

    n = migration.fix_production_entries(db, OLD, NEW, fix=True)

    assert n == 2
    assert db.production_entries.count_documents({"office": OLD}) == 0
    after_new = migration.office_checksum(db, NEW)["production_entries"]
    assert after_new["count"] == before_new["count"] + 2
    assert after_new["gross_alp"] == before_new["gross_alp"] + 300  # 100 + 200
    assert db.production_entries.find_one({"entry_id": "pe_4"})["office"] == "MCM"  # untouched


def test_fix_renames_historical_vault_key_when_no_collision(db):
    db.historical_vault.insert_one({
        "week_id": "wk_1", "week_start": "2026-06-01",
        "by_office": {OLD: {"gross_alp": 500, "net_alp": 500, "sits": 4, "sales": 3},
                      "MCM": {"gross_alp": 10, "net_alp": 10, "sits": 1, "sales": 1}},
    })

    n = migration.fix_historical_vault(db, OLD, NEW, fix=True)

    doc = db.historical_vault.find_one({"week_id": "wk_1"})
    assert n == {"renamed": 1, "merged": 0}
    assert OLD not in doc["by_office"]
    assert doc["by_office"][NEW] == {"gross_alp": 500, "net_alp": 500, "sits": 4, "sales": 3}
    assert doc["by_office"]["MCM"] == {"gross_alp": 10, "net_alp": 10, "sits": 1, "sales": 1}  # untouched


def test_fix_merges_historical_vault_when_both_names_present(db):
    """A week that already has both the old and new name (e.g. the rename
    landed mid-week) must sum into the new bucket, never overwrite it."""
    db.historical_vault.insert_one({
        "week_id": "wk_2", "week_start": "2026-08-19",
        "by_office": {OLD: {"gross_alp": 100, "net_alp": 100, "sits": 2, "sales": 1},
                      NEW: {"gross_alp": 50, "net_alp": 50, "sits": 1, "sales": 1}},
    })

    n = migration.fix_historical_vault(db, OLD, NEW, fix=True)

    doc = db.historical_vault.find_one({"week_id": "wk_2"})
    assert n == {"renamed": 0, "merged": 1}
    assert OLD not in doc["by_office"]
    assert doc["by_office"][NEW] == {"gross_alp": 150, "net_alp": 150, "sits": 3, "sales": 2}


def test_dry_run_reports_merge_case_without_writing(db):
    db.historical_vault.insert_one({
        "week_id": "wk_2", "week_start": "2026-08-19",
        "by_office": {OLD: {"gross_alp": 100, "net_alp": 100, "sits": 2, "sales": 1},
                      NEW: {"gross_alp": 50, "net_alp": 50, "sits": 1, "sales": 1}},
    })

    n = migration.fix_historical_vault(db, OLD, NEW, fix=False)

    doc = db.historical_vault.find_one({"week_id": "wk_2"})
    assert n == {"renamed": 0, "merged": 1}
    assert OLD in doc["by_office"] and NEW in doc["by_office"]  # untouched


def test_rerun_after_fix_is_a_noop(db):
    """Running the script again after a clean migration must find nothing
    left to do — this is what makes it safe to commit after the fact."""
    seed_entries(db)
    db.historical_vault.insert_one({
        "week_id": "wk_1", "week_start": "2026-06-01",
        "by_office": {OLD: {"gross_alp": 500, "net_alp": 500, "sits": 4, "sales": 3}},
    })
    migration.fix_production_entries(db, OLD, NEW, fix=True)
    migration.fix_historical_vault(db, OLD, NEW, fix=True)

    n_pe = migration.fix_production_entries(db, OLD, NEW, fix=True)
    n_hv = migration.fix_historical_vault(db, OLD, NEW, fix=True)

    assert n_pe == 0
    assert n_hv == {"renamed": 0, "merged": 0}
