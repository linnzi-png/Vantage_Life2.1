"""Roster email audit CLI (audit_roster_emails.py): matching, dry-run
accounting, and what --fix writes.

Like the other CLI scripts this one uses sync pymongo, so tests run on
mongomock directly rather than the async fixtures in conftest.
"""
import mongomock
import pytest

import audit_roster_emails as cli


@pytest.fixture()
def db():
    return mongomock.MongoClient()["vantagelife_test"]


def seed_profile(db, agent_id, name, email, role="level_1"):
    db.agent_profiles.insert_one(
        {"agent_id": agent_id, "name": name, "email": email, "role": role})


ROSTER = [
    {"app_id": "AO0001", "name": "Mohamed Aljahmi", "email": "mj@aopremier.com"},
    {"app_id": "AO0029", "name": "Landy Sitto", "email": "landy.sitto.ail@gmail.com"},
    {"app_id": "AO0100", "name": "Nicolas Smith", "email": "nicolasscottsmith@gmail.com"},
]


def test_name_matching_is_order_and_case_insensitive():
    assert cli.norm_name("SITTO, LANDY") == cli.norm_name("Landy Sitto")
    assert cli.norm_name("Mohamed Aljahmi") != cli.norm_name("Ali Musa")


def test_ok_when_email_current(db):
    seed_profile(db, "A1", "SITTO, LANDY", "landy.sitto.ail@gmail.com")
    f = cli.audit(db, [ROSTER[1]])
    assert [e["name"] for e in f["ok"]] == ["Landy Sitto"]
    assert not f["mismatch"] and not f["missing"]


def test_mismatch_reported_but_not_written_without_fix(db):
    seed_profile(db, "A1", "Landy Sitto", "landy.sitto.ali@gmail.com")
    f = cli.audit(db, [ROSTER[1]], fix=False)
    assert len(f["mismatch"]) == 1
    assert db.agent_profiles.find_one({"agent_id": "A1"})["email"] == "landy.sitto.ali@gmail.com"


def test_fix_updates_email_links_pending_login_and_unlinks_stale(db):
    seed_profile(db, "A1", "Landy Sitto", "landy.sitto.ali@gmail.com", role="level_2")
    # She signed in with her real email and got stuck on pending:
    db.users.insert_one({"user_id": "u1", "email": "landy.sitto.ail@gmail.com",
                         "role": "pending", "agent_id": None})
    # A login still keyed to the stale address:
    db.users.insert_one({"user_id": "u2", "email": "landy.sitto.ali@gmail.com",
                         "role": "level_2", "agent_id": "A1"})
    f = cli.audit(db, [ROSTER[1]], fix=True)
    assert len(f["mismatch"]) == 1
    assert db.agent_profiles.find_one({"agent_id": "A1"})["email"] == "landy.sitto.ail@gmail.com"
    linked = db.users.find_one({"user_id": "u1"})
    assert linked["role"] == "level_2" and linked["agent_id"] == "A1"
    stale = db.users.find_one({"user_id": "u2"})
    assert stale["role"] == "pending" and stale["agent_id"] is None
    log = db.audit_log.find_one({"action": "sync_email"})
    assert log and log["agent_id"] == "A1" and log["new_value"] == "landy.sitto.ail@gmail.com"


def test_non_lowercase_email_flagged_and_fixed(db):
    # Exact-match login lookup lowercases its side, so this profile is
    # unreachable at sign-in even though the address itself is right.
    seed_profile(db, "A1", "Nicolas Smith", "NICOLASSCOTTSMITH@GMAIL.COM")
    f = cli.audit(db, [ROSTER[2]], fix=True)
    assert len(f["not_lower"]) == 1
    assert db.agent_profiles.find_one({"agent_id": "A1"})["email"] == "nicolasscottsmith@gmail.com"
    # After normalization the row counts as current, not a mismatch.
    assert len(f["ok"]) == 1 and not f["mismatch"]


def test_missing_and_extra_reported_never_written(db):
    seed_profile(db, "A9", "Tyler Grant", "tylergrant@cmail.live")  # demo seed
    f = cli.audit(db, [ROSTER[0]], fix=True)
    assert [e["name"] for e in f["missing"]] == ["Mohamed Aljahmi"]
    assert [p["agent_id"] for p in f["extra"]] == ["A9"]
    assert db.agent_profiles.count_documents({}) == 1  # nothing created/deleted


def test_ambiguous_multiple_candidates_not_fixed(db):
    seed_profile(db, "A1", "Landy Sitto", "old1@gmail.com")
    seed_profile(db, "A2", "SITTO, LANDY", "old2@gmail.com")
    f = cli.audit(db, [ROSTER[1]], fix=True)
    assert len(f["ambiguous"]) == 1
    emails = {p["email"] for p in db.agent_profiles.find({})}
    assert emails == {"old1@gmail.com", "old2@gmail.com"}  # untouched


def test_match_by_email_when_name_spelling_differs(db):
    # Sheet reconciliation tab: 'Waleedjasholih Othman' vs 'Waleed Othman' —
    # name tokens don't line up, but the email does, so it's the same person.
    seed_profile(db, "A1", "Waleedjasholih Othman", "willothman.ao@gmail.com")
    f = cli.audit(db, [{"app_id": "AO0019", "name": "Waleed Othman",
                        "email": "willothman.ao@gmail.com"}])
    assert len(f["ok"]) == 1 and not f["missing"]


def test_default_csv_loads_full_roster():
    roster = cli.load_roster(cli.DEFAULT_CSV)
    assert len(roster) == 159
    emails = [r["email"] for r in roster]
    assert all(e == e.strip().lower() for e in emails)
    assert "landy.sitto.ail@gmail.com" in emails
