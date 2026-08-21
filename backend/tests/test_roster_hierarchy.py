"""Loader for the office's full app-sheet hierarchy snapshot
(backend/data/roster/agent_hierarchy_2026-08-20.csv) — the derivation rules
and the sheet quirks it must absorb."""
import roster_hierarchy


def entry(name):
    return roster_hierarchy.load_hierarchy().get(roster_hierarchy.name_key(name))


def test_row_count_after_dedup_and_exclusion():
    h = roster_hierarchy.load_hierarchy()
    # 159 sheet rows - duplicate Connor Cook row - owner-excluded Annie Ransom.
    assert len(h) == 157


def test_sa_own_column_derives_sa_and_ga_upline():
    e = entry("Snoor Qaradaghi")
    assert e["io_role"] == "SA" and e["role"] == "level_2"
    assert e["upline_name"] == "Ali Musa"


def test_plain_agent_upline_is_lowest_filled_tier():
    e = entry("Shiko Qaradaghi")
    assert e["io_role"] == "Agent" and e["role"] == "level_1"
    assert e["upline_name"] == "Snoor Qaradaghi"


def test_rga_root_has_no_upline():
    e = entry("Joseph Gojcaj")
    assert e["io_role"] == "RGA" and e["role"] == "level_4"
    assert e["upline_name"] == ""


def test_mga_upline_is_rga():
    e = entry("Mohamed Aljahmi")
    assert e["io_role"] == "MGA"
    assert e["upline_name"] == "Joseph Gojcaj"


def test_duplicate_connor_row_first_wins():
    e = entry("Connor Cook")
    # AO0005 (with the SA column filled) wins over the AO0038 repeat.
    assert e["upline_name"] == "Aleskander Murshed"


def test_annie_ransom_excluded():
    assert entry("Annie Ransom") is None


def test_typo_in_own_sa_column_still_reads_as_sa():
    # The sheet writes "Afnan Alfatlaway" in her own row's SA column while the
    # name column says "Afnan Alfatlawy" — one-edit tolerance must recognize
    # the self-reference, making her an SA under her GA.
    e = entry("Afnan Alfatlawy")
    assert e["io_role"] == "SA"
    assert e["upline_name"] == "Serage Jamil"


def test_keys_match_tolerates_one_edit_but_not_different_people():
    km = roster_hierarchy.keys_match
    nk = roster_hierarchy.name_key
    assert km(nk("Afnan Alfatlawy"), nk("Afnan Alfatlaway"))
    assert km(nk("QARADAGHI, SNOOR"), nk("Snoor Qaradaghi"))
    assert not km(nk("Ali Musa"), nk("Basel Musaed"))
    assert not km(nk("Ali Musa"), nk("Ali Musaed"))  # 2 edits — distinct person
    assert not km(nk("Snoor Qaradaghi"), nk("Snoor"))  # token counts differ


def test_nickname_alias_self_reference_eddie_leon():
    # Owner-confirmed: the Gojcaj book's GA "Edward Leon" is Eddie Leon's own
    # row. The alias must make his row read as GA, reporting to the MGA.
    e = entry("Eddie Leon")
    assert e["io_role"] == "GA" and e["role"] == "level_2"
    assert e["upline_name"] == "Joseph Gojcaj"


def test_nickname_alias_monty_alsheeblawy():
    e = entry("Monty Alsheeblawy")
    assert e["io_role"] == "SA"
    assert e["upline_name"] == "Serage Jamil"


def test_alias_names_returns_both_spellings():
    assert roster_hierarchy.alias_names("Edward Leon") == ["Edward Leon", "Eddie Leon"]
    assert roster_hierarchy.alias_names("Eddie Leon") == ["Eddie Leon", "Edward Leon"]
    assert roster_hierarchy.alias_names("Snoor Qaradaghi") == ["Snoor Qaradaghi"]
