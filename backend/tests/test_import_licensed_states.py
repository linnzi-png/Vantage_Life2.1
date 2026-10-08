"""The licensed-states import (Linnzi, 2026-09-29): matcher, validator, plan,
idempotence and the audit trail. The plan is pure; apply runs against a fake
sync database so no Mongo is needed."""
import os

import import_licensed_states as imp
import server

TODAY = "2026-10-07"


def prof(agent_id, name, office="MJ RGA", **over):
    return {"agent_id": agent_id, "name": name, "office": office, **over}


def row(name, lic="", pend="", aka=""):
    names = [name] + [a for a in aka.split(";") if a]
    return {"name": name, "names": names, "licensed": lic.split(), "pending": pend.split()}


def plan(seed, profiles, office="MJ RGA"):
    return imp.build_plan(seed, profiles, office, TODAY)


def test_the_valid_codes_are_exactly_the_servers():
    assert set(imp.VALID_CODES) == set(server.LICENSED_STATE_CODES)
    assert "PR" in imp.VALID_CODES


def test_names_match_ignoring_case_spacing_and_punctuation():
    assert imp.normalize_name("  Ali  T. Alwatan ") == imp.normalize_name("ali t alwatan")
    p = plan([row("Korey mucchiello", "ID")], [prof("A", "Korey Mucchiello")])
    assert p["unmatched"] == [] and len(p["changes"]) == 1


def test_validator_uppercases_dedupes_and_rejects():
    assert imp.validate_codes(["MI", "OH", "MI", "ZZ", "GU"]) == (["MI", "OH"], ["GU", "ZZ"])
    assert imp.split_codes("mi, oh;tx  PR") == ["MI", "OH", "TX", "PR"]


def test_an_also_known_as_name_matches_the_other_spelling():
    p = plan([row("Hussein Habhab", "CA", aka="Hussien Habhab")], [prof("A", "Hussien Habhab")])
    assert p["changes"][0]["agent_id"] == "A"


def test_only_the_named_office_is_matched():
    p = plan([row("Pat Lee", "MI")], [prof("A", "Pat Lee", office="AMP")])
    assert p["unmatched"] == ["Pat Lee"] and p["changes"] == []


def test_office_names_match_despite_case_and_spacing():
    p = plan([row("Pat Lee", "MI")], [prof("A", "Pat Lee", office="mj  rga")])
    assert len(p["changes"]) == 1


def test_unmatched_and_not_on_sheet_are_reported():
    p = plan([row("Ghost Person", "MI")], [prof("A", "Real Person")])
    assert p["unmatched"] == ["Ghost Person"] and p["not_on_sheet"] == ["Real Person"]


def test_archived_profiles_are_ignored():
    p = plan([row("Pat Lee", "MI")], [prof("A", "Pat Lee", archived=True)])
    assert p["unmatched"] == ["Pat Lee"] and p["not_on_sheet"] == []


def test_a_name_on_two_profiles_is_skipped_and_reported():
    p = plan([row("Snoor Q", "MI")], [prof("A", "Snoor Q"), prof("B", "Snoor Q")])
    assert p["changes"] == [] and p["ambiguous"] == [{"name": "Snoor Q", "agent_ids": ["A", "B"]}]


def test_invalid_codes_are_rejected_and_never_written():
    p = plan([row("Pat Lee", "MI ZZ", "GU")], [prof("A", "Pat Lee")])
    assert p["rejected"] == [{"name": "Pat Lee", "codes": ["GU", "ZZ"]}]
    assert p["changes"][0]["fields"]["licensed_states"] == ["MI"]
    assert p["changes"][0]["fields"]["pending_states"] == []


def test_a_code_on_both_lists_is_written_as_active_only():
    p = plan([row("Pat Lee", "MI", "MI IA")], [prof("A", "Pat Lee")])
    f = p["changes"][0]["fields"]
    assert f["licensed_states"] == ["MI"] and f["pending_states"] == ["IA"]
    assert p["overlap"] == [{"name": "Pat Lee", "codes": ["MI"]}]


