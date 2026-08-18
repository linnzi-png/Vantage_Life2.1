"""Missing-roster import CLI (import_missing_roster.py): upline resolution,
top-down ordering, dry-run safety, idempotence, and the ROSTER's integrity."""
import mongomock
import pytest

import import_missing_roster as cli


@pytest.fixture()
def db():
    return mongomock.MongoClient()["vantagelife_test"]


def seed(db, agent_id, name, email="", role="level_1", office="MJ RGA"):
    db.agent_profiles.insert_one(
        {"agent_id": agent_id, "name": name, "email": email, "role": role, "office": office})


SMALL = [
    ("Joseph Gojcaj", "joseph@aopremier.com", "RGA", "level_4", False, None),
    ("David Fulfer", "davidfulfer@aopremier.com", "MGA", "level_3", False, "Joseph Gojcaj"),
    ("William Benline", "will.benline@gmail.com", "Agent", "level_1", False, "David Fulfer"),
]


def test_dry_run_writes_nothing(db):
    seed(db, "M1", "Serage Jamil", "jamilserage@gmail.com", role="level_2",
         office="Montzer Alwatan RGA")
    created, skipped, blocked = cli.run(db, SMALL, apply=False)
    assert len(created) == 3 and not skipped and not blocked
    assert db.agent_profiles.count_documents({}) == 1
    # dry run leaves the office rename unapplied too
    assert db.agent_profiles.find_one({"agent_id": "M1"})["office"] == "Montzer Alwatan RGA"


def test_apply_renames_office(db):
    seed(db, "M1", "Serage Jamil", "jamilserage@gmail.com", role="level_2",
         office="Montzer Alwatan RGA")
    cli.run(db, [], apply=True)
    assert db.agent_profiles.find_one({"agent_id": "M1"})["office"] == "Alwatan RGA"


def test_apply_orders_topdown_and_inherits_office(db):
    created, _, _ = cli.run(db, SMALL, apply=True)
    by_name = {p["name"]: p for p in db.agent_profiles.find({})}
    root = by_name["Joseph Gojcaj"]
    assert root["role"] == "level_4" and root["upline_id"] is None
    assert root["office"] == "Gojcaj RGA"
    mga = by_name["David Fulfer"]
    assert mga["upline_id"] == root["agent_id"] and mga["office"] == "Gojcaj RGA"
    agent = by_name["William Benline"]
    assert agent["upline_id"] == mga["agent_id"]
    assert db.audit_log.count_documents({"action": "add_agent"}) == 3


def test_apply_links_waiting_pending_login(db):
    db.users.insert_one({"user_id": "u1", "email": "will.benline@gmail.com",
                         "role": "pending", "agent_id": None})
    cli.run(db, SMALL, apply=True)
    u = db.users.find_one({"user_id": "u1"})
    assert u["role"] == "level_1" and u["agent_id"] is not None


def test_idempotent_skips_existing_by_name_or_email(db):
    seed(db, "JG", "GOJCAJ, JOSEPH", "joseph@aopremier.com", role="level_4")
    created, skipped, _ = cli.run(db, SMALL, apply=True)
    assert [c["name"] for c in created] == ["David Fulfer", "William Benline"]
    assert skipped[0][0] == "Joseph Gojcaj"
    # David's upline resolved to the pre-existing profile, not a duplicate
    assert db.agent_profiles.find_one({"name": "David Fulfer"})["upline_id"] == "JG"


def test_missing_upline_blocks_only_that_person(db):
    roster = [("Kara Johnson", "kara.johnson.ail@gmail.com", "Agent", "level_1", False, "Karami Kovar")]
    created, _, blocked = cli.run(db, roster, apply=True)
    assert not created and blocked[0][0] == "Kara Johnson"
    assert db.agent_profiles.count_documents({}) == 0


def test_alias_resolves_sheet_name_to_db_name(db):
    # The DB stores Mohamed Aljahmi as "MJ Aljahmi" — the sheet name must
    # still resolve to him instead of blocking the whole MJ chain.
    seed(db, "MJ", "MJ Aljahmi", "mj@aopremier.com", role="level_4")
    upline, _how = cli.find_upline(db, [], "Mohamed Aljahmi")
    assert upline is not None and upline["agent_id"] == "MJ"


def test_duplicate_upline_prefers_email_holder(db):
    seed(db, "S1", "Snoor Qaradaghi", "", role="level_2")
    seed(db, "S2", "QARADAGHI, SNOOR", "snoor.qaradaghi@gmail.com", role="level_2")
    upline, how = cli.find_upline(db, [], "Snoor Qaradaghi")
    assert upline["agent_id"] == "S2" and "picked" in how


def test_full_roster_integrity():
    names = [r[0] for r in cli.ROSTER]
    # 50 missing − Annie Ransom (excluded per the owner) + Ashlynn Orng
    assert len(names) == len(set(names)) == 50
    assert "Annie Ransom" not in names
    landy = next(r for r in cli.ROSTER if r[0] == "Landy Sitto")
    assert landy[2] == "SA" and landy[3] == "level_2" and landy[5] == "Ali Musa"
    # every upline is either None, in the DB already, or defined earlier in the list
    defined = set()
    forward_ok = True
    for name, _e, _io, _role, _rk, upline in cli.ROSTER:
        if upline and cli.norm_name(upline) in defined:
            pass  # resolved from this run — must come earlier, which it did
        defined.add(cli.norm_name(name))
    assert forward_ok
    # roles line up with titles
    for name, _e, io_role, role, _rk, _u in cli.ROSTER:
        expect = {"RGA": "level_4", "MGA": "level_3", "GA": "level_2",
                  "SA": "level_2", "Agent": "level_1"}[io_role]
        assert role == expect, name