def test_new_pending_codes_get_the_import_day_and_the_reminder_on():
    f = plan([row("Pat Lee", "MI", "IA NE")], [prof("A", "Pat Lee")])["changes"][0]["fields"]
    assert f["pending_added_at"] == {"IA": TODAY, "NE": TODAY}
    assert f["pending_reminder"] == {"IA": True, "NE": True}


def test_an_existing_pending_date_and_switch_are_kept():
    existing = prof("A", "Pat Lee", licensed_states=["MI"], pending_states=["IA"],
                    pending_added_at={"IA": "2026-09-01"}, pending_reminder={"IA": False})
    f = plan([row("Pat Lee", "MI", "IA NE")], [existing])["changes"][0]["fields"]
    assert f["pending_added_at"] == {"IA": "2026-09-01", "NE": TODAY}
    assert f["pending_reminder"] == {"IA": False, "NE": True}


def test_a_second_run_changes_nothing():
    seed = [row("Pat Lee", "MI OH", "IA")]
    first = plan(seed, [prof("A", "Pat Lee")])
    assert len(first["changes"]) == 1
    applied = prof("A", "Pat Lee", **first["changes"][0]["fields"])
    second = plan(seed, [applied])
    assert second["changes"] == [] and second["unchanged"] == ["Pat Lee"]


class _Coll:
    def __init__(self):
        self.updates, self.inserts = [], []

    def update_one(self, flt, upd):
        self.updates.append((flt, upd))

    def insert_one(self, doc):
        self.inserts.append(doc)


class _Db:
    def __init__(self):
        self.agent_profiles, self.audit_log = _Coll(), _Coll()


def test_apply_writes_one_audit_entry_per_person_and_never_touches_state():
    p = plan([row("Pat Lee", "MI", "IA")], [prof("A", "Pat Lee", state="OH", licensed_states=["TX"])])
    db = _Db()
    assert imp.apply_plan(db, p) == 1
    (flt, upd), = db.agent_profiles.updates
    assert flt == {"agent_id": "A"} and "state" not in upd["$set"]
    assert set(upd["$set"]) >= {"licensed_states", "pending_states", "pending_added_at", "pending_reminder"}
    audit, = db.audit_log.inserts
    assert audit["action"] == "import_licensed_states" and audit["agent_id"] == "A"
    assert audit["original_value"] == ["TX"] and audit["new_value"] == ["MI"] and audit["new_pending"] == ["IA"]


def test_a_dry_run_plan_writes_nothing():
    db = _Db()
    plan([row("Pat Lee", "MI")], [prof("A", "Pat Lee")])
    assert db.agent_profiles.updates == [] and db.audit_log.inserts == []


def test_the_committed_seed_is_clean():
    path = os.path.join(os.path.dirname(imp.__file__), "..", "docs", "data", "licensed_states_seed.csv")
    seed = imp.read_seed(path)
    assert len(seed) == 72
    names = [imp.normalize_name(n) for r in seed for n in r["names"]]
    assert len(names) == len(set(names)), "a name appears twice in the seed"
    for r in seed:
        assert not imp.validate_codes(r["licensed"] + r["pending"])[1], r["name"]
        assert not set(r["licensed"]) & set(r["pending"]), r["name"]
    merged = {r["name"]: r for r in seed}
    assert "Hussein Habhab" in merged and "Hussien Habhab" in merged["Hussein Habhab"]["names"]
    assert "Saufaiga Sunshine Faimalo" in merged and "Saufaiga Faimalo" in merged["Saufaiga Sunshine Faimalo"]["names"]
    assert "MJ Aljahmi" in merged["Mohamed Aljahmi"]["names"]
    assert "PR" in merged["Adnan Aljida"]["licensed"]
